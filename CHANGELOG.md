# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial Mosquitto charm implementation
- MQTT broker configuration management
- User authentication and management actions
- WebSocket support for web-based MQTT clients
- TLS certificate integration via relations
- Persistent storage support for message persistence
- Backup and restore functionality
- Monitoring integration (Prometheus scrape)
- Logging integration (Loki push API)
- Comprehensive configuration options
- GitHub Actions CI/CD workflows
- Pre-commit hooks for code quality
- Security workflow with Zizmor
- Development tooling (tox, ruff, mypy)
- Comprehensive documentation (README, TUTORIAL, CONTRIBUTING)
- Security policy and code of conduct

### Security
- Anonymous access disabled by default
- Password file permissions set to 600
- Input validation for all configuration options
- Secure defaults for production deployment

## [0.1.0] - TBD

Initial release of the Mosquitto charm.

### Added
- Core charm functionality for Eclipse Mosquitto MQTT broker
- Machine charm deployment model
- APT-based installation and systemd service management
- Configuration management for MQTT and WebSocket ports
- User management with password authentication
- Persistence configuration and storage support
- Action-based management (get-stats, add-user, remove-user, etc.)
- Relation interfaces for certificates, logging, and monitoring
- Comprehensive test suite (unit and integration tests)
- Documentation and tutorials
- Development and contribution guidelines