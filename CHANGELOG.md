# Changelog

All notable changes to this charm are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for its
commit messages.

Charm revisions are published to [Charmhub](https://charmhub.io/mosquitto).
Each release below notes the Charmhub revision it corresponds to, where one was
published. Unlike a library, this charm has no independent version number: the
revision is the version.

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
- `extra-config` rejects the twelve directives that would let an operator
  disable the charm's own security invariants. Removing the charm's listener
  would otherwise silently re-enable anonymous access, because Mosquitto 2.x
  only defaults `allow_anonymous` to false once a listener exists.

[Unreleased]: https://github.com/tonyandrewmeyer/mosquitto-operator/commits/main
