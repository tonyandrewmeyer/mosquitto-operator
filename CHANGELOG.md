# Changelog

All notable changes to this charm are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for its
commit messages.

The charm is not published on Charmhub yet; build it from this repository. Once
it is, each release below will note the Charmhub revision it corresponds to:
unlike a library, a charm has no independent version number, so the revision is
the version.

Add entries for user-visible changes under `## [Unreleased]` as you work. When
a revision is published, `[Unreleased]` is renamed to the release heading and a
fresh `[Unreleased]` section is added above it.

## [Unreleased]

The first working version of the charm. Everything below is new, so this is a
description of what the charm does rather than a list of changes to it.

### Added

- Installs and operates Mosquitto on a machine, from the Ubuntu archive, the
  upstream PPA or the snap, with 33 configuration options covering listeners,
  authentication, TLS, persistence, limits, logging and tuning.
- Distinguishes a configuration change that needs a reload from one that needs
  a restart, at the level of individual directives, so that most
  reconfiguration does not disconnect a single client. Anything not known to be
  reload-safe is treated as needing a restart, because the reload-safe set
  differs between Mosquitto 2.0 and 2.1.
- Manages MQTT users and topic permissions through the `set-password`,
  `remove-user`, `list-users`, `grant` and `revoke` actions.
  Passwords are held in application-owned Juju secrets and never appear in
  action results, relation data, logs or command lines.
- Offers the `mqtt` integration, so related applications get their own user,
  their own password in a Juju secret, and only the topic permissions they
  asked for. The same integration is used in the requiring direction to bridge
  two Mosquitto applications together, which is how multi-broker topologies are
  built, since Mosquitto does not cluster.
- Obtains TLS certificates over `tls-certificates`, and opens the TLS listeners
  only once a certificate is available.
- Ships a dependency-free `$SYS` metrics exporter, Prometheus alert rules and a
  Grafana dashboard, published over `cos-agent`.
- Emits charm traces over `charm-tracing`.
- `health-check` performs a real MQTT round trip rather than a TCP connect, and
  checks the TLS listener separately, which is the only way to catch a
  certificate renewal that left the key unreadable.
- `create-backup`, `restore-backup`, `broker-stats`, `force-reconfigure`,
  `pause` and `resume` for day-2 operations.
- Sets the broker's file descriptor limit, which the packaged systemd unit does
  not: without it the broker inherits 1024 and stops accepting connections at
  roughly a thousand clients.
- Adds systemd sandboxing, since Ubuntu 24.04 ships no AppArmor profile for
  Mosquitto despite what its `README.Debian` says.
- Refuses to run more than one unit. Mosquitto does not replicate state, so two
  units are two unrelated brokers, and a client reconnecting to the other one
  finds its session, queued messages and retained messages gone.
- Refuses to configure a bridge on Mosquitto older than 2.0.19, which is
  vulnerable to CVE-2024-3935 through bridge topic remapping. Ubuntu 24.04
  ships 2.0.18.
- Repository infrastructure: `pyproject.toml` and `tox.ini` driven entirely
  from `uv.lock`, GitHub Actions CI (lint, unit, a dependency audit of the
  locked runtime graph, pack, and integration against Juju 3.6 and 4.0), a
  zizmor workflow, Dependabot, pre-commit hooks, issue and pull request
  templates, and the security, contributing, code-of-conduct and changelog
  files.

### Changed

- The `mqtt/v0` interface documents `client-id-prefix` as something a provider
  *may* publish rather than something it does. Mosquitto has no way to reserve a
  client ID prefix, so this charm publishes none, and a requirer is expected to
  choose its own client ID when none is published. `mtls-cert` is likewise
  documented as reserved for a later version, with no provider behaviour in v0.
- The security model documents the bridge configuration fragment as a place a
  remote broker's password sits in plain text, which is the one credential the
  charm cannot protect any further: Mosquitto will read a bridge password from
  nowhere else.

### Deprecated

### Removed

### Fixed

- `grant` and `revoke` refuse a user that came from an `mqtt` integration, as
  `remove-user` already did. Those permissions are rewritten from the relation
  during the very reconciliation the action performs, so the action reported a
  permission the broker had already dropped.
- `create-backup` will not create a root-owned file wherever it is pointed. A
  destination outside the charm's backup directory has to be an absolute path in
  a directory that already exists, and never under `/etc`, `/usr`, `/bin`,
  `/sbin`, `/lib`, `/boot`, `/root`, `/run`, `/dev`, `/proc`, `/sys` or
  `/var/lib/juju`. The parent is resolved first, so a symlinked directory is not
  a way around it. Backups to a mounted share still work.
