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

### Added

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

[Unreleased]: https://github.com/tonyandrewmeyer/mosquitto-operator/commits/main
