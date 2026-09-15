# Research notes

Raw research gathered while designing this charm, on 2026-09-15. These are working
notes, not maintained documentation — they record what was true at the time and are
kept for provenance and for the detail that did not survive into
[WORKLOAD.md](../../WORKLOAD.md) and [DESIGN.md](../../DESIGN.md).

| File | Subject |
| --- | --- |
| [research-mosquitto.md](research-mosquitto.md) | Operating Mosquitto: packaging, config surface, security, day-2, metrics, scaling, tuning, failure modes |
| [research-ecosystem.md](research-ecosystem.md) | Charmhub prior art, the `mqtt` interface, tls-certificates, COS, tracing, secrets, Juju 3.6 vs 4.0 |
| [research-ops.md](research-ops.md) | Current `ops`, `charmcraft.yaml`, `ops.testing`, `pytest-jubilant`, `charmlibs` |
| [research-repo.md](research-repo.md) | Python packaging, ruff, type checking, GitHub Actions, zizmor, pre-commit, tox, hygiene |

Where these disagree with WORKLOAD.md or DESIGN.md, those two win.
