# Contributing

Thanks for your interest in the Mosquitto charm.

## Before you start

- Check the
  [existing issues](https://github.com/tonyandrewmeyer/mosquitto-operator/issues)
  to see whether your problem or idea has already been raised. If it has not,
  please
  [open an issue](https://github.com/tonyandrewmeyer/mosquitto-operator/issues/new/choose)
  describing your use case before writing a large change — that is much less
  frustrating than having a finished pull request turned down.
- For anything security-related, follow [SECURITY.md](SECURITY.md) rather than
  opening an issue.
- This project follows the
  [Ubuntu Code of Conduct v2.0](.github/CODE_OF_CONDUCT.md).
- If you are new to charming, the
  [Ops documentation](https://documentation.ubuntu.com/ops/) and the
  [charm development best practices](https://documentation.ubuntu.com/ops/latest/reference/best-practices/)
  are the place to start.

## Prerequisites

| Tool | Why | Install |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Manages Python and the dependency groups; `uv.lock` is the single source of truth for every tool version. | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [tox](https://tox.wiki/) 4.21+ | Runs every check. The `tox-uv` plugin is auto-provisioned from `[tox] requires`, so a bare `tox` is enough. | `uv tool install tox --with tox-uv` |
| [charmcraft](https://canonical-charmcraft.readthedocs-hosted.com/) | Packs the `.charm`. | `sudo snap install charmcraft --classic` |
| [LXD](https://canonical.com/lxd) | Charmcraft's build backend, and the machine cloud the integration tests deploy to. | `sudo snap install lxd && sudo lxd init --auto` |
| [Juju](https://juju.is/) 3.6 or later | Deploying the charm. | `sudo snap install juju` |
| [concierge](https://github.com/canonical/concierge) | Sets all of the above up in one command. Recommended. | `sudo snap install --classic concierge` |

The quickest route to a working environment is concierge:

```shell
sudo snap install --classic concierge
sudo concierge prepare -p machine
```

That installs LXD, initialises it, installs charmcraft and snapcraft, and
bootstraps a Juju controller onto the LXD cloud. `sudo concierge restore` is
the exact inverse.

Then:

```shell
git clone https://github.com/tonyandrewmeyer/mosquitto-operator
cd mosquitto-operator
uv sync --all-groups
```

## Dependencies

Dependencies live in `pyproject.toml`:

- `[project].dependencies` — the charm's **runtime** dependencies. These, and
  only these, are installed into the venv inside the `.charm`. Anything a
  Charmhub library in `lib/` declares in its `PYDEPS` must be listed here too.
- `[dependency-groups]` — `lint`, `unit`, `functional` and `integration`.
  There is deliberately **no `dev` group**: the charmcraft uv plugin runs
  `uv sync` at pack time, and `uv sync` installs `dev` by default, so a `dev`
  group would ship every linter and test tool inside the `.charm`.
  `[tool.uv] default-groups = []` is there as belt and braces.

Add dependencies with uv rather than by hand — `uv add pydantic`, or
`uv add --group unit pytest-mock` — and commit the updated `uv.lock`. CI runs
`uv lock --check`, so a pull request that edits `pyproject.toml` without
relocking fails early.

## Testing

Every environment installs from `uv.lock`, so the tool versions are identical
locally, in CI, and in the pre-commit hooks.

```shell
tox run -e format        # apply formatting: ruff format, then ruff check --fix
tox run -e lint          # codespell, ruff check, ruff format --check
tox run -e static        # pyright, in strict mode
tox run -e unit          # unit tests (ops.testing) under coverage, fail_under=80
tox run -e functional    # functional tests: the real workload, no Juju
tox run -e integration   # integration tests: a real Juju controller
tox                      # runs 'format', 'lint', 'static' and 'unit'
```

`tox` on its own deliberately skips `functional` and `integration`, so it is
safe to run on a laptop with no controller and no Mosquitto installed.

- **Unit tests** use
  [`ops.testing`](https://documentation.ubuntu.com/ops/latest/reference/ops-testing/)
  and need no Juju controller. `tox -e unit` also writes `coverage.xml`, which
  CI uploads. Its `fail_under = 80` counts the unit suite alone, and the unit
  suite deliberately does not reach the half of `src/mosquitto.py` that talks to
  apt, systemd and a real broker — `tox -e functional` reports coverage of that
  separately, as `coverage-functional.xml`, ungated.
- **Functional tests** exercise the workload-interaction code against a real
  Mosquitto installation, without Juju in the picture. They install packages and
  drive systemd, so they need root and only run when
  `MOSQUITTO_FUNCTIONAL_TESTS=1` is set — do that in a throwaway machine, not on
  your laptop. CI runs them on every pull request, on a GitHub runner, because
  they are the only tests that cover `src/mosquitto.py` against real apt and
  real systemd.
- **Integration tests** use [Jubilant](https://documentation.ubuntu.com/jubilant/)
  and `pytest-jubilant`, and need a bootstrapped controller. Each file gets its
  own model, so `tests/integration/test_snap.py` deploys onto the snap while the
  rest use the archive.

`tox -e audit` runs `pip-audit` over the locked *runtime* dependencies — the
graph that ships inside the `.charm` and runs as root on the unit — and CI runs
it on every pull request. An advisory that is genuinely unreachable from this
charm can be ignored in `tox.ini`, but only alongside the analysis that says
why it is unreachable and what would make it reachable again.

### Running the integration tests

The integration tests do not pack the charm. Pack first, then either leave the
`.charm` in the project directory or point at it with `CHARM_PATH`:

```shell
charmcraft pack
CHARM_PATH=./mosquitto_amd64.charm tox run -e integration
```

To test against a particular Juju version, provision that version and then run
the tests. CI does exactly this, as a matrix over `3.6/stable` and
`4.0/stable`:

```shell
sudo concierge restore                                    # tear down what is there
sudo concierge prepare --verbose --juju-channel=4.0/stable -p machine
CHARM_PATH=./mosquitto_amd64.charm tox run -e integration
```

Anything after `--` is passed through to pytest, so
`tox run -e integration -- -k tls --juju-dump-logs logs` works as you would
expect.

Please add tests with every behavioural change. New code should keep unit test
coverage at or above its current level; the build fails below 80%.

## Building the charm

```shell
charmcraft pack
charmcraft analyse ./mosquitto_amd64.charm
```

Packing needs a few GB of free disk space, and is much happier with four or
more cores and 8 GB of RAM. To try the result out:

```shell
juju add-model dev
juju model-config logging-config="<root>=INFO;unit=DEBUG"
juju deploy ./mosquitto_amd64.charm
juju status --watch 1s
juju debug-log
```

## pre-commit

The hooks run the same ruff, codespell and pyright that tox does, at the same
locked versions — they are `repo: local` hooks that shell out to
`uv run --frozen`, so there is no second set of version pins to keep in step.

```shell
uv tool install pre-commit
pre-commit install
```

[prek](https://github.com/j178/prek) is a faster drop-in replacement that reads
the same `.pre-commit-config.yaml`, and is worth using if the hooks feel slow:

```shell
uv tool install prek
prek install
```

## Code style

- [Ruff](https://docs.astral.sh/ruff/) handles formatting and linting; the
  configuration is in `pyproject.toml`. Line length is 99, quotes are single.
  Run `tox run -e format` before pushing, and do not hand-format around it.
- Type annotations everywhere, checked with
  [Pyright](https://microsoft.github.io/pyright/) in strict mode via
  `tox run -e static`.
- Import modules, not objects: `import pathlib` and `pathlib.Path(...)`, not
  `from pathlib import Path`. Names from `typing` (and `typing_extensions`, and
  `__future__`) are the exception. Ruff's `ICN003` enforces this against a
  curated module list in `pyproject.toml`; the rule applies everywhere, not
  just to the listed modules.
- Google-style docstrings on all public modules, classes and functions.
- Every source file starts with the two-line header:

  ```python
  # Copyright 2026 Tony Meyer
  # See LICENSE file for licensing details.
  ```

- Follow the
  [charm development best practices](https://documentation.ubuntu.com/ops/latest/reference/best-practices/):
  keep `src/charm.py` thin and holistic, use `collect-unit-status` rather than
  setting status ad hoc, never catch exceptions you cannot handle, and never
  log secrets or relation credentials.
- British English in prose, comments, docstrings and commit messages. American
  spellings only inside identifiers that mirror an external API.

## Commit messages and pull requests

- Commits **must** follow
  [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/):
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`,
  `chore:`, with an optional scope (`fix(tls): ...`) and either a `!` or a
  `BREAKING CHANGE:` footer for incompatible changes. The changelog is
  organised around these, so they matter.
- Add a `CHANGELOG.md` entry under `## [Unreleased]` for anything a charm user
  would notice. `[Unreleased]` accumulates entries as work lands, and is
  renamed to the release heading when a revision is published to Charmhub —
  so put your entry there rather than inventing a version number. Changes that
  are invisible to users (refactors, test-only changes, CI tweaks) do not need
  an entry.
- Keep pull requests focused, and rebase onto `main` rather than merging it in,
  so the history stays linear.
- Fill in the pull request template, including the checklist.
- CI (lint, static, unit, functional, pack, and integration against both Juju
  3.6 and 4.0) must be green before merge.

## Licence

This project is licensed under the Apache Licence 2.0 — see [LICENSE](LICENSE).
By contributing, you agree that your contributions are licensed under the same
terms (Apache-2.0 §5). There is no separate contributor licence agreement.