- `stop`, `storage-detaching` and `remove` operate the broker through the
  install source it was installed from, recorded in the peer relation, rather
  than the configured one. On a snap unit whose configuration had become
  invalid, the charm reached for `systemctl stop mosquitto` and `apt`, failed,
  and let Juju detach the storage underneath a running broker.
- The `MosquittoExporterDown` alert names the service the charm actually
  installs, `mosquitto-charm-exporter`. The runbook text sent an operator
  looking for `mosquitto-exporter`, which is not on the unit.
- The metrics exporter listens on `127.0.0.1` rather than on the unit's private
  address. The `cos_agent` library builds its scrape target as
  `localhost:<metrics-port>` and the collector is a subordinate on the same
  machine, so a socket bound to the private address refused every scrape it
  made: the metrics integration collected nothing at all.
- A configuration the broker accepts and then dies on, or one it keeps running
  while breaking authentication or the ACL file, is taken back off disk and the
  broker is put back on the one it was serving. Reconciliation now proves the
  change with the same QoS 1 round trip `health-check` uses. The archive's 2.0
  build has no `--test-config` to catch any of this first, and a rejected
  configuration left on disk takes the broker down at the next logrotate SIGHUP
  or reboot, hours after the operator walked away from a blocked unit.
- Changing `package-channel` refreshes the snap, which is what the upgrade
  documentation has always said it does. The charm holds the snap, so nothing
  else ever moved it: the documented way to take a security update quietly did
  nothing until some unrelated charm upgrade came along.
- The unit count comes from Juju's goal state rather than from peer relation
  membership. Juju 4.x never removes a departed unit from a *peer* relation and
  sends no departed hook, so a deployment that was scaled to two units and back
  stayed blocked for ever with nothing left to wake it.
- `storage-detaching` stops the broker and the exporter. The persistence
  database lives on that storage and the broker holds it open, so detaching
  underneath a running broker either failed to unmount or lost everything since
  the last autosave.
- Mutating actions fail when the broker did not take the change, instead of
  reporting success against a record only the charm can see. `pause` records
  that the broker is paused only once it really is down — recording it first and
  then failing to stop left the charm reporting a paused broker that was still
  serving every client on it, through a flag that stopped every later
  reconciliation from noticing.
- `restore-backup` fails when the broker will not start on what was restored,
  rather than reporting `restored` over a broker that is still down.
- A configuration whose only listeners are TLS ones keeps the broker stopped
  until a certificate arrives. Rendering it with no `listener` directive at all
  did not disable the broker: Mosquitto 2.x answers that by opening its own
  plaintext listener on loopback, which is what `port=0` asked it not to do.
- TLS material and the bridge authority are removed when their integrations go,
  rather than leaving a private key on a machine that no longer serves TLS and
  sweeping it into every later backup.
- The exporter's staleness window follows `sys-interval` — three intervals, and
  never less than 60 seconds — so a broker with `sys-interval` above 60 no
  longer flaps between up and down between publishes and pages on the critical
  `MosquittoDown` alert while working perfectly well.
- `MosquittoConnectionsNearLimit` is a ratio against the configured
  `max-connections`, which the exporter now publishes as
  `mosquitto_max_connections`, rather than a threshold of 870 tied to the
  default.
- `health-check` covers the WebSocket listeners, which were advertised in the
  metadata and the relation endpoints with no way to check them at all: a
  WebSocket-only deployment could be active with nothing having proved that its
  only transport worked.
- An archive build of Mosquitto without the ESM revision is named in the unit
  status. The default install source has no standard security support, which was
  documented but only where an operator who had already deployed would not look.
- `open-file-limit` at or below `max-connections` is rejected. The broker would
  start refusing connections before reaching the ceiling that was configured,
  with `accept: Too many open files` in a log nobody reads as the only symptom.
- An empty `password` for `set-password` is rejected rather than quietly
  replaced with a generated one while the action reported `generated=false`.
- `create-backup` opens its destination with `O_EXCL` and `O_NOFOLLOW`. The
  action's own check that the path does not exist is a syscall earlier, and the
  backup is written as root.
- Changing `certificate-common-name`, `certificate-extra-sans-dns` or
  `certificate-organization` now sends a new certificate request. The charm
  previously left the old request in place, so the authority never issued a
  matching certificate — and because no issued certificate matched the new
  attributes any more, the TLS listeners disappeared at the next
  reconfiguration.
