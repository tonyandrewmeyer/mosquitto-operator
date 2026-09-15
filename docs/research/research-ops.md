# Modern charming practice — research notes for the Mosquitto machine charm

Compiled 2026-09-15. Everything below was read from live docs, live PyPI metadata, or real
upstream source; nothing is from memory. Inline URLs throughout.

Primary sources used:

- Ops docs, `llms.txt` / `llms-full.txt`: <https://documentation.ubuntu.com/ops/latest/llms.txt>,
  <https://canonical.com/juju/docs/ops/latest/llms-full.txt> (the whole site is served as
  Markdown — append `.md` or use `index.html.md` on any page).
- `canonical/operator` on GitHub — `CHANGES.md`, and the `examples/machine-tinyproxy` and
  `examples/httpbin-demo` example charms.
- Charmcraft 4.4.2 installed locally (`snap info charmcraft` → `latest/stable: 4.4.2`, published
  2026-09-09), used to run `charmcraft init --profile machine` for the real scaffold.
- `canonical/charmlibs`, `canonical/jubilant`, `canonical/pytest-jubilant` source + PyPI JSON API.

---

## 0. Version snapshot (as of 2026-09-15)

| Thing | Current | Notes |
|---|---|---|
| `ops` | **3.8.2** (2026-08-31) | `>=3.10`. `ops 2.23` is the LTS (EOL 2038-01-25); `ops 3.8` is EOL 2027-08-31 |
| `ops-scenario` (via `ops[testing]`) | 8.8.2 | never depend on it directly — use `ops[testing]` |
| `ops-tracing` (via `ops[tracing]`) | 3.8.2 | |
| Charmcraft | **4.4.2** | `4.x/stable`. 3.x is stuck at 3.5.3 (2025-08-13) |
| Juju | 3.6 LTS (EOL 2039-04-11) and **4.0** (released 2025-11-14) | local CLI here is 3.6.28 |
| `jubilant` | **1.13.0** (2026-08-31) | there is **no** jubilant 2.x |
| `pytest-jubilant` | **2.3.0** (2026-09-03) | separate repo `canonical/pytest-jubilant` |
| `charmlibs-apt` | 1.0.0.post1 | |
| `charmlibs-systemd` | 1.0.0.post0 | |
| `charmlibs-pathops` | 1.3.0.post0 | |
| `charmlibs-passwd` | 1.0.1.post0 | |
| `charmlibs-sysctl` | 1.0.0.post0 | |
| `charmlibs-snap` | **2.0.0** (2026-08-31) | ground-up rewrite, not API-compatible with 1.x |

