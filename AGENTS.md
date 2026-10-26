# OX-Alpha

Use this repository to inspect tabular data quality. The approved product name is **OX-Alpha**. The repository slug, Python package, CLI and GitHub Action identifiers remain unchanged for compatibility.

## Where to go

- Product and command usage: [README.md](README.md)
- Implementation: [ox_alpha/](ox_alpha/)
- Tests: [tests/](tests/)
- Package metadata: [pyproject.toml](pyproject.toml)
- ICM contract: [CONTEXT.md](CONTEXT.md)

## Rules

- Read inputs; write reports to a separate output directory.
- Do not silently write results back into customer data or a canonical lead database.
- Treat type inference as heuristic and exact duplicate detection as exact, not fuzzy.
- A report is evidence about the supplied file, not a guarantee that every fact is true.
- Do not add dependencies or features until a customer acceptance test requires them.
