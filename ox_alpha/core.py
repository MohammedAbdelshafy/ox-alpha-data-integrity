"""OX-Alpha Data Integrity: audit CSV/JSON/JSONL datasets for quality issues.

Single-file core. stdlib only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone

NUMERIC = {"int", "float"}

SUPPORTED_EXTENSIONS = (".csv", ".json", ".jsonl")


# ---------------------------------------------------------------- loading

def _require_object_rows(rows: list, path: str) -> list[dict]:
    """JSON/JSONL rows must all be objects; fail loudly otherwise."""
    for i, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            raise ValueError(
                f"{path}: row {i} is {type(r).__name__}, not an object — "
                "JSON/JSONL input must be a list of objects")
    return [dict(r) for r in rows]


def load_table(path: str) -> tuple[list[str], list[dict]]:
    """Load a CSV, JSON array, or JSONL file into (columns, rows).

    All cell values are kept as raw strings except JSON native types;
    empty strings and None count as nulls.

    Raises FileNotFoundError if the file doesn't exist, and ValueError
    with a descriptive message for unsupported extensions, undecodable
    bytes, or malformed JSON/JSONL.
    """
    ext = os.path.splitext(path.lower())[1]
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"unsupported file type {ext or '(no extension)'} for {path!r}: "
            f"expected one of {', '.join(SUPPORTED_EXTENSIONS)}")

    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"cannot decode {path!r} as UTF-8: {exc}") from exc

    if ext == ".jsonl":
        rows: list = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}: invalid JSON on line {lineno}: {exc.msg}") from exc
        rows = _require_object_rows(rows, path)
        return _union_columns(rows), rows

    if ext == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON: {exc.msg}") from exc
        if isinstance(data, dict) and "rows" in data and isinstance(data["rows"], list):
            data = data["rows"]
        if not isinstance(data, list):
            raise ValueError(
                f"{path}: JSON input must be a list of objects (or {{\"rows\": [...]}}), "
                f"got {type(data).__name__}")
        rows = _require_object_rows(data, path)
        return _union_columns(rows), rows

    # CSV
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], []
    rows = [dict(r) for r in reader]
    return list(reader.fieldnames), rows


def _union_columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- typing

def _scalar_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    s = str(value).strip()
    if s == "":
        return "null"
    if s.lower() in ("true", "false"):
        return "bool"
    try:
        int(s)
        return "int"
    except ValueError:
        pass
    try:
        # Non-finite strings ("nan", "inf") are not usable numbers;
        # typing them as float would poison stats and emit invalid JSON.
        return "float" if math.isfinite(float(s)) else "str"
    except ValueError:
        pass
    return "str"


def _to_float(value):
    """Best-effort numeric conversion; None if not numeric or non-finite."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    s = str(value).strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------- audit

def infer_schema(columns: list[str], rows: list[dict]) -> dict:
    """Per-column: inferred type, nulls, distincts, min/max/mean/std for numerics."""
    schema: dict = {}
    for col in columns:
        values = [r.get(col) for r in rows]
        types = Counter(_scalar_type(v) for v in values)
        nulls = types.pop("null", 0)
        inferred = types.most_common(1)[0][0] if types else "null"
        distinct = len({json.dumps(v, sort_keys=True, default=str) for v in values})
        col_info: dict = {
            "inferred_type": inferred,
            "null_count": nulls,
            "null_pct": round(nulls / len(rows) * 100, 2) if rows else 0.0,
            "distinct_count": distinct,
            "type_breakdown": dict(types),
        }
        if inferred in NUMERIC:
            nums = [x for x in (_to_float(v) for v in values) if x is not None]
            if nums:
                mean = sum(nums) / len(nums)
                var = sum((x - mean) ** 2 for x in nums) / len(nums)
                col_info.update(
                    numeric_count=len(nums),
                    min=min(nums),
                    max=max(nums),
                    mean=round(mean, 6),
                    std=round(math.sqrt(var), 6),
                )
        schema[col] = col_info
    return schema