Tool-versions-by-base table (<https://canonical.com/juju/docs/ops/latest/explanation/versions/>):
**24.04 LTS (Noble) → Python 3.12, Juju 2.9/3.6/4.0, Ops 2.x or 3.x, Charmcraft 3.x or 4.x.**
26.04 (Resolute) → Python 3.14, Charmcraft >= 4.3 required for `base: ubuntu@26.04`.

Pebble version is fixed by the Juju version: Juju 3.6 and 4.0 both ship Pebble 1.26.0.

---

## 1. `ops` — entrypoint, status, and the reconciler pattern

### 1.1 Entrypoint: `ops.main(Charm)`

`ops.main.main()` has been **deprecated since ops 2.16.0**. The current form, straight from
<https://canonical.com/juju/docs/ops/latest/reference/ops-main-entrypoint/>:

```python
import ops

class SomeCharm(ops.CharmBase): ...

if __name__ == "__main__":
    ops.main(SomeCharm)
```

Signature: `ops.main(charm_class: type[ops.CharmBase], use_juju_for_storage: bool | None = None)`.
The charmcraft `machine` profile writes `if __name__ == "__main__":  # pragma: nocover` — keep the
`pragma`, it keeps coverage honest.

### 1.2 `ops.CharmBase` and `__init__`

Still `class MyCharm(ops.CharmBase)` with `def __init__(self, framework: ops.Framework)` and
`super().__init__(framework)`. Note the modern signature takes `framework`, **not** `*args`, and
observers are registered with `framework.observe(...)` rather than `self.framework.observe(...)`
in the current examples. From
<https://canonical.com/juju/docs/ops/latest/howto/write-and-structure-charm-code/>, arrange the
class as:

1. `__init__` — observe all relevant events, instantiate collaborators.
2. Event handlers, **in the order they are observed**, all private (`_on_foo`).
3. Other helper methods.

> "If an event handler needs to pass event data to a helper method, extract the relevant data from
> the event object and pass that data to the helper method. Don't pass the event object itself."

And: for each workload, create `src/<workload>.py` containing functions for interacting with the
workload. The charm calls the module; the module knows nothing about Ops.

### 1.3 Status: `collect_unit_status` is the default, `self.unit.status` is the exception

From the same how-to, section "Handle status":

> To report the unit status, observe the `collect_unit_status` event. This event is triggered by
> Ops at the end of each hook and provides a callback method for reporting the unit status.

```python
def _on_collect_status(self, event: ops.CollectStatusEvent):
    if 'port' not in self.config:
        event.add_status(ops.BlockedStatus('no port specified'))
        return
    event.add_status(ops.ActiveStatus())
```

You may call `event.add_status()` many times; Ops sends the **highest-priority** status to Juju.
Priority order (highest first) is Blocked > Maintenance > Waiting > Active (Error is set by Juju).
The handler has **no access to the triggering Juju event**.

`collect_app_status` is the application-level equivalent and **fires on the leader unit only**.
Observe it if you expect more than one unit. (Mosquitto: worth doing if we ever support scale.)

`self.unit.status = ops.MaintenanceStatus('...')` still exists and sends immediately — use it for
*transient, in-flight* status during a long handler. Ops still runs `collect_unit_status` at the
end of the hook, which will overwrite it with the settled status. `self.app.status` requires
`self.unit.is_leader()` first.

`ops.ActiveStatus`, `ops.BlockedStatus`, `ops.MaintenanceStatus`, `ops.WaitingStatus`,
`ops.UnknownStatus`, `ops.ErrorStatus` are all unchanged and all still live at the top level of
`ops`. In tests, compare with `==`, never `is`, and you may compare against either the `ops.*` or
the `ops.testing.*` variants.

### 1.4 Holistic vs delta — the documented guidance

<https://canonical.com/juju/docs/ops/latest/explanation/holistic-vs-delta-charms/> is the page.
Key verbatim points:

- "Holistic charms reconcile towards a goal state on every event. Delta charms handle each Juju
  event individually."
- The reconciler body has exactly three parts: **read the inputs, compute the new state, write the
  outputs.**
- "A good rule of thumb is this: if you're starting to use `defer` in various places, consider
  whether it's time to rewrite the charm using the reconciler pattern."
- "At a high level, simple workloads are served well by delta charms. Complex workloads are more
  robust if the reconciler pattern is followed. The reconciler pattern is especially suitable for
  mature, feature-rich charms that use several charm libraries."
- **"Notably, machine charms map to the delta model more readily than Kubernetes charms."**

Events that get a **dedicated handler even in a holistic charm**:

- `stop` and `remove` (the goal of reconciliation is different)
- action events (synchronous; the `ops.ActionEvent` holds args and results)
- `secret-rotate`, `secret-remove`, `secret-expired`
- Ops lifecycle events such as `collect_unit_status`
- some custom events

> "A good rule of thumb is this: if an event cannot be deferred, it needs a dedicated handler."

Events the reconcile method should observe: `install`, `start`, `config-changed`, most or all
relation events, Pebble events, storage events, `secret-changed`, `upgrade-charm`, `update-status`.

The documented reconciler skeleton (copied verbatim from the page):

```python
def __init__(self, framework: ops.Framework):
    super().__init__(framework)
    self.typed_config = self.load_config(ConfigClass, errors='blocked')
    self.workload = Workload()
    self.foo_requirer = FooRequirer()
    self.bar_provider = BarProvider()

    events = [
        self.on.start,
        self.on.config_changed,
        self.on['foo-relation'].relation_changed,
        self.on['bar-relation'].relation_changed,
        ...,
    ]

    for event in events:
        framework.observe(event, self._reconcile)


def _reconcile(self, _: ops.EventBase):
    # Early checks
    workload_ready = self.workload.is_ready
    foo_ready = self.foo_requirer.is_ready
    bar_ready = self.bar_provider.is_ready

    if not workload_ready or not foo_ready or not bar_ready:
        # Status will be set in `_on_collect_unit_status`
        return

    try:
        # 1. Read the inputs: configuration, libraries and the workload
        # 2. Compute the new state
        # 3. Write the outputs to the libraries and the workload
        ...
    except (WorkloadError, FooError, BarError, ops.ModelError, ...):
        # Error handling
        ...
```

**Verdict for Mosquitto:** the official machine-charm example (`machine-tinyproxy`) is *not* a pure
reconciler — it uses delta handlers (`_on_install`, `_on_start`, `_on_config_changed`, `_on_stop`,
`_on_remove`) that all funnel into a single idempotent `configure_and_run()` method, plus a
`collect_unit_status` handler. That "delta handlers, shared idempotent body" shape is the sweet
spot for a machine charm with a handful of relations, and is what the docs actually ship. If
Mosquitto grows TLS + auth + multiple relations, promote `configure_and_run` to a real `_reconcile`
observed by everything.

### 1.5 Deferring

<https://canonical.com/juju/docs/ops/latest/explanation/defer-guidance/>

- **Good:** retrying a short-lived transient failure (retry for up to ~a second first, then defer
  and set waiting status).
- **Reconsider:** sequencing (use a peer relation and `charm-rolling-ops` instead); waiting for a
  collection of events (use holistic handling instead).
- **Impossible (raises `RuntimeError`):** actions, `pre-commit`/`commit`/`update-status`,
  `secret-expired`/`secret-rotate`, and effectively `stop`/`remove`.
- All deferred events vanish when the unit is removed.

### 1.6 Error handling contract

From "Handle errors" in the write-and-structure guide:

- **Automatically recoverable** → `maintenance` status, retry a small number of times with short
  delays, then escalate.
- **Operator recoverable** → `blocked` status (e.g. invalid config).
- **Unexpected/unrecoverable** → raise, and let the charm enter `error` state. Make the log message
  and exception explain what happened and how to fix it.

"By default, Juju will retry hooks that fail, but users can disable this behaviour, so charms should
not rely on it."

### 1.7 Tracing is now first-class (`ops[tracing]`)

<https://canonical.com/juju/docs/ops/latest/howto/trace-your-charm/>. This is a notable 2026
addition. Add `ops[tracing]` to dependencies, declare the relations, and instantiate in `__init__`:

```yaml
requires:
  charm-tracing:
    interface: tracing
    limit: 1
    optional: true
  receive-ca-cert:
    interface: certificate_transfer
    limit: 1
    optional: true
```

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.tracing = ops.tracing.Tracing(
            self,
            tracing_relation_name='charm-tracing',
            ca_relation_name='receive-ca-cert',
        )
```

Ops then traces `ops.main()`, observer invocations, hook commands, and Pebble API access. Traces
buffer in a local sqlite DB (`.tracing-data.db`) until a tracing provider is integrated. Custom
spans use the plain OpenTelemetry API:

```python
import opentelemetry.trace
tracer = opentelemetry.trace.get_tracer(__name__)

with tracer.start_as_current_span('migrate-db') as span:
    span.add_event('db-migrate-failed', {'attempt': attempt})
```

The docs prefer the context-manager form over the decorator. In unit tests, finished spans land in
`ctx.trace_data` (a list of `opentelemetry.sdk.trace.ReadableSpan`). There is also a lower-level
`ops.tracing.set_destination(url, ca)` escape hatch, which is a no-op when called with unchanged
arguments and is therefore safe to call unconditionally from a reconciler.

The old `charm_tracing` charm library is superseded; drop `@trace_charm` and the
`opentelemetry-sdk`/`-proto`/`-exporter-*` direct dependencies.

---

## 2. Config and action typing — **first-class, and it is `load_config` / `load_params`**

This is the single biggest change from 2025-era practice. Ops now has first-class typed config,
typed action params, **and** typed relation data. There is **no** `ops.ConfigBase` and no action
base class — the API is *generic over your own class*. Your class can be a plain dataclass, a
Pydantic `BaseModel`, or anything that accepts keyword arguments and raises `ValueError` on bad
input. This is exactly the house style we wanted, and it is supported natively.

### 2.1 `ops.CharmBase.load_config`

Reference: <https://canonical.com/juju/docs/ops/latest/reference/ops/#ops.CharmBase.load_config>

```
load_config(cls: type[_T], *args: Any, errors: Literal['raise', 'blocked'] = 'raise', **kwargs: Any) -> _T
```

Verbatim from the docstring:

> Load the config into an instance of a config class.
>
> The raw Juju config is passed to the config class's `__init__`, as keyword arguments, with the
> following changes:
>
> - `secret` type options have a `model.Secret` value rather than the secret ID. Note that the
>   secret object is not validated by Juju at this time, so may raise `SecretNotFoundError` when it
>   is used later (if the secret does not exist or the unit does not have permission to access it).
> - dashes in names are converted to underscores.
>
> For dataclasses and Pydantic `BaseModel` subclasses, only fields in the Juju config that have a
> matching field in the class are passed as arguments. Pydantic fields that have an `alias`, or
> dataclasses that have a `metadata{'alias'=}`, will have the alias applied when loading.

```python
class Config(pydantic.BaseModel):
    # This field is called 'class' in the Juju config options.
    workload_class: str = pydantic.Field(alias='class')

def _on_config_changed(self, event: ops.ConfigChangedEvent):
    data = self.load_config(Config, errors='blocked')
    # `data.workload_class` has the value of the Juju option `class`
```

`errors`:

- `'raise'` (default) — no exceptions caught; the charm handles `ValueError` /
  `pydantic.ValidationError` itself.
- `'blocked'` — sets the unit to blocked with an appropriate message and **exits successfully**
  (so Juju considers the hook handled and does not retry).

Caveat worth knowing: "Pydantic classes that have fields that are not simple or Pydantic types,
such as `ops.Secret`, require setting `arbitrary_types_allowed` in the Pydantic model config."

`self.config` still exists and returns `ops.ConfigData` (a lazy mapping of
`bool | int | float | str`), but `ConfigData`'s own docstring now says: "Don't instantiate
ConfigData objects directly. To get configuration data for the application that this unit is part
of, use `CharmBase.load_config()` or `CharmBase.config`." — `load_config` is listed first.

There is also `ops.ConfigMeta(name, type, default, description)` where
`type: Literal['boolean', 'int', 'float', 'string', 'secret']` — that is the authoritative list of
Juju config option types, and note `secret` is one of them.

**Two documented placements of the call:**

1. In `__init__` (the holistic/reconciler style), so the whole charm sees `self.typed_config`:
   ```python
   self.typed_config = self.load_config(WikiConfig, errors='blocked')
   ```
2. Per-handler with `errors='raise'` and an explicit `try`, which is what `machine-tinyproxy` does,
   because it wants a *custom* blocked message built from the Pydantic error:
   ```python
   def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
       try:
           self.load_config(TinyproxyConfig)
       except pydantic.ValidationError as e:
           (slug_error,) = e.errors()
           slug_value = slug_error["input"]
           message = f"Invalid slug: '{slug_value}'. Slug must match the regex [a-z0-9-]+"
           event.add_status(ops.BlockedStatus(message))
       ...
   ```

   ...paired with a silent early-return in the worker method:
   ```python
   def configure_and_run(self) -> None:
       try:
           config = self.load_config(TinyproxyConfig)
       except pydantic.ValidationError:
           # The collect-status handler will run next and will set status for the user to see.
           return
   ```

For Mosquitto I'd use pattern (2): it gives a *useful* blocked message instead of a raw Pydantic
dump, and it keeps status-setting in exactly one place.

The full example config class, verbatim from `examples/machine-tinyproxy/src/charm.py`:

```python
class TinyproxyConfig(pydantic.BaseModel):
    """Schema for the charm's config options."""

    slug: str = pydantic.Field(
        "example",
        pattern=r"^[a-z0-9-]+$",
        description="Configures the path of the reverse proxy. Must match the regex [a-z0-9-]+",
    )
```

Note that the charmcraft `machine` profile does **not** add `pydantic` — you add it with
`uv add pydantic` (the tutorial tells you to). `pydantic>=2.13.3` is what machine-tinyproxy pins.

### 2.2 `ops.ActionEvent.load_params`

Reference: <https://canonical.com/juju/docs/ops/latest/reference/ops/#ops.ActionEvent.load_params>

```
load_params(cls: type[_T], *args: Any, errors: Literal['raise', 'fail'] = 'raise', **kwargs: Any) -> _T
```

> The raw Juju action parameters are passed to the action class's `__init__` method as keyword
> arguments, with dashes in names converted to underscores.

`errors='fail'` sets the action to failed with an appropriate message and **immediately exits**.
`errors='raise'` leaves it to you.

Documented full example (from
<https://canonical.com/juju/docs/ops/latest/howto/manage-actions/>) — note that nested `object`
params map to nested Pydantic models:

```yaml
actions:
  snapshot:
    description: Take a snapshot of the database.
    params:
      filename:
        type: string
        description: The name of the snapshot file.
      compression:
        type: object
        description: The type of compression to use.
        properties:
          kind:
            type: string
            enum:
            - gzip
            - bzip2
            - xz
            default: gzip
          quality:
            description: Compression quality
            type: integer
            default: 5
            minimum: 0
            maximum: 9
    required:
    - filename
    additionalProperties: false
```

```python
class CompressionKind(enum.Enum):
    GZIP = 'gzip'
    BZIP = 'bzip2'
    XZ = 'xz'


class Compression(pydantic.BaseModel):
    kind: CompressionKind = pydantic.Field(CompressionKind.BZIP)
    quality: int = pydantic.Field(5, description='Compression quality.', ge=0, le=9)


class SnapshotAction(pydantic.BaseModel):
    """Take a snapshot of the database."""

    filename: str = pydantic.Field(description='The name of the snapshot file.')
    compression: Compression = pydantic.Field(
        default_factory=Compression,
        description='The type of compression to use.',
    )
```

```python
def _on_snapshot_action(self, event: ops.ActionEvent):
    """Handle the snapshot action."""
    params = event.load_params(SnapshotAction, errors='fail')
    event.log(f'Generating snapshot into {params.filename}')
    size = self.do_snapshot(
        filename=params.filename,
        kind=params.compression.kind,
        quality=params.compression.quality,
    )
    if size is None:
        event.fail('Failed to generate snapshot.')
        return
    event.set_results({'snapshot-size': str(size)})
```

Observation form: `framework.observe(self.on['snapshot'].action, self._on_snapshot_action)`.

Other `ActionEvent` members: `.params` (raw dict), `.id` (the Juju task ID — use for temp filenames
and log correlation), `.log(message)`, `.fail(message)` (**does not interrupt control flow — always
follow it with `return`**), `.set_results(dict)`.

### 2.3 Bonus: typed relation data (`Relation.load` / `Relation.save`)

New enough that most 2025 charms won't have it. Reference:
<https://canonical.com/juju/docs/ops/latest/reference/ops/#ops.Relation.load>

```
load(cls: type[_T], src: Unit | Application, *args: Any, decoder: Callable[[str], Any] | None = None, **kwargs: Any) -> _T
save(obj: object, dst: Unit | Application, *, encoder: Callable[[Any], str] | None = None)
```

Values are decoded with `json.loads()` / encoded with `json.dumps()` by default, so you do **not**
need to wrap fields in `pydantic.Json`. Pydantic `alias` maps between the Python attribute name and
the Juju databag key.

```python
class Data(pydantic.BaseModel):
    # This field is called 'secret-id' in the Juju relation data.
    secret_id: str = pydantic.Field(alias='secret-id')

def _observer(self, event: ops.RelationEvent):
    data = event.relation.load(Data, event.app)
    secret = self.model.get_secret(data.secret_id)
```

```python
relation = self.model.get_relation('tracing')
data = TracingRequirerData(receivers=['otlp_http'])
relation.save(data, self.app)
```

`save` raises `RelationDataTypeError`, `RelationNotFoundError`, `RelationDataAccessError`. If a
Pydantic `model_dump` omits a field (e.g. the `MISSING` sentinel), that field is **erased** from the
databag.

Also new: `Relation.remote_model` → `ops.RemoteModel` (added in Juju 3.6.2; raises `ModelError` on
older Juju).

### 2.4 Verdict

**Use `load_config` and `load_params` with Pydantic v2 models.** Do not hand-roll a config
dataclass reader, do not use `TypedDict`, do not reach for a third-party settings library. One
Pydantic model per config schema and one per action, living in `src/charm.py` next to the charm
class (that is where every official example puts them). Keep `charmcraft.yaml` as the source of
truth for defaults/descriptions **and** mirror them in the model — the docs explicitly accept the
duplication because it buys IDE hints and static checking.

---

## 3. `charmcraft.yaml` — complete reference for a machine charm (charmcraft 4.4.2)

Verified against **charmcraft 4.4.2** (`snap info charmcraft` → `latest/stable`/`4.x/stable` =
4.4.2, 2026-09-09). The authoritative schema is the pydantic model in
`charmcraft/models/project.py` inside the snap; docs at
<https://canonical.com/juju/docs/charmcraft/4/reference/files/charmcraft-yaml-file/>.
Note `documentation.ubuntu.com/charmcraft/...` now 301-redirects to `canonical.com/juju/docs/...`,
and `/stable/` currently serves 4.5 content — pin your reading to `/charmcraft/4/`.

### 3.1 The model split: `PlatformCharm` vs `BasesCharm`

`CharmcraftProject.unmarshal()` dispatches on the presence of `bases:` — if `bases` is present you
get the legacy `BasesCharm`, otherwise the modern `PlatformCharm`. **Use `PlatformCharm`.**

### 3.2 Every top-level key

| Key | Type | Notes |
|---|---|---|
| `type` | `Literal["charm"]` | **Required.** `type: bundle` was **removed in Charmcraft 4** |
| `name` | `ProjectName` | **Required** |
| `title` | `ProjectTitle \| None` | optional |
| `summary` | str, `max_length=200` | **Required.** Docs still say "no more than 78 characters"; the model allows 200 and the source comment says it may shrink back toward 78. **Stay under 78.** |
| `description` | str | **Required** |
| `base` | `BaseStr \| None` | `PlatformCharm` only |
| `build-base` | `BuildBaseStr \| None` | `PlatformCharm` only; required **only** for devel bases |
| `platforms` | `PlatformsDict` | **Required** for `PlatformCharm` |
| `bases` | `list[BasesConfiguration]` | **Deprecated**; `BasesCharm` only; see 3.4 |
| `parts` | `dict[str, dict]`, `min_length=1` | **Required for `PlatformCharm`** — there is no implicit default part |
| `assumes` | `list[str \| dict] \| None` | optional |
| `config` | `dict \| None` | optional |
| `actions` | `dict \| None` | optional |
| `provides` / `requires` / `peers` | `dict[FieldName, Any] \| None` | optional |
| `storage` | `dict \| None` | optional |
| `devices` | `dict \| None` | optional |
| `resources` | `dict \| None` | optional |
| `extra-bindings` | `dict \| None` | optional; **deprecated in ops** ("a deprecated, regretful feature") |
| `subordinate` | `bool \| None` | optional |
| `terms` | `list[str] \| None` | optional |
| `charm-user` | `Literal["root","sudoer","non-root"] \| None` | **k8s only** — see 3.8 |
| `containers` | `dict \| None` | **k8s only** |
| `links` | `Links \| None` | optional |
| `charm-libs` | `list[CharmLib]` | optional; for Charmhub-fetched libs (which we won't use) |
| `analysis` | `AnalysisConfig \| None` | optional; suppress linters/attributes |
| `charmhub` | `Charmhub \| None` | **DEPRECATED, no longer used** |
| `extensions` | `list[str]` | popped from the raw YAML before model validation, so it isn't in `project.py` |

Keys accepted but silently ignored: `version`. Keys forced to `None` (they live under `links`
now): `license`, `contact`, `issues`, `source-code`.

`FieldName` (endpoint names) must be non-empty, must not start with `$`, must not contain `.`.
Charmcraft 4.0.0 started erroring on invalid relation names (issue #2431).

**Legacy split files** (`metadata.yaml`, `config.yaml`, `actions.yaml`) are still read and merged,
but you may **not** have both — e.g. a `config:` section plus a `config.yaml` gives
*"Cannot specify 'config' section in 'charmcraft.yaml' when 'config.yaml' exists"* (exit 65).
We use the single-file form. (Our repo currently has a stale `lib/` directory and a packed
`mosquitto_amd64.charm` — both should go.)

### 3.3 `base` + `platforms` — the exact 24.04 syntax

`base` sets the OS; `platforms` sets the architectures; **they are used together** in the
single-base form.

```yaml
base: ubuntu@24.04
platforms:
  amd64:
  arm64:
```

The shorthand `amd64:` is a YAML key with a **null value**. The `_preprocess_platforms` validator
expands it:

```python
platforms = {
    name: value if value else {"build-on": [name], "build-for": [name]}
    for name, value in values.items()
}
for name, value in platforms.items():
    if value.get("build-for") is None:
        value["build-for"] = [name]
```

Equivalent long form:

```yaml
base: ubuntu@24.04
platforms:
  amd64:
    build-on: [amd64]
    build-for: [amd64]
```

Rules:

- Shorthand requires the platform name to be a valid Debian architecture. Arbitrary platform names
  need the long form.
- Supported architectures: `amd64`, `arm64`, `armhf`, `ppc64el`, `s390x`.
- `build-for` may only contain **one** architecture, despite being a list.
- `build-for: [all]` marks an architecture-independent charm; `all` is never valid for `build-on`.
- Recommended platform name is the `build-for` architecture.

Allowed `base` / `build-base` values (`charmcraft/const.py`):

```python
CommonBaseStr = Literal[
    "ubuntu@18.04", "ubuntu@20.04", "ubuntu@22.04", "ubuntu@24.04",
    "ubuntu@25.04", "ubuntu@25.10", "ubuntu@26.04", "ubuntu@26.10",
    "almalinux@9",
]
BaseStr = CommonBaseStr
BuildBaseStr = CommonBaseStr | Literal["ubuntu@devel"]
DEVEL_BASE_STRINGS = ("ubuntu@25.04", "ubuntu@25.10", "ubuntu@26.10")
```

**`build-base` defaults to `base` and is required only when `base` is a devel base — so for
`ubuntu@24.04`, omit `build-base` entirely.**

**Multi-base** (one `.charm` per base): omit top-level `base`/`build-base` and put the base in each
platform entry. "`base` and `build-base` can't be defined for multi-base charms."

```yaml
platforms:
  ubuntu@22.04:amd64:
  ubuntu@24.04:amd64:
```

or long form with the recommended `<distribution>-<series>-<build-for-arch>` naming:

```yaml
platforms:
  ubuntu-24.04-amd64:
    build-on: [ubuntu@24.04:amd64]
    build-for: [ubuntu@24.04:amd64]
```

### 3.4 `bases:` — deprecated, and unusable for 24.04

Still accepted in 4.4.2, but:

> `bases` is deprecated, replaced by `base`, `build-base`, and platforms. The `bases` key is only
> accepted for bases supported before 2024-01-01.
> **Status:** Deprecated. Conflicts with the `base`, `build-base`, and platforms keys.

Enforced in code:

```python
LEGACY_BASES = ("ubuntu@18.04", "ubuntu@20.04", "ubuntu@22.04", "almalinux@9")
```

**So `bases:` cannot be used for Ubuntu 24.04 at all.** Anything else raises
`Base requires 'platforms' definition: {...}`. What replaced it: `base:` + `build-base:` +
`platforms:` (with `build-on`/`build-for` moving from `bases[].build-on`/`run-on` into
`platforms.<name>`).

One behavioural difference: `preprocess.add_default_parts()` injects
`parts: {charm: {plugin: charm, source: .}}` **only when `bases` is present**:

```python
# Only for backwards compatibility for bases charms.
# Platforms charms expect parts to be explicit.
if yaml_data.get("type") == "charm" and "bases" in yaml_data:
    yaml_data["parts"] = {"charm": {"plugin": "charm", "source": "."}}
```

### 3.5 `parts` — the `charm` plugin, and how to build a **uv** charm

#### The `charm` plugin (what we are moving away from)

`CharmPluginProperties` (`charmcraft/parts/plugins/_charm.py`):

```python
plugin: Literal["charm"] = "charm"
source: str = "."
charm_entrypoint: str = "src/charm.py"
charm_binary_python_packages: list[str] = []
charm_python_packages: list[str] = []
charm_requirements: list[str] = []
charm_strict_dependencies: bool = False
```

YAML spellings are kebab-case: `charm-entrypoint`, `charm-binary-python-packages`,
`charm-python-packages`, `charm-requirements`, `charm-strict-dependencies`.

- `charm-requirements` dynamically defaults to `["requirements.txt"]` **if that file exists**.
- `charm-strict-dependencies: true` requires at least one requirements file, is mutually exclusive
  with `charm-python-packages`, and changes `charm-binary-python-packages` to mean "package *names*
  allowed to be installed from binary". Its docstring: "all dependencies, direct or indirect, be
  specified within a requirements file. This includes any `PYDEPS` specified from a charm library."

Base restriction (`_validate_removed_questing_plugins`):

```python
CHARM_PLUGIN_BASES = frozenset((*LEGACY_BASES, "ubuntu@24.04", "ubuntu@24.10", "ubuntu@25.04"))
CHARM_PLUGIN_EXPERIMENTAL_BASES = frozenset(("ubuntu@26.04", "ubuntu@26.10"))
```

So the `charm` plugin still works on 24.04 but **fails on 25.10** and needs the experimental flag on
26.04+. It is on its way out.

#### The **uv plugin** — yes, it exists, and it is the machine-profile default

There is a real craft-parts `uv` plugin (`craft_parts/plugins/uv_plugin.py`), subclassed by
charmcraft (`charmcraft/parts/plugins/_uv.py`) and registered alongside `charm`, `poetry`,
`python`, and `reactive`.

**It reads `pyproject.toml` and `uv.lock`, not `requirements.txt.`** The build runs:

```python
sync_command = ["uv", "sync", "--no-dev", "--no-editable", "--reinstall"]
```

with charmcraft appending `--no-install-project`, under an environment of:

```python
"VIRTUAL_ENV": venv_dir, "UV_COMPILE_BYTECODE": "1",
"UV_PROJECT_ENVIRONMENT": venv_dir, "UV_FROZEN": "true",
"UV_PYTHON_DOWNLOADS": "never", "UV_PYTHON": '"${PARTS_PYTHON_INTERPRETER}"',
"UV_PYTHON_PREFERENCE": "only-system",
```

`UV_FROZEN=true` means **`uv.lock` must exist and be current, or the build fails.** Charmcraft
overrides the venv location to `<part install dir>/venv`, which is what the `pip-check` linter
expects.

Plugin-specific keys: `uv-extras` (`set[str]`) and `uv-groups` (`set[str]`).

**The exact working block** (verbatim from `charmcraft init --profile machine` on 4.4.2):

```yaml
parts:
  charm:
    plugin: uv
    source: .
    build-snaps:
      - astral-uv
```

`build-snaps: [astral-uv]` is **required** — the plugin's environment validator raises
`PluginEnvironmentValidationError` if `uv` isn't on `PATH`.

**Critical gotcha:** `PlatformCharm.parts` has `min_length=1` and there is **no implicit default
part** for platforms-style charms. A `charmcraft.yaml` with `base:`/`platforms:` and no `parts:`
fails validation.

Migration guide: <https://canonical.com/juju/docs/charmcraft/4/howto/migrate-plugins/charm-to-uv/>.
It also notes that uv will **not** resolve the transitive deps of Charmhub-fetched charm libs —
find their `PYDEPS` with
`find lib -name "*.py" -exec awk '/PYDEPS = \[/,/\]/' {} +` and add them manually. (Not an issue
for us: `charmlibs-*` are ordinary PyPI packages.)

### 3.6 `config`

`models/config.py` is a discriminated union on `type`:

| `type` | Python |
|---|---|
| `string` | `str \| None` |
| `int` | `pydantic.StrictInt \| None` (strict — `1.0` rejected) |
| `float` | `float \| None` |
| `boolean` | `bool \| None` |
| `secret` | `str` matching `^secret:[a-z0-9]{20}$` |

Per-option keys: `type` (required), `default`, `description`. **There is no `list`/`array`/`object`
config type.**

`secret` semantics: the charm receives a **secret URI** (`secret:<20 chars>`), and looks up the
content through the Juju secret API — or, with `load_config`, Ops hands you an `ops.Secret` object
directly (see §2.1). The source comment is candid that a `default` makes little sense for a secret:

```python
# A secret doesn't really make sense, since it's unlikely
# that anyone would know what the secret ID (specific to
# the deployment in a model) is at the time that they are
# writing the config, but included for completeness.
```

So: `type: secret` with a `description` and no `default`. Example:

```yaml
config:
  options:
    certificate:
      type: secret
      description: TLS certificate to use for securing connections
```

Best practices: lowercase alphanumeric, hyphen-separated names; good defaults so the charm deploys
with no config; don't duplicate `juju model-config` options; consider a `profile:` option for very
complex applications.

### 3.7 `actions`

Charmcraft models `actions` as `dict[str, Any]`; the real schema is Juju's
(<https://canonical.com/juju/docs/charmcraft/4/reference/files/actions-yaml-file/>):

```yaml
<action name>:
  description: <string>
  parallel: <boolean>
  execution-group: <string>
  params:
    <param>: <JSON Schema>
  required: [<param>, ...]
  additionalProperties: true | false
```

- `description` — optional but recommended.
- `params` — each value is "the YAML equivalent of a valid JSON Schema". The whole `params` map is
  inserted as the `properties` keyword of the action's schema object.
- `execution-group` — string, **defaults to `""`**. Which execution group the task goes into.
- `parallel` — boolean, **defaults to `false`**. Whether tasks may execute in parallel.
- `required` and `additionalProperties` are plain JSON Schema keywords, usable at the top level of
  an action (adjacent to `description`/`params`) **and** inside any nested schema.
- `$schema` and `$ref` are **prohibited**.

**Juju-version gating:** the one documented gate is on `additionalProperties` —
"Juju 4 flips the default used in JSON Schema (Juju 3 and JSON Schema use a `true` default, Juju 4
uses a default of `false`)." Hence the hard best practice: **always spell `additionalProperties`
explicitly**, and prefer `false`. For `parallel` and `execution-group` the 4.4.2 docs give **no**
Juju minimum version — *unconfirmed*; check the Juju changelog before quoting one.

Action names must match `^[a-zA-Z_][a-zA-Z0-9-_]*$` and must not be a Python keyword. Hyphens map
to underscores in the ops handler name. Best practice: lowercase alphanumeric with hyphens.

### 3.8 `provides` / `requires` / `peers`

Identical sub-schema for all three:

```yaml
<role>:
  <endpoint name>:
    interface: <required>
    limit: <optional int>
    optional: <optional bool, default false>
    scope: global | container   # default: global
```

- **`interface`** — **required**. Cannot be `juju`, cannot begin with `juju-`, only `a-z` and `-`,
  cannot start with `-`. **It is the only compatibility check Juju makes between two charms.**
- **`limit`** — maximum number of connections to the endpoint.
- **`optional`** — "To define if the relation is required. **Not enforced by Juju.**" Purely
  informational. Best practice: **include it on every endpoint**, explicitly, rather than relying
  on the default. *(Which Juju version added it: **unconfirmed** — charmcraft 4.4.2 gives no
  version note, unlike `charm-user` which does. It is most likely charmcraft/Charmhub metadata
  rather than a gated Juju feature.)*
- **`scope`** — `global` (default) or `container`. "Subordinate charms are only valid if they have
  at least one `requires` integration with `container` scope."

### 3.9 `storage`, `devices`, `resources`, `subordinate`, `terms`, `charm-user`, `links`

`storage` (very relevant to Mosquitto — persistence for retained messages and the broker DB):

```yaml
storage:
  <storage name>:
    type: filesystem | block        # required
    description: <description>
    location: <mount location>      # filesystem stores only
    read-only: true | false
    multiple:
      range: <n> | <n>-<m> | <n>- | <n>+
    minimum-size: <n> | <n><multiplier>   # M, G, T, P, E, Z, Y; M implied
    properties:
      - transient                   # the only supported value
```

`devices` (GPUs — irrelevant to us):

```yaml
devices:
  <device name>:
    type: gpu | nvidia.com/gpu | amd.com/gpu   # required
    description: <description>
    countmin: <n>
    countmax: <n>
```

`resources`:

```yaml
resources:
  <resource-name>:
    type: file | oci-image
    description: <string>
    filename: <path>        # file resources only
```

`oci-image` is k8s-only ("Kubernetes charms must declare an `oci-image` resource for each container
they define"). A machine charm uses `type: file`. Best practice: "For resources that are binary
files, provide binaries for all the CPU architectures you intend to support."

`subordinate: true | false` — whether the charm deploys alongside a principal. Requires at least
one `requires` endpoint with `scope: container`.

`terms: [<term>, ...]` — terms a user agrees to by using the charm.

**`charm-user`** — values `root`, `sudoer`, `non-root`; default is root. Semantics: `root` → hooks
run as root; `sudoer` → non-root user with `sudo` available to elevate; `non-root` → non-root
without sudo. But the reference carries an explicit admonition:

> `charm-user` was added in Juju 3.6.0. It's currently **only supported by Kubernetes charms and
> has no effect on machine charms.**

**So: omit `charm-user` from our `charmcraft.yaml` entirely.**

`links` (`models/charmcraft.py`, class `Links`) — note `documentation` is the only one that is
**not** list-able:

```python
contact:       pydantic.StrictStr | list[pydantic.StrictStr] | None = None
documentation: pydantic.AnyHttpUrl | None = None
issues:        pydantic.AnyHttpUrl | list[pydantic.AnyHttpUrl] | None = None
source:        pydantic.AnyHttpUrl | list[pydantic.AnyHttpUrl] | None = None
website:       pydantic.AnyHttpUrl | list[pydantic.AnyHttpUrl] | None = None
```

Best practice: "Documentation links should apply to the charm, and not to the application that is
being charmed."

`assumes` — optional, "Recommended for Kubernetes charms" but useful everywhere. Supported features
are `juju <comparison predicate> <version>` (since Juju 2.9.23) and `k8s-api` (since Juju 2.9.23),
optionally nested under `any-of` / `all-of`:

```yaml
assumes:
  - juju >= 3.6
```

(That's what the machine profile generates, and it's right for us.)

`charm-libs` — for Charmhub-fetched libs: `{lib: <charm>.<lib>, version: "<api>[.<patch>]"}` where
`version` must be a **quoted string** (`strict=True, coerce_numbers_to_str=False`, so `version: 1`
is rejected). **We shouldn't need this** — charmlibs come from PyPI.

`analysis` — suppress linters/attributes; names are validated against the real registry, so a typo
is a hard error:

```yaml
analysis:
  ignore:
    attributes: [framework]
    linters: [entrypoint]
```

`extensions` — all six available extensions (`django-framework`, `expressjs-framework`,
`fastapi-framework`, `flask-framework`, `go-framework`, `spring-boot-framework`) are **Kubernetes
12-factor extensions. There is no machine-charm extension.**

### 3.10 `charmcraft analyse` — the actual checks

The command is `charmcraft analyse` (the `analyze` spelling is **not** accepted by the 4.4.2 CLI).
It runs on a **packed** `.charm`. Options: `--format json`, `--ignore <comma-separated>`,
`--force`. The same checks run implicitly during `charmcraft pack`, and **a linter ending in
`error` blocks packing**.

The registry, in run order (`charmcraft/linters.py`, `CHECKERS`):

**Attributes** (informational; results feed Charmhub):

1. **`language`** → `python` | `unknown`. `python` when dispatch is text and executes a `.py`,
   there's a `.py` entry point, and it's executable.
2. **`framework`** → `operator` | `reactive` | `unknown`. `operator` when language is `python`,
   the charm contains `venv/ops`, and the entry point imports `ops`.

**Linters:**

3. **`metadata`** — `metadata.yaml` present, valid YAML, has `name`, `summary`, `description`.
4. **`juju-actions`** — `actions.yaml`, if present, is valid YAML. Contents not checked.
5. **`juju-config`** — `config.yaml`, if present, has an `options` dict and every item has `type`.
6. **`naming-conventions`** — **warns** when config option names, action names, or action param
   names use snake_case or mix snake_case with hyphens.
7. **`entrypoint`** — the entry point named by `dispatch` exists, is a file, and is executable.
8. **`ops-main-call`** — the entry point contains a call to `ops.main()`. `nonapplicable` when
   `framework != operator`.
9. **`additional-files`** — **errors** on files in the prime dir that weren't staged (i.e. files
   that appeared without going through a part).
10. **`pip-check`** — runs `pip --python <charm>/venv/bin/python check`. A failure is a **warning**,
    not an error. `nonapplicable` when there's no `venv/`.
11. **`pydeps`** — every `PYDEPS` declared by bundled charm libs is present in the venv, with
    version-specifier matching.

Result vocabulary (`models/lint.py`): `ok`, `warning`, `error`, `fatal`, `ignored`, `unknown`,
`nonapplicable`. Exit codes: fatal→1, error→2, warning→3, else 0.

Caveat: the shipped `docs/reference/analyzers-and-linters.rst` at 4.4.2 documents only the first
six. `naming-conventions`, `ops-main-call`, `additional-files`, `pip-check` and `pydeps` exist in
code but are undocumented there.

Practical consequences for us: the `naming-conventions` linter is why config and action names
should be hyphenated, and `ops-main-call` is why `ops.main(MosquittoCharm)` must be a literal call
in `src/charm.py`.

### 3.11 The skeleton for our charm

```yaml
# This file configures Charmcraft.
# See https://canonical.com/juju/docs/charmcraft/4/reference/files/charmcraft-yaml-file/
type: charm
name: mosquitto
title: Mosquitto
summary: Eclipse Mosquitto, an open-source MQTT broker.
description: |
  Mosquitto is a lightweight open-source message broker that implements the
  MQTT protocol versions 5.0, 3.1.1 and 3.1.

  This charm deploys and operates Mosquitto on a machine, managing its
  configuration, listeners, authentication and TLS.

  It is useful to anyone who needs an MQTT broker as part of a Juju-modelled
  deployment, from IoT gateways to inter-service messaging.

base: ubuntu@24.04
platforms:
  amd64:
  arm64:

assumes:
  - juju >= 3.6

parts:
  charm:
    plugin: uv
    source: .
    build-snaps:
      - astral-uv

links:
  documentation: https://github.com/tonyandrewmeyer/mosquitto-operator/blob/main/README.md
  issues: https://github.com/tonyandrewmeyer/mosquitto-operator/issues
  source: https://github.com/tonyandrewmeyer/mosquitto-operator
  website: https://mosquitto.org/

config:
  options:
    port:
      type: int
      default: 1883
      description: TCP port for the unencrypted MQTT listener.
    allow-anonymous:
      type: boolean
      default: false
      description: Whether clients may connect without a username and password.
    log-level:
      type: string
      default: information
      description: |
        Mosquitto log types to enable. One of "none", "error", "warning",
        "notice", "information", "debug" or "all".

actions:
  set-password:
    description: Create or update an MQTT user's password.
    params:
      username:
        type: string
        description: The MQTT username.
      password:
        type: string
        description: The new password.
    required:
      - username
      - password
    additionalProperties: false
    parallel: false

provides:
  mqtt:
    interface: mqtt
    optional: false
    scope: global

requires:
  certificates:
    interface: tls-certificates
    limit: 1
    optional: true
  charm-tracing:
    interface: tracing
    limit: 1
    optional: true
  receive-ca-cert:
    interface: certificate_transfer
    limit: 1
    optional: true

peers:
  mosquitto-peers:
    interface: mosquitto-peers
    optional: true

storage:
  data:
    type: filesystem
    location: /var/lib/mosquitto
    description: Persistence store for retained messages and queued QoS 1/2 messages.
    minimum-size: 1G
```

**Do not include:** `bases`, `containers`, `charm-user`, `charmhub`, `extensions`, `charm-libs`,
`metadata.yaml`, `config.yaml`, `actions.yaml`, `requirements.txt`, or a vendored `lib/` directory.

---

## 4. Testing

Reference: <https://canonical.com/juju/docs/ops/latest/reference/ops-testing/>
Explanation: <https://canonical.com/juju/docs/ops/latest/explanation/testing/> and
<https://canonical.com/juju/docs/ops/latest/explanation/state-transition-testing/>

Four layers are now recognised, and a machine charm should have at least three of them:

1. **Unit / state-transition tests** — `ops.testing`, no Juju, no real system calls.
2. **Functional tests** — the workload module against a *real* apt/systemd/binary, inside an LXD
   container or VM, but no Juju. *(New in the 2026 docs; 2025 charms mostly didn't have these.)*
3. **Interface tests** — `pytest-interface-tester` against `charm-relation-interfaces`. Only if we
   publish an interface.
4. **Integration tests** — Jubilant + pytest-jubilant, real Juju model.

### 4.1 `ops.testing` — never `scenario`, never `Harness`

> "In your testing dependencies, add `ops[testing]` rather than `ops-scenario` … to get access to
> the various framework classes, use the `ops.testing` namespace, rather than `scenario`."

`ops.testing.Harness` is **deprecated since ops 2.17** and will be moved out of the base package.
Migration guide:
<https://canonical.com/juju/docs/ops/latest/howto/migrate/migrate-unit-tests-from-harness/>

Import convention used by every official example:

```python
import ops
from ops import testing
```

### 4.2 The full current `ops.testing` surface

Classes (complete list from the reference page):

`ActionFailed`, `ActiveStatus`, `Address`, `BindAddress`, `BlockedStatus`, `CharmEvents`,
`CheckInfo`, `CloudCredential`, `CloudSpec`, `Container`, `Context`, `DeferredEvent`,
`ErrorStatus`, `Exec`, `ICMPPort`, `JujuLogLine`, `MaintenanceStatus`, `Manager`, `Model`, `Mount`,
`Network`, `Notice`, `PeerRelation`, `Port`, `Relation`, `RelationBase`, `Resource`, `Secret`,
`State`, `Storage`, `StoredState`, `SubordinateRelation`, `TCPPort`, `UDPPort`, `UnknownStatus`,
`WaitingStatus`, plus `ops.testing.layer_from_rockcraft` and the `ops.testing.errors.*` exceptions
(`ContextSetupError`, `AlreadyEmittedError`, `ScenarioRuntimeError`, `UncaughtCharmError`,
`InconsistentScenarioError`, `StateValidationError`, `MetadataNotFoundError`,
`ActionMissingFromContextError`, `NoObserverError`, `BadOwnerPath`).

#### `Context`

```
Context(charm_type, meta=None, *, actions=None, config=None, charm_root=None,
        juju_version='3.6.14', capture_deferred_events=False, capture_framework_events=False,
        app_name=None, unit_id=0, machine_id=None, availability_zone=None,
        principal_unit=None, app_trusted=False)
```

Note `juju_version` now defaults to `'3.6.14'` (bumped in ops 3.6.0). `machine_id` and
`availability_zone` are the machine-charm-relevant knobs; `principal_unit` is for subordinates.

Side-effect recorders on the `Context` (things that are write-only from the charm's perspective and
therefore *not* in `State`):

- `ctx.juju_log: list[JujuLogLine]`
- `ctx.app_status_history` / `ctx.unit_status_history` — note "the *current* status is **not** in
  the history", and the first unit status is always `UnknownStatus()` unless you seeded it
- `ctx.workload_version_history: list[str]`
- `ctx.removed_secret_revisions: list[int]`
- `ctx.requested_storages: dict[str, int]`
- `ctx.emitted_events: list[ops.EventBase]`
- `ctx.action_logs: list[str]`
- `ctx.action_results: dict[str, Any] | None` (None if `set_results` was never called)
- `ctx.trace_data: list[ReadableSpan]`
- `ctx.exec_history: dict[str, list[ExecArgs]]` (Pebble exec only)

`Context` is single-use. It is now also a context manager for cleanup:
`with Context(...) as ctx:` — or call `ctx.close()`. This matters because we run pytest with
`-W error` / `filterwarnings = ["error"]`, and leaving the temp dir to the GC "can clash with
pytest's teardown".

`ctx.charm_spec` is **deprecated** (ops 3.5.0) and will be removed in a future major version; use
`State.from_context()` instead.

#### Running an event

```python
state_out = ctx.run(ctx.on.<event>(...), state_in)
```

`ctx.on.*` (complete): `action(name, params=None, id=None)`, `collect_app_status()`,
`collect_unit_status()`, `config_changed()`, `custom(event, *args, **kwargs)`, `install()`,
`leader_elected()`, `pebble_check_failed(container, info)`, `pebble_check_recovered(container,
info)`, `pebble_custom_notice(container, notice)`, `pebble_ready(container)`,
`relation_broken(relation)`, `relation_changed(relation, *, remote_unit=None)`,
`relation_created(relation)`, `relation_departed(relation, *, remote_unit=None,
departing_unit=None)`, `relation_joined(relation, *, remote_unit=None)`, `remove()`,
`secret_changed(secret)`, `secret_expired(secret, *, revision)`, `secret_remove(secret, *,
revision)`, `secret_rotate(secret)`, `start()`, `stop()`, `storage_attached(storage)`,
`storage_detaching(storage)`, `update_status()`, `upgrade_charm()`.

`pre_series_upgrade()` / `post_series_upgrade()` are marked **Versionremoved**.

#### Actions: `ctx.on.action(...)`, not `ctx.run_action(...)`

`Context.run_action` is now documented as *private* with the one-line body "Use run() instead."
The current API:

```python
def test_backup_action():
    ctx = testing.Context(MyCharm)
    ctx.run(
        ctx.on.action('snapshot', params={'filename': 'db-snapshot.tar.gz'}),
        testing.State(),
    )
    assert ctx.action_logs == ['Starting snapshot', 'Table1 complete', 'Table2 complete']
    assert 'snapshot-size' in ctx.action_results
```

Failure is an **exception**, not a return value:

```python
def test_backup_action_failed():
    ctx = testing.Context(MyCharm)

    with pytest.raises(testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action('do-backup'), State())
    assert exc_info.value.message == "sorry, couldn't do the backup"
    # The state is also available if that's required:
    assert exc_info.value.state.get_container(...)

    # You can still assert action results and logs that occurred as well as the failure:
    assert ctx.action_logs == ['baz', 'qux']
    assert ctx.action_results == {'foo': 'bar'}
```

`testing.ActionFailed(message, output=None, *, state=None)` — `.message`, `.state`, and `.output`
(but `.output` is empty when using `Context.run`; the logs/results live on the `Context`).

#### `State`

```
State(*, config=None, relations=(), networks=(), containers=(), storages=(), opened_ports=(),
      leader=False, model=None, secrets=(), resources=(), planned_units=1, deferred=(),
      stored_states=(), app_status=None, unit_status=None, workload_version='')
```

All state objects are **frozen dataclasses**. Mutate with `dataclasses.replace`:

```python
import dataclasses

relation = testing.Relation('foo', remote_app_data={'1': '2'})
relation2 = dataclasses.replace(relation, remote_app_data={'3': '4'})
```

Accessors on the output state: `get_container(name)`, `get_network(binding_name)`,
`get_relation(id_or_relation_object)`, `get_relations(endpoint)`, `get_secret(*, id=, label=)`,
`get_storage(name, *, index=0)`, `get_stored_state(name, *, owner_path=None)`.

`State.from_context(ctx, *, config=None, relations=None, containers=None, storages=None,
stored_states=None, **kwargs)` (added in a recent release) builds a `State` pre-populated from the
charm's own metadata: config defaults, one relation per `requires`/`provides`/`peers` endpoint,
containers with `can_connect=True`, storages, and stored states found as class attributes. This is
a big ergonomics win over hand-building state:

```python
def test_peer_changed():
    ctx = testing.Context(MyCharm)
    state_in = testing.State.from_context(ctx, leader=True)
    rel_in = state_in.get_relations('group-chat')[0]
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
```

> **Machine-charm gotcha:** `testing.Model` defaults to `type='kubernetes'`. For a machine charm,
> pass `testing.State(model=testing.Model(type='lxd'))` when the charm's behaviour depends on
> `self.model.type` (or when you want the consistency checker to reflect reality).
> `Model(name=..., *, uuid=..., type: Literal['kubernetes','lxd']='kubernetes', cloud_spec=None)`.

`Storage(name, *, index)` has a machine-specific note: "For Kubernetes charms, this will always be
1. For machine charms, each new Storage instance gets a new index." `storage.get_filesystem(ctx)`
gives you the simulated root.

#### Relations

- `testing.Relation(endpoint, ...)` — regular.
- `testing.PeerRelation(endpoint, ...)` — peers; has `peers_data`.
- `testing.SubordinateRelation(endpoint, ...)`.
- `testing.RelationBase` is the common base and the type the `State.relations` field holds.

`State.get_relations(endpoint)` matches the endpoint **verbatim** against metadata — pass `foo-bar`,
not `foo_bar`.

#### Secrets

```
Secret(tracked_content, *, latest_content=None, id=None, owner=None, remote_grants={},
       label=None, description=None, expire=None, rotate=None)
```
`owner: Literal['unit','app'] | None` — `None` means "this charm was merely granted read access".
`tracked_content` is what `Secret.get_content()` returns; `latest_content` is what
`peek_content()` returns.

#### Deferred events

```python
ctx = testing.Context(MyCharm, capture_deferred_events=True, capture_framework_events=True)
deferred = ctx.on.update_status().deferred(MyCharm._on_foo)
ctx.run(ctx.on.start(), State(deferred=[deferred]))

assert [e.handle.kind for e in ctx.emitted_events] == [
    'update_status', 'start', 'collect_unit_status', 'pre_commit', 'commit',
]
```

To assert that the charm *deferred* something, inspect `state_out.deferred` (a sequence of
`testing.DeferredEvent(handle_path, owner, observer, snapshot_data)`).

#### Manager mode

```python
def test_status_leader(leader):
    ctx = testing.Context(MyCharm, meta={'name': 'foo'})
    with ctx(ctx.on.start(), testing.State(leader=leader)) as mgr:
        charm = mgr.charm
        assert charm.msg == ''
        assert charm.unit.status == testing.UnknownStatus()
        state_out = mgr.run()
    msg = 'I rule' if leader else 'I am ruled'
    assert charm.msg == msg
    assert charm.unit.status == testing.ActiveStatus(msg)
    assert state_out.unit_status == charm.unit.status
```

`ctx(event, state)` returns a `testing.Manager` with `.charm` (only valid inside the `with`) and
`.run()` (callable exactly once — a second call is an error). For "just poke at the charm object,
don't actually fire anything meaningful", the docs recommend using an event the charm doesn't
observe, e.g. `ctx.on.update_status()`.

#### Automatic charmcraft-extension expansion

New in ops 3.7.0: if `charmcraft.yaml` has `extensions: [flask-framework]` etc., the testing
framework expands it when loading metadata, exactly as `charmcraft expand-extensions` does. Also
new in 3.7.0: `testing.Context` accepts the `charmcraft.yaml` format directly as `meta`.

#### Consistency checking

Every `ctx.run` runs a consistency check ("is this scenario plausible in Juju?") and raises
`InconsistentScenarioError` if not — e.g. firing `foo-relation-changed` for an endpoint the charm
never declared.

### 4.3 Unit-testing a *machine* charm's workload — there is no container

This is covered explicitly at
<https://canonical.com/juju/docs/ops/latest/howto/run-workloads-with-a-charm-machines/>.

**The key point: do not patch `subprocess`, `apt` or `systemd` in the charm's state-transition
tests. Patch the whole workload module.** That only works because of the module-separation rule
(§1.2): `src/charm.py` never imports `subprocess`, only `src/mosquitto.py` does.

> "Lets you unit test the charm by mocking the module (no `subprocess` patching in state-transition
> tests). Lets you unit test the module on its own, patching only its direct system calls."

Layer A — state-transition tests, mocking the module with a hand-rolled fake object (copied
verbatim from the how-to):

```python
# tests/unit/test_charm.py
import pytest
from ops import testing

from charm import MyCharm


class MockWorkload:
    """In-memory stand-in for the workload module."""

    def __init__(self, installed: bool = False, running: bool = False):
        self.installed = installed
        self.running = running
        self.signals: list[str] = []

    def install(self) -> None:
        self.installed = True

    def uninstall(self) -> None:
        self.installed = False

    def is_installed(self) -> bool:
        return self.installed

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def reload_config(self) -> None:
        self.signals.append('SIGUSR1')

    def get_version(self) -> str:
        return '1.0.0'


@pytest.fixture
def workload(monkeypatch: pytest.MonkeyPatch) -> MockWorkload:
    mock = MockWorkload()
    monkeypatch.setattr('charm.myworkload', mock)
    return mock


def test_install(workload: MockWorkload):
    # Arrange
    ctx = testing.Context(MyCharm)
    # Act
    state_out = ctx.run(ctx.on.install(), testing.State())
    # Assert
    assert workload.is_installed()
    assert state_out.workload_version == '1.0.0'
```

Note: a *stateful fake object* (not `MagicMock`), swapped in with
`monkeypatch.setattr('charm.myworkload', mock)`. That gives you meaningful assertions like
`assert workload.is_running()` instead of `assert mock.start.called`.

The `machine-tinyproxy` example goes one step further, with a `MockTinyproxy` fixture and a second
fixture representing "installed, configured, and running" (see
<https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy/tests/unit>).

Layer B — tests for the workload module itself, patching only its direct system calls (verbatim):

```python
# tests/unit/test_myworkload.py
import signal

import pytest

from charm import myworkload


def test_install_calls_apt(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        'charm.myworkload.apt.update',
        lambda: calls.append(('update', '')),
    )
    monkeypatch.setattr(
        'charm.myworkload.apt.add_package',
        lambda name, version: calls.append((name, version)),
    )
    myworkload.install()
    assert calls == [('update', ''), ('tinyproxy-bin', '1.11.1-3')]


def test_reload_config_sends_sigusr1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
):
    pid_file = tmp_path / 'myworkload.pid'
    pid_file.write_text('1234')
    monkeypatch.setattr('charm.myworkload.PID_FILE', pid_file)

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr('os.kill', lambda pid, sig: sent.append((pid, sig)))

    myworkload.reload_config()
    assert sent == [(1234, signal.SIGUSR1)]


