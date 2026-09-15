# Design: the Mosquitto charm

How the charm operates the workload described in [WORKLOAD.md](WORKLOAD.md).

## 1. Substrate: a machine charm

**Recommendation: machine charm only.**

Reasoning:

- There is no maintained Mosquitto rock or Pebble-bearing OCI image. The upstream
  `eclipse-mosquitto` image has no Pebble in it, so a Kubernetes charm means also
  authoring and maintaining a rock — a second build pipeline for a workload whose
  natural home is not Kubernetes.
- Mosquitto's dominant real-world deployment is an edge or gateway box: a VM, a NUC,
  a Raspberry Pi. That is a machine charm.
- Mosquitto is stateful and does not cluster (WORKLOAD.md §7). Kubernetes' main draw
  — rescheduling and horizontal scale — is of no use here and is actively misleading.
- Full integration testing against both Juju 3.6 and Juju 4.0 is far cheaper with
  LXD than with two MicroK8s substrates.

A Kubernetes charm remains a reasonable follow-up once there is a rock, and the
`src/mosquitto.py` split keeps that door open.

**Base:** `ubuntu@24.04`, platforms `amd64` and `arm64` (arm64 matters for edge).
Python 3.12.

## 2. Prior art

There is none. Verified: the Charmhub info API 404s for `mosquitto`,
`mosquitto-operator`, `mqtt`, `mqtt-broker`, `emqx`, `vernemq`; `packages.json?q=mqtt`
returns zero; the old `~charmers` Launchpad branches do not resolve; `juju/layer-index`
has no mosquitto layer and no `mqtt` interface; and a GitHub code search for
`mosquitto` + `charmcraft.yaml` returns nothing. **The `mqtt` interface name is
unclaimed.**

Closest analogues to borrow shape from: `kafka` (machine, 24.04), `rabbitmq-server`,
`postgresql`, `nats`.

> **Action needed from you:** `charmcraft register mosquitto` is the only definitive
> test of whether the name is available, and it claims the name. I have not run it —
> it is outward-facing and irreversible. Say the word and I will, or run it yourself.

## 3. Ecosystem decisions

Two things changed recently enough that they reframe the obvious choices:

- **`charm-relation-interfaces` is archived.** Interfaces now live in
  `canonical/charmlibs` under `interfaces/<name>/`, published to PyPI as
  `charmlibs-interfaces-<name>`. Our `mqtt` interface spec should be written in that
  shape, and can be upstreamed there later.
- **`grafana-agent` is EOL** (upstream Nov 2025; the charm's bug-fix window ended
  July 2026). The replacement subordinate is `opentelemetry-collector`. The
  provider-side contract is unchanged — still the `cos-agent` interface, still
  `COSAgentProvider` — so this costs us nothing, but it does mean **`log_dest` must
  be `file`, not `syslog`**: otelcol has no journald receiver, whereas both
  collectors unconditionally scrape `/var/log/**/*log`.

Consequent choices:

| Concern | Choice |
| --- | --- |
| Packaging | `apt`, from the archive by default; `ppa` and `snap` available |
| Charm libs | PyPI `charmlibs-*` throughout; no `charmcraft fetch-libs`, no vendored `lib/` |
| TLS | `charmlibs-interfaces-tls-certificates` (not the v4 Charmhub lib), `Mode.UNIT` |
| Observability | `COSAgentProvider` (`cos-agent`), works with grafana-agent and otelcol |
| Tracing | `ops[tracing]`, `ops.tracing.Tracing(self, "charm-tracing", ca_relation_name="receive-ca-cert")` |
| Auth backend | `password_file` + `acl_file`, **not** the dynamic security plugin |
| Build | `parts.charm.plugin: uv`, `uv.lock` committed |

On auth: dynsec is where upstream is heading, but it is imperative (the charm would
have to speak MQTT to itself to change anything), its settings are explicitly *not*
reloaded on SIGHUP, and it does not map onto a declarative reconciler. `password_file`
+ `acl_file` reconcile from desired state, reload without dropping connections, and
map 1:1 onto our relation interface. Revisit when 3.0 removes them.

## 4. Scaling: one unit

