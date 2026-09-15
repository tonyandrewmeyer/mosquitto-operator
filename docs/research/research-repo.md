<!--
Research notes for the repository infrastructure of tonyandrewmeyer/mosquitto-operator.
Compiled 2026-09-15. Scratchpad document - not part of the repository.
-->

# Repository infrastructure: current best practice (September 2026)

For **`tonyandrewmeyer/mosquitto-operator`** — a Juju machine charm, uv-managed, published to
Charmhub.

Local toolchain observed while researching: `charmcraft 4.4.2`, `uv 0.9.18`, `tox` present.
The working tree already contains the output of `charmcraft init --profile=machine` from
charmcraft 4.4, so much of what follows is framed as a **delta from that scaffold** rather than
a from-scratch design.

## The three findings that matter most

1. **There is an official Canonical charm Python style guide**, at
   <https://github.com/canonical/charm-tech/blob/main/style/python.md>. It codifies line length
   99, single quotes, pyright strict, a specific ruff rule set — and, notably, the exact house
   rule about importing modules rather than objects. Cite it rather than reverse-engineering
   conventions from individual repos. Spec **OP061** in the same repo mandates the
   `format`/`lint`/`unit`/`integration`/`docs` command names, which matches the house tox
   requirement exactly.
2. **The charmcraft `uv` plugin runs `uv sync` at pack time, and `uv sync` installs the `dev`
   group by default.** Therefore a charm's `pyproject.toml` must **not** define a `dev` group (the
   scaffold correctly uses `lint`/`unit`/`integration` instead). Get this wrong and your dev tools
   ship inside the `.charm`. See §1.3.
3. **`charmed-kubernetes/actions-operator` is effectively legacy**; `concierge` is now the way to
   provision Juju and LXD in CI. `canonical/charming-actions` is in maintenance mode. See §4.

## Contents