def test_start_runs_subprocess(monkeypatch: pytest.MonkeyPatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        'subprocess.run',
        lambda cmd, **kwargs: commands.append(cmd) or None,
    )
    myworkload.start()
    assert commands == [['myworkload']]
```

> "Keep these tests small: they exist to check that the module invokes its dependencies correctly,
> not to test those dependencies."

**Trap:** `ops.testing.Exec` is *not* for this. Its docstring is "Mock data for simulated
`ops.Container.exec()` calls" — it is Pebble-only and has no effect on `subprocess` in a machine
charm. Same for `ctx.exec_history`. Do not reach for them.

Because `PID_FILE` is a module-level `pathops.LocalPath`, monkeypatching it to a `tmp_path` works
cleanly — another argument for `charmlibs-pathops` over bare string paths.

### 4.4 Functional tests for a machine charm

New guidance, and worth adopting for Mosquitto. Quoting:

> Functional tests exercise the workload module against a real system — apt, snap, systemd, and the
> actual workload binary — but without going through Juju. They sit between unit tests (fast, fully
> mocked) and integration tests (slow, full Juju model), and catch problems that mocks can't: a
> package name typo, an apt repo that isn't enabled on the charm's base, a service that fails to
> start.
>
> Run them inside an LXD container or VM that matches the charm's base, so the side effects don't
> touch your host.

```python
# tests/functional/test_myworkload.py
import subprocess