- A failed install during the `install` or `upgrade-charm` hook now blocks the
  unit with the reason, as it already did everywhere else, instead of ending the
  hook in a traceback. A first deploy against a slow PPA is where this happens.
- A unit that is not the leader no longer errors its hook when a client's
  relation departs, or when it reconciles before leadership is settled. It waits
  instead, and `leader-elected` is now observed so that something wakes it.
- The metrics exporter is started again when it is not running. The check was
  against the broker's service, which is always running by that point, so an
  exporter that failed to start or was stopped by hand stayed down.
- `remove-exporter` takes the exporter's MQTT password with it. It was left on
  the machine, readable by root, after the application was removed.
- The `cos-agent` endpoint declares `limit: 1`, as the library it implements
  asks for.
- The exporter reports a disabled plaintext listener through the unit status
  rather than logging the same warning on every update-status for ever.
- `allow-anonymous` is documented as what it actually is: anonymous clients are
  granted no topics, so they can connect and then neither publish nor subscribe.
  The option's description, the unit status and the documentation all promised a
  working, dangerous mode that did not exist, and `render_acl_file` carried an
  unused parameter for granting anonymous access that nothing could reach.
- Notes on an otherwise-active unit are aggregated into one status message. ops
  keeps the first of several equal-priority statuses, so the anonymous-access
  warning could be hidden behind a disabled bridge.
- `set-password` rejects a password containing a line break. The password file
  is one user per line, so such a password broke authentication for every user.
- `remove-user` refuses a user that came from an `mqtt` integration instead of
  removing it and letting the next reconciliation recreate it.
- `create-backup` refuses to overwrite an existing file. It writes as root, so
  an operator who can run actions but not `juju ssh` could truncate any file on
  the machine by naming it.
- `restore-backup` puts the password and ACL files back as 0o600, which is how
  they are written. The ACL file was being widened to 0o640.
- Changing `install-source` between the archive or PPA and the snap now removes
  the package it moved away from. The old broker was stopped and disabled but
  left installed — a second Mosquitto on the machine, held at a revision nothing
  updates in the snap's case, waiting to bind 1883.
- Documents that broker logs are not forwarded to Loki with `install-source:
  snap`: the log lives under `/var/snap`, outside the trees the COS machine
  collectors scrape, and strict confinement means the broker cannot write to
  `/var/log`.
- A reload the broker accepts and then exits on is noticed inside the hook that
  caused it. `systemctl reload` is asynchronous and reports success either way,
  and Mosquitto 2.0 has no `--test-config` to have rejected the configuration
  first, so the unit went on reporting active for a broker that had stopped.
- `last-log` reads the broker's log file as well as the journal. The broker is
  configured with `log_dest file`, so anything that went wrong after it opened
  that file was not in what the charm put in front of the operator.
- The `grafana_agent.cos_agent` library is pinned to the exact revision
  committed in `lib/`, so packing cannot pick up a different one than the tests
  ran against.
- `links.documentation` points at the documentation rather than the README.
- Changing `bridge-topics` now republishes the request to the upstream broker,
  so the new topics are actually granted. The bridge previously forwarded
  topics the upstream broker had never granted it, and carried no traffic on
  them while appearing healthy.

### Security

- The `restore-backup` action validates every path in the tarball after
  normalisation, and rejects symbolic and hard links. An earlier revision
  compared the un-normalised path, so a member named
  `etc/mosquitto/../../tmp/x` escaped the broker's directories and was written
  as root.
- MQTT passwords never reach a command line. The password file is written as a
  private temporary file and hashed in place with `mosquitto_passwd -U`, and
  the client tools are given their password through
  `$XDG_CONFIG_HOME/mosquitto_<tool>` rather than `-P`.
- The `upstream` integration validates the host and the credentials it receives
  before writing them into a bridge configuration. The topic filter was already
  checked; the other three fields a remote charm chooses were not, so a
  compromised or buggy upstream broker could have appended directives of its own
  — another listener, an ACL grant, or `allow_anonymous true` — to a fragment
  this broker includes.
- `extra-config` rejects the twelve directives that would let an operator
  disable the charm's own security invariants. Removing the charm's listener
  would otherwise silently re-enable anonymous access, because Mosquitto 2.x
  only defaults `allow_anonymous` to false once a listener exists.

[Unreleased]: https://github.com/tonyandrewmeyer/mosquitto-operator/commits/main
