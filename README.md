# OX-Alpha | Data Quality Checks

**Catch data problems before they reach your reports, imports, and automated workflows.**

OX-Alpha checks CSV, JSON, and JSONL files and compares two dataset snapshots. It shows what looks wrong, creates a report your team can review, and can fail a CI workflow when findings meet the severity you choose.

**For:** developers, data teams, and operators who receive structured files from exports, partners, internal systems, or scheduled jobs.

**What you get:** a readable Markdown report, a machine-readable JSON report, and an optional pass/fail signal for your workflow.

OX-Alpha is the product name. **Data Quality Checks** is its plain-language description, not a product rename.

## The outcome

- Find missing required fields, inconsistent data types, exact duplicate rows, and unusual numeric values before a file is used downstream.
- Compare two snapshots to see whether the structure or key numeric summaries changed.
- Give your team a readable report plus JSON output, with an optional CI pass/fail gate.

The point is not another dashboard. It is an earlier, clearer signal that a file needs attention.

## What it checks, and why it matters

- **audit** — check a file before using it in an import, report, or automated workflow. It:
  - infers a schema per column (inferred type, null count, distinct count, min/max/mean/std for numerics),
  - validates rows (type violations, missing required fields via `--required`),
  - flags outliers on numeric columns (IQR rule),
  - detects exact duplicate rows,
  - computes a SHA-256 checksum of the input file,
  - writes `report.md` (human-readable) and `report.json` (machine-readable) into the output directory.
- **drift** — compare two snapshots to spot added/removed columns, type changes,
  row-count delta, checksum comparison, and numeric mean shifts.

## What OX-Alpha does not do

- It is a file-based check, not continuous production monitoring.
- It reports findings; it does not repair or write back to your source dataset.
- Duplicate detection is exact-match only, not fuzzy matching.
- It does not verify real-world facts or prove that contact details are reachable.

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

Use OX-Alpha as a GitHub Action (`v1`) to check a dataset during CI and fail the workflow when findings reach your chosen severity:

```yaml
- uses: MohammedAbdelshafy/ox-alpha-data-integrity@v1
  with:
    path: data/customers.csv      # CSV or JSON/JSONL, relative to your repo root
    required: 'email,id'          # optional: columns that must be non-empty
    fail-on: error                # optional: error (default), warning, or none
    out-dir: ./ox-alpha-report    # optional: where report.md + report.json go
```

**Outcome:** the workflow receives a clear pass/fail signal and a report when the dataset does not meet the selected threshold.

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

## Limits to understand before you rely on it

- Files are loaded fully into memory — best suited to files under roughly 1M rows.
- Type inference is heuristic (int/float/bool/str); ambiguous columns fall back to `str`.
- Outlier detection needs at least 4 numeric values per column (IQR rule).
- Duplicate detection is exact-match only (null-normalized), not fuzzy.

## Tests

```bash
python3 tests/run_tests.py
```

## Project details

- Product name: OX-Alpha
- Plain-language description: Data Quality Checks for CSV, JSON, and JSONL files
- Python package: `ox_alpha` (unchanged)
- Command: `ox-alpha` (unchanged)
- Repository: `ox-alpha-data-integrity` (unchanged)

## License

MIT — see [LICENSE](LICENSE).