1. [Project layout and packaging](#1-project-layout-and-packaging)
2. [Ruff](#2-ruff)
3. [Type checking](#3-type-checking)
4. [GitHub Actions, zizmor, dependency updates and publishing](#4-github-actions-zizmor-dependency-updates-and-publishing)
5. [pre-commit](#5-pre-commit)
6. [tox](#6-tox)
7. [Repo hygiene files](#7-repo-hygiene-files)

---

# Repository infrastructure best practice for `tonyandrewmeyer/mosquitto-operator`

Research date: 2026-09-15. Local toolchain observed: `charmcraft 4.4.2`, `uv 0.9.18`.
The repo already contains the output of `charmcraft init --profile=machine` from charmcraft 4.4,
so several recommendations below are framed as deltas from that scaffold.

---

## 1. Project layout and packaging

### 1.1 What charmcraft 4.4 already gives you

`charmcraft init --profile=machine` in 4.4 scaffolds a **uv-native** project. The generated
`charmcraft.yaml` uses the uv plugin directly:

```yaml
parts:
  charm:
    plugin: uv
    source: .
    build-snaps:
      - astral-uv
```

So: **yes, `parts.<name>.plugin: uv` exists and is the current default for machine and
Kubernetes profiles.** The old `plugin: charm` (which drove `pip install -r requirements.txt`)
is legacy; there is an official migration guide
(<https://canonical.com/juju/docs/charmcraft/4/howto/migrate-plugins/charm-to-uv/>).
Charmcraft 4 ships five part plugins: `python`, `poetry`, `uv`, `dump`, `nil`
(<https://canonical.com/juju/docs/charmcraft/en/stable/reference/parts/>).

### 1.2 What the uv plugin requires and does

From <https://canonical.com/juju/docs/charmcraft/4/reference/plugins/uv_plugin/>:

- Requires `pyproject.toml` and — because `UV_FROZEN` defaults to **true** — `uv.lock`.
  "If true, `uv.lock` must exist and will be used as the single source of truth for dependency
  versions, with no attempt made to update them before installation."
- The plugin does **not** provision uv itself. You supply it via `build-snaps: [astral-uv]`
  (what the scaffold does) or a custom `uv-deps` part that stages the uv binary.
- Plugin keywords:
  - `uv-extras` — list; each element passed as `--extra EXTRA`.
  - `uv-groups` — list; each element passed as `--group GROUP`.
  - `python-keep-bins` — bool, default `false`; whether scripts stay in `venv/bin`.
- Relevant env defaults: `UV_FROZEN=true`, `UV_PROJECT_ENVIRONMENT=${CRAFT_PART_INSTALL}`,
  `UV_PYTHON_DOWNLOADS=never`, `UV_PYTHON=${PARTS_PYTHON_INTERPRETER}`,
  `UV_PYTHON_PREFERENCE=only-system`, `UV_COMPILE_BYTECODE=true`.
- Build step: creates `${CRAFT_PART_INSTALL}/venv`, runs `uv sync` against `pyproject.toml` +
  `uv.lock` with the requested groups/extras, then copies `src/` and `lib/` into the charm.

### 1.3 The key interaction: `[dependency-groups]` and what ships in the `.charm`

This is the part people get wrong. Two independent facts combine:

1. PEP 735 dependency groups are **never** included when building or publishing a distribution —
   only `[project].dependencies` and `[project.optional-dependencies]` are
   (<https://docs.astral.sh/uv/concepts/projects/dependencies/>).
2. The charmcraft uv plugin runs `uv sync` in the build environment, and `uv sync` **by default
   installs the `dev` group** (uv's `default-groups` is `["dev"]`).

Consequences:

- **Do not create a `dev` group** in a charm's `pyproject.toml`, or set
  `[tool.uv] default-groups = []`. Otherwise every dev tool (ruff, pyright, pytest) is at risk of
  being synced into the charm's venv and shipped inside the `.charm`, bloating it and enlarging
  the attack surface. The charmcraft 4.4 scaffold deliberately uses `lint`, `unit`, `integration`
  — **not** `dev`. Keep it that way. This is the single most important packaging decision here.
- Anything the **charm runtime** needs at execution time must be in `[project].dependencies`.
  That includes the `PYDEPS` of any Charmhub library you `charmcraft fetch-libs` (the libraries
  themselves land in `lib/` and are copied verbatim, but their Python dependencies are not).
- If you want to keep charm-lib PYDEPS visually separate from your own direct deps, the
  documented pattern is a group plus an explicit opt-in at pack time:

  ```toml
  [dependency-groups]
  charmlibs-pydeps = ["cosl", "pydantic", "cryptography"]
  ```
  ```yaml
  parts:
    charm:
      plugin: uv
      source: .
      build-snaps: [astral-uv]
      uv-groups:
        - charmlibs-pydeps
  ```
  For a charm with few or no Charmhub libs (mosquitto likely), skip this and just use
  `[project].dependencies`.

### 1.4 Recommended `pyproject.toml` `[project]` / `[dependency-groups]`

The scaffold's `requires-python = ">=3.10"` is wrong for this charm. `base: ubuntu@24.04` means
the charm runs on Python 3.12. Pin to what you actually target — otherwise ruff's
`target-version`, pyright's `pythonVersion` and `uv`'s resolver all solve for 3.10 and you lose
3.12 syntax and get needless back-compat shims.

```toml
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

[project]
name = "mosquitto"
version = "0.0.1"
description = "A Juju charm for the Eclipse Mosquitto MQTT broker."
requires-python = ">=3.12"          # ubuntu@24.04 ships Python 3.12

# Runtime dependencies of the charm code in src/. These, and only these, are
# installed into the venv inside the .charm.
dependencies = [
    "ops~=3.7",
]

[dependency-groups]
# NB: deliberately NO `dev` group -- see below.
lint = [
    "codespell",
    "ruff",
]
typing = [
    "pyright",
    # stubs and anything else needed to typecheck src/ and tests/
    {include-group = "unit"},
    {include-group = "integration"},
]
unit = [
    "coverage[toml]",
    "ops[testing]",
    "pytest",
]
integration = [
    "jubilant>=1.8,<2",
    "pytest",
    "pytest-jubilant>=2.0.1,<3",
]

[tool.uv]
# Belt and braces: even if a `dev` group is added later, never sync it implicitly.
# This matters because `charmcraft pack` runs `uv sync` in the build environment.
default-groups = []
```

Notes:

- `{include-group = "..."}` is PEP 735 group nesting, supported by uv
  (<https://docs.astral.sh/uv/concepts/projects/dependencies/>). It is the clean way to make a
  `typing` group that can see the test dependencies without duplicating them — you cannot
  typecheck `tests/` without `pytest` and `ops[testing]` installed.
- The scaffold lumps pyright into `lint`. Splitting `lint` (fast, no project deps) from `typing`
  (slow, needs everything) means `tox -e lint` stays quick. If you prefer the scaffold's single
  group, that is defensible — just accept that `lint` then pulls the whole test stack.
- Add a `docs` group only if you actually build docs.

### 1.5 `uv.lock`

**Commit it.** It is required by the uv plugin at pack time (`UV_FROZEN=true`), it is what
`tox-uv`'s lock runner reads, and charmcraft's own reference page says charmcraft creates it for
the machine profile and that you "shouldn't manually edit this file"
(<https://canonical.com/juju/docs/charmcraft/4/reference/files/uv-lock-file/>).

Keeping it fresh:

- Change deps only via `uv add` / `uv remove` (updates `pyproject.toml` and the lock together),
  or edit `pyproject.toml` and run `uv lock`.
- Periodic refresh: `uv lock --upgrade` (all) or `uv lock --upgrade-package ruff` (one).
- **CI gate:** `uv lock --check` fails if the lock is stale relative to `pyproject.toml`
  (<https://docs.astral.sh/uv/concepts/projects/sync/>). Run this in the lint job — it is the
  cheapest possible check and it catches the classic "edited pyproject.toml, forgot to relock"
  PR, which would otherwise fail much later at `charmcraft pack`.
- Same thing locally via the `uv-lock` pre-commit hook (see §5).
- Automate bumps with Dependabot/Renovate (see §4).

### 1.6 Layout

```
mosquitto-operator/
├── .editorconfig
├── .github/
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── ISSUE_TEMPLATE/{bug_report.yml,feature_request.yml,config.yml}
│   ├── pull_request_template.md
│   └── workflows/{ci.yaml,release.yaml,zizmor.yaml,scorecard.yaml}
├── .gitignore
├── .pre-commit-config.yaml
├── .zizmor.yml
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── SECURITY.md
├── charmcraft.yaml
├── pyproject.toml
├── tox.ini
├── uv.lock
├── lib/charms/...        # fetched Charmhub libs -- COMMITTED, not gitignored
├── src/{charm.py,mosquitto.py}
└── tests/{unit/,integration/}
```

`lib/` is committed: `charmcraft fetch-libs` output is vendored in every Canonical charm repo so
that packing is reproducible and offline-capable, and because `PYTHONPATH` includes `lib` at
runtime. Do not put `lib/` in `.gitignore`; do exclude it from ruff/pyright/codespell, because it
is third-party code you do not control.

---

## 2. Ruff

### 2.1 The authoritative source: there *is* an official Canonical charm Python style guide

The single most important finding in this whole report:
**<https://github.com/canonical/charm-tech/blob/main/style/python.md>**
(raw: `https://raw.githubusercontent.com/canonical/charm-tech/refs/heads/main/style/python.md`).
It is referenced from `canonical/operator`'s `CONTRIBUTING.md` and `AGENTS.md`. Cite this rather
than reverse-engineering conventions from individual repos.

Its rules:

1. **Import modules, not objects** — "An exception is names from `typing`." *This is exactly the
   house rule, and it is Canonical's own documented rule.* You are not inventing local policy.
2. **Use relative imports inside a package** — `from . import charm`, or
   `from . import charm as _charm` to avoid exporting the name.
3. Avoid nested comprehensions and generator expressions.
4. Compare `enum.Enum` values by identity (`is`), not `==`.

And a "Tooling configuration" section that settles most of this question:

> - **Line length is 99.**
> - **Single quotes** for strings (`ruff format` `quote-style = "single"`).
> - **Type-checking is `strict`** (pyright), with `reportPrivateUsage = false` and
>   `reportUnnecessaryTypeIgnoreComment = "error"`.
> - **Set `target-version` / `pythonVersion` to the project's actual minimum supported Python** —
>   don't leave it stale.
> - **Coverage runs with `branch = true`.**
> - The agreed **ruff rule set** is `F`, `E`, `W`, `I001`, `N`, `A`, `CPY`, `UP`, `YTT`, `S`, `B`,
>   `SIM`, `RUF`, `PERF`, `D`, `FA`, `TC` — ignoring `TC001`–`TC003`, `S101`, and `D105`/`D107`.
>   Tests additionally drop `D` and `S101`/`S105`/`S106`.

The guide says a ready-to-copy `pyproject.toml` will eventually be distributed via a shared
template ([canonical/charm-tech#6](https://github.com/canonical/charm-tech/issues/6)) —
**that template does not exist yet**, so hand-rolling from the rule list above is correct today.

Related: spec **OP061** (`specs/OP061-linting-and-testing-command-standardisation-in-charms.md`,
status Approved) mandates the command names `format`, `lint`, `unit`, `integration`, `docs`,
runnable from the repo root, with bare `tox` running `lint` + `unit`. That is precisely the house
tox requirement in §6, so the two are aligned. Notably OP061 now says static type checking may be
"pyright, **ty**, or mypy".

### 2.2 What real repos actually have

**`canonical/operator`** (<https://raw.githubusercontent.com/canonical/operator/main/pyproject.toml>)
is the reference implementation of the guide: `line-length = 99`, `target-version = "py310"`,
`[tool.ruff.format] quote-style = "single"`, the rule set above, `convention = "google"`, and a
`[tool.ruff.lint.flake8-builtins] builtins-ignorelist`.

> **Gotcha, verified empirically:** operator selects and ignores rules **by name**
> (`select = ["unsorted-imports"]`, `ignore = ["typing-only-first-party-import", ...]`) rather
> than by code. That **requires preview mode**:
>
> ```
> $ uvx ruff@0.16.7 check --config ruff.toml
> ruff failed
>   Cause: Invalid selector `unsorted-imports` in `select`. Selecting rules by name requires preview mode
> ```
>
> operator gets away with it only because its `tox.ini` runs `ruff check --preview` and
> `ruff format --preview`. **Do not copy the name-based selectors** unless you also set
> `preview = true`. Use codes.

**Data Platform charms** (`postgresql-operator`, `postgresql-k8s-operator`, `mysql-operator`) set
`preview = true` + `explicit-preview-rules = true` purely to get `CPY001`. That is now **stale**:
CPY001 has been stable since ruff 0.16.0. Drop both flags. They also still carry the comment
"Ignore E501 because using black creates errors with this" despite no longer using black.

**`canonical/kafka-operator`** is the most dated (still `black ^26.3.0` + `isort profile=black`
alongside ruff), but has one pattern worth stealing: **every `lib/` directory, including those of
nested test charms, is in `extend-exclude`.**

**`charmcraft init --profile=machine`** (the scaffold now in this repo) is markedly weaker than
the style guide: **no `target-version`**, **no `[tool.ruff.format]`**, and **no
`pydocstyle.convention = "google"`** — which is why it carries a long list of `D2xx`/`D4xx`
ignores that the Google convention would have disabled automatically. Treat the scaffold as a
floor, not a target.

### 2.3 Enforcing "import modules, not objects" in ruff

**Short answer: partially, with `ICN003` and `flake8-import-conventions.banned-from`, and only
against an explicit list of modules. There is no wildcard.**

```toml
[tool.ruff.lint]
select = ["ICN"]

[tool.ruff.lint.flake8-import-conventions]
banned-from = ["ops", "subprocess", "json", "pathlib"]
```

- Settings: <https://docs.astral.sh/ruff/settings/#lint_flake8-import-conventions>
- Rule: <https://docs.astral.sh/ruff/rules/banned-import-from/> — `ICN003`, `banned-import-from`,
  stable since v0.0.263, category `pedantic`, **no autofix**
  ([#6372](https://github.com/astral-sh/ruff/issues/6372) still open).
- The docs' own example is `banned-from = ["typing"]` — the exact opposite of the house rule,
  amusingly.

**Limitations, all verified empirically against ruff 0.16.7:**

1. **An explicit list is required. No wildcard, no glob, no prefix match, no "all stdlib"
   shortcut.** [astral-sh/ruff#10664](https://github.com/astral-sh/ruff/issues/10664) —
   "`ICN003`: Allow banning all `from` stdlib imports", opened 29 March 2024 — is **still open,
   unassigned, no comments, no PR**.
2. **Matching is exact string equality on the dotted module name.** The implementation is a
   one-line `banned_conventions.contains(name)` over a hash set. So `banned-from = ["os"]`
   catches `from os import path` but **not** `from os.path import join`; submodules must be
   listed separately.
3. Relative imports (`from . import sibling`) are never flagged — which happens to match the
   charm-tech "use relative imports inside a package" rule exactly.
4. It flags only the import statement, not usage, and says nothing about aliasing.

**What does *not* work: `TID251` `banned-api`.** Tempting, but wrong.
`[tool.ruff.lint.flake8-tidy-imports.banned-api]` bans a *qualified name everywhere it appears*,
not just in `from` clauses. Tested:

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"ops.CharmBase" = { msg = "import ops instead" }
```
```python
import ops
class C(ops.CharmBase): ...   # -> TID251 `ops.CharmBase` is banned
```

It fires on the *correct* code too. Unusable for this rule. (`banned-api` remains right for
genuine bans, e.g. `"urllib.request.urlopen" = {msg = "use requests instead"}`.)

**The other TID rules**, for completeness: `TID251` banned-api (stable), `TID252` relative-imports
(stable, autofix, default `ban-relative-imports = "parents"` — keep the default, it permits
`from . import x` as the style guide wants), `TID253` banned-module-level-imports (stable),
`TID254` lazy-import-mismatch and `TID255` lazy-import-immediately-resolved (both **preview**, new
in 2026, and about *lazy* imports, not `from`-import style).
**There is no new ruff rule for this house rule as of 0.16.7.**

**Nobody at Canonical enforces it mechanically.** A GitHub code search across `org:canonical`
finds **zero** `pyproject.toml` files containing `banned-from`. The charm-tech import rule is
enforced by code review and `AGENTS.md`, not CI.

**Practical recommendation:** curate a list of the modules the charm actually imports — 20–30
entries, and stable. Regenerate occasionally:

```bash
python3 - <<'EOF'
import ast, pathlib
mods = set()
for p in pathlib.Path('.').rglob('*.py'):
    if any(part in {'lib', '.tox', '.venv'} for part in p.parts):
        continue
    for node in ast.walk(ast.parse(p.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module)
print(sorted(mods - {'typing', 'typing_extensions', '__future__'}))
EOF
```

Always exempt `typing`, `typing_extensions` and `__future__` by simply never listing them. If you
want airtight enforcement across every module, ruff cannot do it — that needs ~15 lines of `ast`
in a `tests/test_style.py` or a `language: system` pre-commit hook. Given the charm-tech guide
itself doesn't enforce it mechanically, the curated ICN003 list is the right cost/benefit.

### 2.4 Ruff: what changed for 2026

- **0.16.7, released 2026-09-10** is current.
- **Rule selection by name** (`select = ["unsorted-imports"]`) — preview only, added in 0.16.5
  ([#28049](https://github.com/astral-sh/ruff/pull/28049)). In preview, diagnostics also *print*
  by name rather than code.
- **Category selectors** — preview only, 0.16.5
  ([#27666](https://github.com/astral-sh/ruff/pull/27666)). New categories, highest to lowest
  severity: `correctness`, `suspicious`, `complexity`, `performance`, `style`, `security`,
  `formatting`, `pedantic`, `restriction`. The first five are the preview default set. This is
  the long-term replacement for hand-curated `select` lists — **worth watching, not worth
  adopting yet.**
- **CPY001 went stable in 0.16.0**, so the Data Platform `preview`/`explicit-preview-rules`
  workaround is obsolete.
- **ANN101 / ANN102 were removed in 0.8.0** (`missing-type-self`, `missing-type-cls`). Do not put
  them in `ignore` — ruff errors on unknown rules. Plenty of 2025-era configs still carry them.
- The top-level `select` → `lint.select` move is ancient history (0.2/0.5). `ruff format` is fully
  stable; some Canonical repos still set `[tool.ruff.format] preview = true` for preview
  *formatter* behaviours only.
- **`S602`/`S603`/`S607`/`S609` now also check keyword arguments** (0.16.3,
  [#27687](https://github.com/astral-sh/ruff/pull/27687)) — a `subprocess.run(args=...)` that was
  clean in 2025 may now trip. Directly relevant to a machine charm that shells out.
- **black and isort are finally gone** from the Charm Tech and Data Platform stacks (kafka is the
  laggard). `ruff format` with `quote-style = "single"` is the standard.

### 2.5 Recommended ruff configuration

This is the charm-tech agreed set plus the extras requested, plus the import rule. It has been
checked against a fake charm tree (`src/`, `tests/unit/`, `lib/charms/foo/v0/`) under ruff
0.16.7: it parses, `lib/` is skipped, and ICN003 fires correctly.

```toml
# Linting tools configuration
[tool.ruff]
line-length = 99
target-version = "py312"          # keep in sync with requires-python
# Charm libs fetched with `charmcraft fetch-libs` are third-party code: never lint them.
extend-exclude = ["lib", "__pycache__", "*.egg_info"]

[tool.ruff.format]
quote-style = "single"

[tool.ruff.lint]
select = [
    "F",    # Pyflakes
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "I001", # isort: unsorted-imports
    "N",    # pep8-naming
    "A",    # flake8-builtins
    "CPY",  # flake8-copyright
    "UP",   # pyupgrade
    "YTT",  # flake8-2020
    "S",    # flake8-bandit
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific
    "PERF", # perflint
    "D",    # pydocstyle
    "FA",   # flake8-future-annotations
    "TC",   # flake8-type-checking
    # Beyond the charm-tech agreed set:
    "C4",   # flake8-comprehensions
    "PT",   # flake8-pytest-style
    "ICN",  # flake8-import-conventions ("import modules, not objects")
    "TID",  # flake8-tidy-imports
    "LOG",  # flake8-logging
    "G",    # flake8-logging-format
]
ignore = [
    # Don't force imports into `if TYPE_CHECKING` blocks.
    "TC001", "TC002", "TC003",
    # `assert` is fine.
    "S101",
    # No docstrings required for magic methods or __init__.
    "D105", "D107",
    # Conflict with the D211/D212 that ruff's google convention selects.
    "D203", "D213",
    # We prefer returning the condition explicitly / an explicit try-except.
    "SIM103", "SIM105", "SIM117",
    # We build subprocess argument lists ourselves.
    "S603",
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = [
    "D",                      # no docstrings required in tests
    "S105", "S106", "S107",   # hard-coded "passwords" in fixtures
    "B018",                   # a bare expression is sometimes the assertion
    "PLR2004",                # magic values in assertions
    "CPY",                    # no copyright header on every test file
]
"tests/integration/*" = [
    "S603", "S607",           # these shell out to juju/charmcraft by name
]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.flake8-copyright]
author = "Tony Meyer"
notice-rgx = "Copyright\\s\\d{4}([-,]\\d{4})*\\s+"

[tool.ruff.lint.flake8-builtins]
builtins-ignorelist = ["id", "type", "format", "input", "min", "map", "range"]

[tool.ruff.lint.flake8-tidy-imports]
# The charm-tech style guide *wants* `from . import x` inside a package,
# so ban only parent-relative imports (this is also ruff's default).
ban-relative-imports = "parents"

[tool.ruff.lint.flake8-import-conventions]
# House rule: import modules, not objects. `typing`, `typing_extensions` and
# `__future__` are deliberately absent -- they are the exceptions.
# ICN003 matches the module name exactly: there is no wildcard, and submodules
# (e.g. `os.path`) must be listed separately.
# See https://github.com/astral-sh/ruff/issues/10664
banned-from = [
    # Charming
    "ops", "ops.testing", "ops.pebble", "ops.charm", "ops.model", "ops.framework",
    "jubilant", "charmlibs", "charmlibs.pathops",
    # stdlib we actually use
    "collections", "collections.abc", "contextlib", "dataclasses", "datetime",
    "enum", "functools", "itertools", "json", "logging", "os", "os.path",
    "pathlib", "re", "shutil", "socket", "subprocess", "sys", "tempfile",
    "textwrap", "time", "urllib", "urllib.parse",
    # third party
    "pytest", "requests", "yaml",
]

[tool.ruff.lint.mccabe]
max-complexity = 10
```

Deliberate choices worth flagging:

- **`lib/` is excluded wholesale via `extend-exclude`**, matching kafka-operator and the
  charmcraft template's codespell `skip`. Do *not* try to handle `lib/` with `per-file-ignores` —
  you would have to enumerate every rule. If the repo grows nested test charms, add their `lib`
  dirs too.
- **`ANN` (flake8-annotations) is deliberately omitted.** It is not in the charm-tech agreed set,
  and pyright in strict mode catches missing annotations more precisely and with far less noise
  (ANN complains endlessly about `-> None` on `__init__`). Let pyright do it.
- **`PL` (pylint) is omitted too.** Not in the agreed set, and the PLR rules are noisy for charms
  — `PLR0913` (too many arguments) and `PLR0912`/`PLR0915` (too many branches/statements) fire
  constantly on reconciler-style handlers. If you do enable `PL`, budget for those ignores.
- `S` (bandit) **is** included, per the agreed set, with `S101` globally ignored and `S603`
  ignored because charms legitimately build their own subprocess argument lists.
- `D203`/`D213` in `ignore` are belt-and-braces; `convention = "google"` already disables the
  conflicting ones.
- Set `author` in `flake8-copyright` to your name, not "Canonical Ltd." — this is a personal repo.
  Drop `"CPY"` from `select` entirely if you don't want headers enforced mechanically.

**One tension to resolve:** the style guide says set `target-version` to the project's *actual
minimum supported Python*. The scaffold says `requires-python = ">=3.10"` and `target-version`
is absent. Since `base: ubuntu@24.04` means the charm runs on Python 3.12, `py312` and
`requires-python = ">=3.12"` are the honest values, and they let you use 3.11/3.12 syntax. Only
keep 3.10 if you intend to add `ubuntu@22.04` to `platforms`.

---

## 3. Type checking

Versions live on PyPI as of 2026-09-15: **pyright 1.1.414**, **ty 0.0.81**,
**basedpyright 1.40.1**, **mypy 2.3.1**, ruff 0.16.7.

### 3.1 `ty` status — beta, not GA

- PyPI latest is **`ty` 0.0.81**. Still `0.0.x`; the version number alone tells you it is not 1.0.
- Astral **announced the Beta on 16 December 2025** (<https://astral.sh/blog/ty>): *"Today, we're
  announcing the Beta release of ty. We now use ty exclusively in our own projects and are ready
  to recommend it to motivated users for production use."*
- Stable/1.0 was targeted for 2026 and **has not shipped as of today**. The remaining gap is
  (1) stability and bug fixes, (2) the long tail of the typing spec, (3) first-class support for
  popular third-party libraries.
- Docs: <https://docs.astral.sh/ty/>. Getting started is literally `uvx ty check`.
- Performance claim: 10–60x faster than mypy and pyright, uncached.

`[tool.ty]` configuration (<https://docs.astral.sh/ty/reference/configuration/>):

| Section | Option | Default |
|---|---|---|
| `environment` | `python` | auto-detected — path to interpreter or venv |
| | `python-version` | `"3.14"` (supports `"3.10"`–`"3.15"`) |
| | `python-platform` | current platform (`linux`, `darwin`, `win32`, `all`) |
| | `extra-paths` | `[]` — extra module-resolution paths |
| | `root` | auto-detected first-party roots |
| | `typeshed` | bundled |
| `src` | `include` / `exclude` | auto-detected / `.git/`, `venv/`, … |
| | `respect-ignore-files` | `true` |
| `analysis` | `allowed-unresolved-imports` | `[]` (glob patterns) |
| | `replace-imports-with-any` | `[]` — **the `lib/` escape hatch** |
| | `respect-type-ignore-comments` | `true` |
| | `strict-equality-semantics` / `strict-generic-narrowing` | `false` |
| `rules` | *(rule name)* | `"ignore"` / `"warn"` / `"error"` |
| `terminal` | `output-format` | `"full"` (also `concise`, `github`, `gitlab`, `junit`) |
| | `error-on-warning` | **`false`** — warnings do not fail CI unless you opt in |
| `[[overrides]]` | `include`/`exclude`/`rules`/`analysis` | per-glob overrides |

Note there is **no `typeCheckingMode`-style global strictness dial**. ty's model is per-rule
severities plus a handful of `analysis` toggles.

### 3.2 What Canonical charm repos actually use, today

| Repo | Type checker | Notes |
|---|---|---|
| `canonical/operator` | **pyright**, `typeCheckingMode = "strict"` | `mypy>=1.19` in a separate group *only* to cross-check example charms |
| `canonical/jubilant` | **pyright strict** | `pythonPlatform = "All"` |
| `canonical/charmlibs` | **pyright** | |
| charmcraft machine profile | **pyright** | `[tool.pyright] include = ["src", "tests"]` — that is the *entire* config |
| `canonical/kafka-operator` | **pyright**, `typeCheckingMode = "basic"` | |
| `canonical/postgresql-operator` | **`ty` ^0.0.78** | pyright *removed* |
| `canonical/postgresql-k8s-operator` | **`ty`** | |

**This is the single biggest 2025→2026 change in the charm ecosystem.** The Data Platform team has
migrated off pyright to ty. Charm Tech (operator, jubilant, charmlibs) and the charmcraft
scaffolding have stayed on pyright, and the charm-tech style guide still says *"We use Ruff for
formatting, and run our code through the Pyright type checker"* and *"Type-checking is `strict`
(pyright)"*. Spec OP061 was widened to list ty as acceptable.

`canonical/operator`'s pyright config, verbatim, as the reference:

```toml
[tool.pyright]
include = ["ops/*.py", "ops/_private/*.py", "test/*.py", ...]
exclude = ["tracing/*"]
extraPaths = ["testing", "tracing"]
pythonVersion = "3.10"      # check no python > 3.10 features are used
pythonPlatform = "All"
typeCheckingMode = "strict"
reportIncompatibleMethodOverride = false
reportImportCycles = false
reportMissingModuleSource = false
reportPrivateUsage = false
reportUnnecessaryIsInstance = false
reportUnnecessaryComparison = false
reportUnnecessaryTypeIgnoreComment = "error"
disableBytesTypePromotions = true
stubPath = ""
```

The Data Platform `ty` config is the charm-shaped reference for the other side:

```toml
[tool.ty.environment]
python = ".tox/lint/"
extra-paths = ["./lib"]     # fetched charm libs resolvable but not checked

[tool.ty.src]
include = ["src", "scripts"]
exclude = ["tests"]
```

### 3.3 Recommendation

**Use pyright. Add `ty` as a fast, advisory secondary if you like it, but do not make it the
gate yet.**

Reasoning: pyright is what the charm-tech style guide mandates, what `charmcraft init` scaffolds,
and what `ops` itself is checked with — so `ops`' own inline types are validated against
pyright's inference, not ty's, and you will hit fewer spurious disagreements. ty is still
`0.0.x`. mypy 2.x is out but no charm repo uses it for charm code. **basedpyright** (1.40.1, a
community fork with stricter defaults and no Node dependency) has **zero adoption in the charming
ecosystem** — don't introduce it into a repo you want charm people to contribute to.

Revisit in 6–12 months: if ty hits 1.0 and Charm Tech adopts it, switching is a small change.

### 3.4 Recommended `[tool.pyright]` for a charm

```toml
[tool.pyright]
include = ["src", "tests"]
# `lib/` holds charm libs fetched from Charmhub. They're third-party, frequently
# untyped, and not ours to fix -- resolve imports from them but don't check them.
exclude = ["lib", "**/__pycache__", ".tox", ".venv", "build", "dist"]
extraPaths = ["lib"]
pythonVersion = "3.12"          # keep in sync with requires-python / target-version
pythonPlatform = "Linux"        # charms run on Linux; use "All" for a library
typeCheckingMode = "strict"
# Charm-tech style guide: things that are effectively public still need to be
# private to users.
reportPrivateUsage = false
# Catch stale `# type: ignore` comments.
reportUnnecessaryTypeIgnoreComment = "error"
# Charm libs ship no stubs and often no inline types; without these, every
# `import charms.foo.v0.bar` is an error under strict.
reportMissingTypeStubs = false
reportMissingModuleSource = false
# Charm libs are untyped, so anything crossing that boundary is Unknown.
# Delete these three if you have no lib/ directory -- see below.
reportUnknownMemberType = false
reportUnknownVariableType = false
reportUnknownArgumentType = false
```

**If you have no `lib/` directory** — all charm libs consumed as PyPI `charmlibs-*` packages —
delete `extraPaths`, the `lib` exclude, and the three `reportUnknown*` lines, and you get genuine
strict mode. **That is materially the better place to be**, and it is the 2026 direction of
travel (see §1.3 and §7).

If strict is too much for an existing codebase, `typeCheckingMode = "standard"` is the sensible
intermediate — that has been pyright's default since 1.1.358, and `"basic"` is now just a
compatibility alias (which is what kafka-operator still uses).

`venvPath`/`venv`: leave both unset. With tox + `uv-venv-lock-runner`, pyright runs *inside* the
env it should introspect and discovers it automatically. Only set them
(`venvPath = "."`, `venv = ".venv"`) if you invoke pyright from outside that venv.

### 3.5 Running pyright via uv, without a global install

The [`pyright` PyPI package](https://pypi.org/project/pyright/) is
[RobertCraigie/pyright-python](https://github.com/RobertCraigie/pyright-python), a wrapper: it
looks for `node` on `PATH` and, if absent, downloads Node at runtime via `nodeenv`, then
`npm install`s the real `pyright` npm package.

```bash
# 1. Via the lint/typing dependency group (what charmcraft scaffolds) -- tox handles it:
tox -e static

# 2. Locally, as a project dependency:
uv run --group typing pyright

# 3. Ad hoc, no install at all:
uvx pyright src/
```

**The nodeenv problem, and the fix.** The default nodeenv path is flaky: it needs network on
first run, breaks behind proxies, and on CI runners without a compiler it sometimes tries to
build Node from source. Use the **`nodejs` extra**, which pulls `nodejs-wheel-binaries`
(prebuilt Node as a wheel) instead:

```toml
[dependency-groups]
typing = [
    "pyright[nodejs]>=1.1,<2",   # nodejs-wheel-binaries: no nodeenv download
    ...
]
```

Confirmed present in pyright 1.1.414's metadata (`nodejs-wheel-binaries; extra == "nodejs"`; also
available as `pyright[all]`). Ad hoc equivalent: `uvx --with nodejs-wheel-binaries pyright src/`.

**Pin the npm pyright too.** `PYRIGHT_PYTHON_FORCE_VERSION=1.1.414` pins the *npm* pyright version
independently of the PyPI wrapper version — and it is the npm version that actually determines
your diagnostics. The charmcraft template pins `pyright>=1.1,<2` (the wrapper) but not the npm
package, so a template-generated charm's lint results drift with upstream releases and can break
CI overnight. Set it in the tox env:

```ini
[testenv:static]
set_env =
    {[testenv]set_env}
    PYRIGHT_PYTHON_FORCE_VERSION = 1.1.414
```

(`PYRIGHT_PYTHON_ENV_DIR=~/.cache/nodeenv` caches nodeenv across CI runs if you stay on that
route; the `pyright[nodejs]` extra sidesteps it entirely.)

### 3.6 Running `ty` as an advisory second opinion

```bash
uvx ty check                          # checks the CWD
uvx ty check src tests
uvx ty check --output-format=github   # GHA annotations
uvx ty check --error-on-warning       # make warnings fail (default: they don't)
```

In tox, with a leading `-` so it cannot fail the build:

```ini
[testenv:static]
runner = uv-venv-lock-runner
dependency_groups = typing
commands =
    pyright {posargs}
    - ty check {posargs}     # leading '-': advisory only
```

### 3.7 2025 → 2026 deltas

1. **ty went beta (Dec 2025) and got real charm adoption** — postgresql and postgresql-k8s have
   *replaced* pyright with it. Still `0.0.x`, still no 1.0.
2. **Charm Tech has not moved** — operator, jubilant, charmlibs and the charmcraft profiles are
   all still pyright strict.
3. **The `canonical/charm-tech` style guide is new-ish and is now the authoritative source** for
   the ruff rule set, line length, quote style and pyright strictness. Cite it.
4. **pyright 1.1.414**, and the `pyright[nodejs]` extra using `nodejs-wheel-binaries` is now
   recommended over the legacy nodeenv download.
5. **mypy is at 2.x** but remains a CI-only cross-check in operator, not a charm tool.
6. **Charm libs are moving to PyPI** (`charmlibs-*`), which removes the untyped-`lib/` problem
   that forces the `reportUnknown*` relaxations. Prefer PyPI charm libs in a new repo.

---

## 4. GitHub Actions, zizmor, dependency updates and publishing

Research date: **15 September 2026**. Every action SHA below was resolved live from the GitHub API today; I flag the ones I could not verify.

---

### Executive summary / what I'd actually do

For `tonyandrewmeyer/mosquitto-operator` (a single machine charm, uv-based):

| Concern | 2026 answer |
|---|---|
| Provision Juju + LXD | **`sudo snap install --classic concierge` + `sudo concierge prepare -p machine`**. This is now the documented, mainstream way. |
| `charmed-kubernetes/actions-operator` | **Effectively legacy.** Not archived, no deprecation notice, but last functional change May 2025; last commit at all 2026-04-09 and it was only "pin GitHub Actions to commit SHAs". Latest release `1.1.0` is from **February 2023**. Canonical's own repos have migrated off it to concierge. Don't use it for a new repo. |
| `canonical/setup-lxd` | **Current and useful**, but only as charmcraft's *build backend* — it does not give you Juju. Now has a `v1` tag (Dec 2025). README still says "alpha, pin a SHA". |
| `canonical/craft-actions` | **Current** (commits from 2026-09-14). `charmcraft/setup` and `charmcraft/pack` both exist and work. Only tagged `v0.1.1`/`v0`, so most people use `@main` — I'd pin the SHA. |
| `canonical/charming-actions` | **Maintenance mode.** Last release `2.7.0` (Jan 2025); only two commits since April 2025, the most recent being "run JavaScript actions on Node 24". Still works and is still name-checked by the official ops docs for publishing, but nothing new is landing. For a one-charm repo, plain `charmcraft upload`/`charmcraft release` with `CHARMCRAFT_AUTH` is simpler and has no third-party JS in the credential path. |
| `canonical/operator-workflows` | Still actively developed, but **explicitly being superseded** — `canonical/charm-ci` says in its own README that it "replaces the monolithic `operator-workflows` approach". Unversioned (`@main` only, no tags/releases), heavyweight, assumes tox env names and `secrets: inherit`. **Not what I'd pick for a single machine charm.** |
| Integration tests | **jubilant + pytest-jubilant**, not pytest-operator. |
| uv in CI | `astral-sh/setup-uv`, then `uv tool install tox --with tox-uv`. |
| Workflow linting | **zizmor**, SARIF to code scanning. |
| Dependency updates | **Renovate** if you want automatic tag→SHA conversion; **Dependabot** if you want zero external app installs. Details in §4. |

---

### Charm CI structure in 2026

### 1.1 The authoritative reference

The official how-to is **[How to set up continuous integration for a charm](https://canonical.com/juju/docs/ops/latest/howto/set-up-continuous-integration-for-a-charm/)** (ops docs). Its recommended shape is:

- `lint` and `unit` jobs: checkout → `astral-sh/setup-uv` → `uv tool install tox --with tox-uv` → `tox -e lint` / `tox -e unit`
- `integration` job: checkout → setup-uv → tox → `sudo snap install --classic concierge` → `sudo concierge prepare -p machine` → `charmcraft pack` → `tox -e integration -- --juju-dump-logs logs` → upload logs artefact
- `permissions: {}` at workflow level
- `persist-credentials: false` on every checkout

It explicitly says: use `-p machine` instead of `-p k8s` for machine charms.

Note the docs page itself uses **floating tags** (`actions/checkout@v6`, `actions/upload-artifact@v7`) in some snippets and SHAs in others — inconsistent, and not a model of hardening. Everything below is SHA-pinned.

Two more live reference workflows worth copying from, both maintained by the Charm Tech team:

- **[canonical/operator `.github/workflows/integration.yaml`](https://github.com/canonical/operator/blob/main/.github/workflows/integration.yaml)** — concierge matrix over `['k8s', 'machine']` × Juju channels, `permissions: {}`, `persist-credentials: false`, per-matrix `timeout-minutes`, and script-injection-safe `env: MATRIX_TEST: ${{ matrix.test }}`.
- **[canonical/jubilant `.github/workflows/ci.yaml`](https://github.com/canonical/jubilant/blob/main/.github/workflows/ci.yaml)** — separate `integration-machine` / `integration-k8s` jobs, per-matrix concurrency groups, `concierge prepare --verbose --juju-channel="$JUJU_CHANNEL" --charmcraft-channel=3.x/stable -p machine`.

### 1.2 concierge — yes, this is the recommended way now

- Repo: <https://github.com/canonical/concierge>, docs: <https://canonical.com/juju/docs/concierge/>
- Latest release **v1.8.0**, 2 September 2026. Actively developed (last push 2026-09-07).
- **There is no `setup-concierge` GitHub Action** — it is used as a snap, in two lines:

```yaml
- run: sudo snap install --classic concierge
- run: sudo concierge prepare -p machine
```

- A GitHub code search for `"concierge prepare" path:.github/workflows` returns **131 hits**, essentially all of Canonical's charm estate (operator, jubilant, kafka-operator, mongodb-k8s-operator, zookeeper-k8s-operator, kfp-operators, observability, …). This is the de-facto standard.

**Presets** ([reference](https://canonical.com/juju/docs/concierge/reference/presets/)), selected with `-p`/`--preset`:

| Preset | Components |
|---|---|
| `crafts` | LXD, snapcraft, charmcraft, rockcraft |
| `dev` | Juju, k8s, LXD, snapcraft, charmcraft, rockcraft, jhack, astral-uv |
| `k8s` | Juju, k8s, LXD (build backend only, not bootstrapped), rockcraft, charmcraft |
| `microk8s` | Juju, microk8s, LXD, rockcraft, charmcraft |
| **`machine`** | **Juju, LXD (bootstrapped), snapcraft, charmcraft** ← yours |

Useful flags seen in the wild: `--verbose`, `--juju-channel=3/stable`, `--charmcraft-channel=3.x/stable`, `-c <config file>`. `sudo concierge restore --verbose` is the exact inverse (destroys the controller) — worth running in `if: always()` on self-hosted runners; unnecessary on ephemeral GitHub-hosted ones.

**Custom config** ([schema reference](https://canonical.com/juju/docs/concierge/reference/configuration/)). Full schema:

```yaml
juju:
  disable: true | false
  channel: <channel>
  revision: <revision>
  agent-version: <version>
  model-defaults:
    <model-default>: <value>
  bootstrap-constraints:
    <bootstrap-constraint>: <value>
  extra-bootstrap-args: <args>

providers:
  microk8s:
    enable: true | false
    bootstrap: true | false
    channel: <channel>
    model-defaults: {}
    bootstrap-constraints: {}
    addons: [<addon>[:<params>]]
    image-registry: {url: ..., username: ..., password: ...}
  k8s:
    enable: true | false
    bootstrap: true | false
    channel: <channel>
    features:
      <feature>:
        <key>: <value>
    image-registry: {url: ..., username: ..., password: ...}
  lxd:
    enable: true | false
    bootstrap: true | false
    channel: <channel>
    model-defaults: {}
    bootstrap-constraints: {}
  google:
    enable: true | false
    bootstrap: true | false
    credentials-file: <path>

host:
  packages:
    - <package>
  snaps:
    <snap>:
      channel: <channel>
      connections:
        - <snap>:<plug-interface>
```

A good machine-charm CI config (adapted from `canonical/charm-factory`'s `.github/concierge.machine.yaml`), drop at `.github/concierge.yaml`:

```yaml
# .github/concierge.yaml
juju:
  model-defaults:
    test-mode: "true"
    automatically-retry-hooks: "false"
    update-status-hook-interval: "60s"

providers:
  lxd:
    enable: true
    bootstrap: true

host:
  snaps:
    charmcraft:
      channel: latest/stable
    jq:
    yq:
```

Used as `sudo concierge prepare -c .github/concierge.yaml --verbose`. For a simple repo, `-p machine` is enough and I'd skip the file.

### 1.3 `canonical/setup-lxd`

- Repo: <https://github.com/canonical/setup-lxd>. Not archived, last push 2026-05-28.
- **`v1` tag → `8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee`** (released 2025-12-11). Older: `v0.1.3` → `a3c85fc6fb7fff43fcfeae87659e41a8f635b7dd`.
- README still carries: *"NB: this action is currently in alpha, breaking changes can occur at any time. Please pin a SHA or exact version in your CI."*
- Inputs: `channel` (default `latest/candidate`), `group`, `preseed`.
- **Role:** installs/configures LXD only. It does **not** install Juju or bootstrap a controller. Use it in a *pack-only* job where you want charmcraft's LXD build backend without paying for a full concierge provision; use concierge in the integration job.

The ops CI how-to uses it in exactly that way for the spread/`charmcraft test` path, pinned to the `v1` SHA above.

### 1.4 `canonical/craft-actions`

- Repo: <https://github.com/canonical/craft-actions>. Very active (commits 2026-09-14).
- Only tags are `v0.1.0`, `v0.1.1` and a floating `v0`; **`v0.1.1` = `v0` = `acd2f2e61c7563b38ba89390ca0e910fa7d2784f`**. No GitHub Releases published.
- Actions: `snapcraft/pack`, `snapcraft/setup`, `rockcraft-pack`, **`charmcraft/pack`**, **`charmcraft/setup`**.

`charmcraft/setup` — installs and configures LXD *and* charmcraft:

```yaml
- name: Set up Charmcraft
  uses: canonical/craft-actions/charmcraft/setup@main
  with:
    channel: 'latest/stable'   # default
    revision: ''               # overrides channel
    lxd-channel: ''            # default: charmcraft's recommended channel
# outputs: charmcraft-revision, lxd-revision
```

`charmcraft/pack` (`action.yaml`, verbatim inputs) — runs on `node24`:

```yaml
- uses: canonical/craft-actions/charmcraft/pack@<sha>
  with:
    path: '.'                  # location of the Charmcraft project
    verbosity: 'trace'         # quiet|brief|verbose|debug|trace
    channel: 'latest/stable'
    revision: ''
    lxd-channel: '5.21/stable'
    test: 'false'              # run `charmcraft test` after packing
# outputs: charms (space-separated), lxd-revision, charmcraft-revision
```

Verdict: fine, and nicer than hand-rolling if you want the `charms` output. But a two-line `sudo snap install charmcraft --classic` + `charmcraft pack` has no JS supply chain at all, and that's what Canonical's own newest workflows do. Your call; I show the plain version in the YAML below.

### 1.5 `canonical/charming-actions`

- Repo: <https://github.com/canonical/charming-actions>. Latest release **`2.7.0`, 29 January 2025**, SHA `1753e0803f70445132e92acd45c905aba6473225`.
- Commits since: only `38f9966` + `d0b5438` (April 2025) and `9180b22` "ci: run JavaScript actions on Node 24" (June 2026). So: alive, but only just.
- Actions provided: `check-libraries`, `release-libraries`, `channel`, `upload-charm`, `upload-bundle`, `dump-logs`.
- Nothing has formally *replaced* it. The closest successors are `canonical/charm-ci` (see below) for teams, and plain `charmcraft upload`/`charmcraft release` for everyone else.
- `upload-charm` inputs ([README](https://github.com/canonical/charming-actions/blob/main/upload-charm/README.md)): `charm-path`, `built-charm-path`, `channel` (default `latest/edge`), `credentials` (required — the `charmcraft login --export` blob), `github-token` (required, for auto-tagging), `destructive-mode`, `tag-prefix`, `upload-image`, `pull-image`, `charmcraft-channel`, `resource-overrides`.

The `github-token` requirement is worth noting from a hardening point of view: `upload-charm` wants a token with write access so it can tag, which means handing a third-party JS action both your Charmhub credential and a repo write token in the same step. I'd rather run `charmcraft upload` myself and tag with `gh` in a separate, scoped step.

**`check-libraries` note:** it's still the only off-the-shelf way to detect stale `lib/charms/*` copies, and it's a legitimate reason to keep charming-actions around even if you publish by hand. But charm libraries are increasingly being replaced by PyPI-published `charmlibs`, which Dependabot/Renovate handle natively — worth checking whether mosquitto needs any charm libs at all.

### 1.6 `canonical/operator-workflows` — still recommended?

- Repo: <https://github.com/canonical/operator-workflows>. Very active (1100+ commits, last push 2026-09-14). **No tags, no releases** — you consume them as `@main`, which is itself a supply-chain smell and will make zizmor's `unpinned-uses` unhappy.
- Workflows: `test.yaml`, `comment.yaml`, `integration_test.yaml`, `publish_charm.yaml`, `promote_charm.yaml`, `auto_update_charm_libs.yaml`, `bot_pr_approval.yaml`, `docs_rtd.yaml`, `docs_spread.yaml`, `terraform_modules_test.yaml`, `terraform_modules_release.yaml`.
- README says they are "parametrized CI workflows to be used for both kubernetes and machine charms", require a `tox.ini` with specific env names, `secrets: inherit`, and a `CHARMHUB_TOKEN`.

**My recommendation: no, not for this repo.** Reasons: `secrets: inherit` is the opposite of least privilege (zizmor flags it under `secrets-inherit`); `@main` is unpinnable; the whole thing is shaped around the IS/WebOps team's monorepo conventions; and Canonical's own newer tooling explicitly positions itself as the replacement.

### 1.7 New in 2026: `canonical/charm-ci` / `opcli`

Worth knowing about even if you don't adopt it. Announced as *[Introducing charm-ci 1.0.0](https://discourse.charmhub.io/t/introducing-charm-ci-1-0-0-run-charm-integration-tests-locally-and-on-github-actions/20774)*.

- Repo: <https://github.com/canonical/charm-ci>. Latest **`v1.0.1`, 27 August 2026** (SHA `58ae6614a3b143d4e57eff0fd1770e97d8c30fab`); `v1.0.0` = `0eef5b8cbef3ee74907850f790cab64bcf0499e5`.
- The CLI is called **`opcli`**. From its README, verbatim: *"`opcli` replaces the monolithic `operator-workflows` approach with a modular pipeline based on explicit build plans (`artifacts.yaml`), stable build output (`artifacts.build.yaml`), and spread-based test execution."*
- It wraps — rather than replaces — charmcraft, rockcraft, concierge, spread and pytest-jubilant, so the same commands run locally and in CI.
- Four reusable workflows, properly tagged: `build-artifacts.yml`, `integration-test.yml`, `publish-artifacts.yml`, `doc-test.yml`, e.g.:

```yaml
jobs:
  publish:
    uses: canonical/charm-ci/.github/workflows/publish-artifacts.yml@v1.0.0
    permissions:
      contents: write
      actions: read
    secrets:
      CHARMHUB_TOKEN: ${{ secrets.CHARMHUB_TOKEN }}
    with:
      channel: latest/edge
      environment: charmhub-publish
```

  Note it passes `CHARMHUB_TOKEN` explicitly rather than `secrets: inherit`, and supports scoping to a GitHub Environment — both good signs.
- **But:** 5 stars, v1.0.x, and it pulls in `artifacts.yaml` + `spread.yaml` + `concierge.yaml` scaffolding. Overkill for one machine charm with no rocks. Revisit if mosquitto grows into a monorepo.

### 1.8 jubilant / pytest-jubilant vs pytest-operator

**jubilant wins outright in 2026.** pytest-operator/python-libjuju is legacy; Canonical publishes migration guides *away* from it:
- <https://canonical.com/juju/docs/ops/latest/howto/migrate/migrate-integration-tests-from-pytest-operator/>
- <https://documentation.ubuntu.com/jubilant/how-to/migrate-from-pytest-operator/> (301s to the above)

Versions today:
- **jubilant `v1.13.0`** (2026-08-31), SHA `219383422ad2c6f846b0a6c5db632ef9eb4d06a9`. Repo <https://github.com/canonical/jubilant>. 1.0.0 shipped April 2025 with an API-stability promise.
- **pytest-jubilant `2.3.0`** on PyPI (<https://pypi.org/project/pytest-jubilant/2.3.0/>), repo <https://github.com/canonical/pytest-jubilant>.

jubilant is a thin Pythonic wrapper over the **Juju CLI** — no websockets, no `async`, which removes the two biggest sources of flake in pytest-operator suites.

pytest-jubilant provides:
- fixtures: `juju` (module-scoped, temporary model, auto-torn-down) and `juju_factory` (multiple temp models, for cross-model relations)
- CLI options: `--juju-model`, `--no-juju-setup`, `--no-juju-teardown`, `--juju-controller`, `--juju-cloud`, **`--juju-dump-logs <dir>`**
- markers: `@pytest.mark.juju_setup`, `@pytest.mark.juju_teardown`

Declare it with PEP 735 groups:

```toml
[dependency-groups]
integration = [
    "pytest>=9,<10",
    "pytest-jubilant>=2,<3",
]
```

```python
import jubilant

def test_deploy(juju: jubilant.Juju):
    juju.deploy("./mosquitto_amd64.charm", "mosquitto")
    juju.wait(lambda status: jubilant.all_active(status, "mosquitto"), timeout=1000)
```

Run with `uv run --group integration pytest tests/integration`.

There is also a `migrate-to-jubilant` skill available in this environment if you have existing pytest-operator tests to port.

**Sidebar — spread / `charmcraft test`:** the ops CI how-to now also recommends running integration tests under **spread**, one matrix job per test module, so wall-clock is bounded by the slowest module. `charmcraft init --profile test-machine` scaffolds `spread.yaml` plus `spread/integration/<module>/task.yaml`. The minimal workflow from the docs:

```yaml
  integration:
    name: Integration / ${{ matrix.task }}
    runs-on: ubuntu-latest
    needs: [unit]
    strategy:
      fail-fast: false
      matrix:
        task: [test_charm]
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up LXD
        uses: canonical/setup-lxd@8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee
        with:
          channel: 5.21/stable
      - name: Install charmcraft
        run: sudo snap install charmcraft --classic
      - name: Run spread test
        run: charmcraft test "craft:ubuntu-24.04:spread/integration/${{ matrix.task }}"
```

(That's the docs' YAML verbatim; note the unpinned `actions/checkout@v6` and the `${{ matrix.task }}` interpolated directly into `run:` — both things zizmor would flag. Pin the SHA and hoist the matrix value into `env:`.) Reference implementation: <https://github.com/canonical/operator/tree/main/examples/httpbin-demo>.

I'd start with plain concierge + tox + pytest-jubilant and only move to spread if the suite gets slow.

### 1.9 `astral-sh/setup-uv`

- Repo: <https://github.com/astral-sh/setup-uv>. Last push 2026-09-14.
- **Latest: `v10.1.0` (2026-09-10) → `bec219d24cd3e171d82865faccec33120bb574f4`**
- Previous: `v10.0.1` → `20cfd1bf945f4377ade1205e4dbc17946fc9a30d` (this is what canonical/operator and canonical/jubilant currently pin)
- `v10.0.0` → `ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d`; `v9.0.0` → `c771a70e6277c0a99b617c7a806ffedaca235ff9`

Canonical pattern in charm repos: `setup-uv`, then `uv tool install tox --with tox-uv`, then `tox -e <env>`.

---

### Security hardening

### 2.1 Full-SHA pinning

Pin every third-party action to a 40-hex commit SHA with a trailing `# vX.Y.Z` comment. Since zizmor **v1.20.0** the default `unpinned-uses` policy requires hash-pinning on *all* actions, including `actions/*` — the old "first-party may be tag-pinned" default is gone (re-enable via config if you must).

zizmor's `ref-version-mismatch` audit checks that the comment matches the SHA, so the comment is load-bearing, not decoration.

Verified SHAs, 2026-09-15:

| Action | Version | SHA |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `astral-sh/setup-uv` | v10.1.0 | `bec219d24cd3e171d82865faccec33120bb574f4` |
| `actions/upload-artifact` | v7.0.1 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `actions/download-artifact` | v8.0.1 | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` |
| `actions/setup-python` | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `github/codeql-action/upload-sarif` | v4.38.0 | `b96794f015dfd88f77b49b1c93e0fa7110f94c63` |
| `step-security/harden-runner` | v2.21.1 | `e14015d583714f6e62063499dc959a02595150a1` |
| `canonical/setup-lxd` | v1 | `8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee` |
| `canonical/craft-actions` | v0.1.1 / v0 | `acd2f2e61c7563b38ba89390ca0e910fa7d2784f` |
| `canonical/charming-actions` | 2.7.0 | `1753e0803f70445132e92acd45c905aba6473225` |
| `actions/dependency-review-action` | v5.0.0 | `a1d282b36b6f3519aa1f3fc636f609c47dddb294` |
| `ossf/scorecard-action` | v2.4.4 | `2d1146689b8cda280b9bc96326124645441f03bc` |

These came from the tags API today; re-verify with `gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq .object.sha` before committing, since a maintainer can move a tag.

**Coming:** GitHub published a 2026 Actions security roadmap in March 2026 whose headline is **workflow-level dependency locking** — a `dependencies:` section (an `actions.lock`-style mechanism) recording the pinned state of every *direct and transitive* action, closing the composite-action blind spot, plus a `gh actions pin` CLI and Dependabot integration. Public preview was signalled for ~3–6 months out, so it may land during this project's life. Evidence it's real: `github_actions_pin_to_sha` and `actions.lock` already appear in `dependabot-core`'s `github_actions/lib/dependabot/github_actions/update_checker.rb`. See [community discussion #194494](https://github.com/orgs/community/discussions/194494).

### 2.2 `permissions:`

Set `permissions: {}` at workflow top level, then grant the minimum per job. This is what canonical/operator and canonical/jubilant do. zizmor's `excessive-permissions` audit enforces it; the pedantic `undocumented-permissions` audit additionally wants a comment explaining each grant.

Typical grants:
- lint/unit/pack/integration jobs: **nothing** (the default `contents: read` from checkout's implicit token is enough for a public repo; be explicit with `contents: read` if the repo is private)
- zizmor job: `security-events: write`, `contents: read`, `actions: read`
- release job: `contents: read` for the Charmhub upload; `contents: write` only in a separate tagging step/job
- issue-on-scheduled-failure job: `issues: write`

### 2.3 `persist-credentials: false`

Always, on every `actions/checkout`. Without it the `GITHUB_TOKEN` is written to `.git/config` and stays readable by every subsequent step — including anything a compromised dependency runs. This is zizmor's `artipacked` audit.

### 2.4 Avoid `pull_request_target`

Don't use it. `pull_request_target` runs with the base repo's secrets and write token while checking out attacker-controlled code — the classic "pwn request". zizmor flags it under `dangerous-triggers` (along with `workflow_run`). If you need to comment on fork PRs, use the upload-artifact-then-`workflow_run` pattern with a job that never checks out the PR head, or just accept that fork PRs don't get secrets.

Related: **do not give fork PRs the `CHARMHUB_TOKEN`.** Gate publishing behind a GitHub Environment with required reviewers.

### 2.5 Script injection from `${{ github.event.* }}`

Never interpolate untrusted context directly into `run:`. `${{ github.event.pull_request.title }}`, `.body`, `.head.ref`, `github.actor`, and matrix values derived from them are all attacker-controlled and are substituted *before* the shell sees the script. Hoist into `env:` and reference as a quoted shell variable:

```yaml
      # WRONG
      - run: echo "Title: ${{ github.event.pull_request.title }}"

      # RIGHT
      - env:
          PR_TITLE: ${{ github.event.pull_request.title }}
        run: echo "Title: $PR_TITLE"
```

canonical/operator does exactly this with `MATRIX_TEST: ${{ matrix.test }}`. zizmor audit: `template-injection`.

Related audit: `bot-conditions` — `if: github.actor == 'dependabot[bot]'` is spoofable; check `github.event.pull_request.user.login` plus the PR's actual author association, or better, don't branch on actor at all.

### 2.6 `step-security/harden-runner`

v2.21.1, SHA `e14015d583714f6e62063499dc959a02595150a1`. Adds an eBPF egress monitor to the runner. Start in `audit` mode to learn the endpoints, then switch to `block` with an allowlist.

Honest caveat for a charm repo: concierge/LXD/snapd/Juju/Charmhub make for a *very* wide and not-fully-stable egress surface (snapcraft.io, api.snapcraft.io, Charmhub CDN, cloud-images.ubuntu.com, archive.ubuntu.com, streams.canonical.com, juju agent binaries…). `block` mode on the integration job will fight you. I'd apply `block` to the lint/unit/zizmor/release jobs and `audit` (or omit it) on the integration job.

### 2.7 Concurrency groups

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Cancel superseded PR runs — saves runner minutes and, for charm CI, avoids two LXD provisions fighting. **Do not** set `cancel-in-progress: true` on the release workflow; use `cancel-in-progress: false` there so a publish is never killed mid-upload. jubilant's CI puts concurrency at *job* level with the matrix value in the group key, which is the right move when a matrix dimension is expensive. zizmor's pedantic `concurrency-limits` audit checks for this.

### 2.8 `timeout-minutes`

Every job. GitHub's default is 360 minutes, which is how a hung `juju wait` burns six hours. Rules of thumb: lint/unit 10, pack 30, integration 60–90, release 45.

### 2.9 zizmor

See §3 in full.

### 2.10 Other bits worth doing

- **`cache-poisoning`** (zizmor audit): don't use `actions/cache` or setup-action caching in a workflow that also publishes. `setup-uv` enables caching by default — pass `enable-cache: false` in the release workflow.
- Give the Charmhub publish job a **GitHub Environment** (`charmhub`) with required reviewers, so `CHARMHUB_TOKEN` is only reachable after a human approves. zizmor's auditor-persona `secrets-outside-env` audit checks precisely this.
- `secrets: inherit` on reusable workflows — avoid; name the secrets. (`secrets-inherit` audit.)
- Set the repo's default `GITHUB_TOKEN` permissions to read-only in Settings → Actions, so a workflow that forgets `permissions:` fails closed.
- Consider a branch ruleset requiring all actions be SHA-pinned — GitHub Actions policy has supported this since the [August 2025 changelog](https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/).

---

### zizmor

Docs: <https://docs.zizmor.sh/>. Repo: <https://github.com/zizmorcore/zizmor>.

### 3.1 Version

**Latest release: `v1.30.1`, published 2026-09-09.** (Prior: `v1.30.0` 2026-08-30, `v1.29.0` 2026-08-01.) Note the docs on `main` already reference behaviour "as of v1.32.0", so a 1.31/1.32 release is imminent — check <https://github.com/zizmorcore/zizmor/releases> before pinning.

It is a static analyser for CI/CD generally — GitHub Actions workflows, composite actions, Dependabot configs and pre-commit configs.

### 3.2 Complete audit list (current, from <https://docs.zizmor.sh/audits/>)

| Audit | One-line description | Persona |
|---|---|---|
| `adhoc-packages` | Ad-hoc package installation outside a managed lockfile | regular |
| `anonymous-definition` | Workflow/action lacks a `name:` | **pedantic** |
| `archived-uses` | Uses an action from an archived repository | regular |
| `artipacked` | Credential persistence on disk (missing `persist-credentials: false`) | regular |
| `bot-conditions` | Spoofable bot checks via `github.actor` | regular |
| `cache-poisoning` | Cache usage in a release/publishing workflow | regular |
| `concurrency-limits` | Missing or insufficient concurrency limits | **pedantic** |
| `dangerous-triggers` | Risky triggers: `pull_request_target`, `workflow_run` | regular |
| `dependabot-cooldown` | Missing/insufficient Dependabot `cooldown` settings | regular |
| `dependabot-execution` | `insecure-external-code-execution: allow` in Dependabot config | regular |
| `excessive-permissions` | Over-scoped workflow/job `permissions:` | regular |
| `forbidden-uses` | Opt-in allow/deny-list for `uses:` clauses | regular (opt-in) |
| `github-app` | Misuse of GitHub App installation tokens | regular |
| `github-env` | Dangerous writes to `GITHUB_ENV` / `GITHUB_PATH` | regular |
| `hardcoded-container-credentials` | Hardcoded Docker credentials | regular |
| `impostor-commit` | Commit obscured via GitHub's fork network | regular |
| `insecure-commands` | Opt-in to deprecated insecure workflow commands | regular |
| `insecure-url-scheme` | Plaintext transport (`http://`) in URLs | regular |
| `known-vulnerable-actions` | Actions with publicly disclosed vulnerabilities | regular |
| `misfeature` | Problematic GitHub Actions features | **auditor** |
| `obfuscation` | Obfuscated paths/expressions | regular |
| `overprovisioned-secrets` | Excessive sharing of the `secrets` context | regular |
| `ref-confusion` | Action pinned to an ambiguous symbolic ref | regular |
| `ref-version-mismatch` | Hash pin whose `# vX` comment is wrong or missing | regular |
| `secrets-inherit` | Blanket `secrets: inherit` | regular |
| `secrets-outside-env` | Secrets used outside a dedicated Environment | **auditor** |
| `self-hosted-runner` | Self-hosted runner usage | **pedantic** |
| `self-repository` | In-repo action not using the new self-repository syntax | regular |
| `stale-action-refs` | Pinned SHA doesn't correspond to a Git tag | **pedantic** |
| `superfluous-actions` | Action duplicating a tool preinstalled on the runner | regular |
| `template-injection` | Code injection via `${{ }}` expansion into `run:` | regular |
| `typosquat-uses` | `uses:` resembling a popular action under a different owner | regular |
| `undocumented-permissions` | `permissions:` block without explanatory comments | **pedantic** |
| `unpinned-images` | Container image without a specific version pin | regular |
| `unpinned-tools` | Tool used without a version pin | regular |
| `unpinned-uses` | `uses:` not pinned by commit hash | regular |
| `unredacted-secrets` | Secrets appearing unmasked in logs | regular |
| `unsound-condition` | Problematic conditional logic | regular |
| `unsound-contains` | Unsafe `contains()` usage | regular |
| `unsound-ternary` | Risky ternary pattern | regular |
| `use-trusted-publishing` | Recommends trusted publishing over long-lived tokens | regular |

41 audits: 36 regular, 5 pedantic-or-auditor.

### 3.3 Personas

Three, cumulative — each includes everything the previous one reports:

- **`regular`** (default) — high-signal, low false positive. What CI should gate on.
- **`pedantic`** — adds code smells and stylistic findings (`anonymous-definition`, `concurrency-limits`, `self-hosted-runner`, `stale-action-refs`, `undocumented-permissions`).
- **`auditor`** — everything, including likely false positives (`misfeature`, `secrets-outside-env`). For a one-off manual review, not for CI.

```bash
zizmor workflow.yml                      # regular (default)
zizmor --persona=pedantic workflow.yml   # or the shorthand:
zizmor --pedantic workflow.yml
zizmor --persona=auditor workflow.yml
```

### 3.4 Configuration

File names: **`zizmor.yml`** or **`zizmor.yaml`**. Discovery, when no `--config`/`ZIZMOR_CONFIG` is given, inside a Git repo starts *and ends at the repo root*, in this order:

1. `.github/zizmor.yml`
2. `.github/zizmor.yaml`
3. `zizmor.yml`
4. `zizmor.yaml`

(Outside a Git repo it walks upward to the filesystem root or first `.git/`. `zizmor .github/workflows/` is a special case: discovery starts two parents up, to avoid confusing a `zizmor.yml` *config* with a `zizmor.yml` *workflow*.)

Skip config entirely with `--no-config`. JSON Schema: <https://raw.githubusercontent.com/woodruffw/zizmor/main/support/zizmor.schema.json> (also on SchemaStore, so any IDE picks it up).

Settings, verbatim from the docs:

```yaml title="zizmor.yml"
rules:
  template-injection:
    disable: true
```

```yaml title="zizmor.yml"
rules:
  template-injection:
    ignore:
      # ignore line 100 in ci.yml, any column
      - ci.yml:100
      # ignore all lines and columns in tests.yml
      - tests.yml
  use-trusted-publishing:
    ignore:
      # ignore line 12, column 10 on pypi.yml
      - pypi.yml:12:10
```

Rule format is `filename.yml[:line[:column]]` — base filename only, 1-based line/column, both optional.

Severity remapping (added v1.25.0):

```yaml
rules:
  artipacked:
    remap:
      severity: high   # informational | low | medium | high
```

Per-audit config (`rules.<id>.config`) — only some audits are configurable; `unpinned-uses` is the main one, letting you allow symbolic refs for trusted namespaces (`foocorp/*`).

Docs are emphatic that `disable:` is a **last resort**: disabled rules don't appear in ignored/suppressed counts, so you silently miss new findings. Prefer a targeted `ignore:` or a less sensitive persona.

**Inline ignore comments** (added v0.6.0) — `# zizmor: ignore[rulename]`, comma-separated for several, optional trailing explanation. Verbatim from the docs:

```yaml title="example.yml"
run: | # zizmor: ignore[template-injection]
  echo "${{ github.event.issue.title }}"
```

```yaml title="example.yml"
run: | # zizmor: ignore[template-injection] i promise this is safe
  echo "${{ github.event.issue.title }}"
```

Multiple: `# zizmor: ignore[artipacked,ref-confusion]`. The comment may sit anywhere within the span the finding identifies, so long as it parses as a YAML comment. **Composite-action findings can only be ignored inline** — `zizmor.yml` rules don't reach them.

### 3.5 Running it

```bash
uvx zizmor@1.30.1 .                 # pinned, no install — what CI should do
uvx zizmor .                        # latest
zizmor /path/to/repo                # installed binary
zizmor .github/workflows/ci.yaml    # single file
zizmor owner/repo                   # remote repository (online only)
```

Online vs offline:

```bash
zizmor --offline workflow.yml                              # no network
ZIZMOR_OFFLINE=1 zizmor .                                  # same, via env
zizmor --gh-token "$(gh auth token)" example/example        # online
zizmor --no-online-audits --gh-token "$(gh auth token)" .   # fetch inputs but skip online audits
```

Token env vars — setting any of these switches on online mode automatically: **`GH_TOKEN`**, **`GITHUB_TOKEN`**, **`ZIZMOR_GITHUB_TOKEN`**. Online mode is needed for audits like `impostor-commit`, `known-vulnerable-actions`, `archived-uses`, `stale-action-refs` and `ref-version-mismatch`. In CI, `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` is enough.

Output formats: `--format=plain` (default), `--format=json`, **`--format=sarif`**, `--format=github` (annotations).

Other flags: `--collect=workflows[,actions]`, `--min-severity=medium`, `--min-confidence=medium`, `--fix` (safe fixes) / `--fix=all` (includes unsafe), `--color=never`, `--config`, `--no-config`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success, no findings |
| 1 | error during audit |
| 2 | argument parsing failure |
| 3 | no inputs collected |
| 11 | findings, highest = informational |
| 12 | findings, highest = low |
| 13 | findings, highest = medium |
| 14 | findings, highest = high |

Because non-zero is returned on *any* finding, the SARIF-upload workflow below needs `continue-on-error` or `if: always()` on the upload step if you want the SARIF to reach code scanning even when zizmor fails. The official YAML relies on `>` redirection so the file exists either way — but the job still fails, and with `--format=sarif` findings go to the file rather than the exit path, so in practice the redirect + upload works. I add `if: always()` belt-and-braces.

### 3.6 Official GitHub Actions workflow (verbatim from <https://docs.zizmor.sh/integrations/>)

```yaml
name: GitHub Actions Security Analysis with zizmor 🌈

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["**"]

env:
  ZIZMOR_VERSION: 1.30.1

permissions: {}

jobs:
  zizmor:
    name: zizmor via PyPI
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      contents: read
      actions: read
    steps:
      - name: Checkout repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false

      - name: Install the latest version of uv
        uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d

      - name: Run zizmor 🌈
        run: uvx "zizmor@${ZIZMOR_VERSION}" --format=sarif . > results.sarif
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Upload SARIF file
        uses: github/codeql-action/upload-sarif@cdf488f595d80d6e07e03d4674febd5ab45fa938
        with:
          sarif_file: results.sarif
          category: zizmor
```

(The docs' pins: checkout `3d3c42e5…` = v7.0.1 ✓ current; setup-uv `20cfd1bf…` = v10.0.1, one minor behind; codeql-action `cdf488f5…` = v4.37.9, one minor behind v4.38.0. My version below bumps them.)

**Note:** SARIF upload to code scanning requires GitHub Advanced Security on private repos; it's free on public repos. If `mosquitto-operator` will be private, drop the SARIF job and use `--format=github` for inline annotations plus a failing exit code instead.

### 3.7 Pre-commit hook

Docs give:

```yaml
- repo: https://github.com/zizmorcore/zizmor-pre-commit
  rev: v1.22.0
  hooks:
  - id: zizmor
```

The docs' `rev` is stale — the hook repo tracks zizmor releases exactly, and **`v1.30.1` (2026-09-09)** is current. Use:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/zizmorcore/zizmor-pre-commit
    rev: v1.30.1
    hooks:
      - id: zizmor
```

Note the pre-commit hook runs **offline by default** unless `GH_TOKEN` is in the environment, so it won't catch `impostor-commit`/`known-vulnerable-actions`. Keep the CI job as the real gate.

---

### Dependabot vs Renovate in 2026 for a uv project

### 4.1 Dependabot and uv

**Yes, `uv` is a first-class ecosystem.** `package-ecosystem: "uv"` updates `pyproject.toml` *and* `uv.lock`. Official uv guide: <https://docs.astral.sh/uv/guides/integration/dependabot/>. The GitHub reference lists `uv` alongside `pip`, supporting indirect dependencies, dev/production classification, and `prefix-development` commit-message customisation ([options reference](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference)).

**PEP 735 `[dependency-groups]`: yes, landed.** [dependabot-core#10847](https://github.com/dependabot/dependabot-core/issues/10847) was **closed 13 February 2026** with the maintainer comment: *"PEP 735 support is in. The parser detects and processes `[dependency-groups]` sections in `pyproject.toml`."* This matters a lot for charm repos, which now conventionally put integration deps in `[dependency-groups]`.

**Known rough edges:**
- [dependabot-core#13202](https://github.com/dependabot/dependabot-core/issues/13202) is **still open**: `dependency-type: development` / `production` in a `groups:` block is *accepted* by the config validator but silently does nothing for uv. So group by `patterns:` for uv, not `dependency-type:`.
- Local path dependencies in non-default groups can break the uv updater (same issue thread, June 2026).
- [dependabot-core#10478](https://github.com/dependabot/dependabot-core/issues/10478) ("Support updating uv.lock") was closed April 2025 but drew sustained complaints that it was marked shipped prematurely. It is materially better in 2026, but it is still slower than Renovate.
- uv's docs recommend aligning Dependabot's `cooldown` with uv's `exclude-newer` if you use the latter, otherwise Dependabot opens PRs that uv can't lock.

### 4.2 Dependabot and GitHub Actions SHA pinning

Two separate questions, and the answers differ:

1. **Does it keep the version comment in sync when bumping an existing SHA pin?** **Yes**, since the [October 2022 changelog](https://github.blog/changelog/2022-10-31-dependabot-now-updates-comments-in-github-actions-workflows-referencing-action-versions/): *"Dependabot will now update the semver version in comments when updating Actions workflows with a commit SHA version."* It parses the trailing `# v8.0.0`, finds the newer release, and bumps SHA and comment together. This is the single most important behaviour for a SHA-pinned repo, and it works well.

2. **Does it convert a tag pin into a SHA pin for you?** **Not via `.github/dependabot.yml`.** `github_actions_pin_to_sha` exists in `dependabot-core` (`github_actions/lib/dependabot/github_actions/update_checker.rb`, methods `pin_to_sha?`, `tag_to_sha_requirement?`, `ref_for_release`) but it's read from the internal `options` hash — an experiment/feature flag, not a user-settable config key. I searched `github/docs` for `github_actions_pin_to_sha`: **zero hits**, i.e. undocumented. Treat it as unavailable to you today.

   **So: you must do the initial tag→SHA conversion yourself.** Options: `gh actions pin` (RFC only, [cli/cli#13314](https://github.com/cli/cli/issues/13314), not shipped), StepSecurity's pinning tool, `pinact`, or a one-off script. After that, Dependabot maintains it.

Known Dependabot bugs worth knowing: [#7912](https://github.com/dependabot/dependabot-core/issues/7912) — an *incorrect* version comment is not corrected (zizmor's `ref-version-mismatch` catches this); [#13466](https://github.com/dependabot/dependabot-core/issues/13466) — hash pins sometimes bumped to the latest *commit* rather than the latest *release*.

### 4.3 Renovate

- uv: officially supported via `uv.lock` detection — project, optional, and dev dependencies, updating both `pyproject.toml` and `uv.lock`. Also PEP 723 inline script metadata via the `pep723` manager (though it can't yet update the associated lock). Docs: <https://docs.astral.sh/uv/guides/integration/renovate/>, <https://docs.renovatebot.com/modules/manager/pep621/>.
- `lockFileMaintenance: { enabled: true }` refreshes transitive deps on a schedule — Dependabot has no real equivalent.
- Align `minimumReleaseAge` with uv's `exclude-newer`, same as Dependabot's `cooldown`.
- **Decisive advantage: `helpers:pinGitHubActionDigests`.** Renovate will *convert* tag pins to digest pins with version comments, and keep them updated. This is exactly the gap in Dependabot.
- Far better grouping, scheduling and automerge control. Canonical uses it: `canonical/craft-actions` is Renovate-managed (see its `chore(deps): update …` commits), and `canonical/charm-ci` ships a `renovate.json`.

### 4.4 Concrete `.github/dependabot.yml`

```yaml
# .github/dependabot.yml
# Docs: https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference
version: 2

updates:
  # ---------------------------------------------------------------------
  # Python, via uv. Updates pyproject.toml (including PEP 735
  # [dependency-groups], supported since Feb 2026) and uv.lock.
  # ---------------------------------------------------------------------
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "Pacific/Auckland"
    open-pull-requests-limit: 5
    # Keep in step with any `exclude-newer` in pyproject.toml, or uv will
    # fail to lock the versions Dependabot proposes.
    cooldown:
      default-days: 7
      semver-major-days: 14
    commit-message:
      prefix: "chore(deps)"
      prefix-development: "chore(deps-dev)"
    groups:
      # NOTE: `dependency-type: development|production` is accepted but is a
      # no-op for the uv ecosystem (dependabot-core#13202). Group by pattern.
      ops-and-charmlibs:
        patterns:
          - "ops"
          - "ops-*"
          - "charmlibs*"
      test-tooling:
        patterns:
          - "pytest"
          - "pytest-*"
          - "jubilant"
          - "coverage*"
          - "tox*"
      lint-tooling:
        patterns:
          - "ruff"
          - "pyright"
          - "codespell"
          - "mypy"
      python-minor-and-patch:
        patterns:
          - "*"
        update-types:
          - "minor"
          - "patch"

  # ---------------------------------------------------------------------
  # GitHub Actions. Dependabot bumps the SHA *and* the trailing `# vX.Y.Z`
  # comment together. It will NOT convert a tag pin into a SHA pin — do that
  # once by hand (or with pinact), then Dependabot maintains it.
  # ---------------------------------------------------------------------
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "Pacific/Auckland"
    open-pull-requests-limit: 5
    cooldown:
      default-days: 7
    commit-message:
      prefix: "chore(ci)"
    groups:
      github-official-actions:
        patterns:
          - "actions/*"
          - "github/*"
      canonical-actions:
        patterns:
          - "canonical/*"
      all-other-actions:
        patterns:
          - "*"
        exclude-patterns:
          - "actions/*"
          - "github/*"
          - "canonical/*"
```

A couple of notes on that file:
- GitHub applies a **3-day cooldown to version updates by default** as of 2026 (security updates are exempt). I set it explicitly.
- If you later add reusable workflows from another repo, add a second `github-actions` entry with `directory: "/.github/workflows"` — Dependabot's actions ecosystem only scans `/.github/workflows` from the `/` directory value, so `"/"` is correct here.
- zizmor's `dependabot-cooldown` audit will flag this file if `cooldown` is missing or too short, and `dependabot-execution` flags `insecure-external-code-execution: allow`. zizmor lints `dependabot.yml` as well as workflows, so `zizmor .` covers it.

### 4.5 Which would I recommend?

**Dependabot, for this repo.** Reasoning:

- It's built in — no GitHub App to install, no `renovate.json` to maintain, and it works identically for an external contributor who forks.
- The single thing Dependabot can't do (tag→SHA conversion) is a **one-time** job on a greenfield repo. You'll write the workflows SHA-pinned from day one, so you never need it.
- uv + PEP 735 support is genuinely there now, which was the blocker in 2025.
- Security updates for Python deps are integrated with GitHub's advisory database and the repo's Security tab with no extra wiring.

**Switch to Renovate if** any of these become true: you want `lockFileMaintenance` for transitive deps; the repo becomes a monorepo with several charms and you need per-directory rules; you want automerge for patch-level CI bumps; or you end up with contributors who keep adding tag-pinned actions and you want them auto-converted. Canonical's own newer tooling repos have gone this way.

---

### Publishing to Charmhub from CI

### 5.1 The credential

`charmcraft login --export` produces an **attenuated** credential blob you store as a repo secret and hand to charmcraft via **`CHARMCRAFT_AUTH`**. Docs: [charmcraft login reference](https://canonical.com/juju/docs/charmcraft/4/reference/commands/login/), [Manage the current Charmhub user](https://canonical.com/juju/docs/charmcraft/4/howto/manage-the-current-charmhub-user/).

Generate it locally (the docs' verbatim example):

```bash
charmcraft login --export=secrets.auth --charm=my-charm \
  --permission=package-manage --channel=edge --ttl=2592000
```

Then in CI:

```bash
export CHARMCRAFT_AUTH=$(cat secrets.auth)
charmcraft upload my-charm.charm --release edge
```

Attenuation options — **use all of them**:

| Flag | Effect |
|---|---|
| `--charm=<name>` | scope to specific charms (repeatable) |
| `--permission=<perm>` | e.g. `package-manage`, `package-manage-releases`, `package-view`, `package-view-releases` |
| `--channel=<channel>` | restrict to given channels |
| `--ttl=<seconds>` | lifetime; **default 30 days** (the reference page also mentions a 30-*hour* default for non-exported tokens — treat 30 days as the `--export` default and always set it explicitly) |
| `--bundle=<name>` | bundles (legacy) |

For mosquitto, I'd mint:

```bash
charmcraft login --export charmhub.token \
  --charm=mosquitto \
  --permission=package-manage-releases \
  --permission=package-view \
  --channel=latest/edge \
  --ttl=7776000          # 90 days
cat charmhub.token       # paste into the CHARMHUB_TOKEN repo secret
shred -u charmhub.token
```

Note the deliberate use of `package-manage-releases` + `package-view` rather than blanket `package-manage`: the CI token can upload and release revisions but cannot, say, transfer ownership or manage collaborators.

### 5.2 Rotation and expiry

This is the weak point and there is **no automatic rotation**. The token is a static secret with a hard expiry, and when it lapses the release workflow fails with an auth error — there's no warning.

Practical mitigations:
- Set an explicit `--ttl` you can live with (30–90 days is the common choice) and put a calendar reminder at TTL minus one week.
- Store it in a **GitHub Environment** (`charmhub`) with required reviewers rather than a plain repo secret, so it's only exposed to an approved deployment.
- Add a cheap canary: a scheduled workflow that runs `charmcraft whoami` (or `charmcraft status mosquitto`) weekly with the token and opens an issue on failure. That turns a surprise release failure into advance notice.
- zizmor's `use-trusted-publishing` audit will nag about this. There is **no OIDC/trusted-publishing equivalent for Charmhub yet** (unlike PyPI), so the static token is unavoidable in 2026 — a legitimate `# zizmor: ignore[use-trusted-publishing]` if it fires.

### 5.3 Recommended shape

For a single machine charm: **`workflow_dispatch` + a tag push**, with a `charmhub` Environment gate, and plain `charmcraft upload`/`charmcraft release` rather than `charming-actions/upload-charm`.

`canonical/charm-factory`'s publish workflow (July 2026, Canonical-authored) is deliberately **`workflow_dispatch`-only** with a `dry-run: true` default and an explicit guard that refuses any other event, and its comments recommend a protected `charmhub` Environment with required reviewers. That's the conservative end. I give you a tag-triggered version below with the Environment gate doing the same job.

Do **not** auto-publish on every push to `main` to `latest/stable`. The usual policy is: push to `main` → `latest/edge`; tag `v*` → `latest/beta` or `latest/candidate`; promote to `stable` manually (`charmcraft promote` or `charming-actions/channel-promotion`).

---

### Complete workflow files

Everything below is SHA-pinned to versions I verified on 2026-09-15. **Re-verify before committing** — a tag can be moved. Verification command:

```bash
gh api repos/actions/checkout/git/ref/tags/v7.0.1 --jq .object.sha
```

I could **not** verify a SHA for `canonical/craft-actions`'s individual sub-actions beyond the repo-level `v0.1.1`/`v0` tag (`acd2f2e61c7563b38ba89390ca0e910fa7d2784f`) — the repo publishes no GitHub Releases, so if you use `charmcraft/pack` you must look up and pin a commit SHA yourself. The YAML below avoids it in favour of `snap install charmcraft`.

### 6.1 `.github/workflows/lint.yaml`

```yaml
# Lint and static analysis. Cheap, no cloud, runs on every push and PR.
name: Lint

on:
  push:
    branches: [main]
  pull_request:
  workflow_call:
  workflow_dispatch:

# Least privilege: grant nothing by default, opt in per job.
permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: Lint and static type check
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read        # read the repo under test

    steps:
      - name: Harden the runner
        uses: step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1 # v2.21.1
        with:
          egress-policy: audit

      - name: Check out the repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Set up uv
        uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0

      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv

      - name: Lint
        run: tox -e lint

      - name: Static type check
        run: tox -e static
```

### 6.2 `.github/workflows/ci.yaml`

```yaml
# Unit tests, charm pack, and Juju integration tests on an LXD machine cloud.
name: CI

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
  schedule:
    # Weekly canary against Juju edge, so upstream breakage surfaces early.
    - cron: "43 6 * * MON"

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  unit:
    name: Unit tests (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.12", "3.14"]

    steps:
      - name: Harden the runner
        uses: step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1 # v2.21.1
        with:
          egress-policy: audit

      - name: Check out the repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: ${{ matrix.python-version }}

      - name: Set up uv
        uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0

      - name: Run unit tests
        run: uv run --group unit pytest tests/unit -v

  pack:
    name: Pack the charm
    runs-on: ubuntu-latest
    timeout-minutes: 30
    permissions:
      contents: read

    steps:
      - name: Harden the runner
        uses: step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1 # v2.21.1
        with:
          egress-policy: audit

      - name: Check out the repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      # setup-lxd gives charmcraft a build backend without provisioning Juju,
      # which is all the pack job needs. Alpha action: pin the SHA.
      - name: Set up LXD
        uses: canonical/setup-lxd@8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee # v1
        with:
          channel: 5.21/stable

      - name: Install charmcraft
        run: sudo snap install charmcraft --classic --channel latest/stable

      - name: Pack
        run: charmcraft pack --verbose

      - name: Upload the packed charm
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: charm
          path: "*.charm"
          if-no-files-found: error
          retention-days: 5

  integration:
    name: Integration (Juju ${{ matrix.juju-channel }})
    runs-on: ubuntu-latest
    needs: [unit, pack]
    timeout-minutes: 90
    permissions:
      contents: read

    strategy:
      fail-fast: false
      matrix:
        # Scheduled runs additionally exercise edge; see the `if` below if you
        # want to trim this on PRs.
        juju-channel: ["3/stable", "4.0/stable"]

    # Two LXD bootstraps racing on one runner is never what you want.
    concurrency:
      group: ${{ github.workflow }}-${{ github.ref }}-integration-${{ matrix.juju-channel }}
      cancel-in-progress: true

    steps:
      # harden-runner is deliberately in `audit` mode here: concierge, snapd,
      # LXD image streams and Charmhub have a wide and shifting egress surface,
      # and `block` mode will produce false failures.
      - name: Harden the runner
        uses: step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1 # v2.21.1
        with:
          egress-policy: audit

      - name: Check out the repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Download the packed charm
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        with:
          name: charm

      - name: Install concierge
        run: sudo snap install --classic concierge

      # `-p machine` installs LXD, runs `lxd init` (storage pool + bridge) and
      # bootstraps a Juju controller onto the LXD cloud: the full machine
      # substrate in one command.
      - name: Provision Juju and LXD
        env:
          JUJU_CHANNEL: ${{ matrix.juju-channel }}
        run: |
          sudo concierge prepare --verbose \
            --juju-channel="$JUJU_CHANNEL" \
            --charmcraft-channel=3.x/stable \
            -p machine

      - name: Set up uv
        uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0

      - name: Run integration tests
        run: uv run --group integration pytest tests/integration -v --log-cli-level=INFO --juju-dump-logs logs

      - name: Upload Juju debug logs
        if: ${{ !cancelled() }}
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: juju-logs-${{ matrix.juju-channel }}
          path: logs
          if-no-files-found: ignore

  open-issue-on-failure-if-scheduled:
    name: Open an issue on scheduled failure
    if: ${{ failure() && github.event_name == 'schedule' }}
    needs: [unit, pack, integration]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      issues: write         # the whole point of this job

    steps:
      - name: Create an issue
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          REPO: ${{ github.repository }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          gh issue create --repo "$REPO" \
            --title "Scheduled CI failed" \
            --body "The scheduled CI run failed: $RUN_URL"
```

Note the `${{ matrix.juju-channel }}` is hoisted into `env: JUJU_CHANNEL` before touching the shell — same pattern canonical/operator uses, and it's what keeps `template-injection` quiet. `matrix.juju-channel` isn't attacker-controlled here, but the habit matters the moment a value derives from `github.event`.

### 6.3 `.github/workflows/zizmor.yaml`

Based on the official docs YAML, with pins bumped to current and the SARIF upload made failure-tolerant.

```yaml
# Static analysis of this repo's own GitHub Actions workflows and Dependabot
# config. Results land in the Security > Code scanning tab.
# Docs: https://docs.zizmor.sh/integrations/
name: zizmor

on:
  push:
    branches: [main]
  pull_request:
    branches: ["**"]
  workflow_dispatch:

env:
  ZIZMOR_VERSION: 1.30.1

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  zizmor:
    name: zizmor via PyPI
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      security-events: write   # upload SARIF to code scanning
      contents: read           # read the workflows under audit
      actions: read            # required for SARIF upload on private repos

    steps:
      - name: Harden the runner
        uses: step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1 # v2.21.1
        with:
          egress-policy: audit

      - name: Check out the repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Set up uv
        uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0

      # GH_TOKEN switches zizmor into online mode, enabling the audits that
      # need the API: impostor-commit, known-vulnerable-actions,
      # archived-uses, stale-action-refs, ref-version-mismatch.
      - name: Run zizmor
        run: uvx "zizmor@${ZIZMOR_VERSION}" --format=sarif . > results.sarif
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Upload the SARIF file
        if: ${{ !cancelled() }}
        uses: github/codeql-action/upload-sarif@b96794f015dfd88f77b49b1c93e0fa7110f94c63 # v4.38.0
        with:
          sarif_file: results.sarif
          category: zizmor
```

If `mosquitto-operator` is private and you don't have Advanced Security, replace the last two steps with:

```yaml
      - name: Run zizmor
        run: uvx "zizmor@${ZIZMOR_VERSION}" --format=github .
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 6.4 `.github/zizmor.yml`

```yaml
# zizmor configuration.
# Docs: https://docs.zizmor.sh/configuration/
# Schema: https://raw.githubusercontent.com/woodruffw/zizmor/main/support/zizmor.schema.json
rules:
  # Charmhub has no OIDC / trusted-publishing equivalent as of 2026, so the
  # release workflow necessarily uses a long-lived CHARMCRAFT_AUTH token.
  # Scoped with --charm / --permission / --channel / --ttl instead.
  use-trusted-publishing:
    ignore:
      - release.yaml
```

Keep this file minimal. Prefer inline `# zizmor: ignore[rule] <reason>` comments for one-offs, and remember that `disable:` hides the finding from the suppressed-findings count entirely.

### 6.5 `.github/workflows/release.yaml`

```yaml
# Publish to Charmhub.
#
#   push to main  -> latest/edge
#   tag v*        -> latest/candidate
#   manual        -> the channel you type
#
# Promotion to latest/stable is deliberately manual (`charmcraft promote`).
#
# REQUIRED: a `charmhub` GitHub Environment holding the CHARMHUB_TOKEN secret,
# ideally with required reviewers so the credential is only exposed after a
# human approves the deployment.
#
# Mint the token with:
#   charmcraft login --export charmhub.token \
#     --charm=mosquitto \
#     --permission=package-manage-releases \
#     --permission=package-view \
#     --channel=latest/edge --channel=latest/candidate \
#     --ttl=7776000            # 90 days -- put a reminder in your calendar
#   cat charmhub.token         # paste into the CHARMHUB_TOKEN secret
#   shred -u charmhub.token
name: Release

on:
  push:
    branches: [main]
    tags: ["v*"]
  workflow_dispatch:
    inputs:
      channel:
        description: "Charmhub channel to release to (e.g. latest/edge)."
        type: string
        required: true
        default: latest/edge
      dry-run:
        description: "Pack and validate only; do not upload or release."
        type: boolean
        default: true

permissions: {}

concurrency:
  # Never cancel a publish mid-upload.
  group: release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  # Re-run the full test suite before anything reaches Charmhub.
  ci:
    uses: ./.github/workflows/ci.yaml
    permissions:
      contents: read

  publish:
    name: Publish to Charmhub
    needs: [ci]
    runs-on: ubuntu-latest
    timeout-minutes: 45
    environment: charmhub      # gate: required reviewers + scoped secret
    permissions:
      contents: read           # publishing goes to Charmhub, not to GitHub

    steps:
      - name: Harden the runner
        uses: step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1 # v2.21.1
        with:
          egress-policy: audit

      - name: Check out the repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Set up LXD
        uses: canonical/setup-lxd@8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee # v1
        with:
          channel: 5.21/stable

      - name: Install charmcraft
        run: sudo snap install charmcraft --classic --channel latest/stable

      # No build cache in a publishing workflow: cache poisoning is a real
      # path from a PR into a released artefact. (zizmor: cache-poisoning)
      - name: Pack
        run: |
          set -euo pipefail
          charmcraft pack --verbose
          ls -la ./*.charm

      - name: Work out the target channel
        id: channel
        env:
          EVENT_NAME: ${{ github.event_name }}
          REF_TYPE: ${{ github.ref_type }}
          INPUT_CHANNEL: ${{ github.event.inputs.channel }}
        run: |
          set -euo pipefail
          if [ "$EVENT_NAME" = "workflow_dispatch" ]; then
            CHANNEL="$INPUT_CHANNEL"
          elif [ "$REF_TYPE" = "tag" ]; then
            CHANNEL="latest/candidate"
          else
            CHANNEL="latest/edge"
          fi
          echo "name=$CHANNEL" >> "$GITHUB_OUTPUT"
          echo "Target channel: $CHANNEL"

      - name: Upload and release
        if: ${{ github.event.inputs.dry-run != 'true' }}
        env:
          # charmcraft reads credentials from CHARMCRAFT_AUTH. Never echoed.
          CHARMCRAFT_AUTH: ${{ secrets.CHARMHUB_TOKEN }}
          CHANNEL: ${{ steps.channel.outputs.name }}
        run: |
          set -euo pipefail

          if [ -z "${CHARMCRAFT_AUTH:-}" ]; then
            echo "::error::CHARMHUB_TOKEN is not set in the charmhub environment."
            exit 1
          fi

          # Fail loudly and early if the token has expired, rather than
          # halfway through an upload.
          charmcraft whoami

          CHARM_FILE="$(ls ./*.charm | head -n1)"
          echo "Uploading ${CHARM_FILE} ..."
          UPLOAD_OUT="$(charmcraft upload "${CHARM_FILE}" --format json)"
          REV="$(printf '%s' "${UPLOAD_OUT}" | jq -r '.revision')"
          echo "Uploaded revision ${REV}"

          echo "Releasing mosquitto revision ${REV} to ${CHANNEL} ..."
          charmcraft release mosquitto --revision "${REV}" --channel "${CHANNEL}"

          {
            echo "### Published to Charmhub"
            echo ""
            echo "- charm: \`mosquitto\`"
            echo "- revision: \`${REV}\`"
            echo "- channel: \`${CHANNEL}\`"
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Dry-run notice
        if: ${{ github.event.inputs.dry-run == 'true' }}
        run: echo "::notice::dry-run=true - packed only. Nothing was uploaded."
```

If you prefer `charming-actions`, the equivalent last step is:

```yaml
      - name: Upload charm to Charmhub
        uses: canonical/charming-actions/upload-charm@1753e0803f70445132e92acd45c905aba6473225 # 2.7.0
        with:
          credentials: ${{ secrets.CHARMHUB_TOKEN }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          channel: ${{ steps.channel.outputs.name }}
          built-charm-path: ./mosquitto_amd64.charm
```

…but that needs `permissions: contents: write` on the job (it tags), which is why I'd keep the plain-charmcraft version.

### 6.6 Optional: token-expiry canary

Cheap insurance against a surprise release failure.

```yaml
# .github/workflows/charmhub-token-check.yaml
name: Charmhub token check

on:
  schedule:
    - cron: "17 5 * * MON"
  workflow_dispatch:

permissions: {}

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    environment: charmhub
    permissions:
      issues: write

    steps:
      - name: Install charmcraft
        run: sudo snap install charmcraft --classic --channel latest/stable

      - name: Verify the Charmhub credential
        id: whoami
        continue-on-error: true
        env:
          CHARMCRAFT_AUTH: ${{ secrets.CHARMHUB_TOKEN }}
        run: charmcraft whoami

      - name: Open an issue if the credential is bad
        if: ${{ steps.whoami.outcome == 'failure' }}
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          REPO: ${{ github.repository }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          gh issue create --repo "$REPO" \
            --title "CHARMHUB_TOKEN appears to have expired or been revoked" \
            --body "\`charmcraft whoami\` failed. Re-mint with \`charmcraft login --export\` and update the secret. Run: $RUN_URL"
```

### 6.7 `.pre-commit-config.yaml` (zizmor portion)

```yaml
repos:
  - repo: https://github.com/zizmorcore/zizmor-pre-commit
    rev: v1.30.1
    hooks:
      - id: zizmor
```

---

### Caveats on SHAs

- All SHAs above were resolved from the GitHub tags/refs API on **2026-09-15**. Tags are mutable; re-verify before committing, and let Dependabot/Renovate keep them fresh afterwards.
- **`canonical/craft-actions` sub-actions have no per-action release.** The only usable pin is the repo-level `v0.1.1`/`v0` commit `acd2f2e61c7563b38ba89390ca0e910fa7d2784f`, which is from an older commit than `main` (repo has moved on to commit `18dd03ef9a20`, 2026-09-14). If you want `charmcraft/pack`, **you must look up a current commit SHA yourself** — I could not verify a "blessed" one.
- `canonical/setup-lxd@v1` = `8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee` is the tag as it stood today, but the README's own alpha warning means a SHA pin is mandatory, not optional.
- zizmor `1.30.1` is the latest *release*, but docs on `main` already describe v1.32.0 behaviour — check releases before pinning `ZIZMOR_VERSION`.
- `github_actions_pin_to_sha` is **not** a documented `dependabot.yml` key; I confirmed zero hits in `github/docs` and two hits in `dependabot-core` internals. Don't put it in your config expecting it to work.

### Sources

- [zizmor docs](https://docs.zizmor.sh/) · [audits](https://docs.zizmor.sh/audits/) · [configuration](https://docs.zizmor.sh/configuration/) · [usage](https://docs.zizmor.sh/usage/) · [integrations](https://docs.zizmor.sh/integrations/) · [repo](https://github.com/zizmorcore/zizmor) · [pre-commit hook](https://github.com/zizmorcore/zizmor-pre-commit)
- [canonical/concierge](https://github.com/canonical/concierge) · [concierge docs](https://canonical.com/juju/docs/concierge/) · [configuration schema](https://canonical.com/juju/docs/concierge/reference/configuration/) · [presets](https://canonical.com/juju/docs/concierge/reference/presets/)
- [canonical/setup-lxd](https://github.com/canonical/setup-lxd) · [canonical/craft-actions](https://github.com/canonical/craft-actions) · [canonical/charming-actions](https://github.com/canonical/charming-actions) · [upload-charm README](https://github.com/canonical/charming-actions/blob/main/upload-charm/README.md) · [canonical/operator-workflows](https://github.com/canonical/operator-workflows) · [charmed-kubernetes/actions-operator](https://github.com/charmed-kubernetes/actions-operator)
- [canonical/charm-ci (opcli)](https://github.com/canonical/charm-ci) · [Introducing charm-ci 1.0.0](https://discourse.charmhub.io/t/introducing-charm-ci-1-0-0-run-charm-integration-tests-locally-and-on-github-actions/20774)
- [How to set up CI for a charm](https://canonical.com/juju/docs/ops/latest/howto/set-up-continuous-integration-for-a-charm/) · [canonical/operator integration.yaml](https://github.com/canonical/operator/blob/main/.github/workflows/integration.yaml) · [canonical/jubilant ci.yaml](https://github.com/canonical/jubilant/blob/main/.github/workflows/ci.yaml)
- [canonical/jubilant](https://github.com/canonical/jubilant) · [canonical/pytest-jubilant](https://github.com/canonical/pytest-jubilant) · [pytest-jubilant on PyPI](https://pypi.org/project/pytest-jubilant/2.3.0/) · [migrate from pytest-operator](https://canonical.com/juju/docs/ops/latest/howto/migrate/migrate-integration-tests-from-pytest-operator/)
- [charmcraft login reference](https://canonical.com/juju/docs/charmcraft/4/reference/commands/login/) · [Manage the current Charmhub user](https://canonical.com/juju/docs/charmcraft/4/howto/manage-the-current-charmhub-user/)
- [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) · [uv + Dependabot](https://docs.astral.sh/uv/guides/integration/dependabot/) · [uv + Renovate](https://docs.astral.sh/uv/guides/integration/renovate/) · [Renovate PEP 621 manager](https://docs.renovatebot.com/modules/manager/pep621/)
- [Dependabot options reference](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference) · [Dependabot updates SHA version comments (2022)](https://github.blog/changelog/2022-10-31-dependabot-now-updates-comments-in-github-actions-workflows-referencing-action-versions/) · [dependabot-core#10847 (PEP 735, closed Feb 2026)](https://github.com/dependabot/dependabot-core/issues/10847) · [#10478 (uv.lock)](https://github.com/dependabot/dependabot-core/issues/10478) · [#13202 (uv dependency-type grouping, open)](https://github.com/dependabot/dependabot-core/issues/13202) · [#7912](https://github.com/dependabot/dependabot-core/issues/7912) · [#13466](https://github.com/dependabot/dependabot-core/issues/13466)
- [Actions policy: blocking and SHA pinning (Aug 2025)](https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/) · [Workflow dependency locking discussion](https://github.com/orgs/community/discussions/194494) · [RFC: gh actions pin](https://github.com/cli/cli/issues/13314)
- [step-security/harden-runner](https://github.com/step-security/harden-runner)

---

## 5. pre-commit

### 5.1 The version-duplication problem, and how to resolve it

The house requirement — tool versions come from `pyproject.toml`/`uv.lock`, not a second pin in
`.pre-commit-config.yaml` — is a real and widely-felt problem. When `uv lock --upgrade` moves ruff
from 0.16.4 to 0.16.7 but `.pre-commit-config.yaml` still says `rev: v0.16.4`, the hook and
`tox -e lint` disagree, and a PR can pass locally and fail in CI (or the reverse).

Three approaches are current in 2026:

1. **`repo: local` hooks with `language: system` calling `uv run`** — versions come from
   `uv.lock` at execution time; no `rev` to sync. This is the approach that satisfies the house
   rule exactly, and it is what I recommend.
   - Cost: hooks need `uv` and a synced environment on the machine, so pre-commit is no longer
     self-bootstrapping. For a repo where every contributor already has uv (required to build the
     charm at all), that is not a real cost.
   - Use `uv run --frozen --only-group lint ruff ...` so the hook is fast and cannot silently
     re-lock.
2. **`sync-with-uv`** (<https://pypi.org/project/sync-with-uv/>, and the pre-commit hook at
   <https://github.com/ewjoachim/sync-pre-commit-with-uv>) — keeps the upstream `rev:` fields
   rewritten from `uv.lock`. `uv.lock` stays the source of truth, but the versions are still
   *written down twice*, just mechanically. Good compromise if you want pre-commit to remain
   self-bootstrapping for drive-by contributors.
3. Leave the duplication and let Dependabot/Renovate bump both. Simplest, but it is precisely
   what the house rule forbids.

**Recommendation: (1), with the small set of language-agnostic upstream hooks
(`pre-commit-hooks`, `uv-pre-commit`, `zizmor`) kept as normal pinned repos** — those tools are
not in `uv.lock` at all, so there is no duplication to eliminate, and pinning them is correct.

### 5.2 Recommended `.pre-commit-config.yaml`

```yaml
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# Tool versions for ruff, codespell and pyright come from uv.lock -- these hooks
# deliberately use `language: system` + `uv run` so that there is exactly one
# source of truth for those versions. See CONTRIBUTING.md.
#
# Install with: uv tool install pre-commit && pre-commit install
# (or use prek, a drop-in replacement: uv tool install prek && prek install)

minimum_pre_commit_version: "4.0.0"

default_install_hook_types: [pre-commit, commit-msg]

ci:
  # We run these in GitHub Actions ourselves; disable pre-commit.ci autofix PRs.
  skip: [ruff-format, ruff-check, codespell, pyright, uv-lock]

repos:
  # --- Generic hygiene (not Python tools; pinning here is correct) -------------
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: check-added-large-files
      - id: check-case-conflict
      - id: check-executables-have-shebangs
      - id: check-merge-conflict
      - id: check-shebang-scripts-are-executable
      - id: check-symlinks
      - id: check-toml
      - id: check-vcs-permalinks
      - id: check-yaml
        args: [--allow-multiple-documents]
        # charmcraft.yaml and workflows only; skip vendored libs.
        exclude: ^lib/
      - id: destroyed-symlinks
      - id: detect-private-key
      - id: end-of-file-fixer
        exclude: ^(lib/|LICENSE$)
      - id: fix-byte-order-marker
      - id: mixed-line-ending
        args: [--fix=lf]
      - id: trailing-whitespace
        exclude: ^lib/

  # --- uv lockfile freshness ---------------------------------------------------
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.9.18          # keep in step with the uv you actually use
    hooks:
      - id: uv-lock

  # --- GitHub Actions static analysis -----------------------------------------
  - repo: https://github.com/zizmorcore/zizmor-pre-commit
    rev: v1.17.0
    hooks:
      - id: zizmor

  # --- Python tools: versions resolved from uv.lock ----------------------------
  - repo: local
    hooks:
      - id: ruff-format
        name: ruff format
        entry: uv run --frozen --only-group lint ruff format --force-exclude
        language: system
        types_or: [python, pyi]
        require_serial: true

      - id: ruff-check
        name: ruff check
        entry: uv run --frozen --only-group lint ruff check --force-exclude --fix
        language: system
        types_or: [python, pyi]
        require_serial: true

      - id: codespell
        name: codespell
        entry: uv run --frozen --only-group lint codespell
        language: system
        types: [text]
        exclude: ^(lib/|uv\.lock$|.*\.svg$)

      - id: pyright
        name: pyright
        entry: uv run --frozen --group typing pyright
        language: system
        types: [python]
        pass_filenames: false
        require_serial: true
```

Notes on the hook definitions:

- **Hook ids:** the ruff pre-commit repo's current ids are **`ruff-check`** and **`ruff-format`**
  (<https://github.com/astral-sh/ruff-pre-commit>). The bare `ruff` id is the old name and is
  deprecated — if you ever revert to the upstream repo, use `ruff-check`. The repo's current rev
  at time of writing is `v0.16.7`.
- `--force-exclude` is essential: pre-commit passes explicit filenames, and without it ruff
  ignores its own `exclude`/`extend-exclude` settings and will happily reformat `lib/`.
- `pyright` gets `pass_filenames: false` — type checking a subset of files gives wrong answers.
- `uv-lock` regenerates `uv.lock` when `pyproject.toml` changes
  (<https://docs.astral.sh/uv/guides/integration/pre-commit/>). Keep its `rev` roughly in step
  with the uv version you use; Dependabot will bump it.
- `codespell` config lives in `pyproject.toml` (`[tool.codespell] skip = ...`), so the hook needs
  no args.

### 5.3 `prek` — the notable 2026 change

`prek` (<https://github.com/j178/prek>, <https://prek.j178.dev/>) is a Rust reimplementation of
pre-commit: a single binary, no Python runtime needed, hooks run in parallel, and it consumes the
same `.pre-commit-config.yaml` unchanged. It was released in late 2025 and through 2026 has been
adopted by CPython, Apache Airflow, FastAPI, ruff itself, and Home Assistant
(<https://developers.home-assistant.io/blog/2026/01/13/replace-pre-commit-with-prek/>). Reported
speedups are in the 5-6x range.

**This is the clearest "2025 vs 2026" delta in this whole report.** Recommendation: keep the
config file as `.pre-commit-config.yaml` (both tools read it) and mention both in
`CONTRIBUTING.md`, e.g. `uv tool install prek && prek install`. Do not switch CI to prek-only yet
if you want `pre-commit.ci`; but since the recommendation below is to run the same checks through
`tox -e lint` in GitHub Actions rather than via pre-commit.ci, that is moot.

### 5.4 Should CI run pre-commit?

No — run `tox -e lint` and `tox -e static` in CI, and let pre-commit be a local convenience. They
execute the same tools at the same locked versions, so there is nothing to diverge, and you avoid
a second CI integration (pre-commit.ci) with write access to the repo. The one exception is
`zizmor`, which is not in `uv.lock`; run that as its own workflow with SARIF upload (§4).

---

## 6. tox

### 6.1 Background: does tox-uv actually solve "install from the lock file"?

Yes. `tox-uv` (<https://github.com/tox-dev/tox-uv>) provides several runners; the one that matters
is **`uv-venv-lock-runner`**, which drives `uv sync` against `uv.lock` instead of `pip install`.
Relevant settings, from the README:

- `dependency_groups` — list of PEP 735 groups, maps to `uv sync --group X` (added *on top of*
  the project's own dependencies).
- `only_groups` — maps to `uv sync --only-group X`; installs *only* those groups, no project
  dependencies. Useful for a `format`/`lint` env that does not need `ops`.
- `no_default_groups` — automatically set to `true` when `dependency_groups` is non-empty.
- `extras` — `uv sync --extra X`.
- `uv_sync_flags` — extra flags, e.g. `--no-editable, --inexact`.
- `uv_sync_locked` — defaults to `true`, i.e. `--locked` is passed, so **a stale lock file fails
  the run**. That is exactly the behaviour the house rule wants: envs cannot silently drift from
  `uv.lock`. (`UV_FROZEN=1` in the environment flips this to `--frozen`.)
- **Important limitation:** under the lock runner, `deps = ...` is *ignored*. Everything comes
  from the lock. The charmcraft 4.4 scaffold's `[testenv:format]` still uses `deps = ruff` with
  the default runner — so `tox -e format` installs a floating, unlocked ruff. **That violates the
  house rule and must be fixed** (see the config below).

Distribution choice: use the `tox-uv` package (bundles a uv binary) rather than `tox-uv-bare`.

### 6.2 How to get tox + tox-uv without polluting the project

Three workable options; pick (a).

(a) **`requires` in `[tox]` (recommended).** tox auto-provisions its own plugins, so a bare
`tox` on `PATH` is enough and nothing tox-related needs to live in `pyproject.toml`:

```ini
[tox]
requires =
    tox>=4.21
    tox-uv>=1.36
```

(b) `uv tool install tox --with tox-uv` — a one-off developer/CI setup step.

(c) `uvx --with tox-uv tox -e lint` — no install at all, good for CI one-liners.

Do **not** add `tox`/`tox-uv` to a `[dependency-groups]` group: tox is the thing that creates the
environments, so it should not live inside one, and a `dev` group is off-limits anyway (§1.3).

### 6.3 Recommended `tox.ini`

This starts from the charmcraft 4.4 machine-profile scaffold and changes: `format` now uses the
lock runner (`only_groups = lint`) rather than floating `deps`; `lint` is split from `static`
(type checking) so the fast check stays fast; a `lock` env gates lockfile freshness; coverage
gets `--fail-under` and XML output for CI; `docs` is included but commented.

```ini
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

[tox]
requires =
    tox>=4.21
    tox-uv>=1.36
no_package = true
skip_missing_interpreters = true
env_list = lock, format, lint, static, unit
min_version = 4.21

[vars]
src_path = {tox_root}/src
tests_path = {tox_root}/tests
lib_path = {tox_root}/lib
all_path = {[vars]src_path} {[vars]tests_path}

[testenv]
runner = uv-venv-lock-runner
set_env =
    PYTHONPATH = {tox_root}/lib:{[vars]src_path}
    PYTHONBREAKPOINT = pdb.set_trace
    PY_COLORS = 1
pass_env =
    PYTHONPATH
    CHARM_BUILD_DIR
    MODEL_SETTINGS

[testenv:lock]
description = Check that uv.lock is in sync with pyproject.toml
skip_install = true
commands =
    uv lock --check

[testenv:format]
description = Apply coding style standards to code
only_groups = lint
commands =
    ruff format {[vars]all_path}
    ruff check --fix {[vars]all_path}

[testenv:lint]
description = Check code against coding style standards
only_groups = lint
commands =
    codespell {tox_root}
    ruff check {[vars]all_path}
    ruff format --check --diff {[vars]all_path}

[testenv:static]
description = Run static type checks
dependency_groups =
    typing
commands =
    pyright {posargs}

[testenv:unit]
description = Run unit tests
dependency_groups =
    unit
commands =
    coverage run --source={[vars]src_path} -m pytest \
        --tb native \
        -v \
        -s \
        {[vars]tests_path}/unit \
        {posargs}
    coverage report
    coverage xml -o {tox_root}/coverage.xml

[testenv:integration]
description = Run integration tests
dependency_groups =
    integration
pass_env =
    {[testenv]pass_env}
    # The integration tests don't pack the charm. If CHARM_PATH is set, the tests deploy the
    # specified .charm file. Otherwise, the tests look for a .charm file in the project dir.
    CHARM_PATH
    JUJU_MODEL
    JUJU_DATA
commands =
    pytest \
        --tb native \
        -v \
        -s \
        --log-cli-level=INFO \
        {[vars]tests_path}/integration \
        {posargs}

# Uncomment when there are docs to build.
# [testenv:docs]
# description = Build the documentation
# dependency_groups =
#     docs
# commands =
#     sphinx-build -W --keep-going docs {tox_root}/docs/_build/html
```

Points worth calling out:

- `runner = uv-venv-lock-runner` is set once on `[testenv]` and inherited, rather than repeated
  per-env as the scaffold does. (tox-uv discussion #208 confirms inheritance works; it is not a
  global `[tox]`-level setting.)
- `only_groups = lint` for `format`/`lint` means those envs install **just** ruff and codespell —
  no `ops`, no pytest. They run in a second or two, and, crucially, at the versions in `uv.lock`.
- `dependency_groups = typing` for `static` pulls project deps **plus** the typing group (which
  itself includes `unit` and `integration` via `include-group`), so pyright can actually resolve
  `ops`, `pytest` and `jubilant`.
- `env_list` deliberately excludes `integration` — `tox` with no `-e` should be safe to run on a
  laptop without a Juju controller.
- `pass_env` in `[testenv:integration]` must re-include `{[testenv]pass_env}`; tox does not merge
  it automatically when the key is redefined. The scaffold quietly drops the inherited values.
- `coverage xml` so the CI job can upload to Codecov or use a coverage comment action.

### 6.4 tox config in `pyproject.toml` instead?

tox 4.21+ supports `[tool.tox]` in `pyproject.toml` (TOML-native config). It is stable but the
ecosystem — including every charmcraft scaffold and every Canonical charm repo — is still on
`tox.ini`. Recommendation: **stay on `tox.ini`** for now. The TOML form buys nothing here and
costs familiarity for anyone who has seen another charm repo.

### 6.5 Does `uv run tox` work?

It does, but do not use it as the standard entry point: it requires tox to be a project
dependency, which drags tox into `pyproject.toml` and (given the `dev`-group hazard in §1.3) is
more trouble than it is worth. Use plain `tox` with `requires = tox-uv`, or `uvx --with tox-uv tox`.

---

## 7. Repo hygiene files

### What I actually fetched

Real files from `raw.githubusercontent.com`:

- https://raw.githubusercontent.com/canonical/postgresql-operator/main/SECURITY.md, `CONTRIBUTING.md`, `.gitignore`, `LICENSE`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/renovate.json5`
- https://raw.githubusercontent.com/canonical/kafka-operator/main/SECURITY.md, `CONTRIBUTING.md`, `.gitignore`, `.github/pull_request_template.md`
- https://raw.githubusercontent.com/canonical/mysql-operator/main/SECURITY.md, `CONTRIBUTING.md`, `.gitignore`
- https://raw.githubusercontent.com/canonical/operator/main/SECURITY.md, `.gitignore`, `.github/CODE_OF_CONDUCT.md`, `.github/dependabot.yaml`, `.github/workflows/publish.yaml`, `CHANGES.md`
- The **charmcraft `init-machine` profile**, which is the single most authoritative statement of current convention: https://github.com/canonical/charmcraft/tree/main/charmcraft/templates/init-machine (`.gitignore.j2`, `CONTRIBUTING.md.j2`, `pyproject.toml.j2`, `tox.ini.j2`, `LICENSE.j2`, `src/charm.py.j2`)

Headline observations:

- **No Canonical charm repo I checked has a `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `.editorconfig`, or YAML issue forms.** They all still use a single markdown `bug_report.md`. So on several of these you are ahead of the ecosystem, not behind it — that is fine, but it means "what Canonical does" is not a useful bar for 4 of the 10 items.
- The charmcraft `init-machine` template is now **uv-first**: `pyproject.toml` with `[dependency-groups]` (`lint`/`unit`/`integration`), `tox.ini` using `runner = uv-venv-lock-runner` and `dependency_groups = ...`, `ops~=3.8`, `jubilant>=1.11`, `pytest-jubilant>=2.1`, `ruff~=0.16`, `pyright`. Poetry (still in postgresql/mysql CONTRIBUTING) is legacy — do not copy it.
- `canonical/operator` uses **Dependabot with the `uv` ecosystem**, hash-pinned actions, `permissions: {}` at workflow top level, `actions/attest@v4` for provenance, and a `dependency-review-action`. The data-platform charms use **Renovate** instead (`.github/renovate.json5` extending `github>canonical/data-platform//renovate_presets/charm.json5`, which you cannot use — it's team-specific).

---

### `SECURITY.md`

### Private vulnerability reporting (PVR)

Per https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository: **Settings → Advanced Security (under "Security and quality") → Private vulnerability reporting → Enable.** Free for public repos. Once on, a "Report a vulnerability" button appears on the repo's Advisories tab, reports arrive as draft security advisories, and you get a private fork for the fix plus one-click CVE request and GHSA publication. Repo admins are notified if watching with "All Activity" or "Security alerts".

There is no first-class `gh` subcommand; via the REST API:

```bash
gh api -X PATCH repos/tonyandrewmeyer/mosquitto-operator \
  -F security_and_analysis[secret_scanning][status]=enabled
# PVR toggle:
gh api -X PUT repos/tonyandrewmeyer/mosquitto-operator/private-vulnerability-reporting
```

(`PUT .../private-vulnerability-reporting` enables, `DELETE` disables — https://docs.github.com/en/rest/repos/repos)

All four Canonical repos point at `https://github.com/<org>/<repo>/security/advisories/new` and link the same GitHub doc plus https://ubuntu.com/security/disclosure-policy. `canonical/operator` additionally has a **Supported versions** section, an explicit response SLA (3 working days to respond, 90 days to resolve) and a "tell us your disclosure deadline" line — that is the best of the four and worth copying. Do **not** copy kafka's CONTRIBUTING claim that security issues go to Launchpad; that contradicts its own SECURITY.md and is stale.

Since this is your personal repo, drop the Ubuntu embargo policy as *your* policy (you can't commit Canonical's security team to anything) but you can still reference it as context, and point at `security@ubuntu.com` only for issues in `ops` or the Juju stack itself.

### Recommended `SECURITY.md`

```markdown
# Security policy

## Supported versions

Security fixes are released for the most recent revision published to the
`latest/stable` channel of the [Mosquitto charm on Charmhub](https://charmhub.io/mosquitto),
and for the `main` branch of this repository. Older revisions are not
supported; please refresh to the latest revision before reporting.

## What qualifies as a security issue

Issues in *this charm* that could lead to unprivileged or unauthorised access
to the Mosquitto broker, to its configuration or TLS material, or to the
machine or Kubernetes workload it runs on. That includes, for example:

- leakage of credentials, certificates or private keys through logs, Juju
  application data, relation data, or the charm's own state;
- default configuration that exposes the broker without authentication;
- command or template injection reachable from charm configuration, actions
  or relation data;
- dependencies vendored into the charm with known vulnerabilities.

Vulnerabilities in the Mosquitto broker itself should go to
[Eclipse Mosquitto](https://github.com/eclipse-mosquitto/mosquitto/security/policy),
and vulnerabilities in Juju, `ops` or Charmhub to
[security@ubuntu.com](mailto:security@ubuntu.com) (see the
[Ubuntu Security disclosure and embargo policy](https://ubuntu.com/security/disclosure-policy)).

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a security problem.

The easiest way to report one is privately through
[GitHub](https://github.com/tonyandrewmeyer/mosquitto-operator/security/advisories/new).
See [Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
for instructions.

Please include:

- a description of the issue and its impact;
- the charm revision and channel, and the Juju version and cloud;
- the steps you took to reproduce it;
- any known mitigations or workarounds.

## What to expect

This is a personal, volunteer-maintained project, so I can't offer a
commercial SLA, but I aim to:

- acknowledge your report within 5 working days;
- agree an assessment and a fix plan with you within 14 days;
- release a fix, and request a CVE where one is warranted, within 90 days.

I'll work with you on the disclosure timing — if you have a deadline for
public disclosure, please say so in your report. I'm happy to credit you in
the resulting advisory unless you'd rather not be named.
```

---

### `CONTRIBUTING.md`

Sources: charmcraft's template CONTRIBUTING (https://github.com/canonical/charmcraft/blob/main/charmcraft/templates/init-machine/CONTRIBUTING.md.j2), postgresql's and mysql's (both poetry-era), kafka's (a stub that defers to the published docs). The template's `tox` target list (`format`, `lint`, `static`, `unit`, `integration`) is the canonical set; the real `tox.ini.j2` collapses `static` into `lint` (codespell + ruff check + ruff format --check + pyright) — I've written the file to match the real `tox.ini`.

Note: omit the Canonical contributor agreement (https://ubuntu.com/legal/contributors). It exists so Canonical can relicense; for a personal repo it is inappropriate and will deter contributors. Apache-2.0 §5 already covers inbound contributions.

```markdown
# Contributing

Thanks for your interest in the Mosquitto charm!

## Before you start

- Check the [existing issues](https://github.com/tonyandrewmeyer/mosquitto-operator/issues)
  to see whether your problem or idea has already been raised. If it hasn't,
  please [open an issue](https://github.com/tonyandrewmeyer/mosquitto-operator/issues/new/choose)
  describing your use case before writing a large change — it's much less
  frustrating than having a finished pull request turned down.
- For anything security-related, follow [SECURITY.md](SECURITY.md) instead of
  opening an issue.
- If you're new to charming, the [Juju SDK documentation](https://documentation.ubuntu.com/ops/)
  and the [charm development best practices](https://documentation.ubuntu.com/ops/latest/reference/best-practices/)
  are the best place to start.

## Development setup

You'll need:

- [uv](https://docs.astral.sh/uv/) — manages Python and the project's
  dependency groups (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [tox](https://tox.wiki/) 4.0+ with the uv plugin
  (`uv tool install tox --with tox-uv`)
- [charmcraft](https://canonical-charmcraft.readthedocs-hosted.com/)
  (`sudo snap install charmcraft --classic`)
- [LXD](https://canonical.com/lxd) for packing and for machine integration
  tests (`sudo snap install lxd && lxd init --auto`)
- [Juju](https://juju.is/) 3.6 LTS or later (`sudo snap install juju`)
- Optionally [concierge](https://github.com/canonical/concierge) to set the
  whole lot up in one go: `concierge prepare -p machine`

Then:

```shell
git clone https://github.com/tonyandrewmeyer/mosquitto-operator
cd mosquitto-operator
uv sync --all-groups
```

Dependencies live in `pyproject.toml`: runtime dependencies of the charm in
`[project].dependencies`, and everything else in `[dependency-groups]`
(`lint`, `unit`, `integration`). Add to them with uv rather than by hand,
e.g. `uv add ops` or `uv add --group unit pytest-mock`, and commit the
updated `uv.lock`.

## Testing

```shell
tox run -e format        # apply formatting (ruff format, ruff check --fix)
tox run -e lint          # codespell, ruff, and pyright static type checks
tox run -e unit          # unit tests (ops.testing / Scenario) with coverage
tox run -e integration   # integration tests (jubilant + pytest-jubilant)
tox                      # runs 'format', 'lint' and 'unit'
```

The unit tests use [`ops.testing`](https://documentation.ubuntu.com/ops/latest/reference/ops-testing/)
and should not need a Juju controller. The integration tests use
[Jubilant](https://documentation.ubuntu.com/jubilant/) and do need a
bootstrapped controller. They don't pack the charm themselves: pack first and
either leave the `.charm` file in the project directory or point at it —

```shell
charmcraft pack
CHARM_PATH=./mosquitto_amd64.charm tox run -e integration
```

Please add tests with every behavioural change. New code should keep unit
test coverage at or above its current level.

## Building the charm

```shell
charmcraft pack
```

Packing needs a few GB of free disk space and is much happier with 4+ cores
and 8 GB of RAM. To try it out:

```shell
juju add-model dev
juju model-config logging-config="<root>=INFO;unit=DEBUG"
juju deploy ./mosquitto_amd64.charm
juju status --watch 1s
juju debug-log
```

## Code style

- [Ruff](https://docs.astral.sh/ruff/) handles formatting and linting; the
  configuration is in `pyproject.toml`. Line length is 99. Run
  `tox run -e format` before pushing and don't hand-format around it.
- Type annotations everywhere, checked with
  [Pyright](https://microsoft.github.io/pyright/) in strict-ish mode via
  `tox run -e lint`.
- Docstrings on all public modules, classes and functions (ruff's `D` rules);
  Google style.
- Every source file starts with the two-line header:

  ```python
  # Copyright 2026 Tony Meyer
  # See LICENSE file for licensing details.
  ```

- Follow the [charm development best practices](https://documentation.ubuntu.com/ops/latest/reference/best-practices/)
  — in particular: keep `src/charm.py` thin and holistic, use
  `collect-unit-status` rather than setting status ad hoc, don't catch
  exceptions you can't handle, and never log secrets or relation credentials.
- British English in prose; American spellings only where an API or a
  third-party term requires it (`color`, `serialize` in code identifiers).

## Commit messages and pull requests

- Commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/):
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`,
  `chore:`, with an optional scope (`fix(tls): ...`) and `!` or a
  `BREAKING CHANGE:` footer for incompatible changes. The changelog is
  generated from these, so they matter.
- Keep pull requests focused, and rebase onto `main` rather than merging it
  in, so the history stays linear.
- Fill in the pull request template, including the checklist.
- All changes need review before merge, and CI (lint, unit, integration,
  and a `charmcraft pack` smoke test) must be green.
- Add a `CHANGELOG.md` entry under `## [Unreleased]` for anything a charm
  user would notice.

## Releasing

Charm revisions are built and published to Charmhub from CI on merge to
`main` (to `latest/edge`), and promoted to `latest/stable` by hand once
they've soaked. See `.github/workflows/`.

## Licence

This project is licensed under the Apache Licence 2.0 — see [LICENSE](LICENSE).
By contributing, you agree that your contributions will be licensed under the
same terms (Apache-2.0 §5). There is no separate CLA.
```

---

### `CHANGELOG.md`

**What Canonical does:** charm repos have none. `canonical/operator` maintains a hand-curated `CHANGES.md` (https://raw.githubusercontent.com/canonical/operator/main/CHANGES.md) with `# 3.8.2 - 31 August 2026` headings and `## Fixes` / `## Documentation` / `## Tests` / `## CI` sections, each bullet ending in a PR number. `canonical/charmcraft` publishes its changelog as documentation (`docs/reference/changelog.rst`), not a root file.

**Should a charm repo have one?** Yes, but be honest about the audience. Charm users consume revisions from Charmhub and mostly read the Charmhub release notes, not your repo. A `CHANGELOG.md` is still worth it because (a) it's the only place the mapping from *revision* to *what changed* lives durably, and (b) it forces you to decide what's user-visible. Add a **Revision** column convention so entries tie back to Charmhub.

**One correction to your brief:** Keep a Changelog is at **1.1.2** (27 September 2024), not 1.1.0 — https://keepachangelog.com/en/1.1.0/ redirects/points at the 1.1.x line. Link `1.1.0` only if you want a stable URL; `https://keepachangelog.com/en/1.1.0/` does still resolve. I've used 1.1.0 below since that's the canonical citable URL, but note 1.1.2 is the current point release.

**Automation in 2026:**

- **towncrier** — fragment files in `changes/`, assembled at release. Best-in-class for avoiding merge conflicts on busy repos; overkill for a single-maintainer charm. Used across the Python packaging world.
- **git-cliff** (https://git-cliff.org/) — Rust, reads Conventional Commits straight from git history, highly templatable, no PR-bot machinery. This is the 2026 sweet spot for a small repo: one `cliff.toml`, one CI step, no bot permissions.
- **release-please** (Google) — opens and maintains a "release PR" that bumps versions and updates `CHANGELOG.md`, merging it cuts the release. Excellent for libraries with semver; awkward for charms, because a charm's "version" is a Charmhub revision assigned at upload, not something you bump in a file.

**Recommendation:** hand-write `CHANGELOG.md` now, keep Conventional Commits rigorously, and add **git-cliff** later if it becomes a chore. Don't adopt release-please for a charm.

```markdown
# Changelog

All notable changes to this charm are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
for its commit messages.

Charm revisions are published to [Charmhub](https://charmhub.io/mosquitto).
Each release below notes the Charmhub revision it corresponds to, where one
was published. Unlike a library, this charm has no independent version
number: the revision is the version.

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.1.0] - 2026-09-15

Charmhub revision: _unreleased_

### Added

- Initial release of the Mosquitto charm: installs and manages the Eclipse
  Mosquitto MQTT broker, with configuration for listeners, persistence and
  authentication.

[Unreleased]: https://github.com/tonyandrewmeyer/mosquitto-operator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tonyandrewmeyer/mosquitto-operator/releases/tag/v0.1.0
```

---

### `LICENSE`

**Confirmed.** `postgresql-operator`, `mysql-operator` and `kafka-operator` all ship an identical 11.3 KB Apache-2.0 text, and charmcraft's `init-machine` template emits Apache-2.0 (`LICENSE.j2` begins "Apache License / Version 2.0, January 2004"). Get the canonical text from https://www.apache.org/licenses/LICENSE-2.0.txt:

```bash
curl -sLo LICENSE https://www.apache.org/licenses/LICENSE-2.0.txt
```

Leave the `[yyyy] [name of copyright owner]` appendix boilerplate as-is — that's what Canonical's copies do; they do not fill it in.

Add to `charmcraft.yaml`: `license: Apache-2.0` (SPDX identifier — charmcraft validates this field against the SPDX list) and a `LICENSE` file in the project root, which `charmcraft pack` includes automatically.

### Header convention

The **two-line header is correct and current** for charm source files. Verbatim from https://github.com/canonical/charmcraft/blob/main/charmcraft/templates/init-machine/src/charm.py.j2:

```python
#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm the application."""
```

and without the shebang for non-entry-point modules, `tox.ini`, `pyproject.toml`, test files, etc.

By contrast, Canonical's *tooling* repos (not charms) use the full Apache boilerplate: `ops/__init__.py` starts `# Copyright 2020 Canonical Ltd.` followed by the 11-line Apache notice, and `charmcraft/application/main.py` the same with `# Copyright 2023-2025 Canonical Ltd.`. So the rule is: **charms get the two-line header, libraries/tools get the full notice.** Use the two-line form.

### SPDX / REUSE

**Not adopted, and not recommended here.** I found no `REUSE.toml`, `.reuse/dep5`, `LICENSES/` directory or `SPDX-License-Identifier:` headers in `canonical/operator`, `canonical/charmcraft`, or any of the three charm repos (`https://raw.githubusercontent.com/canonical/operator/main/REUSE.toml` → 404). REUSE 3.3 / the `REUSE.toml` migration (https://reuse.software/spec-3.3/) has real traction in the EU-funded, KDE and Eclipse worlds, and the FSFE pushes it, but the Canonical charm ecosystem has not moved. Adding SPDX headers would make your repo *more* machine-auditable (and nudges one OpenSSF Scorecard-adjacent check) but diverges from every charm reviewer's expectations.

If you want both, the compromise that stays idiomatic is three lines:

```python
# Copyright 2026 Tony Meyer
# SPDX-License-Identifier: Apache-2.0
# See LICENSE file for licensing details.
```

That is valid REUSE-ish without the `LICENSES/` directory ceremony. My recommendation: **stick to the plain two-line Canonical header.**

---

### `.gitignore`

The four real ones I fetched are minimal and inconsistent (postgresql: 14 lines; mysql: 13; ops: 40; kafka: 50 with Terraform and Sphinx). None of them ignores `.ruff_cache`, `.mypy_cache`, `.pytest_cache` or charmcraft's `prime`/`stage`/`parts`. That is an oversight on their part (charmcraft builds those inside LXD by default, so they rarely appear locally — but `charmcraft pack --destructive-mode` leaves them in the tree).

### The `lib/` question — answered

**Fetched charm libraries ARE committed.** `canonical/postgresql-operator` has `lib/charms/` committed with `certificate_transfer_interface`, `data_platform_libs`, `glauth_k8s`, `grafana_agent`, `postgresql_k8s`, `rolling_ops`, `tls_certificates_interface` all in git. None of the four repos gitignores `lib/`. The rationale: `charmcraft fetch-libs` pulls from Charmhub at a pinned version, and committing means builds/lints/tests are reproducible without network access to Charmhub, and library bumps show up as reviewable diffs.

The 2026 direction of travel is away from Charmhub libs entirely: charmcraft's template `pyproject.toml` says *"We recommend using uv to maintain this list. For example, `uv add charmlibs-pathops`"*, and *"If your code uses any libraries from Charmhub, don't list those here. Instead, add a `charm-libs` block in charmcraft.yaml, run `charmcraft fetch-libs`…"*. So:

- **Prefer PyPI `charmlibs-*` packages** (`uv add charmlibs-pathops`) — locked in `uv.lock`, no `lib/` at all.
- For Charmhub-only libs, declare `charm-libs:` in `charmcraft.yaml`, run `charmcraft fetch-libs`, and **commit the result under `lib/`. Do not gitignore `lib/`.**
- The one exception in Canonical's tree is `canonical/operator`'s `/examples/*/lib`, which *is* ignored — but those are throwaway example charms.

Note also `ops`'s trick: it ignores `.claude/settings.local.json` but not `.claude/` — worth copying if you use Claude Code, so shared project settings stay in git while local overrides don't.

```gitignore
# Charm build artefacts
*.charm
build/
dist/
/parts/
/prime/
/stage/
.charmcraft_output_packages.txt
charmcraft.log
# Generated by some charmcraft/poetry-era workflows; harmless to keep ignored.
/requirements.txt
/requirements-last-build.txt

# NOTE: lib/ is deliberately NOT ignored. Charm libraries fetched with
# `charmcraft fetch-libs` are committed, so builds and CI are reproducible
# without reaching Charmhub. Prefer PyPI `charmlibs-*` packages where one
# exists — those are locked in uv.lock and need no lib/ directory at all.

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
.eggs/

# Virtual environments (uv creates .venv; tox devenv creates venv/)
.venv/
venv/
ENV/
env/

# uv
# uv.lock IS committed - it is the lockfile CI installs from.
.uv-cache/

# tox / nox
.tox/
.nox/

# Testing and coverage
.pytest_cache/
.coverage
.coverage.*
coverage.xml
htmlcov/
.benchmarks/
junit*.xml

# Linters and type checkers
.ruff_cache/
.mypy_cache/
.dmypy.json
dmypy.json
.pyre/
.pytype/
.pyright/

# Juju / deployment
juju-crashdump*.tar.xz
/lxd-profile.yaml
*.log

# Terraform (if you ship a Terraform module for the charm)
.terraform/
.terraform.lock.hcl
*.tfstate
*.tfstate.*
*.tfvars
*.tfvars.json

# Documentation builds
docs/_build/
docs/.sphinx/.doctrees/
docs/.sphinx/warnings.txt

# Editors and IDEs
.idea/
.vscode/
!.vscode/extensions.json
*.swp
*~
.DS_Store

# Local agent/tool overrides (keep shared config in git)
.claude/settings.local.json
.envrc
.env
.secrets
```

---

### `CODE_OF_CONDUCT.md`

**What Canonical charm repos actually use:** nothing at the repo root. All four of `postgresql-operator`, `kafka-operator`, `mysql-operator`, `operator` return 404 for `CODE_OF_CONDUCT.md` at the root. `canonical/operator` has it at **`.github/CODE_OF_CONDUCT.md`** — GitHub picks it up from there for the community-profile checklist — and it is four lines that just point at the Ubuntu CoC:

> This project follows the [Ubuntu Code of Conduct](https://ubuntu.com/community/ethos/code-of-conduct).
> Instances of abusive, harassing, or otherwise unacceptable behaviour may be reported through the channels described there.

Kafka's CONTRIBUTING also says contributions "are subject to the [Ubuntu Code of Conduct](https://ubuntu.com/community/code-of-conduct)".

**Ubuntu CoC v2 vs Contributor Covenant 2.1:** the Ubuntu page confirms it is still "Code of Conduct v2.0" (https://ubuntu.com/community/ethos/code-of-conduct). It's the ecosystem norm and a values-and-behaviour document; Contributor Covenant 2.1 (https://www.contributor-covenant.org/version/2/1/code_of_conduct/) is a more operational document with an explicit four-tier enforcement ladder, and is what GitHub's own "Add a code of conduct" button offers.

**Recommendation:** point at the Ubuntu CoC (ecosystem fit, and it's a *better* document for a community whose norms you're joining), but add the enforcement sentence Ubuntu's own text is vague about, since as an individual maintainer *you* are the escalation path. Put it at the repo root (more discoverable for an individual's repo than `.github/`).

```markdown
# Code of Conduct

This project follows the [Ubuntu Code of Conduct v2.0](https://ubuntu.com/community/ethos/code-of-conduct).

It applies to everyone taking part in this project — in issues, pull
requests, discussions, commit messages, and any other space where you are
representing the project. In short: be considerate, be respectful, take
responsibility for your actions, ask for help when you need it, and step down
considerately.

## Reporting

If you experience or witness behaviour that breaches the Code of Conduct,
please report it privately to Tony Meyer at <tony.meyer@gmail.com>. Reports
will be handled confidentially, and I will not discuss them with the person
reported without your agreement.

Because this is an individual's project rather than a Canonical-owned one,
I'm the only person handling reports here. If that's a conflict — for
instance if the report concerns me — you can also raise it with the
[Ubuntu Community Council](https://ubuntu.com/community/governance/community-council),
who oversee the Code of Conduct across the Ubuntu community.

Possible responses range from a private word, through a request for a public
apology, to a temporary or permanent ban from this repository. I'll aim to
acknowledge any report within five working days.
```

---

### `.editorconfig`

No Canonical charm repo has one (all four 404). But every editor honours it and it costs nothing. Matched to the charmcraft template's ruff config (`line-length = 99`).

```ini
# EditorConfig: https://editorconfig.org
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4
max_line_length = 99

[*.py]
indent_size = 4
max_line_length = 99

[*.{yaml,yml}]
indent_size = 2

# charmcraft.yaml, metadata.yaml, actions.yaml, config.yaml and the
# GitHub workflow files all live here; 2-space is the Juju/YAML norm.
[{charmcraft,metadata,actions,config,manifest}.yaml]
indent_size = 2

[*.{json,json5}]
indent_size = 2

[*.toml]
indent_size = 4

[*.md]
indent_size = 2
# Two trailing spaces are a hard line break in Markdown.
trim_trailing_whitespace = false
max_line_length = 80

[*.{sh,bash}]
indent_size = 2

[*.{tf,tfvars}]
indent_size = 2

[Makefile]
indent_style = tab

[{.gitignore,.gitattributes,.dockerignore}]
indent_size = 2

[LICENSE]
insert_final_newline = false
trim_trailing_whitespace = false
```

---

### Issue and PR templates

Canonical charm repos still use a single markdown `.github/ISSUE_TEMPLATE/bug_report.md` (confirmed for both postgresql and kafka — no `.yml` forms, no `config.yml`, no `feature_request`). YAML issue forms (https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms) are strictly better — required fields, dropdowns, no template debris in the body — so this is a place to be ahead of the ecosystem.

Their PR templates are minimal: postgresql is `## Issue` / `## Solution` / `## Checklist` with two boxes ("I have added or updated any relevant documentation", "I have cleaned any remaining cloud resources from my accounts"). That second one is a genuinely charm-specific gem — integration tests leak clouds resources — so I've kept it.

### `.github/ISSUE_TEMPLATE/bug_report.yml`

```yaml
name: Bug report
description: Report something the Mosquitto charm does wrong
title: "[Bug]: "
labels: ["bug", "triage"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to file a bug.

        **Please do not report security vulnerabilities here.** See
        [SECURITY.md](https://github.com/tonyandrewmeyer/mosquitto-operator/blob/main/SECURITY.md)
        and report privately instead.

  - type: textarea
    id: summary
    attributes:
      label: What happened?
      description: A clear description of the problem, and what you expected instead.
      placeholder: |
        After relating mosquitto to my-client, the broker unit went to blocked
        with "waiting for TLS certificate", and stayed there. I expected it to
        become active once the certificate was issued.
    validations:
      required: true

  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      description: The exact `juju` commands you ran, in order.
      value: |
        1. `juju add-model test`
        2. `juju deploy mosquitto --channel latest/edge`
        3.
      render: shell
    validations:
      required: true

  - type: input
    id: charm-revision
    attributes:
      label: Charm revision
      description: "From `juju status --format=yaml`, or the revision you deployed. Use `git rev-parse HEAD` if you built it yourself."
      placeholder: "42"
    validations:
      required: true

  - type: dropdown
    id: channel
    attributes:
      label: Charmhub channel
      options:
        - latest/stable
        - latest/candidate
        - latest/beta
        - latest/edge
        - "Built locally from source"
        - Other (say which below)
    validations:
      required: true

  - type: input
    id: juju-version
    attributes:
      label: Juju version
      description: Output of `juju version`.
      placeholder: "3.6.10-ubuntu-amd64"
    validations:
      required: true

  - type: dropdown
    id: base
    attributes:
      label: Base
      description: The base the charm is running on.
      options:
        - "ubuntu@24.04"
        - "ubuntu@22.04"
        - "ubuntu@26.04"
        - Other (say which below)
    validations:
      required: true

  - type: dropdown
    id: cloud
    attributes:
      label: Cloud
      description: The substrate you're running on.
      options:
        - LXD
        - MicroK8s
        - Canonical Kubernetes (k8s)
        - MAAS
        - AWS
        - Azure
        - Google Cloud
        - OpenStack
        - VMware vSphere
        - Multipass
        - Other (say which below)
    validations:
      required: true

  - type: input
    id: architecture
    attributes:
      label: Architecture
      placeholder: "amd64"

  - type: textarea
    id: status
    attributes:
      label: juju status
      description: Output of `juju status --relations`. Redact anything sensitive.
      render: text

  - type: textarea
    id: logs
    attributes:
      label: Logs
      description: |
        Relevant output from `juju debug-log --replay --include mosquitto`,
        and any tracebacks. A [crashdump](https://github.com/juju/juju-crashdump)
        is even better — please attach it rather than pasting it.
        **Check for credentials, certificates and private keys before pasting.**
      render: text

  - type: textarea
    id: config
    attributes:
      label: Charm configuration
      description: Non-default options, from `juju config mosquitto`.
      render: yaml

  - type: checkboxes
    id: checks
    attributes:
      label: Before submitting
      options:
        - label: I have searched the existing issues and this isn't a duplicate.
          required: true
        - label: I have removed credentials, certificates and other secrets from the output above.
          required: true
        - label: I have reproduced this on the latest revision in the channel I'm tracking, or explained why I can't.
          required: false
```

### `.github/ISSUE_TEMPLATE/feature_request.yml`

```yaml
name: Feature request
description: Suggest a capability or improvement for the Mosquitto charm
title: "[Feature]: "
labels: ["enhancement", "triage"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for the suggestion. The most useful feature requests start with
        the problem rather than the solution — it's often the case that the
        charm can already solve it, or can solve it more neatly a different
        way.

  - type: textarea
    id: problem
    attributes:
      label: What problem are you trying to solve?
      description: Describe your use case and what's getting in the way.
      placeholder: |
        I run Mosquitto in front of a fleet of sensors and need per-device
        ACLs, but the charm only exposes a single username and password, so
        every device shares credentials.
    validations:
      required: true

  - type: textarea
    id: proposal
    attributes:
      label: What would you like the charm to do?
      description: |
        If you have a concrete proposal, sketch it — new config options,
        actions, or relation endpoints, and roughly what they'd look like.
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: What have you tried or considered?
      description: Workarounds you're using now, or alternatives you've ruled out and why.

  - type: dropdown
    id: area
    attributes:
      label: Which part of the charm does this touch?
      multiple: true
      options:
        - Configuration options
        - Actions
        - Relations / integrations
        - TLS and certificates
        - Authentication and ACLs
        - Bridging / clustering
        - Observability (metrics, logs, dashboards, alerts)
        - Backup and restore
        - Upgrades
        - Documentation
        - Testing
        - Not sure

  - type: dropdown
    id: cloud
    attributes:
      label: Where would you use this?
      multiple: true
      options:
        - Machine charm (LXD, MAAS, public cloud VMs)
        - Kubernetes charm
        - Both

  - type: checkboxes
    id: contribute
    attributes:
      label: Contribution
      options:
        - label: I'd be willing to work on this myself, with some guidance.
          required: false

  - type: checkboxes
    id: checks
    attributes:
      label: Before submitting
      options:
        - label: I have searched the existing issues and this isn't a duplicate.
          required: true
```

### `.github/ISSUE_TEMPLATE/config.yml`

```yaml
blank_issues_enabled: false
contact_links:
  - name: Security vulnerability
    url: https://github.com/tonyandrewmeyer/mosquitto-operator/security/advisories/new
    about: Report security issues privately — please do not open a public issue.
  - name: Question or discussion
    url: https://github.com/tonyandrewmeyer/mosquitto-operator/discussions
    about: Ask how to use the charm, or float an idea before filing a feature request.
  - name: Charmhub Matrix community
    url: https://matrix.to/#/#charmhub:ubuntu.com
    about: Chat with the wider charming community about Juju and charm development.
  - name: Charmhub Discourse
    url: https://discourse.charmhub.io/
    about: Longer-form discussion about charms, Juju and the ecosystem.
  - name: Mosquitto broker bugs
    url: https://github.com/eclipse-mosquitto/mosquitto/issues
    about: For bugs in the Mosquitto broker itself, rather than in this charm.
  - name: Juju bugs
    url: https://github.com/juju/juju/issues
    about: For bugs in Juju itself, rather than in this charm.
```

(`blank_issues_enabled: false` forces people through the forms. Remove the Discussions link if you don't enable Discussions — a dead link there is worse than no link.)

### `.github/pull_request_template.md`

```markdown
## What does this change?

<!-- A short description of the change and why it's needed. -->

## Why?

<!-- The problem being solved. Link the issue: "Fixes #123" / "Part of #123". -->

Fixes #

## How was it tested?

<!--
Which tox environments did you run, and on what? For anything touching charm
behaviour, say which cloud and Juju version you tested against, e.g.
"tox -e unit; integration on LXD, Juju 3.6.10, ubuntu@24.04".
-->

## Checklist

- [ ] The commit messages follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
- [ ] `tox` passes locally (`format`, `lint`, `unit`).
- [ ] I have added or updated unit tests covering this change.
- [ ] I have added or updated integration tests, or explained why they aren't needed.
- [ ] I have added or updated any relevant documentation (README, `charmcraft.yaml` descriptions, config option docs).
- [ ] I have added a `CHANGELOG.md` entry under `## [Unreleased]`, or this change isn't user-visible.
- [ ] I have cleaned up any remaining cloud resources from my test runs.
- [ ] `charmcraft pack` still succeeds.

## Breaking changes

<!--
Does this change config option names, action names, relation interfaces, or
stored state in a way that will break existing deployments on upgrade? If so,
describe the upgrade path. If not, write "None".
-->

None

## Anything else reviewers should know?

<!-- Trade-offs you made, things you're unsure about, follow-up work. -->
```

---

### `CODEOWNERS`, Renovate, OpenSSF Scorecard

### `.github/CODEOWNERS` — **yes, add it (one line)**

`canonical/postgresql-operator` has exactly `* @canonical/data-postgresql`. For a single-maintainer repo it's near-pointless for review routing, but it's useful for two things: it auto-requests you on every PR (so your own forks and bots don't merge silently), and it's a prerequisite if you later turn on "require review from Code Owners" in branch protection. Cost: one line.

```
# Every change is reviewed by the repository owner.
* @tonyandrewmeyer
```

Add a second stanza if you ever want stricter gating on the security-sensitive bits:

```
# Every change is reviewed by the repository owner.
* @tonyandrewmeyer

# Belt and braces on CI, packaging and security policy.
/.github/           @tonyandrewmeyer
/charmcraft.yaml    @tonyandrewmeyer
/SECURITY.md        @tonyandrewmeyer
```

### Dependency updates — **Dependabot, not Renovate**

The data-platform charms use Renovate, but their config is a one-line `extends` of `github>canonical/data-platform//renovate_presets/charm.json5`, which is a private-to-Canonical preset you can't inherit. Meanwhile `canonical/operator` — the newest, most carefully-maintained config of the four — uses **Dependabot with the `uv` ecosystem** (https://raw.githubusercontent.com/canonical/operator/main/.github/dependabot.yaml), grouped along sensible seams, with `cooldown` (`default-days: 7`, `semver-major-days: 14`) to avoid ingesting a compromised release on day zero. Dependabot needs no app installation, works out of the box on a personal repo, and now supports uv natively. Use it.

`.github/dependabot.yaml`:

```yaml
# Routine version-update sweeps only. CVE patches are raised by the repo-level
# "Dependabot security updates" toggle (Settings -> Advanced Security), which is
# event-driven and does not honour the schedules below. Turn that on too.
version: 2

updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
    labels:
      - "dependencies"
    commit-message:
      prefix: "ci"
    cooldown:
      default-days: 7
    groups:
      actions:
        patterns:
          - "*"

  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "monthly"
    labels:
      - "dependencies"
    commit-message:
      prefix: "build"
    cooldown:
      default-days: 7
      semver-major-days: 14
    groups:
      # Charm Tech's own releases - trusted, batch them together.
      charm-tech:
        patterns:
          - "ops"
          - "ops-scenario"
          - "ops-tracing"
          - "charmlibs-*"
          - "jubilant"
          - "pytest-jubilant"
      # Linters, formatters and type checkers. Majors ride along: low risk.
      dev-tooling:
        patterns:
          - "ruff"
          - "pyright"
          - "codespell"
          - "coverage"
          - "pre-commit"
          - "zizmor"
          - "types-*"
      test-deps:
        patterns:
          - "pytest"
          - "pytest-*"
      # Everything else, minor and patch only. A runtime MAJOR falls through to
      # its own PR so it never silently rides along in a patch bundle.
      runtime:
        patterns:
          - "*"
        update-types:
          - "minor"
          - "patch"
```

If you'd rather have Renovate (better monorepo/lockfile handling, `charmcraft.yaml` custom managers), the minimal personal-repo config is:

`renovate.json`:
```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended",
    ":semanticCommits",
    ":dependencyDashboard",
    "helpers:pinGitHubActionDigests"
  ],
  "timezone": "Pacific/Auckland",
  "schedule": ["before 6am on the first day of the month"],
  "minimumReleaseAge": "7 days",
  "labels": ["dependencies"],
  "lockFileMaintenance": { "enabled": true },
  "packageRules": [
    {
      "groupName": "charm tech",
      "matchPackageNames": ["ops", "ops-scenario", "ops-tracing", "jubilant", "pytest-jubilant", "/^charmlibs-/"]
    },
    {
      "groupName": "dev tooling",
      "matchPackageNames": ["ruff", "pyright", "codespell", "coverage", "zizmor"],
      "matchUpdateTypes": ["major", "minor", "patch"]
    },
    {
      "groupName": "GitHub Actions",
      "matchManagers": ["github-actions"]
    }
  ]
}
```

**Pick one, not both** — running Dependabot and Renovate together produces duplicate PRs.

### OpenSSF Scorecard — **marginal; my recommendation is no, with a caveat**

**What it checks** (https://github.com/ossf/scorecard): 18-ish probes scored 0–10 each — Binary-Artifacts, Branch-Protection, CI-Tests, CII-Best-Practices, Code-Review, Contributors, Dangerous-Workflow, Dependency-Update-Tool, Fuzzing, License, Maintained, Packaging, Pinned-Dependencies, SAST, SBOM, Security-Policy, Signed-Releases, Token-Permissions, Vulnerabilities, Webhooks.

For a small single-maintainer charm repo the arithmetic is unkind:

- **Contributors** requires ≥3 contributors from ≥2 organisations — you structurally cannot pass it.
- **Code-Review** wants every commit reviewed by someone other than the author — you structurally cannot pass it as a solo maintainer.
- **Fuzzing** — not applicable to a charm.
- **Branch-Protection** scores best with required reviews, which again needs a second human.
- **Signed-Releases** expects signed release artefacts; charm revisions are published to Charmhub, which Scorecard doesn't understand as a packaging ecosystem.

So you'd plateau around 5–6.5/10 no matter how careful you are, and the badge would under-sell the repo. Meanwhile the checks that *do* pay off — Token-Permissions, Dangerous-Workflow, Pinned-Dependencies — are better served directly by **zizmor**, which `canonical/postgresql-operator` ships as `.github/zizmor.yaml` and which `canonical/operator` ran until it hash-pinned everything and dropped the config ("Hash-pin actions and drop zizmor config (#2612)" in `CHANGES.md`).

**Verdict:** skip the Scorecard badge. Instead: hash-pin every action, set `permissions: {}` at workflow top level and grant per-job, and run zizmor in CI. That gets you the actual security benefit without the misleading score. If you later want Scorecard for a specific consumer's supply-chain requirement, here is the workflow (note `publish_results: true` is what feeds the public API and enables the badge; `id-token: write` is required for it):

`.github/workflows/scorecard.yaml`:
```yaml
name: OpenSSF Scorecard

"on":
  branch_protection_rule:
  schedule:
    - cron: "37 4 * * 1"
  push:
    branches: ["main"]

permissions: {}

jobs:
  analysis:
    name: Scorecard analysis
    runs-on: ubuntu-latest
    permissions:
      # Needed to upload results to code-scanning.
      security-events: write
      # Needed to publish results and get a badge.
      id-token: write
      contents: read
      actions: read
    steps:
      - name: Checkout code
        uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8  # v5.0.0
        with:
          persist-credentials: false

      - name: Run analysis
        uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a  # v2.4.3
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true

      - name: Upload artifact
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02  # v4.6.2
        with:
          name: SARIF file
          path: results.sarif
          retention-days: 5

      - name: Upload to code-scanning
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: results.sarif
```

Then add the badge to the README:
`[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/tonyandrewmeyer/mosquitto-operator/badge)](https://scorecard.dev/viewer/?uri=github.com/tonyandrewmeyer/mosquitto-operator)`

### OpenSSF Best Practices badge (formerly CII Best Practices)

https://www.bestpractices.dev/ — a **self-assessed questionnaire**, not an automated scan. ~67 criteria at "passing" level: has a website, states the licence, has a CONTRIBUTING, uses version control, has a bug reporting process, publishes a vulnerability report process, uses HTTPS, has automated tests, uses a static analyser, and so on.

Unlike Scorecard, **a solo maintainer can legitimately get "passing"** — nothing in it requires multiple contributors. It's about an hour of form-filling, and the exercise is genuinely useful as a checklist: it will surface the two or three things you've forgotten. It also feeds Scorecard's `CII-Best-Practices` check if you ever do run Scorecard.

**Verdict: worth doing, more than Scorecard.** `[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/XXXX/badge)](https://www.bestpractices.dev/projects/XXXX)` once you have a project ID.

---

### Other current 2026 practice

### SLSA provenance / build attestations — **yes**

`canonical/operator` does this in `.github/workflows/publish.yaml`: `permissions: {}` at top, then per-job `id-token: write` + `attestations: write` + `contents: read`, an `environment: publish-pypi`, and `actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6  # v4.2.2` with `subject-path: 'dist/*'`. Note they use the **generalised `actions/attest`**, not `actions/attest-build-provenance` — either works; `attest-build-provenance` is the narrower, simpler one and is what I'd use for a `.charm` file.

Add to whatever workflow packs and publishes your charm:

```yaml
    permissions:
      contents: read
      id-token: write
      attestations: write
    steps:
      # ... charmcraft pack ...
      - name: Attest build provenance for the charm
        uses: actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a  # v3.0.0
        with:
          subject-path: "*.charm"
```

Consumers then verify with `gh attestation verify ./mosquitto_amd64.charm --repo tonyandrewmeyer/mosquitto-operator`. Charmhub doesn't surface attestations yet, but the GitHub release artefact can carry them, and it costs one step.

### zizmor — **yes**

Static analysis for GitHub Actions workflows (template injection, `pull_request_target` pwn requests, over-broad `GITHUB_TOKEN` permissions, unpinned actions, artifact poisoning). `canonical/postgresql-operator` ships `.github/zizmor.yaml`. Add it to your lint group:

```toml
lint = [
    "ruff~=0.16",
    "codespell>=2.4,<3",
    "pyright>=1.1,<2",
    "zizmor>=1.16,<2",
]
```

and to `tox.ini`'s lint env: `zizmor .github/workflows/`.

### `dependency-review-action` — **yes, one job**

Added to `canonical/operator` in 2026 ("Add dependency-review-action on PRs (#2587)"). Blocks PRs that introduce dependencies with known vulnerabilities, before they're merged:

```yaml
  dependency-review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8  # v5.0.0
        with:
          persist-credentials: false
      - uses: actions/dependency-review-action@bc41886e18ea39df68b1b1245f4184881938e050  # v4.8.2
        with:
          fail-on-severity: high
          comment-summary-in-pr: always
```

### `SECURITY-INSIGHTS.yml` — **no**

The OpenSSF Security Insights spec (https://security-insights.openssf.org/, https://github.com/ossf/security-insights) is real and at v2.x, designed to fill the gap between `SECURITY.md` and a full SBOM by making security metadata machine-readable. But adoption in 2026 is concentrated in CNCF/LF-graduated projects and defence-adjacent supply chains. **No Canonical charm repo has one**, nothing in the Juju ecosystem consumes it, and it's a substantial file to keep accurate. Revisit if a downstream consumer asks.

### `.github/FUNDING.yml` — **your call, probably no**

Trivially cheap (`github: [tonyandrewmeyer]`), but it puts a "Sponsor" button on a repo where you're arguably acting in a professional capacity adjacent to Canonical. Given the "individual's repo following Canonical conventions" framing, I'd leave it off to avoid the ambiguity.

### `AGENTS.md` — **yes**

The spec is now under the Agentic AI Foundation (Linux Foundation) and is read by 30+ agents including Codex, Copilot Coding Agent, Cursor, Gemini CLI, Jules, Aider, Zed and Devin; 60,000+ repos as of mid-2026. `canonical/operator` already gitignores `.claude/settings.local.json`, so the team is working this way.

Put the real content in `AGENTS.md` at the repo root and make `.github/copilot-instructions.md` and `CLAUDE.md` one-line symlinks or pointers to it, so there's one source of truth:

`AGENTS.md`:
```markdown
# AGENTS.md

Guidance for AI coding agents working in this repository. Humans should read
[CONTRIBUTING.md](CONTRIBUTING.md), which this file summarises.

## What this is

A [Juju](https://juju.is/) charm that deploys and operates the
[Eclipse Mosquitto](https://mosquitto.org/) MQTT broker. It is published to
[Charmhub](https://charmhub.io/mosquitto).

## Layout

- `src/charm.py` — the charm class. Keep it thin: event handlers here,
  workload logic elsewhere.
- `src/` — workload-specific modules with no charming concerns (no `ops`
  imports), so they can be unit-tested directly.
- `tests/unit/` — `ops.testing` (Scenario) tests. No Juju controller needed.
- `tests/integration/` — Jubilant + pytest-jubilant tests. Needs a controller.
- `charmcraft.yaml` — charm metadata, config options, actions, relations.
- `lib/charms/` — charm libraries fetched with `charmcraft fetch-libs`.
  **Do not edit these by hand**; re-fetch instead.

## Commands

```shell
uv sync --all-groups     # install everything
tox run -e format        # ruff format + ruff check --fix
tox run -e lint          # codespell, ruff, pyright, zizmor
tox run -e unit          # unit tests with coverage
tox run -e integration   # integration tests (needs a Juju controller)
charmcraft pack          # build the .charm
```

Run `tox run -e format` then `tox run -e lint` before proposing any change.

## Conventions

- Python 3.10+, line length 99, ruff for formatting and linting, pyright for
  types. Full type annotations on everything.
- Two-line copyright header on every source file:
  `# Copyright 2026 Tony Meyer` / `# See LICENSE file for licensing details.`
- Google-style docstrings on all public modules, classes and functions.
- British English in prose, comments, docstrings and commit messages.
  American spellings only inside identifiers that mirror an external API.
- Commit messages follow Conventional Commits 1.0.0.
- Add dependencies with `uv add` / `uv add --group <group>`, never by editing
  `pyproject.toml` by hand, and commit the updated `uv.lock`.

## Charm-specific rules

- Follow the
  [charm development best practices](https://documentation.ubuntu.com/ops/latest/reference/best-practices/).
- Event handlers must be **holistic**: reconcile the whole desired state on
  every event rather than making deltas conditional on which event fired.
- Use `collect-unit-status` to report status; don't call `self.unit.status = ...`
  scattered through handlers.
- Never log, or put into relation data, credentials, passwords, private keys
  or certificate material. Use Juju secrets.
- Don't catch exceptions you can't meaningfully handle — let the hook fail so
  Juju retries.
- Prefer PyPI `charmlibs-*` packages over Charmhub libraries where one exists.

## Do not

- Do not commit `.charm` files, `uv.lock` conflicts, or anything under
  `parts/`, `prime/` or `stage/`.
- Do not edit files under `lib/charms/` — re-run `charmcraft fetch-libs`.
- Do not add a Canonical contributor agreement or CLA; this is an individual's
  repository under Apache-2.0.
- Do not run integration tests without cleaning up the models and cloud
  resources afterwards.
```

`.github/copilot-instructions.md`:
```markdown
See [AGENTS.md](../AGENTS.md) in the repository root for the project's
conventions, commands and constraints. That file is the single source of
truth; this one exists only so that GitHub Copilot picks it up.
```

### A note on branch protection (not a file, but it's the highest-value item here)

None of the files above matters as much as: protect `main`, require status checks to pass, require linear history, disallow force-push, and require signed commits if you're willing to set up signing. Settings → Rules → Rulesets. This is what most of Scorecard's Branch-Protection check is measuring, and it's five minutes.

---

### Summary of recommendations

| Item | Verdict |
|---|---|
| `SECURITY.md` + enable PVR | **Yes** — enable PVR in Settings first |
| `CONTRIBUTING.md` | **Yes** — uv-based, no CLA |
| `CHANGELOG.md` | **Yes** — hand-written, Keep a Changelog 1.1.x; git-cliff later if it becomes a chore |
| `LICENSE` Apache-2.0 + two-line headers | **Yes** — confirmed; skip REUSE/SPDX |
| `.gitignore` | **Yes** — and **commit `lib/`**, don't ignore it |
| `CODE_OF_CONDUCT.md` | **Yes** — Ubuntu CoC v2.0, root, with your contact |
| `.editorconfig` | **Yes** — free |
| Issue forms (YAML) + PR template | **Yes** — ahead of Canonical here |
| `.github/CODEOWNERS` | **Yes** — one line |
| Dependabot (uv + actions) | **Yes** — not Renovate, not both |
| OpenSSF Scorecard | **No** — structurally caps ~6/10 solo; use zizmor + hash-pinning instead |
| OpenSSF Best Practices badge | **Yes** — achievable solo, useful checklist |
| `actions/attest-build-provenance` | **Yes** — one step |
| zizmor + dependency-review-action | **Yes** |
| `SECURITY-INSIGHTS.yml` | **No** — no ecosystem consumer |
| `FUNDING.yml` | **Probably not** — role ambiguity |
| `AGENTS.md` + copilot pointer | **Yes** |

### Sources

- [canonical/postgresql-operator SECURITY.md](https://raw.githubusercontent.com/canonical/postgresql-operator/main/SECURITY.md)
- [canonical/kafka-operator SECURITY.md](https://raw.githubusercontent.com/canonical/kafka-operator/main/SECURITY.md)
- [canonical/operator SECURITY.md](https://raw.githubusercontent.com/canonical/operator/main/SECURITY.md)
- [canonical/mysql-operator SECURITY.md](https://raw.githubusercontent.com/canonical/mysql-operator/main/SECURITY.md)
- [canonical/operator .github/CODE_OF_CONDUCT.md](https://raw.githubusercontent.com/canonical/operator/main/.github/CODE_OF_CONDUCT.md)
- [canonical/operator .github/dependabot.yaml](https://raw.githubusercontent.com/canonical/operator/main/.github/dependabot.yaml)
- [canonical/operator .github/workflows/publish.yaml](https://raw.githubusercontent.com/canonical/operator/main/.github/workflows/publish.yaml)
- [canonical/operator CHANGES.md](https://raw.githubusercontent.com/canonical/operator/main/CHANGES.md)
- [charmcraft init-machine template](https://github.com/canonical/charmcraft/tree/main/charmcraft/templates/init-machine)
- [GitHub: Configuring private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository)
- [GitHub: Syntax for issue forms](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [git-cliff](https://git-cliff.org/)
- [Ubuntu Code of Conduct v2.0](https://ubuntu.com/community/ethos/code-of-conduct)
- [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)
- [Ubuntu Security disclosure and embargo policy](https://ubuntu.com/security/disclosure-policy)
- [ossf/scorecard-action](https://github.com/ossf/scorecard-action)
- [OpenSSF Best Practices](https://www.bestpractices.dev/)
- [OpenSSF Security Insights](https://security-insights.openssf.org/)
- [REUSE Specification](https://reuse.software/spec-3.3/)
- [AGENTS.md](https://agents.md/)
- [Apache License 2.0 text](https://www.apache.org/licenses/LICENSE-2.0.txt)

---

## 8. Consistency notes and unresolved choices

The seven sections above were researched partly in parallel, and a few of the recommendations
need reconciling before you commit anything. These are the decisions to make consciously:

1. **Python version.** §1 and §2 recommend `requires-python = ">=3.12"` / `target-version =
   "py312"` / `pythonVersion = "3.12"` on the grounds that `base: ubuntu@24.04` means the charm
   runs on Python 3.12, and the charm-tech guide says to set these to the *actual* minimum. The
   charmcraft scaffold and most Canonical charm repos still say 3.10, because they support
   `ubuntu@22.04` too. **Decide by looking at `platforms:` in `charmcraft.yaml`** — if 24.04 is
   the only base, use 3.12 and set all three in lockstep.
2. **Where pyright lives.** §1 and §6 split a `typing` dependency group out of `lint`, so that
   `tox -e lint` stays fast and `tox -e static` does the slow work. The charmcraft scaffold, the
   `CONTRIBUTING.md` drafted in §7, and OP061 all assume the simpler arrangement where the `lint`
   env runs pyright too. Both are defensible; if you keep the scaffold's single `lint` env, drop
   the `typing` group and the `static` env, and adjust `CONTRIBUTING.md` and `AGENTS.md` to
   match. Note the scaffold is itself inconsistent here: its `CONTRIBUTING.md` documents
   `tox run -e static` but its `tox.ini` never defines that environment.
3. **`ANN` and `PL` in ruff.** The brief asked for flake8-annotations and a broad select set; §2
   recommends dropping both, because they are not in the charm-tech agreed set and pyright strict
   covers annotations more precisely and far less noisily. If you want them anyway, §2 lists the
   ignores you will immediately need (`ANN401`, `ANN204`, `PLR0913`, `PLR2004`, and probably
   `PLR0912`/`PLR0915`).
4. **`lib/` may not exist at all.** Several recommendations (ruff `extend-exclude`, pyright
   `extraPaths` + `reportUnknown*` relaxations, the `charmlibs-pydeps` group) are only needed if
   you fetch Charmhub libraries. The 2026 direction is PyPI `charmlibs-*` packages, which are
   locked in `uv.lock` and need no `lib/`. **If mosquitto needs no Charmhub libs, delete all of
   that** and enjoy genuine pyright strict mode.
5. **Dependabot file name.** §4 and §7 both recommend Dependabot over Renovate, but note GitHub
   accepts either `.github/dependabot.yml` or `.github/dependabot.yaml`. Pick one. The two
   sections offer slightly different grouping strategies; §7's is modelled on
   `canonical/operator`'s actual file and is the one I would start from, since it includes
   `cooldown` (which zizmor's `dependabot-cooldown` audit now checks for).
6. **Tool version pins quoted throughout are as at 2026-09-15** and will go stale. In particular,
   every action SHA in §4 and every pre-commit `rev:` in §5 must be re-verified at the moment you
   write the files. zizmor's `ref-version-mismatch` audit will catch a SHA whose `# vX.Y.Z`
   comment has drifted, and `stale-action-refs` (pedantic) will catch a SHA that no longer
   corresponds to a tag.
7. **Nothing here has been applied to the repository.** This document is research only; no files
   under `/home/tameyer/code/mosquitto-operator` were created or modified.
