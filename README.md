# OX-Alpha Data Integrity

A small Python CLI that audits tabular datasets (CSV, JSON, JSONL) for data-quality issues.

What it does:

- **audit** — reads one dataset file and:
  - infers a schema per column (inferred type, null count, distinct count, min/max/mean/std for numerics),
  - validates rows (type violations, missing required fields via `--required`),
  - flags outliers on numeric columns (IQR rule),
  - detects exact duplicate rows,
  - computes a SHA-256 checksum of the input file,
  - writes `report.md` (human-readable) and `report.json` (machine-readable) into the output directory.
- **drift** — compares two dataset files and reports added/removed columns, type changes,
  row-count delta, checksum comparison, and numeric mean shifts.

## Install

Requires Python 3.9+. No third-party dependencies.

```bash
git clone https://github.com/MohammedAbdelshafy/ox-alpha-data-integrity.git
cd ox-alpha-data-integrity
python3 -m ox_alpha audit samples/customers.csv
```

Optional console entry point:

```bash
pip install .
ox-alpha audit samples/customers.csv
```

## Usage

```bash
# Audit one file
python3 -m ox_alpha audit samples/customers.csv --out-dir ./report

# Audit with required columns and a custom failure threshold
python3 -m ox_alpha audit data.csv --required email,id --fail-on warning

# Compare two snapshots
python3 -m ox_alpha drift before.csv after.csv --out-dir ./drift-report
```

Exit codes: `0` = OK (or no findings at the `--fail-on` severity), `2` = findings at or above
the threshold, `1` = input/parse error. Default `--fail-on` is `error`.

`--version` prints the tool version.

## GitHub Action

This repo is published as a GitHub Action (`v1`). Use it in a workflow to gate CI on dataset quality:

```yaml
- uses: MohammedAbdelshafy/ox-alpha-data-integrity@v1
  with:
    path: data/customers.csv      # CSV or JSON/JSONL, relative to your repo root
    required: 'email,id'          # optional: columns that must be non-empty
    fail-on: error                # optional: error (default), warning, or none
    out-dir: ./ox-alpha-report    # optional: where report.md + report.json go
```

The step fails (exit 2) when findings at or above `fail-on` exist.

## Example

`samples/customers.csv` ships with the repo:

```csv
id,name,email,age,city
1,Alice,alice@example.com,30,New York
2,Bob,bob@example.com,25,Chicago
```

Running `python3 -m ox_alpha audit samples/customers.csv --out-dir ./report` produces
`./report/report.md` (schema table + findings) and `./report/report.json`
(schema, findings, checksum, counts).

## Inputs and outputs

- Inputs: `.csv` (header row required), `.json` (array of objects, or `{"rows": [...]}`),
  `.jsonl` (one object per line). Other extensions are rejected with a clear error;
  files must be UTF-8 decodable.
- Outputs: `report.md` and `report.json` in the chosen `--out-dir`.
- A file with no data rows still produces a report, with an `empty_input` warning finding.
- A `--required` column that doesn't exist in the dataset produces one clear
  `unknown_required_column` error instead of one error per row.

## Limits

- Files are loaded fully into memory — best suited to files under roughly 1M rows.
- Type inference is heuristic (int/float/bool/str); ambiguous columns fall back to `str`.
- Outlier detection needs at least 4 numeric values per column (IQR rule).
- Duplicate detection is exact-match only (null-normalized), not fuzzy.

## Tests

```bash
python3 tests/run_tests.py
```

## License

MIT — see [LICENSE](LICENSE).
