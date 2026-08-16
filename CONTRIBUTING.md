# Contributing to fitbit-mcp

Thanks for your interest in contributing. This is a community MCP server for the Fitbit Web API.

## Getting started

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A [Fitbit developer account](https://dev.fitbit.com/apps) with a registered personal app

### Set up the dev environment

```bash
git clone https://github.com/partymola/fitbit-mcp
cd fitbit-mcp
uv venv --python 3.13 .venv
uv pip install -e ".[dev]"
```

### Install the pre-commit hook

The repo ships with `scripts/check-no-data.sh`, which blocks commits that contain databases, tokens, or other secrets:

```bash
ln -sf ../../scripts/check-no-data.sh .git/hooks/pre-commit
```

Please install it before your first commit.

### Run the test suite

```bash
.venv/bin/python -m pytest tests/ -v
```

### Run lint and formatting checks

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff format --check src tests
```

Tests are fully offline - no real API calls, no real tokens. Fixtures use fictional data and fixed past dates; never paste real health measurements into tests.

## Making changes

- **Open an issue first** for non-trivial changes (new tools, schema migrations, new data types, breaking changes). Small fixes (typos, bug fixes, docs) can go straight to a PR.
- Keep PRs small and focused.
- Add or update tests for any behaviour change.
- **Changing the database schema takes three edits, not one**: the column in `SCHEMA`, an `ALTER` in `db._migrate()` so existing databases get it, and the outgoing schema copied into `tests/schema_baselines/` so the check can see that they do. Skip the second and `fitbit-mcp doctor` tells a user with years of history to re-create their cache. Skip the third and nothing complains at all - the check simply stops covering the table you changed.
- Run `pytest tests/ -v` before opening a PR.

## Releases (maintainers)

1. Bump `version` in `pyproject.toml`, run `uv lock` so the tracked lockfile records the new version, and turn the `[Unreleased]` CHANGELOG heading into `## [X.Y.Z] - YYYY-MM-DD`, adding the compare link at the foot of the file.
2. Push to `main` and wait for CI to pass on that commit.
3. Tag it `vX.Y.Z` and push the tag by name.
4. Create the GitHub Release.

Step 4 is what publishes: `publish.yml` runs on `release: published`, not on the tag push, so the tag on its own ships nothing. It builds the distribution, checks the sdist for secret-shaped files, uploads to PyPI via Trusted Publishing, then registers the release in the MCP registry.

**Do not hand-edit `server.json`'s `version` or `packages[0].version`.** The workflow rewrites both from the tag before publishing, so the values committed to the repo are deliberately left behind and are not a bug. To see what actually published, query the registry rather than reading the file:

```bash
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.partymola/fitbit-mcp"
```

The registry step can fail on its first attempts while PyPI's description catches up; it retries, and a failure there means the PyPI upload still succeeded. `--version` reads the installed package metadata, so it follows `pyproject.toml`.

## Pull requests

- Branch off `main`.
- Reference any related issue.
- Maintainer aims to reply within ~7 days. Feel free to bump if you don't hear back.

## Reporting issues

Helpful details to include:

- Python version (`python --version`)
- MCP client (Claude Desktop, Claude Code, other)
- Fitbit device model if relevant
- Steps to reproduce
- Relevant log output, with any tokens, user IDs, or measurement values redacted

## Security

Please do not open a public issue for credential, OAuth-flow, or token-leak issues. Use [GitHub's private vulnerability reporting](https://github.com/partymola/fitbit-mcp/security/advisories/new) instead.

## License

By contributing, you agree that your contributions are licensed under GPL-3.0-or-later, the project's license.
