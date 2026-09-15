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
  from `uv.lock`, GitHub Actions CI (lint, unit, pack, and integration against
  Juju 3.6 and 4.0), a zizmor workflow, Dependabot, pre-commit hooks, issue and
  pull request templates, and the security, contributing, code-of-conduct and
  changelog files.

### Changed

### Deprecated

### Removed

### Fixed

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
