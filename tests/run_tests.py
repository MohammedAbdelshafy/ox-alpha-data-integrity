"""Plain-stdlib test suite for ox-alpha. Run: python tests/run_tests.py"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ox_alpha.core import audit, drift, file_sha256, report_markdown  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def write_csv(path: str, columns: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        w.writerows(rows)


PKG_DIR = os.path.join(os.path.dirname(__file__), "..")


def run_cli(*args: str, cwd: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=PKG_DIR)
    return subprocess.run(
        [sys.executable, "-m", "ox_alpha", *args],
        cwd=cwd, capture_output=True, text=True, env=env)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="oxalpha-test-")

    # --- fixture: clean CSV
    clean = os.path.join(tmp, "clean.csv")
    write_csv(clean, ["id", "name", "age", "city"],
              [[1, "Alice", 30, "NYC"], [2, "Bob", 25, "LA"], [3, "Carol", 35, "SF"]])

    # --- fixture: messy CSV (dup row, outlier age, type violation, missing required)
    messy = os.path.join(tmp, "messy.csv")
    write_csv(messy, ["id", "name", "age", "city"],
              [[1, "Alice", 30, "NYC"],
               [2, "Bob", 25, "LA"],
               [1, "Alice", 30, "NYC"],       # exact duplicate of row 1
               [4, "Dave", "not-a-number", "SF"],  # type violation
               [5, "Eve", 999, "LA"],          # outlier
               [6, "", 28, "CHI"]])            # missing required name

    # --- fixture: JSON input
    as_json = os.path.join(tmp, "data.json")
    with open(as_json, "w") as fh:
        json.dump([{"id": 1, "v": 10}, {"id": 2, "v": 20}], fh)

    print("== schema inference ==")
    rep = audit(clean)
    check("columns", rep["columns"] == ["id", "name", "age", "city"], str(rep["columns"]))
    check("id is int", rep["schema"]["id"]["inferred_type"] == "int")
    check("name is str", rep["schema"]["name"]["inferred_type"] == "str")
    check("age min/max", rep["schema"]["age"]["min"] == 30 or rep["schema"]["age"]["min"] == 25,
          str(rep["schema"]["age"]))
    check("age mean", rep["schema"]["age"]["mean"] == 30.0, str(rep["schema"]["age"].get("mean")))
    check("no nulls", rep["schema"]["id"]["null_count"] == 0)
    check("row count", rep["row_count"] == 3)
    check("sha256 matches", rep["sha256"] == hashlib.sha256(open(clean, "rb").read()).hexdigest())

    print("== audit findings ==")
    rep = audit(messy, required=["name"])
    kinds = [f["kind"] for f in rep["findings"]]
    check("type violation found", "type_violation" in kinds, str(kinds))
    check("missing required found", "missing_required" in kinds, str(kinds))
    check("duplicate found", "duplicate" in kinds, str(kinds))
    dup = next(f for f in rep["findings"] if f["kind"] == "duplicate")
    check("duplicate rows listed", dup["rows"] == [1, 3], str(dup["rows"]))
    check("outlier found", "outlier" in kinds, str(kinds))
    out = next(f for f in rep["findings"] if f["kind"] == "outlier")
    check("outlier is row 5", out["row"] == 5, str(out))
    check("error count > 0", rep["error_count"] > 0)
    check("warning count > 0", rep["warning_count"] > 0)

    print("== report outputs via CLI ==")
    out_dir = os.path.join(tmp, "report1")
    r = run_cli("audit", messy, "--out-dir", out_dir, "--fail-on", "none", cwd=tmp)
    check("audit cli exit 0 with fail-on=none", r.returncode == 0, r.stderr)
    md = os.path.join(out_dir, "report.md")
    js = os.path.join(out_dir, "report.json")
    check("report.md exists", os.path.exists(md))
    check("report.json exists", os.path.exists(js))
    data = json.load(open(js))
    check("json valid + keys",
          all(k in data for k in ("schema", "findings", "sha256", "error_count")), str(list(data)))
    check("md has findings section", "## Findings" in open(md).read())

    r = run_cli("audit", clean, "--out-dir", os.path.join(tmp, "report2"), cwd=tmp)
    check("clean file exit 0", r.returncode == 0, r.stderr)
    r = run_cli("audit", messy, "--out-dir", os.path.join(tmp, "report3"), cwd=tmp)
    check("messy file exit non-zero", r.returncode != 0, str(r.returncode))

    print("== JSON input ==")
    rep = audit(as_json)
    check("json rows", rep["row_count"] == 2, str(rep["row_count"]))
    check("json schema", rep["schema"]["v"]["inferred_type"] == "int")

    print("== drift ==")
    before = os.path.join(tmp, "before.csv")
    after = os.path.join(tmp, "after.csv")
    write_csv(before, ["id", "age"], [[1, 30], [2, 40], [3, 50]])
    write_csv(after, ["id", "age", "city"], [[1, 300], [2, 400], [3, 500], [4, 600]])  # mean shift + added col
    d = drift(before, after)
    check("row delta", d["row_delta"] == 1, str(d["row_delta"]))
    check("added column", d["added_columns"] == ["city"], str(d["added_columns"]))
    check("no removed", d["removed_columns"] == [])
    check("mean shift flagged",
          any(ms["column"] == "age" and ms["significant"] for ms in d["mean_shifts"]),
          str(d["mean_shifts"]))
    check("not identical", d["identical_content"] is False)

    before2 = os.path.join(tmp, "before2.csv")
    write_csv(before2, ["id", "age"], [[1, 30], [2, 40]])
    after2 = os.path.join(tmp, "after2.csv")
    write_csv(after2, ["id"], [[1], [2]])  # removed column -> error
    d2 = drift(before2, after2)
    check("removed column error", d2["removed_columns"] == ["age"] and d2["error_count"] > 0,
          str(d2["removed_columns"]))

    out_dir_d = os.path.join(tmp, "report-drift")
    r = run_cli("drift", before, after, "--out-dir", out_dir_d, "--fail-on", "none", cwd=tmp)
    check("drift cli exit 0", r.returncode == 0, r.stderr)
    dd = json.load(open(os.path.join(out_dir_d, "report.json")))
    check("drift json valid", dd["command"] == "drift" and dd["row_delta"] == 1)

    print("== input validation ==")

    def expect_value_error(name, fn, needle):
        try:
            fn()
        except ValueError as exc:
            check(name, needle in str(exc), str(exc))
        except Exception as exc:  # noqa: BLE001 - wrong exception type is a failure
            check(name, False, f"wrong exception: {type(exc).__name__}: {exc}")
        else:
            check(name, False, "no exception raised")

    txt = os.path.join(tmp, "data.txt")
    open(txt, "w").write("hello\n")
    expect_value_error("unsupported extension rejected",
                       lambda: audit(txt), "unsupported file type")
    noext = os.path.join(tmp, "noext")
    open(noext, "w").write("a,b\n1,2\n")
    expect_value_error("missing extension rejected",
                       lambda: audit(noext), "no extension")

    scalars = os.path.join(tmp, "scalars.json")
    open(scalars, "w").write("[1, 2, 3]")
    expect_value_error("json array of scalars rejected",
                       lambda: audit(scalars), "not an object")
    notlist = os.path.join(tmp, "notlist.json")
    open(notlist, "w").write('{"a": 1}')
    expect_value_error("json non-list rejected",
                       lambda: audit(notlist), "must be a list of objects")
    wrapped = os.path.join(tmp, "wrapped.json")
    json.dump({"rows": [{"a": 1}, {"a": 2}]}, open(wrapped, "w"))
    rep = audit(wrapped)
    check("json {rows:[...]} still accepted", rep["row_count"] == 2, str(rep["row_count"]))

    badl = os.path.join(tmp, "bad.jsonl")
    open(badl, "w").write('{"a": 1}\nNOT JSON\n')
    expect_value_error("jsonl bad line reports line number",
                       lambda: audit(badl), "line 2")
    scalarl = os.path.join(tmp, "scalar.jsonl")
    open(scalarl, "w").write('{"a": 1}\n42\n')
    expect_value_error("jsonl scalar line rejected",
                       lambda: audit(scalarl), "not an object")

    latin = os.path.join(tmp, "latin.csv")
    open(latin, "wb").write(b"a,b\n\xff\xfe,2\n")
    expect_value_error("non-utf8 rejected", lambda: audit(latin), "UTF-8")

    print("== edge cases ==")
    nanf = os.path.join(tmp, "nan.csv")
    open(nanf, "w").write("a,b\n1,NaN\n2,3.5\n")
    rep = audit(nanf)
    check("NaN string typed as str", rep["schema"]["b"]["inferred_type"] == "str",
          str(rep["schema"]["b"]["inferred_type"]))
    out_dir_nan = os.path.join(tmp, "report-nan")
    r = run_cli("audit", nanf, "--out-dir", out_dir_nan, "--fail-on", "none", cwd=tmp)
    check("nan cli exit 0", r.returncode == 0, r.stderr)
    raw_js = open(os.path.join(out_dir_nan, "report.json")).read()

    def _boom(x):
        raise ValueError("non-finite constant: " + x)

    try:
        json.loads(raw_js, parse_constant=_boom)
        check("report.json strictly valid (no bare NaN/Infinity)", True)
    except ValueError as exc:
        check("report.json strictly valid (no bare NaN/Infinity)", False, str(exc))

    nanj = os.path.join(tmp, "nanj.json")
    open(nanj, "w").write('[{"a": 1, "b": NaN}, {"a": 2, "b": 3.5}]')
    rep = audit(nanj)  # must not crash; native NaN excluded from stats
    check("native json NaN tolerated",
          rep["schema"]["b"].get("numeric_count", 0) == 1, str(rep["schema"]["b"]))

    longrow = os.path.join(tmp, "long.csv")
    open(longrow, "w").write("a,b\n1,2,EXTRA\n3,4\n")
    rep = audit(longrow)  # must not crash on the None-keyed extra field
    ragged = [f for f in rep["findings"] if f["kind"] == "ragged_row"]
    check("ragged row flagged", len(ragged) == 1 and ragged[0]["rows"] == [1],
          str(ragged))

    rep = audit(clean, required=["zzz"])
    unk = [f for f in rep["findings"] if f["kind"] == "unknown_required_column"]
    per_row = [f for f in rep["findings"] if f["kind"] == "missing_required"]
    check("unknown required column: single clear error",
          len(unk) == 1 and rep["error_count"] == 1 and not per_row,
          str([f["kind"] for f in rep["findings"]]))

    empty = os.path.join(tmp, "empty.csv")
    open(empty, "w").write("")
    rep = audit(empty)
    check("empty file warns empty_input",
          any(f["kind"] == "empty_input" and f["severity"] == "warning"
              for f in rep["findings"]),
          str([f["kind"] for f in rep["findings"]]))

    print("== cli errors ==")
    r = run_cli("audit", os.path.join(tmp, "does-not-exist.csv"),
                "--out-dir", os.path.join(tmp, "r-missing"), cwd=tmp)
    check("missing file exit 1", r.returncode == 1, str(r.returncode))
    check("missing file message", "file not found" in r.stderr, r.stderr.strip()[:120])
    r = run_cli("drift", os.path.join(tmp, "does-not-exist.csv"), clean,
                "--out-dir", os.path.join(tmp, "r-missing2"), cwd=tmp)
    check("drift missing file exit 1", r.returncode == 1, str(r.returncode))
    r = run_cli("audit", txt, "--out-dir", os.path.join(tmp, "r-txt"), cwd=tmp)
    check("cli rejects bad extension", r.returncode == 1 and "unsupported file type" in r.stderr,
          r.stderr.strip()[:120])
    r = run_cli("--version", cwd=tmp)
    check("--version works", r.returncode == 0 and "ox-alpha" in r.stdout,
          (r.stdout + r.stderr).strip()[:80])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
