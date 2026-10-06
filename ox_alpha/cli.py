"""OX-Alpha Data Integrity CLI."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from .core import audit, drift, report_markdown


def _write_reports(report: dict, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
        fh.write("\n")
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(report_markdown(report))


def _exit_for(report: dict, fail_on: str) -> int:
    if fail_on == "none":
        return 0
    if fail_on == "error" and report["error_count"] > 0:
        return 2
    if fail_on == "warning" and (report["error_count"] + report["warning_count"]) > 0:
        return 2
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    required = [c.strip() for c in args.required.split(",") if c.strip()] if args.required else None
    report = audit(args.path, required=required)
    _write_reports(report, args.out_dir)
    print(f"audit: {args.path} -> {report['row_count']} rows, "
          f"{report['error_count']} errors, {report['warning_count']} warnings "
          f"(reports in {args.out_dir}/)")
    return _exit_for(report, args.fail_on)


def cmd_drift(args: argparse.Namespace) -> int:
    report = drift(args.before, args.after)
    _write_reports(report, args.out_dir)
    print(f"drift: {args.before} -> {args.after}: row delta {report['row_delta']:+d}, "
          f"{report['error_count']} errors, {report['warning_count']} warnings "
          f"(reports in {args.out_dir}/)")
    return _exit_for(report, args.fail_on)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ox-alpha",
        description="Audit CSV/JSON/JSONL datasets: schema inference, validation, "
                    "outlier and duplicate detection, drift checks, quality reports.")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("audit", help="Audit one dataset file and write report.md + report.json")
    a.add_argument("path", help="Input file: .csv, .json (array of objects), or .jsonl")
    a.add_argument("--required", default=None,
                   help="Comma-separated columns that must be non-empty in every row")
    a.add_argument("--out-dir", default="ox-alpha-report",
                   help="Directory for report.md and report.json (default: ox-alpha-report)")
    a.add_argument("--fail-on", choices=["error", "warning", "none"], default="error",
                   help="Exit non-zero when findings at this severity exist (default: error)")
    a.set_defaults(func=cmd_audit)

    d = sub.add_parser("drift", help="Compare two dataset files and report schema/content drift")
    d.add_argument("before", help="Baseline file")
    d.add_argument("after", help="New file to compare against the baseline")
    d.add_argument("--out-dir", default="ox-alpha-report",
                   help="Directory for report.md and report.json (default: ox-alpha-report)")
    d.add_argument("--fail-on", choices=["error", "warning", "none"], default="error",
                   help="Exit non-zero when findings at this severity exist (default: error)")
    d.set_defaults(func=cmd_drift)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        print(f"ox-alpha: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
