# Code review: mosquitto-operator

A detailed review of the charm, its tests, packaging and documentation. Everything
below was verified against the code, and the two behavioural findings were
reproduced: the full unit suite (709 tests), `ruff check`, `ruff format --check`
and `pyright` (strict, with the tox PYTHONPATH) all pass, and coverage sits at
exactly the 80% gate.

**Overall: this is an exceptionally well-engineered charm.** The
reconcile-everything-through-one-path design, reload-vs-restart classification at
directive level, secret hygiene (passwords never in relation data, argv, or action
results), tarball hardening, systemd sandboxing with justification comments, the
stateful test fake, and the documentation quality are all well above the usual
standard for charms. The findings below are mostly edge conditions the main paths
don't hit — but several of them are real bugs.

Suggested priority order: findings 1–3 first (silent TLS loss, silent bridge loss
and the injection gap are the ones that will bite in production), then 5–8
(error-path and hygiene bugs), then the rest as polish.

## High-severity findings

### 1. Changing TLS certificate config silently disables TLS — no new certificate is ever requested

`TLSCertificatesRequiresV4` only acts on `certificates` relation-created/changed
events (verified in the installed `charmlibs.interfaces.tls_certificates`
`_tls_certificates.py`, lines 1923–1924: the request, cleanup and renewal logic all
live in `_configure`, which nothing else invokes). The charm computes
`certificate_requests` fresh in `__init__` (`src/charm.py:67`) but never calls the
library's public `sync()` method (line 2240 of the library), so:

- Setting `certificate-common-name` / `certificate-extra-sans-dns` (which
  `docs/how-to/enable-tls.md:48-49` explicitly tells operators to do while
  integrated) sends **no new CSR**.
- Worse: on the next reconcile, `get_assigned_certificate(new_request)` finds no
  certificate matching the *new* attributes → `_tls_material()` returns `None` →
  `listeners_for()` drops the TLS listeners → the broker reloads **with TLS turned
  off**. The unit shows plain `active` with no mention that TLS just went away.
- A changed unit address (new SANs needed) hits the same path after a machine move.

**Fix:** call `self.certificates.sync()` in `_reconcile()` (it is a safe no-op when
the relation is absent), plus a unit test.

### 2. `bridge-topics` config changes never reach the upstream broker's ACL

`MQTTRequirer._publish_request` only runs on relation-created/joined/changed and
leader-elected (`src/mqtt.py`). After `juju config mosquitto bridge-topics=...`,
the local bridge fragment is re-rendered, but the *requested topic permissions*
in the requirer databag are stale, so the upstream broker never grants the new
topics — the bridge silently carries no traffic on them. This is exactly the
failure mode `_bridge_permissions()`' own docstring warns about ("asks for
nothing, is granted nothing, and silently carries no traffic").

**Fix:** add a public `sync()` to `MQTTRequirer` that republishes the request
(guarded by leadership), and call it from `_reconcile()`.

### 3. Configuration injection through the `upstream` relation

