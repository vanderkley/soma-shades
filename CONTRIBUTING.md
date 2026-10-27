# Contributing

## Development
```bash
git clone https://github.com/vanderkley/soma-shades.git && cd soma-shades
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pre-commit install
```

| Check      | Command                                                     |
|------------|-------------------------------------------------------------|
| Tests      | `pytest` (the end-to-end tests need `mosquitto` installed)  |
| Lint       | `ruff check . && ruff format --check .`                     |
| Type check | `mypy`                                                      |

The CI runs the checks on Python 3.11 and 3.14. The tests use a fake Bluetooth stack, so test changes to the
Bluetooth protocol with real shades too.

## Release
1. Update the version in `pyproject.toml`, and move the changes under *Unreleased* in [CHANGELOG.md](CHANGELOG.md)
   to a section with the version and date.
2. Push the change to `main` and wait until the CI passes.
3. Push a tag with the version:
   ```bash
   git tag -a v1.1.0 -m "soma-shades 1.1.0"
   git push origin v1.1.0
   ```

The [release workflow](.github/workflows/release.yml) builds the package, publishes it to PyPI through trusted
publishing (the `pypi` environment), pushes the Docker image to `ghcr.io/vanderkley/soma-shades`, and creates a GitHub
release. A version on PyPI cannot be replaced, a failed upload can be retried with *Re-run failed jobs*.