from charm import myworkload


def test_install_and_start():
    assert not myworkload.is_installed()
    myworkload.install()
    assert myworkload.is_installed()
    assert myworkload.get_version() == '1.11.1'

    myworkload.start()
    assert myworkload.is_running()

    # The real systemd unit should be active.
    result = subprocess.run(
        ['/usr/bin/systemctl', 'is-active', 'tinyproxy'],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == 'active'

    myworkload.stop()
    assert not myworkload.is_running()
```

"Functional tests are typically run in CI on a fresh runner per test file, or locally inside a
throwaway LXD container."

For Mosquitto this is exactly the layer that catches "is `mosquitto` in noble main?", "does the deb
ship `mosquitto.service`?", "does `mosquitto_passwd` exist in `mosquitto-clients` or
`mosquitto`?" — all things a mock will happily lie about.

### 4.5 pytest hygiene the profile now bakes in

From `charmcraft init --profile machine`'s `pyproject.toml`:

```toml
[tool.pytest.ini_options]
minversion = "6.0"
log_cli = true
log_cli_level = "INFO"
log_cli_format = "%(levelname)s %(name)s %(message)s"
filterwarnings = ["error"]
```

`filterwarnings = ["error"]` is new and deliberate:

> "Ops uses `DeprecationWarning` when an API is scheduled for removal, and `ResourceWarning` for
> cleanup bugs (for example, leaked Pebble connections), so failing on those gives you early
> notice."

If a dependency raises something you can't fix, add a *targeted* ignore and keep `"error"`:

```toml
filterwarnings = [
    "error",
    "ignore:websockets.legacy is deprecated:DeprecationWarning",
]
```

---

## 5. Jubilant and pytest-jubilant 2.x

**Correction to a common assumption: `jubilant` is at 1.13.0, and there is no jubilant 2.x. It is
`pytest-jubilant` that is at 2.x (2.3.0).** Pin `"jubilant>=1.8,<2"` and
`"pytest-jubilant>=2,<3"` (machine-tinyproxy pins `>=2.0.1,<3`). `pytest-jubilant` requires
`pytest>=9.1.1`. Repos: <https://github.com/canonical/jubilant>,
<https://github.com/canonical/pytest-jubilant>.

### 5.1 Fixtures

pytest-jubilant 2.x provides exactly three fixtures (`pytest_jubilant/_main.py`), one private:

| Fixture | Scope | Public |
|---|---|---|
| `juju` | **module** | yes |
| `juju_factory` | module | yes |
| `_model_prefix` | session | no |

The only public symbol exported from the package is the `JujuFactory` protocol
(`__all__ = ["JujuFactory"]`).

`juju` semantics, verbatim:

```python
@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest, juju_factory: JujuFactory):
    """Module-scoped temporary Juju model.

    Returns a `jubilant.Juju` bound to a freshly created model that lives for
    the duration of the test module. Pass `--juju-switch` to make this the
    active model in your local `juju` CLI while the tests run.
    """
    juju = juju_factory.get_juju("")
    if request.config.getoption("--juju-switch"):
        assert juju.model  # ruff: ignore[assert]
        juju.cli("switch", juju.model, include_model=False)
    return juju