`juju add-unit` puts extra units into `BlockedStatus`. This is deliberate. Letting
every unit run would "work" right up until a client reconnects to a different unit and
finds its session, queued messages and retained messages gone.

What we offer instead:

- **Bridging as a relation between two Mosquitto applications.** The charm both
  *provides* `mqtt` and *requires* it, so `juju integrate edge:upstream
  central:mqtt` configures a bridge from the edge broker to the central one. That is
  the hub-and-spoke topology people actually build, expressed in Juju's own grammar,
  and it reuses one interface instead of inventing a second.
- Documented guidance pointing at EMQX and friends above ~50k connections or for
  genuine HA.

Active/passive with `hacluster` and a VIP is a plausible v2; it is out of scope now.

## 5. `charmcraft.yaml`

### Config options

Grouped; every default is stated explicitly in the rendered config, so a 2.0 → 2.1
upgrade never changes behaviour silently.

**Installation**

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `install-source` | string | `archive` | `archive`, `ppa` or `snap`. The archive has 2.0.18 with no standard security support; `ppa` gets 2.1.x from `ppa:mosquitto-dev/mosquitto-ppa`; `snap` gets 2.1.x strictly confined (see the note below). |

**Listeners**

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `port` | int | `1883` | 0 disables the plaintext MQTT listener. |
| `tls-port` | int | `8883` | Only bound once `certificates` is related. |
| `websockets-port` | int | `0` | 0 disables. |
| `tls-websockets-port` | int | `0` | 0 disables. |

**Security**

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `allow-anonymous` | boolean | `false` | Setting `true` produces an `ActiveStatus` carrying a warning, not a silent success. |
| `tls-version` | string | `tlsv1.2` | Minimum accepted version. |
| `require-client-certificate` | boolean | `false` | mTLS. |
| `use-identity-as-username` | boolean | `false` | Only meaningful with the above. |
| `certificate-common-name` | string | `""` | Defaults to the unit's FQDN. |
| `certificate-extra-sans-dns` | string | `""` | Comma-separated, added to the computed SANs. |
| `certificate-organization` | string | `""` | |

**Persistence**

| Option | Type | Default | Upstream default |
| --- | --- | --- | --- |
| `persistence` | boolean | `true` | true |
| `autosave-interval` | int | `300` | 1800 — half an hour of loss is too much |
| `persistent-client-expiration` | string | `14d` | never — **the classic memory leak** |

**Limits**

| Option | Type | Default | Upstream default |
| --- | --- | --- | --- |
| `max-connections` | int | `1024` | -1 |
| `max-inflight-messages` | int | `20` | 20 |
| `max-queued-messages` | int | `1000` | 1000 |
| `max-queued-bytes` | int | `0` | 0 |
| `max-packet-size` | int | `2000000` | 0 on 2.0, 2000000 on 2.1 — set explicitly so upgrading is a non-event |
| `max-keepalive` | int | `65535` | 65535 |
| `memory-limit` | int | `0` | 0 |
| `retain-available` | boolean | `true` | true |
| `queue-qos0-messages` | boolean | `false` | false |

**Logging and monitoring**

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `log-level` | string | `notice` | `error`\|`warning`\|`notice`\|`information`\|`debug`; maps to a `log_type` set. |
| `connection-messages` | boolean | `true` | |
| `sys-interval` | int | `10` | 0 disables `$SYS`, which also disables metrics. |
| `metrics-port` | int | `9234` | The exporter's bind port; matches sapcc's default. |

**Tuning**

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `open-file-limit` | int | `0` | 0 means "compute it": `max_connections + 1024`, floor 4096. Written as a systemd drop-in, which is the only thing that works for a service. |
| `sysctl-tuning` | boolean | `true` | Sets `somaxconn`, `tcp_max_syn_backlog`, `netdev_max_backlog`, `ip_local_port_range`. Degrades with a warning where the kernel namespace forbids it (common in LXD containers), rather than failing the hook. Set `false` on a shared host. |