`TopicPermission._check_filter` validates topic filters against exactly this
attack ("a filter carrying a line break would let the far side of the relation
append whole `user` blocks"), but `Endpoint.host` and
`UserSecret.username`/`password` have **no** validators, and
`render_bridge_config` writes `address`, `remote_username` and `remote_password`
verbatim. Reproduced by rendering: a password of
`p\nuser _charm_metrics\ntopic readwrite #\n` injects working directives into the
bridge fragment. A compromised or buggy upstream charm could reconfigure this
broker (extra listeners, ACL grants, disabling security).

**Fix:** add the same line-break/length validators to `Endpoint.host` and both
`UserSecret` fields in `src/mqtt.py` (the boundary, where the docstring says
validation belongs), and defensively reject in `render_bridge_config`.

### 4. `allow-anonymous: true` is a no-op for actual messaging

The charm always writes an `acl_file`, and rules before the first `user` line
govern anonymous clients — but `write_acl_file` is only ever called with the
default, empty `anonymous_topics` (`src/charm.py:412`); the `anonymous_topics`
parameter in `mosquitto.render_acl_file` is dead code. So anonymous clients can
*connect* but cannot publish or subscribe anything. That contradicts the option
description ("an anonymous broker reachable off the host is an open relay") and
the status warning, which promise a working (dangerous) mode that doesn't exist.

**Fix:** either wire `anonymous_topics` into a config option (for example
`anonymous-topics`), or document that anonymous clients get no access and drop
the "open relay" phrasing from `charmcraft.yaml`, the status message and
`docs/reference/configuration.md`.

### 5. `install` and `upgrade-charm` error the unit instead of blocking on install failure

Reproduced: `ctx.run(ctx.on.install())` with a failing install raises
`InstallError` → hook error → unit in error status. The `_reconcile` path handles
this correctly (`_install_error` → `BlockedStatus`, and there is a test asserting
it — but for `config_changed`, not `install`). A slow PPA on first deploy is
precisely the situation the design comment in `_reconcile` says should block
rather than traceback. `_on_upgrade` (`src/charm.py:338`) has the same gap.

**Fix:** wrap both in the same `try/except mosquitto.InstallError` →
`self._install_error` pattern as `_install`.

### 6. `cos-agent` endpoint missing `limit: 1`

The cos_agent library's own docstring requires it: "Be sure to add `limit: 1` in
your charm for the cos-agent relation. That is the only way we currently have to
prevent two different grafana agent apps deployed on the same VM."
`charmcraft.yaml:420` has no limit. Two grafana-agent subordinates would
double-scrape and fight over the unit.

### 7. Exporter credentials survive charm removal

`remove_exporter()` (`src/mosquitto.py:1354`) deletes the unit file but leaves
`/usr/local/lib/mosquitto-charm/exporter.password` (root:600, live MQTT password)
and `exporter.py` on disk. `_on_stop`/`_on_remove` don't clean them either. After
`juju remove-application`, a valid broker password remains on the machine.

**Fix:** delete the password file (and ideally the whole
`/usr/local/lib/mosquitto-charm` directory) in `remove_exporter()`.

### 8. `_reconcile_exporter` checks the wrong service when deciding to restart the exporter

```python
if changed or not mosquitto.is_running(paths):   # src/charm.py:738
    mosquitto.start_exporter()
```

`is_running(paths)` is the **broker**, not the exporter. If the exporter unit is
stopped or failed, nothing ever restarts it (systemd's `Restart=always` covers
crashes, but not a start failure that latches, or a manual `systemctl disable`).
Add an `exporter_running()` check, or simply restart unconditionally when
cos-agent is related — it is cheap and idempotent.

## Medium-severity / robustness

1. **`_on_client_departed` isn't leader-guarded** (`src/charm.py:360`).
   `_save_users` writes app relation data and `_forget_password` removes
   app-owned secret revisions — both leader-only. On a follower (leader
   transition, or before the scale guard notices) this errors the hook.

2. **`_password_for` can call `app.add_secret` on a non-leader** (`src/charm.py:250`).
    During the leader-election window on a fresh deploy, `install`/`start` →
    `_reconcile` → `_desired_users` → `add_secret` raises `ModelError`. Guard
    with `unit.is_leader()` (blocked status) or handle the error.

3. **`set-password` doesn't validate the operator-supplied password.**
    `SetPasswordParams` checks the username but not the password
    (`src/config.py:257`); a password containing `\n`/`\r` corrupts the plaintext
    password file (extra lines → broken auth for *all* users). `generate_password`
    is safe; the operator path should get the same character check.

4. **`remove-user` on a relation-owned user silently resurrects.** The relation
    request still exists, so the next reconcile recreates it. Fail with a message
    pointing at `juju remove-relation` instead.

5. **Rejected-config rollback doesn't cover the password/ACL files.**
    `restore_fragments` puts back the three config fragments, but password/ACL
    writes that already happened stay on disk — and the nightly logrotate SIGHUP
    applies them, which is exactly the "dies at 03:00" scenario the comment
    describes, for the non-fragment parts. Consider snapshotting/restoring the
    password and ACL digests too, or writing the fragments *before* the
    password/ACL files and validating earlier.

6. **Install-source migration leaves the old package installed.** `migrate_state`
    stops/disables the old service but never uninstalls it — and the snap stays
    `hold`-ed forever. Uninstall the old source's package after a successful
    migration.

7. **Snap install source breaks log collection.** With `install-source: snap`,
    the broker log lives under `/var/snap/mosquitto/common/`, outside the
    `/var/log` trees the COS machine collectors scrape, and `log_slots` is never
    passed to `COSAgentProvider`. Document it, or pass the snap log slot for the
    snap layout.

8. **Renewal depends on CA-side relation events.** `_renew_expiring_certificates`
    only runs from relation events. Fine with self-signed-certificates (re-issues
    on its own update-status), but worth a line in the TLS how-to. Adopting
    finding #1's `sync()` in reconcile fixes this too.

9. **Status priority quirk:** ops picks the *first* of equal-priority statuses,
    so with `allow-anonymous: true` *and* a disabled bridge, the bridge message
    wins and the anonymous warning is hidden. The security-relevant warning should
    be added first, or the notes aggregated.

## Low-severity / polish

1. `INTERFACE_VERSION = 0` in `src/mqtt.py:47` is unused (the version lives in
    the docs path). Remove it or put it on the wire.

2. `create-backup` writes to any operator-supplied path with `O_TRUNC` as root,
    while `restore-backup` carefully validates paths — inconsistent; at least
    refuse to overwrite an existing non-backup file.

3. **Log spam:** with cos-agent related and `port=0`, `_reconcile_exporter` logs
    a warning every update-status (every 5 minutes) forever. Use the existing
    `_exporter_error` channel instead.

4. **No post-reload verification.** `systemctl reload` is asynchronous and
    reports success for configs the broker then rejects (the code comments
    acknowledge this). A short `health_check()` after `apply(RELOAD)` would catch
    a broker that died on a bad config within the hook — on 2.0 it is the only
    validation available, since `--test-config` is 2.1+.

5. **`last_log` reads only the journal**, but the broker is configured with
    `log_dest file`; failures after the log file opens won't show. Tail
    `paths.log_file` as well.

6. **Charmhub lib pin:** `charm-libs: version: "0"` fetches the latest v0
    revision at pack time, while `lib/` has LIBPATCH 27 committed — pack can
    silently diverge from what tests ran against. Pin the exact revision (for
    example `version: "0.27"`).

7. **Functional tests don't run in CI.** They are the only tests exercising
    `mosquitto.py`'s real apt/systemd/broker interactions (unit coverage of that
    module is 42%); they need root, so a privileged LXD/VM CI step would close
    the gap.