```

**One temporary model per test module, not per test.** The model is destroyed at module teardown
with `--force --destroy-storage`. You cannot change the scope of the shipped fixture (and you
cannot build a session-scoped fixture on top of `juju_factory`, because pytest forbids a wider
scope depending on a narrower one). The intended design is **split tests across modules**; each
module gets a fresh model and can run as its own CI job.

`JujuFactory` protocol, for multi-model tests:

```python
class JujuFactory(typing.Protocol):
    def get_juju(
        self,
        suffix: str,
        *,
        controller: str | None = None,
        cloud: str | None = None,
    ) -> jubilant.Juju: ...
```

```python
import pytest
import pytest_jubilant

@pytest.fixture(scope='module')
def other_model(juju_factory: pytest_jubilant.JujuFactory):
    return juju_factory.get_juju(suffix='other')
```

Calling `get_juju` twice with the same suffix on one factory raises `ValueError`.

Markers: `@pytest.mark.juju_setup` and `@pytest.mark.juju_teardown`.

### 5.2 Command-line options — exact spellings

- `--juju-model <prefix>` — *prefix* for model names (not a model name).
- `--juju-controller <name>`
- `--juju-cloud <cloud[/region]>`
- `--no-juju-setup` — skips `juju_setup`-marked tests **and** skips `juju add-model`. Requires
  `--juju-model` (enforced with a `pytest.UsageError`).
- `--no-juju-teardown` — skips `juju_teardown`-marked tests **and** doesn't destroy models.
- `--juju-switch`
- `--juju-dump-logs [dir]` — bare flag → `./.logs`.

**`--keep-models` does not exist in pytest-jubilant 2.x.** It was removed in 2.0.0. The README
says: "The `--keep-models` flag used by `pytest-operator` is unsupported as of `pytest-jubilant`
2.0! Be sure to use `--no-juju-teardown` instead."

Also gone from 1.x: `--model`, `--no-setup`, `--no-teardown`, `--switch`, `--dump-logs`, and the
markers `setup`/`teardown` (now `juju_setup`/`juju_teardown`). There is **no** `--charm-path`
option — pytest-jubilant deliberately knows nothing about charm files.

Iteration loop (from the ops how-to):

```text
# First run: deploy and keep the models
tox -e integration -- --juju-model mytest --no-juju-teardown
# Subsequent runs: skip deployment, reuse the models
tox -e integration -- --juju-model mytest --no-juju-setup --no-juju-teardown
```

After each run, `pytest_terminal_summary` prints the exact flags to reuse the models.

### 5.3 Model naming

Session prefix is `--juju-model` if given, else `jubilant-<8 hex>`. Per-module:
`<prefix>-<module name with underscores → hyphens>`. So `tests/integration/test_smoke.py` →
model `jubilant-a1b2c3d4-test-smoke`, and `get_juju(suffix='istio')` in that module →
`jubilant-a1b2c3d4-test-smoke-istio`.

### 5.4 Packing the charm — **there is no built-in helper any more**

This is the other big 1.x → 2.x break. `pytest_jubilant.pack()` and
`pytest_jubilant.get_resources()` were **removed in 2.0.0**. `jubilant` has no pack helper either.
From pytest-jubilant's `CONTRIBUTING.md`:

> "We pick up at the same point that Juju does: performing operations with packed charms. This
> means that working with unpacked charm files is out of scope, which includes reading
> `charmcraft.yaml`."

**The blessed pattern is: pack outside pytest (a CI step or a manual `charmcraft pack`), and use a
session-scoped `charm` fixture that locates the `.charm` and honours `CHARM_PATH`.** That is what
the charmcraft template, the ops how-to, and every `canonical/operator` example do.

So "pack the charm once per session" is answered by *not packing in pytest at all*. If you insist
on packing in-session, you must write a session-scoped fixture calling
`subprocess.run(['charmcraft', 'pack'], ...)` yourself; nothing upstream blesses it.

### 5.5 The canonical `conftest.py`

Verbatim from
<https://github.com/canonical/operator/blob/main/examples/machine-tinyproxy/tests/integration/conftest.py>
(byte-identical to the `charmcraft init --profile machine` template and the ops how-to):

```python
# Copyright 2026 <you>
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library and the pytest-jubilant plugin.
# See https://canonical.com/juju/docs/ops/latest/howto/write-integration-tests-for-a-charm/

import os
import pathlib

import pytest


@pytest.fixture(scope="session")
def charm():
    """Return the absolute path of the charm under test."""
    charm = os.environ.get("CHARM_PATH")
    if not charm:
        charm_dir = pathlib.Path()  # Assume the current working directory is the charm root.
        charms = list(charm_dir.glob("*.charm"))
        assert charms, f"No charms were found in {charm_dir.absolute()}"
        assert len(charms) == 1, f"Found more than one charm {charms}"
        charm = charms[0]
    path = pathlib.Path(charm).resolve()
    assert path.is_file(), f"{path} is not a file"
    return path