**Escape hatch**

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `extra-config` | string | `""` | Raw directives written to `conf.d/99-charm-extra.conf`. **Validated**: directives that would subvert the charm's own invariants — `listener`, `port`, `allow_anonymous`, `password_file`, `acl_file`, `plugin`, `per_listener_settings`, `user` — are rejected with a `BlockedStatus`. Without this guard, removing the listener silently re-enables anonymous access (WORKLOAD.md §2). |
| `bridge-topics` | string | `""` | Newline-separated `topic` directives for the `upstream` bridge; ignored when `upstream` is not related. |

Deliberately **not** exposed: `per_listener_settings` (privilege-escalation trap,
deprecated in 2.1), `receive_maximum` (not a broker directive — users would file
bugs), `bind_address` (use Juju spaces).

### Actions

All are leader-only where they mutate shared state; all declare
`additionalProperties: false` and an explicit `required:` list.

| Action | Params | Purpose |
| --- | --- | --- |
| `set-password` | `username`, `password` (optional) | Create or update an MQTT user. With no `password`, generates one and returns a **Juju secret ID**, never the plaintext. |
| `remove-user` | `username` | |
| `list-users` | — | Usernames and their ACL rules. Never passwords. |
| `grant` | `username`, `topic`, `access` (`read`\|`write`\|`readwrite`\|`deny`) | Add an ACL rule. |
| `revoke` | `username`, `topic` | |
| `health-check` | `listener` (optional: `plain`\|`tls`\|`all`) | The real MQTT round trip, per listener. Returns per-listener results. |
| `broker-stats` | — | A snapshot of the `$SYS` tree. |
| `create-backup` | `path` (optional) | Persistence db, password file, ACL file, rendered config, as a tarball. |
| `restore-backup` | `path` | Stops the broker, restores, restarts. |
| `force-reconfigure` | — | Re-render and reconcile unconditionally — the "I edited something by hand" escape hatch. |
| `pause` / `resume` | — | Stop/start the broker for host maintenance without removing the unit. |

Users and ACL rules live in the **peer relation application databag** (usernames and
rules) plus **Juju secrets** (passwords), so they survive unit restarts and are
reconciled onto disk like everything else.

### Relations

```yaml
provides:
  mqtt:        {interface: mqtt}
  cos-agent:   {interface: cos_agent}
requires:
  certificates:    {interface: tls-certificates,     limit: 1, optional: true}
  upstream:        {interface: mqtt,                 limit: 1, optional: true}
  charm-tracing:   {interface: tracing,              limit: 1, optional: true}
  receive-ca-cert: {interface: certificate_transfer, limit: 1, optional: true}
peers:
  mosquitto-peers: {interface: mosquitto-peers}
```

### Storage

```yaml
storage:
  data:
    type: filesystem
    location: /var/lib/mosquitto
    minimum-size: 1G
```

## 6. The `mqtt` interface

Application databags on both sides. **Credentials are never in plaintext**: the
provider creates an app-owned Juju secret holding `{username, password}`, grants it to
the relation, and publishes only the secret URI.

*Requirer → provider:* `topic-permissions` (a set of `{filter, access}` objects),
`client-id-prefix`, `requested-secrets`, `mtls-cert`.

*Provider → requirer:* `endpoints` (a set of `{host, port, tls, protocol}` objects),
`secret-user` (the URI), `granted-permissions`, `client-id-prefix`, `tls-ca`,
`mqtt-version`, `error`.

```python
class Access(enum.StrEnum):
    UNKNOWN = 'UNKNOWN'
    READ = 'read'
    WRITE = 'write'
    READWRITE = 'readwrite'
    DENY = 'deny'

class TopicPermission(pydantic.BaseModel, frozen=True):
    filter: str | None = None
    access: Access = Access.UNKNOWN
```

`filter` and `access` map 1:1 onto Mosquitto's own `acl_file` grammar, so there is no
translation layer.

This departs from `kafka_client` on two points, because `kafka_client` predates the
current interface design rules: collections are sets of **objects**, not
comma-separated primitive strings (`extra-user-roles: "consumer,producer"`), and
`endpoints` is structured rather than `"host:port,host:port"`. Per
`charmlibs/.docs/how-to/design-relation-interfaces.md`: no mandatory top-level fields,
fixed field types forever, no field reuse after removal.

Wire encoding via ops 3's `Relation.load()`/`Relation.save()` with pydantic `alias=`
for the hyphenated names.

