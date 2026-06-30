# Contributing

Thanks for your interest in improving the Alteryx-to-Databricks migration
accelerator (`a2d`). Contributions are welcome.

## Disclaimer

This project is a Databricks field-engineering asset provided **as-is**, with no
SLA or official Databricks support. It is maintained on a best-effort basis by
its owners.

## Ground Rules

- **All changes go through pull requests.** No direct pushes to `main`.
- **Every PR needs a reviewer who is not the author.** Author and approver must
  be different people.
- **No non-public content.** Never commit customer data, PII, credentials,
  access tokens, internal workspace URLs, or proprietary information. `.yxmd`
  fixtures must be synthetic.
- Third-party code must be compatibly licensed (Apache-2.0, MIT, BSD).

## Development Setup

```bash
make dev        # install with all dev dependencies
```

## Before You Open a PR

Run the full local gate and make sure it passes:

```bash
make all        # lint (ruff) + typecheck (mypy) + tests (pytest)
```

Or individually:

```bash
make lint
make typecheck
make test
```

## Adding a New Tool Converter

See [docs/adding-tool-converters.md](docs/adding-tool-converters.md) for the
step-by-step guide. In short:

1. Add a converter in `src/a2d/converters/<category>/` using
   `@ConverterRegistry.register`.
2. Add an IR node in `src/a2d/ir/nodes.py` if needed.
3. Register the plugin name in `src/a2d/parser/schema.py`.
4. Add visitor methods in the PySpark, DLT, and SQL generators (Lakeflow
   inherits from SQL).
5. Add a unit test under `tests/unit/converters/`.

## Code Conventions

- Python 3.10+, type hints on all public functions.
- `dataclasses` for data models (not attrs/pydantic).
- Tests mirror the source layout under `tests/unit/`; fixtures in
  `tests/fixtures/`.

## License

By contributing, you agree that your contributions will be licensed under the
[Databricks License](LICENSE.md).