```

That is the **entire** conftest — the `juju` fixture comes from the plugin and must not be
redefined. The matching test module (from the `machine` profile template):

```python
import logging
import pathlib

import jubilant
import pytest

logger = logging.getLogger(__name__)


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test."""
    juju.deploy(charm, app="mosquitto")
    juju.wait(jubilant.all_active)


def test_workload_version_is_set(charm: pathlib.Path, juju: jubilant.Juju):
    """Check that the correct version of the workload is running."""
    version = juju.status().apps["mosquitto"].version
    assert version == "2.0.18"
```

Convention from the docs: "We recommend including the `charm` fixture (even though it's not used)
so that the test fails immediately if a `.charm` file isn't available."

### 5.6 `jubilant.Juju` API (1.13.0, `jubilant/_juju.py`)

```python
Juju(*, model: str | None = None, wait_timeout: float = 3 * 60.0,
     cli_binary: str | pathlib.Path | None = None)
```

```python
def wait(
    self,
    ready: Callable[[Status], bool],
    *,
    error: Callable[[Status], bool] | None = None,
    delay: float = 1.0,
    timeout: float | None = None,
    successes: int = 3,
) -> Status
```

Polls `juju status` every `delay` seconds and returns once `ready` has returned `True`
`successes` times in a row (default **3**). Raises `TimeoutError` or `jubilant.WaitError`.

```python
def deploy(
    self,
    charm: str | pathlib.Path,
    app: str | None = None,
    *,
    attach_storage=None, base=None, bind=None, channel=None, config=None,
    constraints=None, force=False, num_units=1, overlays=(), resources=None,
    revision=None, storage=None, to=None, trust=False,
) -> None

def run(self, unit: str, action: str, params: Mapping[str, Any] | None = None,
        *, wait: float | None = None) -> Task
```

`run` **raises `jubilant.TaskError` on action failure by default** — you don't have to check.

`jubilant.Task` (frozen dataclass): `.id`, `.status`
(`'aborted'|'cancelled'|'completed'|'error'|'failed'`), `.results: dict[str, Any]`,
`.return_code`, `.stdout`, `.stderr`, `.message`, `.log: list[str]`, property `.success`
(`status == 'completed' and return_code == 0`), and `.raise_on_failure()`.

Other methods: `exec(command, *args, machine=|unit=, wait=)`, `ssh(target, command, *args, ...)`,
`config(app, values=None, *, app_config=False, reset=())` (get if only `app`, set otherwise),
`integrate(app1, app2, *, via=None)`, `add_unit(app, *, num_units=1, to=None, attach_storage=None)`,
`status() -> Status`, `cli(*args, include_model=True, stdin=None)`, plus `add_model`,
`destroy_model`, `add_secret`, `grant_secret`, `show_secret`, `remove_secret`, `update_secret`,
`secrets`, `offer`, `consume`, `refresh`, `remove_application`, `remove_relation`, `remove_unit`,
`scp`, `show_model`, `show_unit`, `model_config`, `model_constraints`, `trust`, `debug_log`,
`version`, `bootstrap`, `add_cloud`, `update_cloud`, `add_credential`, `add_ssh_key`,
`remove_ssh_key`, `add_machine`.

**Gotcha:** `Status` exposes applications as **`status.apps`** (`dict[str, AppStatus]`), plus
`status.get_units(app)`. Some doc snippets still use `status.applications[...]`, which does **not**
exist on the dataclass. Use `juju.status().apps["mosquitto"]`.

### 5.7 Ready-function helpers (`jubilant/_all_any.py`, complete list)

```
all_active, all_blocked, all_error, all_maintenance, all_waiting,
any_active, any_blocked, any_error, any_maintenance, any_waiting,
all_agents_idle
```

Every one is `(status: Status, *apps: str) -> bool`. `all_*` with no apps checks every app in
`status.apps`, and checks the app status **and** every unit's workload status; a named-but-missing
app makes it `False`. `any_*` ignores missing apps. `all_agents_idle` checks the **unit agent**
status, not the workload status. There is no `all_idle`.

```python
juju.wait(jubilant.all_active)
juju.wait(lambda status: jubilant.all_active(status, 'mosquitto', 'tls-certificates-operator'))
juju.wait(jubilant.all_active, error=jubilant.any_error)
```

### 5.8 Other notes

- **No `JUBILANT_*` environment variables exist.** Neither library reads `os.environ` at all.
  `CHARM_PATH` is purely a convention of the template `charm` fixture.
- New in pytest-jubilant 2.3.0: when no `--juju-cloud` is given, each created model gets an `arch`
  model constraint matching the runtime architecture (`x86_64`/`amd64`→`amd64`,
  `aarch64`/`arm64`→`arm64`, `ppc64le`→`ppc64el`).
- **2.2.0 removed** the old behaviour of printing 1000 `juju debug-log` lines per model on failure.
  The ops how-to sentence claiming the `juju` fixture "also dumps debug logs on test failure" is
  stale — use `--juju-dump-logs` explicitly.
- Loggers: `jubilant` and `jubilant.wait` (INFO progress, DEBUG verbose status diff, ERROR on
  error states); `pytest-jubilant`. Silence noisy waits with
  `logging.getLogger('jubilant.wait').setLevel('WARNING')`.
- `jubilant.temp_model(keep=False, controller=None, cloud=None, config=None, credential=None)` is
  the non-pytest context manager, if you ever want a session-scoped model outside the plugin.

---

## 6. `charmlibs` — the PyPI replacement for Charmhub-fetched libraries

Monorepo: <https://github.com/canonical/charmlibs>. Docs:
<https://documentation.ubuntu.com/charmlibs/> (canonical URL
<https://canonical.com/juju/docs/charmlibs/>; there is an `llms.txt`).

The big structural change: **Charmhub-hosted libraries fetched with `charmcraft fetch-libs` are
being phased out in favour of ordinary PyPI packages.** See
<https://canonical.com/juju/docs/charmlibs/explanation/charmhub-libraries-deprecation/>. For our
purposes that means: no `lib/charms/operator_libs_linux/...` vendored in the repo, no
`charm-libs:` block, just `uv add charmlibs-apt`.

**Distribution name is hyphenated, import is dotted, and the idiomatic form is a `from` import:**

```python
from charmlibs import apt, pathops, systemd
```

All six are `requires-python >= 3.10`, namespace-packaged as `charmlibs.<name>`.

| Package | Version (2026-09-15) | Runtime deps | Substrate |
|---|---|---|---|
| `charmlibs-apt` | 1.0.0.post1 | `opentelemetry-api` | machine |
| `charmlibs-systemd` | 1.0.0.post0 | none | machine |
| `charmlibs-pathops` | 1.3.0.post0 | `ops>=2.19,<4` | machine **and** k8s |
| `charmlibs-passwd` | 1.0.1.post0 | none | machine |
| `charmlibs-sysctl` | 1.0.0.post0 | none | machine |
| `charmlibs-snap` | **2.0.0** (2026-08-31) | none | machine |

Migration from the old Charmhub libs: `charmlibs-apt`/`-systemd`/`-passwd`/`-sysctl` and
`charmlibs-snap` **1.x** are drop-in replacements for `operator_libs_linux.v0.apt` /
`v1.systemd` / `v0.passwd` / `v0.sysctl` / `v2.snap` — change the import and delete the vendored
file. `charmlibs-snap` **2.0 is not** (see 6.6).

### 6.1 `charmlibs-apt` 1.0.0.post1

Source:
<https://github.com/canonical/charmlibs/blob/main/apt/src/charmlibs/apt/__init__.py>

```python
def add_package(
    package_names: str | list[str],
    version: str | None = '',
    arch: str | None = '',
    update_cache: bool = False,
) -> DebianPackage | list[DebianPackage]
    # TypeError if no package name, or an explicit version with multiple packages
    # PackageError if install fails, including a package not found in the cache

def remove_package(package_names: str | list[str]) -> DebianPackage | list[DebianPackage]
def update() -> None          # runs `apt-get update --error-on=any`
def import_key(key: str) -> str   # GPGKeyError if the key could not be imported
```

Classes: `PackageState` (enum: `Present`, `Absent`, `Latest`, `Available`), `DebianPackage`
(`.ensure(state)`, `.present`, `.latest`, `.state` (settable), `.version`, `.epoch`, `.arch`,
`.fullversion`, and classmethods `from_system` / `from_installed_package` / `from_apt_cache`, all
raising `PackageNotFoundError`), `Version` (full comparison operators using the Debian algorithm),
`DebianRepository`, `RepositoryMapping`.

Exceptions: `Error` (with `.name` and `.message`) → `PackageError`, `PackageNotFoundError`,
`InvalidSourceError`, `GPGKeyError`; `InvalidSourceError` → `MissingRequiredKeyError`,
`BadValueError`.

Usage, from the module docstring:

```python
from charmlibs import apt

try:
    apt.update()
    apt.add_package("zsh")
    apt.add_package(["vim", "htop", "wget"])
except apt.PackageError as e:
    logger.error("could not install package. Reason: %s", e.message)
```

The blessed machine-charm idiom (from the ops how-to and `machine-tinyproxy`) **pins the version**:

```python
def install() -> None:
    apt.update()
    # Pin to a specific version so deployments are reproducible.
    apt.add_package('tinyproxy-bin', '1.11.1-3')
    # On failure, apt raises charmlibs.apt.PackageError, which puts the
    # charm into error status with a clear message in the Juju logs.
```

This is an explicit **best practice**: "Pin workload versions rather than installing the latest
available package. A charm that silently upgrades between reconciliations is hard to debug, and can
break if upstream introduces a breaking change."

### 6.2 `charmlibs-systemd` 1.0.0.post0

Source: <https://github.com/canonical/charmlibs/blob/main/systemd/src/charmlibs/systemd/_systemd.py>

```python
class SystemdError(Exception): ...

def service_running(service_name: str) -> bool
def service_failed(service_name: str) -> bool
def service_start(*args: str) -> bool
def service_stop(*args: str) -> bool
def service_restart(*args: str) -> bool
def service_enable(*args: str) -> bool
def service_disable(*args: str) -> bool
def service_reload(service_name: str, restart_on_failure: bool = False) -> bool
def service_pause(service_name: str) -> bool
def service_resume(service_name: str) -> bool
def daemon_reload() -> bool
```

The `*args: str` functions pass straight through to `systemctl`, so the service name is the first
arg and extra flags can follow: `systemd.service_start('--no-block', 'mosquitto')`. Everything
except `service_running`/`service_failed` raises `SystemdError` on a non-zero `systemctl` exit;
`service_pause`/`service_resume` additionally raise if the service is still running / still not
running afterwards.

```python
from charmlibs import systemd

systemd.daemon_reload()
systemd.service_enable('mosquitto')
try:
    systemd.service_restart('mosquitto')
except systemd.SystemdError:
    logger.exception('failed to restart mosquitto')
```

**This is the right library for Mosquitto**, because the `mosquitto` deb ships a systemd unit.

### 6.3 `charmlibs-pathops` 1.3.0.post0

Source: <https://github.com/canonical/charmlibs/tree/main/pathops/src/charmlibs/pathops>

```python
__all__ = ('ContainerPath', 'LocalPath', 'PathProtocol', 'PebbleConnectionError',
           'RelativePathError', 'ensure_contents')
```

```python
def ensure_contents(
    path: str | os.PathLike[str] | PathProtocol,
    source: bytes | str | BinaryIO | TextIO,
    *,
    mode: int = 0o644,
    user: str | None = None,
    group: str | None = None,
) -> bool
    # True if any change was made (content, permissions or ownership).
    # Raises LookupError (unknown user/group), NotADirectoryError, PermissionError,
    #        PebbleConnectionError (remote only)

class LocalPath(pathlib.PosixPath):
    def write_bytes(self, data, *, mode=None, user=None, group=None) -> int
    def write_text(self, data, encoding=None, errors=None, newline=None, *,
                   mode=None, user=None, group=None) -> int
    def mkdir(self, mode=0o755, parents=False, exist_ok=False, *, user=None, group=None) -> None
    def glob(self, pattern) -> Iterator[Self]
```

`ContainerPath(*parts, container: ops.Container)` is the k8s half and is irrelevant to us.
`PathProtocol` is the shared interface, only worth using if we want one code path across both
substrates. Note: no `open()`, no relative paths, no symlink manipulation, and deliberately no
`chmod` (Pebble can't) — hence the `mode`/`user`/`group` kwargs on the write/mkdir methods.
Defaults differ from `pathlib`: `0o755` for `mkdir`, `0o644` for writes.

**Two concrete wins for a machine charm:**

1. `ensure_contents` writes a config file with the right mode/owner, creates parent directories,
   and **returns whether anything actually changed** — exactly the "did the config change, do I need
   to reload?" idiom:

   ```python
   from charmlibs import pathops

   CONFIG_FILE = pathops.LocalPath("/etc/mosquitto/conf.d/juju.conf")

   def ensure_config(port: int, ...) -> bool:
       config = f"""..."""
       return pathops.ensure_contents(CONFIG_FILE, config)
   ```

   ```python
   changed = mosquitto.ensure_config(...)
   if changed:
       mosquitto.reload_config()
   ```

2. `LocalPath.write_text(..., mode=0o600, user='mosquitto', group='mosquitto')` in one call,
   instead of `write_text` + `os.chmod` + `shutil.chown`. Relevant for a password file.

It costs nothing: it depends only on `ops`, which we already have.

### 6.4 `charmlibs-passwd` 1.0.1.post0

Source: <https://github.com/canonical/charmlibs/blob/main/passwd/src/charmlibs/passwd/_passwd.py>

```python
def user_exists(user: str | int) -> pwd.struct_passwd | None       # TypeError if not str/int
def group_exists(group: str | int) -> grp.struct_group | None      # TypeError if not str/int

def add_user(
    username: str,
    password: str | None = None,
    shell: str = '/bin/bash',
    system_user: bool = False,
    primary_group: str | None = None,
    secondary_groups: list[str] | None = None,
    uid: int | None = None,
    home_dir: str | None = None,
    create_home: bool = True,
) -> pwd.struct_passwd

def add_group(group_name: str, system_group: bool = False, gid: int | None = None)
def add_user_to_group(username: str, group: str)
def remove_user(user: str | int, remove_home: bool = False) -> bool
def remove_group(group: str | int, force: bool = False) -> bool
```

These shell out to `useradd`/`groupadd`/`gpasswd`/`userdel`/`groupdel`; a failure surfaces as
`subprocess.CalledProcessError`. There is **no** library-specific exception class.

```python
from charmlibs import passwd

passwd.add_group('special_group')
passwd.add_user(username='test', secondary_groups=['sudo'])

if passwd.user_exists('some_user'):
    do_stuff()
```

(Docstring bug to be aware of: the docstring shows `add_group(name=...)`; the real parameter is
`group_name`.)

Probably **not needed** for Mosquitto — the `mosquitto` deb creates the `mosquitto` system user
itself. MQTT users are managed with `mosquitto_passwd`, not `/etc/passwd`.

### 6.5 `charmlibs-sysctl` 1.0.0.post0

Source: <https://github.com/canonical/charmlibs/blob/main/sysctl/src/charmlibs/sysctl/_sysctl.py>

```python
CHARM_FILENAME_PREFIX = '90-juju-'
SYSCTL_DIRECTORY = Path('/etc/sysctl.d')
SYSCTL_FILENAME = Path('/etc/sysctl.d/95-juju-sysctl.conf')

class Error(Exception):
    @property message
class CommandError(Error): ...      # the sysctl command failed
class ApplyError(Error): ...        # values could not be applied (snapshot restored, then re-raised)
class ValidationError(Error): ...   # another charm's 90-juju-* file sets a conflicting value

class Config(dict[str, str]):
    def __init__(self, name: str) -> None      # normally self.meta.name / self.app.name
    @property charm_filepath -> Path           # /etc/sysctl.d/90-juju-<name>
    def configure(self, config: dict[str, str]) -> None
    def remove(self) -> None
```

```python
from charmlibs import sysctl

class MyCharm(CharmBase):
    def __init__(self, *args):
        self.sysctl = sysctl.Config(self.meta.name)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.remove, self._on_remove)

    def _on_install(self, _):
        sysctl_data = {"net.ipv4.tcp_max_syn_backlog": "4096"}
        try:
            self.sysctl.configure(config=sysctl_data)
        except (sysctl.ApplyError, sysctl.ValidationError) as e:
            logger.error(f"Error setting values on sysctl: {e.message}")
            self.unit.status = BlockedStatus("Sysctl config not possible")
        except sysctl.CommandError:
            logger.error("Error on sysctl")

    def _on_remove(self, _):
        self.sysctl.remove()
```

Each charm writes `/etc/sysctl.d/90-juju-<app>`; the lib merges all `90-juju-*` files into
`/etc/sysctl.d/95-juju-sysctl.conf`, validating that charms don't set conflicting values.

Relevant to Mosquitto only if we want to raise `net.core.somaxconn` / file-descriptor-adjacent
limits for a high-connection broker. Probably a "later" item, and it should be config-gated.

### 6.6 `charmlibs-snap` 2.0.0 — **rewritten, read this before using it**

Source: <https://github.com/canonical/charmlibs/tree/main/snap/src/charmlibs/snap>
Migration guide: <https://canonical.com/juju/docs/charmlibs/how-to/charmlibs/snap/migrate-from-1x/>

2.0 (31 Aug 2026) is a ground-up rewrite. It talks to snapd **only over its REST API** (no shelling
out to the `snap` CLI), and there is **no more `SnapCache`, no `Snap` object, no `SnapState`, no
caching, and no runtime dependencies**. Everything is a module-level function taking the snap name.

```python
def ensure_installed(snap: str, channel: str | None = None, *, revision: int | str | None = None,
                     classic: bool = False, update: bool = True) -> object
def list_one(snap: str) -> InstalledInfo          # NotInstalledError if absent
def install(snap, channel=None, *, revision=None, classic=False) -> object
def refresh(snap, channel=None, *, revision=None, classic=False) -> object
def remove(snap: str, *, purge: bool = False) -> object
def hold(snap: str, duration: datetime.timedelta | int | float | None = None) -> None
def unhold(snap: str) -> None

def start(snap, services=None, *, enable: bool = False) -> None
def stop(snap, services=None, *, disable: bool = False) -> None
def restart(snap, services=None) -> None

def get(snap, keys=None) -> dict[str, Any]
def get_one(snap, key) -> Any                     # OptionNotFoundError
def set(snap, config: dict[str, Any]) -> None
def unset(snap, keys) -> None

def connect(plug: tuple[str, str], slot: tuple[str, str] | str | None = None) -> None
def disconnect(plug=None, slot=None, *, forget: bool = False) -> None
def alias(snap: str, app: str, alias: str) -> None
def unalias(alias: str) -> None
def logs(snaps=None, *, limit: int | None = 10) -> list[LogEntry]

class InstalledInfo:
    name: str; classic: bool; tracking: str; revision: str; version: str
    hold: datetime.datetime | None
```

Exceptions all subclass `snap.Error`; bad arguments raise plain `ValueError`. Transport family:
`ConnectionError` → `SocketNotFoundError` (snapd not installed), `TimeoutError` (120 s),
`BadResponseError`. API family: `APIError` → `AppNotFoundError`, `NotInstalledError`,
`NotInStoreError`, `NeedsClassicError`, `ChannelNotAvailableError`, `RevisionNotAvailableError`,
`OptionNotFoundError`, `ChangeError`.

```python
from charmlibs import snap

snap.ensure_installed('lxd', '5.21/stable')
snap.set('lxd', {'core.https_address': ':8443'})
snap.start('lxd', 'daemon', enable=True)

info = snap.list_one('lxd')
info.tracking  # '5.21/stable'
info.revision  # '33110'
info.version   # '5.21.3'
```

> **Warning: the ops how-to's snap example is stale.** It still shows
> `cache = snap.SnapCache(); cache['my-workload'].ensure(snap.SnapState.Latest, channel='stable')`,
> which is the 1.x API and does not exist in 2.0. Either write against 2.0 as above, or pin
> `charmlibs-snap<2`.

Notable 2.0 gap: **no support for installing local snaps** — `install_local` has no replacement
yet. Also gone: `Snap.restart(reload=True)`, per-service log filtering, `Snap.apps`,
`Snap.services`, `hold_refresh` (use `snap.set('system', {'refresh.hold': ...})`).

For Mosquitto: the `mosquitto` deb is in noble main, so **apt is the right choice** and we can skip
snap entirely. (For the record, there is a `mosquitto` snap, but it's third-party and less well
maintained than the archive package.)

---

## 7. What a 2026 charm has that a 2025 charm did not

### 7.1 The `charmcraft init --profile machine` scaffold (charmcraft 4.4.2, verified by running it)

Running `charmcraft init --name my-machine-demo --profile machine` with charmcraft 4.4.2 produces
**exactly** these 13 files (no more, no fewer):

```
.gitignore
CONTRIBUTING.md
LICENSE
README.md
charmcraft.yaml
pyproject.toml
tox.ini
uv.lock
src/charm.py
src/my_machine_demo.py
tests/integration/conftest.py
tests/integration/test_charm.py
tests/unit/test_charm.py
```

Points of note versus a 2025 scaffold:

- **`src/<charm_name>.py` is generated alongside `src/charm.py`.** The workload-module split is now
  the default, not an idea in a how-to. Its docstring says: "The intention is that this module
  could be used outside the context of a charm."
- **`uv.lock` is generated and must be committed.** Best practice: "Ensure that the
  `pyproject.toml` *and* the lock file are committed to version control, so that exact versions of
  charms can be reproduced."
- **No `requirements.txt`, no `metadata.yaml`, no `actions.yaml`, no `config.yaml`,
  no `lib/` directory, no `src/charm.py` `sys.path` hacks.** Everything is in `charmcraft.yaml` and
  `pyproject.toml`.
- **No `.github/workflows/`, no `icon.svg`, no `spread.yaml`** — you add those yourself.
- `tests/unit/` and `tests/integration/` both exist, but **`tests/functional/` does not** — add it.

The generated `src/charm.py` (verbatim, trimmed of the licence header):

```python
#!/usr/bin/env python3
"""Charm the application."""

import logging

import ops

# A standalone module for workload-specific logic (no charming concerns):
import my_machine_demo

logger = logging.getLogger(__name__)


class MyMachineDemoCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)

    def _on_install(self, event: ops.InstallEvent):
        """Install the workload on the machine."""
        my_machine_demo.install()

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("starting workload")
        my_machine_demo.start()
        version = my_machine_demo.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(MyMachineDemoCharm)
```

The generated `tox.ini` (verbatim) — note `runner = uv-venv-lock-runner` and `dependency_groups`
instead of `deps`:

```ini
[tox]
no_package = True
skip_missing_interpreters = True
env_list = format, lint, unit
min_version = 4.0.0

[vars]
src_path = {tox_root}/src
tests_path = {tox_root}/tests
all_path = {[vars]src_path} {[vars]tests_path}

[testenv]
set_env =
    PYTHONPATH = {tox_root}/lib:{[vars]src_path}
    PYTHONBREAKPOINT=pdb.set_trace
    PY_COLORS=1
pass_env =
    PYTHONPATH
    CHARM_BUILD_DIR
    MODEL_SETTINGS

[testenv:format]
description = Apply coding style standards to code
deps =
    ruff
commands =
    ruff format {[vars]all_path}
    ruff check --fix {[vars]all_path}

[testenv:lint]
description = Check code against coding style standards, and static checks
runner = uv-venv-lock-runner
dependency_groups =
    lint
    unit
    integration
commands =
    codespell {tox_root}
    ruff check {[vars]all_path}
    ruff format --check --diff {[vars]all_path}
    pyright {posargs}

[testenv:unit]
description = Run unit tests
runner = uv-venv-lock-runner
dependency_groups =
    unit
commands =
    coverage run --source={[vars]src_path} -m pytest \
        -v \
        -s \
        --tb native \
        {[vars]tests_path}/unit \
        {posargs}
    coverage report

[testenv:integration]
description = Run integration tests
runner = uv-venv-lock-runner
dependency_groups =
    integration
pass_env =
    # The integration tests don't pack the charm. If CHARM_PATH is set, the tests deploy the
    # specified .charm file. Otherwise, the tests look for a .charm file in the project dir.
    CHARM_PATH
commands =
    pytest \
        -v \
        -s \
        --tb native \
        --log-cli-level=INFO \
        {[vars]tests_path}/integration \
        {posargs}
```

**Best practice, explicitly stated:** "All charms should provide the commands configured by the
Charmcraft profile, to allow easy testing across the charm ecosystem. It's fine to tweak the
configuration of individual tools, or to add additional commands, but keep the command names and
meanings that the profile provides." So: keep `tox -e format`, `tox -e lint`, `tox -e unit`,
`tox -e integration`, and bare `tox` running format+lint+unit.

Linting is **ruff + codespell + pyright**. Not black, not flake8, not isort, not mypy.
`line-length = 99`, `lint.select = ["E", "W", "F", "C", "N", "D", "I001"]`.

The generated `pyproject.toml` dependency groups:

```toml
[project]
requires-python = ">=3.10"
dependencies = [
    "ops~=3.7",
]

[dependency-groups]
lint = ["ruff", "codespell", "pyright"]
unit = ["coverage[toml]", "ops[testing]", "pytest"]
integration = ["jubilant>=1.8,<2", "pytest", "pytest-jubilant>=2.0.1,<3"]
```

Note `[dependency-groups]` (PEP 735), **not** `[project.optional-dependencies]` and **not**
`requirements-*.txt`.

### 7.2 uv is the default dependency manager, and the `charm` plugin is deprecated in practice

Explicit best practice: **"Avoid using Charmcraft's `charm` plugin if possible. Instead, migrate to
the uv plugin or the poetry plugin."**
(<https://canonical.com/juju/docs/charmcraft/latest/howto/migrate-plugins/charm-to-uv/>)

Corollaries:

- Use `uv add` / `uv remove`, not hand-editing `pyproject.toml`, then `uv lock`.
- Commit `uv.lock`.
- Set `requires-python` so tooling catches use of features newer than the oldest base.
- "Ensure that tooling is configured to automatically detect new versions, particularly security
  releases, for all your dependencies" — i.e. wire up Dependabot/Renovate.

### 7.3 `charmcraft test` and Spread

`charmcraft test` exists in 4.4.2:

```
Usage:
    charmcraft test [options] <test_expressions>

Summary:
    Run spread tests for the project.
```

But the current recommendation (ops `CHANGES.md` 3.8.2: "Recommend spread directly, rather than
charmcraft test") is:

> "Charmcraft also has an experimental `charmcraft test` command, which is a wrapper around Spread.
> We suggest using Spread directly until `charmcraft test` is finalised. The workflow below uses
> `charmcraft test` as a convenient way to install and configure Spread."

Spread needs two things: a `spread.yaml` at the project root, and one
`spread/integration/<module>/task.yaml` per test module. Real files from `httpbin-demo`:

`spread.yaml`:

```yaml
project: httpbin-demo

backends:
  craft:
    type: craft
    systems:
      - ubuntu-24.04:

prepare: |
  # Juju needs the charm etc. to be owned by the running user.
  chown -R "${USER}" "${PROJECT_PATH}"

suites:
  spread/integration/:
    summary: Integration tests

    environment:
      # `uv tool install` places binaries under the invoking user's ~/.local/bin.
      PATH: $PATH:/root/.local/bin

    prepare: |
      sudo snap install --classic concierge
      sudo concierge prepare --trace -p k8s --extra-snaps astral-uv
      uv tool install tox --with tox-uv

exclude:
  - .git
  - .tox
  - .venv
  - .ruff_cache
  - .pytest_cache
  - .coverage

kill-timeout: 90m
```

(For Mosquitto: `-p machine` instead of `-p k8s`.)

`spread/integration/test_charm/task.yaml`:

```yaml
summary: Run test_charm integration tests

execute: |
  cd "${SPREAD_PATH}"
  CHARM_PATH="${CRAFT_ARTIFACT}" tox -e integration -- tests/integration/test_charm.py
```

CI matrix job:

```yaml
  integration:
    name: Integration / ${{ matrix.task }}
    runs-on: ubuntu-latest
    needs:
      - unit
    strategy:
      fail-fast: false
      matrix:
        task:
          - test_charm
          # Add one entry per spread/integration/<module>/task.yaml.
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up LXD
        uses: canonical/setup-lxd@8c6a87bfb56aa48f3fb9b830baa18562d8bfd4ee  # v1
        with:
          channel: 5.21/stable
      - name: Install charmcraft
        run: sudo snap install charmcraft --classic
      - name: Run spread test
        # On GitHub Actions (CI=true) charmcraft test runs spread against the
        # runner itself, instead of launching a nested LXD VM.
        run: charmcraft test "craft:ubuntu-24.04:spread/integration/${{ matrix.task }}"
```

### 7.4 Splitting integration tests across modules is now the recommended structure

Because the `juju` fixture is module-scoped, one model per module:

- `test_charm.py` — smoke: pack, deploy, reach active.
- `test_<feature>.py` — `test_tls.py`, `test_auth.py`, `test_upgrade.py`, `test_scaling.py`.

"Adding a new `test_*.py` file and corresponding `task.yaml` then automatically adds a new CI job,
with no workflow changes needed."

### 7.5 Concierge replaces bespoke environment setup

<https://canonical.com/juju/docs/concierge/>

```text
sudo snap install --classic concierge
sudo concierge prepare -p machine --extra-snaps astral-uv
```

In CI, the same tool: `sudo concierge prepare -p machine`. Presets are `machine`, `k8s`, etc.
Locally, do it inside Multipass:

```text
multipass launch --cpus 4 --memory 8G --disk 50G --name juju-sandbox 24.04
multipass mount --type native ~/code/mosquitto-operator juju-sandbox:~/mosquitto
uv tool install tox --with tox-uv
```

### 7.6 CI workflow (current, hash-pinned)

From <https://canonical.com/juju/docs/ops/latest/howto/set-up-continuous-integration-for-a-charm/>.
Note `permissions: {}`, `persist-credentials: false`, hash-pinned third-party actions,
`actions/checkout@v6` and `actions/upload-artifact@v7`:

```yaml
name: Charm tests
on:
  push:
    branches:
      - main
  pull_request:
  workflow_call:
  workflow_dispatch:

permissions: {}

jobs:
  lint:
    name: Linting
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Lint the code
        run: tox -e lint

  unit:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run unit tests
        run: tox -e unit

  integration:
    name: Integration tests
    runs-on: ubuntu-latest
    needs:
      - unit
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Set up Concierge
        run: sudo snap install --classic concierge
      - name: Set up Juju and charm development tools
        run: sudo concierge prepare -p machine
      - name: Pack the charm
        run: charmcraft pack
      - name: Run integration tests
        run: tox -e integration -- --juju-dump-logs logs
      - name: Upload logs
        if: ${{ !cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: integration-test-logs
          path: logs
```

Best practice: "Configure your continuous integration tooling so that whenever changes are proposed
for or accepted into your main branch the `lint`, `unit`, and `integration` commands are run, and
will block merging when failing."

### 7.7 Naming and repository conventions

<https://canonical.com/juju/docs/ops/latest/howto/initialise-your-project/>

- Charm name pattern: `<workload name>[-<function>][-k8s]`. ASCII lowercase, digits, hyphens.
- **No `operator` or `charm` prefix/suffix in the charm name**, and no publisher name.
- The `-k8s` suffix is for *disambiguation*, not classification, and only when a machine variant
  exists or could exist. So our charm is **`mosquitto`**, not `mosquitto-operator` and not
  `mosquitto-machine`.
- The **repository** should be `<charm name>-operator` when the charm operates a workload — so
  `mosquitto-operator` is the correct repo name (which is what we have). Pass `--name mosquitto`
  to `charmcraft init` so the charm doesn't inherit the `-operator` suffix from the directory.
- Integrator/configurator charms use `-integrator`/`-configurator` and drop `-operator` from the
  repo name.

### 7.8 Best-practice list (auto-generated upstream, worth treating as a checklist)

From the bottom of
<https://canonical.com/juju/docs/ops/latest/howto/write-and-structure-charm-code/>, the ones that
bind a machine charm:

- Name the repo `<charm name>-operator`.
- Capture output to stdout/stderr in the charm; use logging, not `print()`; capture subprocess
  output.
- Log messages must be clear and meaningful; avoid spurious logging (don't log that a handler was
  called — Juju already does).
- **Never log credentials or other sensitive information.** Also not in CLI arguments.
- Provide the commands the Charmcraft profile configures.
- Don't duplicate model-level config options controlled by `juju model-config`.
- Libraries must never mutate unit/app status — return values or raise.
- **Pin workload versions** rather than installing latest.
- **Safe subprocess:** absolute paths (`/usr/bin/apt`, not `apt`), arguments as a list not a shell
  string, `check=True`, `capture_output=True`.
- Automate the QA pipeline in CI.
- Avoid the Charmcraft `charm` plugin; use uv.
- Commit the lock file; automate dependency updates; set `requires-python`.
- **Include `optional:` in *all* endpoint definitions**, even though Juju doesn't enforce it.
- **Always explicitly include `additionalProperties`** in actions (default flipped from `true` in
  Juju 3 to `false` in Juju 4).
- Prefer lowercase-alphanumeric, hyphen-separated action and config names (but be consistent within
  a charm).
- Configure the application with the best defaults; ideally deployable with no config.
- Documentation links should be about the charm, not the workload.

### 7.9 Charm maturity expectations (phase 4)

<https://canonical.com/juju/docs/ops/latest/explanation/charm-maturity/>. A mature charm:

- has sensible defaults (auto-generate initial passwords and surface them via an action or a
  secret);
- is compatible with the ecosystem (submit new public interfaces for review; ship a library);
- **respects `juju-http-proxy` / `juju-https-proxy` / `juju-no-proxy`**;
- upgrades the workload and application safely, preserving data and settings;
- supports scaling up and down;
- is integrated with observability (COS).

### 7.10 Other smaller changes worth knowing

- `charmcraft analyse` (US spelling `analyze` also accepted) takes `--format json` and
  `--ignore <comma-separated linters>`.
- `ops.hookcmds` is a new public low-level module giving direct access to Juju hook commands. Not
  intended for charms to use directly — it exists for alternatives to Ops.
- Structured **security event logging**: Ops now emits OWASP-vocabulary JSON security events
  (`sys_crash`, `sys_restart`, `sys_monitor_disabled`, `authz_fail`) to `juju-log` at TRACE level.
  Nothing to do on our side except not to set the unit log level above TRACE in production.
- `jhack scenario snapshot` can capture live model state and turn it into `ops.testing` code.
- `juju debug-code` now supports stepping through charm code, and `debugpy` remote debugging into
  a Multipass VM is documented.
- `ops` state DB is `.unit-state.db` in `JUJU_CHARM_DIR`, mode `0600`; the tracing buffer is
  `.tracing-data.db`, mode `0644`.

---

## Appendix A: Pebble — what does *not* apply to a machine charm

Pebble (<https://documentation.ubuntu.com/pebble/>) is the lightweight Linux service manager that
Juju injects into the **workload container of a Kubernetes sidecar charm**. A machine charm has no
Pebble, no workload container, and no `containers:` in `charmcraft.yaml`. Therefore **none** of the
following applies to us, and seeing any of it in a machine charm is a bug:

| Pebble/k8s concept | Machine equivalent |
|---|---|
| `containers:` in `charmcraft.yaml` | (nothing — k8s only) |
| `resources:` with `type: oci-image` / `upstream-source` | (nothing; machine resources are `file` type) |
| `self.on['x'].pebble_ready`, `ops.PebbleReadyEvent` | `install` / `start` |
| `ops.Container`, `unit.get_container()` | the machine itself |
| `container.can_connect()` | n/a — the machine is always "there" |
| `ops.pebble.Layer`, `container.add_layer()`, `container.replan()` | a systemd unit + `charmlibs-systemd` |
| `container.start/stop/restart(service)` | `systemd.service_start/stop/restart` |
| Pebble health checks, `pebble_check_failed`/`pebble_check_recovered` | systemd `Restart=`/watchdog, or our own `update-status` probe |
| Pebble custom notices, `pebble notify` | (nothing) |
| Pebble metrics (`/v1/metrics`) | the workload's own metrics endpoint |
| `container.push/pull/list_files/exec` | ordinary file I/O, `charmlibs-pathops.LocalPath`, `subprocess` |
| `ops.testing.Container`, `Mount`, `Notice`, `CheckInfo`, `Exec`, `layer_from_rockcraft` | not used; mock the workload module instead |
| `ctx.on.pebble_ready(...)`, `ctx.exec_history` | not used |
| Rockcraft / OCI images | apt or snap on the base |

**The one trap worth repeating:** `ops.testing.Exec` mocks `ops.Container.exec()` — that is, Pebble
exec. It does **not** mock `subprocess.run`. In a machine charm, patch `subprocess` (or better, the
whole workload module) with `monkeypatch`.


---

## Appendix B: proposed repository layout

```
mosquitto-operator/
├── charmcraft.yaml            # single source of metadata; see §3.11
├── pyproject.toml             # [project] + [dependency-groups]; PEP 735
├── uv.lock                    # COMMITTED
├── tox.ini                    # format / lint / unit / integration (profile names, unchanged)
├── spread.yaml                # optional: parallel integration tests
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── icon.svg                   # needed for Charmhub listing; not generated by the profile
├── .github/workflows/ci.yaml
├── src/
│   ├── charm.py               # MosquittoCharm, MosquittoConfig, *Action models, ops.main(...)
│   └── mosquitto.py           # workload module: apt, systemd, pathops, mosquitto_passwd
├── spread/
│   └── integration/
│       └── test_charm/task.yaml
└── tests/
    ├── unit/
    │   ├── test_charm.py      # ops.testing, MockMosquitto fake
    │   └── test_mosquitto.py  # monkeypatched apt / systemd / subprocess
    ├── functional/
    │   └── test_mosquitto.py  # real apt + systemd inside LXD
    └── integration/
        ├── conftest.py        # ONLY the session-scoped `charm` fixture
        ├── test_charm.py
        ├── test_config.py
        └── test_actions.py
```

Things to delete from the current repo: the stale `lib/` directory, the committed
`mosquitto_amd64.charm`, `.coverage`, and any `metadata.yaml`/`config.yaml`/`actions.yaml`/
`requirements.txt` if present.

## Appendix C: open questions I could not resolve

1. **Which Juju version added the `optional` endpoint key.** Charmcraft 4.4.2 docs and source give
   no version note (unlike `charm-user`, which explicitly says "added in Juju 3.6.0"), and a web
   search found nothing. Since it is purely informational and not enforced by Juju, it is most
   likely charmcraft/Charmhub metadata rather than a gated Juju feature. Don't quote a version
   without checking the Juju changelog.
2. **Juju version gating for `parallel` and `execution-group` on actions.** Documented with
   defaults but no minimum version.
3. **Whether overriding the `juju` fixture at session scope in your own `conftest.py` is
   supported.** No upstream example exists; the design clearly assumes module scope.
4. An end-to-end `charmcraft pack` of a uv-based machine charm was **not** run (it needs an
   LXD/Multipass build). The `parts:` block is verified valid against the project model via
   `charmcraft expand-extensions` and is the literal 4.4.2 template output, but the build itself
   was not observed.
5. `riscv64` appears in charmcraft's own sample `charmcraft.yaml` and in the select-platforms
   how-to, but is absent from the supported-architecture table in `docs/reference/platforms.rst`.
   Upstream inconsistency.

## Appendix D: stale things in the official docs (don't copy them blindly)

- The machine-workloads how-to's **snap example uses the `charmlibs-snap` 1.x API**
  (`SnapCache`, `SnapState`), which does not exist in 2.0.
- The integration-testing how-to uses **`status.applications[...]`**; the `jubilant.Status`
  dataclass field is **`apps`**.
- The integration-testing how-to says the `juju` fixture "also dumps debug logs on test failure" —
  that behaviour was **removed in pytest-jubilant 2.2.0**. Use `--juju-dump-logs`.
- One `manage-actions` integration-test snippet assigns to `task` then asserts on `action` —
  a typo upstream.
- The `charmcraft.yaml` reference says `summary` is "No more than 78 characters"; the pydantic
  model allows 200.
- The `build-base` reference section's example block shows `base: ubuntu@devel` under the
  `build-base` heading.
- The `machine` profile's generated `config` option describes "the log level of **gunicorn**" —
  copy-paste leftover from the Kubernetes profile.
- `CONTRIBUTING.md` from the profile still advertises `tox run -e static`, an environment removed
  in charmcraft 4.0 (merged into `lint`).