Bridging reuses this: when related on `upstream`, the charm acts as a *requirer*,
consumes the endpoint and credentials, and renders a `connection` block with
`try_private true`, `cleansession false`, a per-unit-unique `remote_clientid`, and a
raised `max_queued_messages` request.

## 7. Metrics: our own exporter

`sapcc/mosquitto-exporter` is the only existing tool that does the right job, but it
is dormant (v0.8.0, Go 1.17 era) and ships only as a Go binary or Docker image — no
deb, no snap. Vendoring a pinned Go binary into a charm is a supply-chain and
`arm64`-support problem.

**Instead: a ~200-line Python exporter shipped in `src/`, run as its own systemd
service.** It subscribes to `$SYS/#` via `mosquitto_sub` (already installed for health
checks) and serves Prometheus text over `http.server`. **Zero third-party
dependencies** — no `paho-mqtt`, no Go toolchain, works on every platform the charm
supports, and is unit-testable.

It emits **sapcc's metric names** (`broker_clients_connected`,
`broker_publish_messages_dropped`, …) so existing dashboards keep working, and we ship
our own dashboard JSON as well rather than relying on a fetchable community ID.

It authenticates as a dedicated `_charm_metrics` user whose ACL grants
`read $SYS/#` and nothing else, and binds to the unit's private address.

Alert rules shipped under `src/prometheus_alert_rules/`, led by
`rate(broker_publish_messages_dropped[5m]) > 0` — the only metric that directly means
data loss.

## 8. Charm structure

```
src/
  charm.py              MosquittoCharm: event observation, relations, status. No subprocess.
  mosquitto.py          Workload: apt, systemd, config render, passwd, ACL, health check.
  config.py             Typed config dataclass + action param classes.
  exporter.py           The $SYS → Prometheus exporter (runs as a separate service).
  prometheus_alert_rules/
  grafana_dashboards/
```

`src/charm.py` never imports `subprocess`, `apt` or `systemd` — that separation is
what makes the test strategy work.

**Typed config is first-class in ops 3.8.** `self.load_config(MosquittoConfig)` and
`event.load_params(SetPasswordParams)` — generic over our own dataclasses, with
dashes mapped to underscores automatically. We use `errors='raise'` with an explicit
`except pydantic.ValidationError` so the blocked message is useful.

**Event handling:** delta handlers that all funnel into one idempotent
`_reconcile()`. Render the config to a temp file, diff it against the live one at the
**directive** level (so comment and ordering churn does not restart the broker),
classify each changed directive against the reload-safe and restart-required sets from
WORKLOAD.md §5 — **defaulting to restart for any directive in neither set**, because
those lists differ between 2.0 and 2.1 — then reload or restart accordingly, then
health-check, and roll back if the health check fails.

**Status** via `collect_unit_status`, with `add_status()` called as many times as
apply and ops picking the highest priority.

**Addresses**: always `self.model.get_binding(...).network.bind_address` /
`.ingress_address`. Never `private-address` from relation data — Juju 4.0 no longer
maintains it.

## 9. Juju 3.6 and 4.0

One charm supports both. `assumes: [juju >= 3.6]`, open-ended — we are greenfield, so
pinning `< 4` would be inheriting someone else's compatibility debt.

The two 4.0 removals that could bite: `leader-get`/`leader-set` (ops never exposed
them; no impact) and `private-address` in relation data (real, handled above). Also:
action schemas now default to `additionalProperties: false`, which we declare
explicitly anyway; and secrets became transactional with hook commits, so we never
re-read a secret created in the same hook.

## 10. Testing

| Layer | Tool | What it covers |
| --- | --- | --- |
| Unit | `ops.testing` (Scenario) | State transitions. `monkeypatch.setattr('charm.mosquitto', FakeMosquitto())` — a stateful hand-rolled fake, not a `MagicMock`. `testing.Model(type='lxd')`, since the default is `kubernetes`. |
| Unit | plain pytest | `mosquitto.py` config rendering, ACL/passwd file generation, the reload-vs-restart classifier, and `exporter.py` parsing — all pure functions, heavily parametrised. |
| Functional | pytest in LXD | The workload module against real apt and systemd, no Juju. |
| Integration | `jubilant` + `pytest-jubilant` 2.x | Real deploys on **both Juju 3.6 and 4.0**, in Multipass VMs. Deploy, configure, relate to `self-signed-certificates`, relate two Mosquitto apps as a bridge, run every action, and — critically — assert that a client can **actually publish after a reload**, not merely that a file changed. |