def validate_rows(columns: list[str], rows: list[dict], schema: dict,
                  required: list[str] | None = None) -> list[dict]:
    """Type violations (value doesn't match column's inferred type) and
    missing required fields. Returns list of finding dicts."""
    findings: list[dict] = []
    required = required or []
    # A typo'd --required should surface once, clearly — not as one
    # missing_required error per row.
    unknown = [c for c in required if c not in columns]
    for col in unknown:
        findings.append({
            "severity": "error",
            "kind": "unknown_required_column",
            "column": col,
            "message": (f"Required column '{col}' not found in dataset "
                        f"(columns: {', '.join(columns) or 'none'})"),
        })
    known_required = [c for c in required if c in columns]
    for i, row in enumerate(rows, start=1):  # 1-based row numbers (data rows)
        for col in known_required:
            v = row.get(col)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                findings.append({
                    "severity": "error",
                    "kind": "missing_required",
                    "row": i, "column": col,
                    "message": f"Row {i}: required column '{col}' is missing/empty",
                })
        for col in columns:
            v = row.get(col)
            if v is None or (isinstance(v, str) and str(v).strip() == ""):
                continue
            want = schema[col]["inferred_type"]
            got = _scalar_type(v)
            if want in NUMERIC and got == "str":
                findings.append({
                    "severity": "error",
                    "kind": "type_violation",
                    "row": i, "column": col,
                    "message": f"Row {i}: column '{col}' expected {want}, got '{str(v)[:40]}'",
                })
            elif want == "int" and got == "float":
                findings.append({
                    "severity": "warning",
                    "kind": "type_violation",
                    "row": i, "column": col,
                    "message": f"Row {i}: column '{col}' expected int, got float '{v}'",
                })
    return findings


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def find_outliers(columns: list[str], rows: list[dict], schema: dict) -> list[dict]:
    """IQR outliers on numeric columns (needs >= 4 numeric values)."""
    findings: list[dict] = []
    for col in columns:
        info = schema[col]
        if info["inferred_type"] not in NUMERIC:
            continue
        pairs = [(i, _to_float(r.get(col))) for i, r in enumerate(rows, start=1)]
        pairs = [(i, x) for i, x in pairs if x is not None]
        if len(pairs) < 4:
            continue
        vals = sorted(x for _, x in pairs)
        q1, q3 = _percentile(vals, 25), _percentile(vals, 75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        for i, x in pairs:
            if x < lo or x > hi:
                findings.append({
                    "severity": "warning",
                    "kind": "outlier",
                    "row": i, "column": col,
                    "message": (f"Row {i}: '{col}' = {x} outside IQR bounds "
                                f"[{round(lo, 4)}, {round(hi, 4)}]"),
                })
    return findings


def _norm_key(k):
    """DictReader parks CSV fields beyond the header under a None key,
    which json.dumps(sort_keys=True) cannot order against str keys."""
    return k if isinstance(k, str) else f"__extra_field_{k!r}"


def find_duplicates(rows: list[dict]) -> list[dict]:
    """Exact duplicate rows (all columns equal, null-normalized)."""
    seen: dict[str, list[int]] = {}
    for i, row in enumerate(rows, start=1):
        key = json.dumps(
            {_norm_key(k): (None if (v is None or (isinstance(v, str) and v.strip() == "")) else v)
             for k, v in row.items()},
            sort_keys=True, default=str)
        seen.setdefault(key, []).append(i)
    findings = []
    for key, idxs in seen.items():
        if len(idxs) > 1:
            findings.append({
                "severity": "warning",
                "kind": "duplicate",
                "rows": idxs,
                "message": f"Rows {idxs} are exact duplicates",
            })
    return findings


def audit(path: str, required: list[str] | None = None) -> dict:
    """Run the full audit; returns the report dict."""
    columns, rows = load_table(path)
    schema = infer_schema(columns, rows)
    findings: list[dict] = []
    if not rows:
        findings.append({
            "severity": "warning",
            "kind": "empty_input",
            "message": f"No data rows found in {path!r}; nothing to audit",
        })
    # csv.DictReader parks fields beyond the header under a None key.
    ragged = [i for i, r in enumerate(rows, start=1) if None in r]
    if ragged:
        shown = ragged[:10]
        suffix = f" (+{len(ragged) - len(shown)} more)" if len(ragged) > len(shown) else ""
        findings.append({
            "severity": "warning",
            "kind": "ragged_row",
            "rows": ragged,
            "message": (f"Rows {shown}{suffix} have more fields than the header "
                        f"({len(columns)} columns); extra values were kept but not typed"),
        })
    findings += validate_rows(columns, rows, schema, required)
    findings += find_outliers(columns, rows, schema)
    findings += find_duplicates(rows)
    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    return {
        "tool": "ox-alpha",
        "command": "audit",
        "file": path,
        "sha256": file_sha256(path),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns,
        "schema": schema,
        "finding_count": len(findings),
        "error_count": errors,
        "warning_count": warnings,
        "findings": findings,
    }


# ---------------------------------------------------------------- drift

def drift(before_path: str, after_path: str) -> dict:
    """Compare two dataset files."""
    b_cols, b_rows = load_table(before_path)
    a_cols, a_rows = load_table(after_path)
    b_schema = infer_schema(b_cols, b_rows)
    a_schema = infer_schema(a_cols, a_rows)

    added = [c for c in a_cols if c not in b_cols]
    removed = [c for c in b_cols if c not in a_cols]
    type_changes = [
        {"column": c, "before": b_schema[c]["inferred_type"], "after": a_schema[c]["inferred_type"]}
        for c in b_cols if c in a_cols
        and b_schema[c]["inferred_type"] != a_schema[c]["inferred_type"]
    ]

    mean_shifts = []
    for c in b_cols:
        if c in a_cols and b_schema[c]["inferred_type"] in NUMERIC and a_schema[c]["inferred_type"] in NUMERIC:
            bm, am = b_schema[c].get("mean"), a_schema[c].get("mean")
            bs = b_schema[c].get("std") or 0
            if bm is not None and am is not None:
                denom = abs(bm) if bm != 0 else 1.0
                pct = (am - bm) / denom * 100
                sig = abs(am - bm) > 2 * bs if bs else pct != 0
                mean_shifts.append({
                    "column": c, "before_mean": bm, "after_mean": am,
                    "pct_change": round(pct, 2), "significant": bool(sig),
                })

    b_hash, a_hash = file_sha256(before_path), file_sha256(after_path)
    findings: list[dict] = []
    if added:
        findings.append({"severity": "warning", "kind": "schema_added",
                         "message": f"Added columns: {added}"})
    if removed:
        findings.append({"severity": "error", "kind": "schema_removed",
                         "message": f"Removed columns: {removed}"})
    for tc in type_changes:
        findings.append({"severity": "error", "kind": "schema_type_change",
                         "message": f"Column '{tc['column']}' changed type {tc['before']} -> {tc['after']}"})
    for ms in mean_shifts:
        if ms["significant"]:
            findings.append({"severity": "warning", "kind": "distribution_drift",
                             "message": (f"Column '{ms['column']}' mean shifted "
                                         f"{ms['before_mean']} -> {ms['after_mean']} "
                                         f"({ms['pct_change']}%)")})

    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    return {
        "tool": "ox-alpha",
        "command": "drift",
        "before": {"file": before_path, "sha256": b_hash, "rows": len(b_rows), "columns": b_cols},
        "after": {"file": after_path, "sha256": a_hash, "rows": len(a_rows), "columns": a_cols},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_delta": len(a_rows) - len(b_rows),
        "identical_content": b_hash == a_hash,
        "added_columns": added,
        "removed_columns": removed,
        "type_changes": type_changes,
        "mean_shifts": mean_shifts,
        "finding_count": len(findings),
        "error_count": errors,
        "warning_count": warnings,
        "findings": findings,
    }


# ---------------------------------------------------------------- report.md

def report_markdown(report: dict) -> str:
    L: list[str] = []
    add = L.append
    add(f"# OX-Alpha Data Integrity Report — `{report['command']}`")
    add("")
    add(f"- Generated: {report['generated_at']}")
    if report["command"] == "audit":
        add(f"- File: `{report['file']}`")
        add(f"- SHA-256: `{report['sha256']}`")
        add(f"- Rows: {report['row_count']}, Columns: {report['column_count']}")
    else:
        add(f"- Before: `{report['before']['file']}` (sha256 `{report['before']['sha256'][:16]}…`, {report['before']['rows']} rows)")
        add(f"- After: `{report['after']['file']}` (sha256 `{report['after']['sha256'][:16]}…`, {report['after']['rows']} rows)")
        add(f"- Row delta: {report['row_delta']:+d}")
        add(f"- Identical content: {report['identical_content']}")
    add(f"- Findings: {report['finding_count']} ({report['error_count']} errors, {report['warning_count']} warnings)")
    add("")

    if report["command"] == "audit":
        add("## Schema")
        add("")
        add("| column | type | nulls | null % | distinct | min | max | mean | std |")
        add("|---|---|---|---|---|---|---|---|---|")
        for col, info in report["schema"].items():
            cells = [col] + [str(info.get(k, "—")) for k in
                ("inferred_type", "null_count", "null_pct", "distinct_count",
                 "min", "max", "mean", "std")]
            add("| " + " | ".join(cells) + " |")
        add("")
    else:
        for section, items, fmt in (
            ("Added columns", report["added_columns"], lambda x: f"- `{x}`"),
            ("Removed columns", report["removed_columns"], lambda x: f"- `{x}`"),
        ):
            if items:
                add(f"## {section}")
                add("")
                for x in items:
                    add(fmt(x))
                add("")
        if report["type_changes"]:
            add("## Type changes")
            add("")
            for tc in report["type_changes"]:
                add(f"- `{tc['column']}`: {tc['before']} → {tc['after']}")
            add("")
        if report["mean_shifts"]:
            add("## Numeric mean shifts")
            add("")
            add("| column | before | after | % change | significant |")
            add("|---|---|---|---|---|")
            for ms in report["mean_shifts"]:
                add(f"| `{ms['column']}` | {ms['before_mean']} | {ms['after_mean']} | {ms['pct_change']}% | {ms['significant']} |")
            add("")

    add("## Findings")
    add("")
    if not report["findings"]:
        add("No issues found.")
    else:
        for f in report["findings"]:
            add(f"- **{f['severity'].upper()}** [{f['kind']}] {f['message']}")
    add("")
    return "\n".join(L) + "\n"
