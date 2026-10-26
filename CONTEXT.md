---
type: repository
status: active
owner_repo: MohammedAbdelshafy/ox-alpha-data-integrity
product_name: OX-Alpha
source_of_truth: https://github.com/MohammedAbdelshafy/ox-alpha-data-integrity
---

# OX-Alpha CONTEXT

One job: check a supplied dataset and return a report that helps a person decide whether it is fit for the next step.

## Inputs

- Reference: [README](README.md)
- Code: [ox_alpha](ox_alpha/)
- Tests: [tests](tests/)
- Package configuration: [pyproject.toml](pyproject.toml)

## Process

1. Read supported CSV, JSON or JSONL input.
2. Infer column shapes and validate the rules explicitly supplied by the user.
3. Report missing required fields, type issues, exact duplicates and supported numeric outliers.
4. When asked, compare two snapshots for schema and selected numeric shifts.
5. Write Markdown/JSON reports and keep the source file separate.

## Outputs

A Markdown report and a JSON report in a selected output directory, with the source SHA-256 checksum and findings.

## Limits

Type inference is heuristic, duplicate matching is exact, data files are loaded into memory and the tool is best suited to inputs under roughly one million rows. A clean report is not a proof of data truth.

## Check

Run the documented test command and verify on a sample input that the source file remains unchanged and both reports are created.