Coverage `fail_under = 80`, and not allowed to drop.

## 11. Repository infrastructure

Following the charmcraft 4.4 scaffold and
[Canonical's charm Python style guide](https://github.com/canonical/charm-tech/blob/main/style/python.md),
with these deltas:

- `requires-python = ">=3.12"` — the scaffold says 3.10, but 24.04 is our only base.
- **No `dev` dependency group.** The uv plugin runs `uv sync`, which installs `dev` by
  default; `[tool.uv] default-groups = []` as belt and braces.
- `uv lock --check` in CI, so "edited pyproject, forgot to relock" fails before
  `charmcraft pack` does.
- **pyright strict** (Charm Tech's choice; Data Platform has moved to `ty`, which is
  still Beta at 0.0.81). `ty` as an advisory, non-blocking tox env.
- Ruff: `F,E,W,I001,N,A,CPY,UP,YTT,S,B,SIM,RUF,PERF,D,FA,TC`, line length 99, single
  quotes. The house "import modules, not objects" rule is *partially* enforceable via
  `flake8-import-conventions.banned-from`, but there is no wildcard
  ([ruff#10664](https://github.com/astral-sh/ruff/issues/10664) is open and
  unassigned), so it gets a curated module list plus review.
- tox: keep the scaffold's `format`/`lint`/`unit`/`integration` names (spec OP061),
  add `functional` and `static`. Fix the scaffold's own bug — its `[testenv:format]`
  uses `deps = ruff` with the default runner, installing an unlocked floating ruff.
- CI on GitHub Actions: `permissions: {}` at workflow level, `persist-credentials:
  false`, every action hash-pinned (zizmor's default policy has required this for
  first-party actions since v1.20.0), concurrency groups, `timeout-minutes`.
  **concierge** provisions Juju + LXD; `charmed-kubernetes/actions-operator` is
  effectively legacy.
- **zizmor** in CI with SARIF upload to code scanning, and in pre-commit.
- **Dependabot**, which since Feb 2026 genuinely handles PEP 735 `[dependency-groups]`
  for uv. Group by `patterns:` — `dependency-type:` silently does nothing for uv.
- pre-commit via `repo: local` + `language: system` + `uv run --frozen --only-group
  lint`, so tool versions come from `uv.lock` and there is no `rev:` to keep in sync.
  `--force-exclude` on the ruff hooks.
- Hygiene: `SECURITY.md` (GitHub private vulnerability reporting), `CONTRIBUTING.md`,
  `CHANGELOG.md`, `CODE_OF_CONDUCT.md` (Ubuntu CoC v2.0), `.editorconfig`, YAML issue
  forms, PR template, `.gitignore`.
- **Not** doing: OpenSSF Scorecard (Contributors, Code-Review and Signed-Releases are
  structurally unpassable for a solo repo, so the badge would under-sell it — the
  checks that matter are better served by zizmor), the Canonical contributor
  agreement (inappropriate for a personal repo; Apache-2.0 §5 covers it), REUSE/SPDX
  headers (no ecosystem adoption).

## 12. Open questions for you

1. **`charmcraft register mosquitto`** — still unclaimed, and still unregistered. It
   is outward-facing and irreversible, so it is yours to run when you are ready. It
   is also the only definitive test that the name is free. (§2)

Resolved during review:

- **`snap` is an `install-source` option** after all. It carries two real costs, which
  the charm must handle rather than hide: strict confinement means every certificate,
  password file and database lives under `/var/snap/mosquitto/common/` rather than the
  FHS paths, so the workload module keeps a path table per install source; and snapd
  auto-refresh can restart the broker outside the charm's control, so the charm holds
  the snap at a pinned revision and refreshes it only via the `upgrade` path.
- **`sysctl-tuning` defaults to `true`**, degrading with a warning where the kernel
  namespace forbids the write.
- **The raw research is committed** under `docs/research/`.
