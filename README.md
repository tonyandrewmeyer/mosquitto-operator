> [!WARNING]
> **Recommendation: archive this repository, or reset `main` for a fresh attempt.**
>
> A 2026 review for "current best practice" found nothing on the default branch to modernise — `main` is a 4-line placeholder. The only Mosquitto charm code lives in the `claude-attempt-1` and `claude-attempt-2` branches (August 2025), both of which the author has already documented as flawed enough that they would "rather start from scratch."
>
> Since August 2025, best practice has also moved on enough that those branches are not a useful starting point for incremental modernisation:
>
> - Workload libraries: charms now prefer the PyPI `charmlibs-*` namespace (`charmlibs-apt`, `charmlibs-systemd`, `charmlibs-pathops`, …) over `charmcraft fetch-libs` of `charms.operator_libs_linux.*`. `attempt-2` uses the latter.
> - Tracing: the recommended pattern is `ops-tracing` from PyPI with `self._tracing = ops_tracing.Tracing(self, "tracing")` in `__init__`. `attempt-2` predates this and pulls tracing in via `ops[tracing] ~= 2.17` in a top-level `requirements.txt`.
> - Project layout: recent `charmcraft init` profiles scaffold a `uv`-based `pyproject.toml` with a committed `uv.lock`; `requirements.txt` is no longer the recommended format. `attempt-2` ships a `requirements.txt` and a `pyproject.toml` that contains only tool config (no `[project]` table, no dependency groups, no lock file).
> - Integration tests: the current pattern is `pytest-jubilant` 2.x with its built-in module-scoped `juju` fixture, `jubilant.all_active` predicates, and deployment from the packed `.charm` (with `.resolve()`). `attempt-2` rolls its own class-based `TestMosquittoCharmIntegration` with class-scoped fixtures, the deprecated `jubilant.temp_model`, the older `status="active"` form, and calls `charmcraft pack` via `subprocess` inside a test fixture.
> - Unit tests: the current pattern passes the charm class to `testing.Context(MyCharm)` and lets it read metadata from `charmcraft.yaml`, compares statuses with `==`, and chains states with `dataclasses.replace()`. The 2025 attempts predate parts of this guidance.
> - `charmcraft.yaml`: should declare `assumes: [juju >= 3.6]` (plus `k8s-api` for K8s charms); actions should set `additionalProperties: false` and list `required:` params. `attempt-2` does neither, and points `links.source` at `canonical/mosquitto-operator` (the repo lives under `tonyandrewmeyer/`).
> - Quality command: `charmcraft analyse` (not `charmcraft lint`) is the post-pack check.
>
> Net: there is no incremental path from `main` (empty) or `claude-attempt-2` (significantly diverged) to a 2026-best-practice charm that is cheaper than scaffolding fresh with the current Charmcraft profile and the `claude-instructions/CLAUDE.md` from `charming-with-claude` as guidance.
>
> The recommendation is therefore one of:
>
> 1. **Archive the repository** if no further experiments are planned, and start a new one when there is a real intent to publish a Mosquitto charm; or
> 2. **Keep the repo but treat `main` as a clean slate** — run `charmcraft init --profile=machine` against an empty working tree, build the charm with current guidance, and leave the existing `claude-attempt-*` branches in place for historical comparison.
>
> No actual archiving has been performed — this notice is for the maintainer's decision on review.

---

Experimentation with having Claude or other LLMs generate a Mosquitto charm.

Each attempt probably to start in a branch, unless we end up with something worth keeping.

Not for actual use!