8. **Coverage is exactly at the gate:** 80% total, `fail_under = 80`. Any growth
    in the workload module pushes under without more pure-function tests or
    counting functional coverage.

9. **Docs inconsistencies:** README says "not published on Charmhub yet",
    CHANGELOG says "Charm revisions are published to Charmhub";
    `links.documentation` points at the README blob while a full `docs/` tree
    exists (point at `docs/index.md`).

10. `restore_backup` chowns the ACL file to 0o640 while the writer uses 0o600 —
    align.

11. The `_config`/`_config_error` properties each re-run `load_config`, so
    validation runs ~4× per hook. Trivial, but a cached property would tidy it.

## Things that are notably good (keep doing these)

- Reconcile funnel with a well-chosen set of observed events, including the
  `relation-broken` gap in the certificates library and the peer-departed/Juju
  4.0 scale-guard subtlety (with a reproducer in `contrib/`).
- Reload-safe vs restart-required directive classification, with the failure
  direction chosen conservatively ("an unnecessary restart beats a broker running
  a config nobody asked for").
- The whole secret-handling story: labels, revision-avoidance via
  `peek_content`, no argv passwords (`mosquitto_passwd -U` on a temp file,
  `$XDG_CONFIG_HOME` option files), digest-based password-file change detection.
- The custom `mqtt` interface implementation follows the charmlibs interface
  rules properly (UNKNOWN enums, `_coerce`, hyphenated wire aliases, stable
  serialisation, drop-unusable members) — apart from the two unvalidated fields
  in finding #3.
- Tarball hardening in `restore_backup` (normpath containment, link refusal,
  `filter='data'`, ownership fix-up) and the reasoning comments throughout.
- Test discipline: 709 passing unit tests, a hand-rolled stateful fake with
  signature-parity tests against the real module, interface round-trip tests,
  and real functional/integration suites.
