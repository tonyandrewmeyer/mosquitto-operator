# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial implementation of Mosquitto MQTT broker charm
- Support for configurable MQTT port (default: 1883)
- WebSocket support with configurable port (default: 9001)
- Anonymous access control configuration
- Message persistence configuration
- Configurable connection limits and message size limits
- Logging level configuration
- `restart` action to restart Mosquitto service
- `get-status` action to retrieve service status and version information
- Comprehensive unit tests using ops.testing
- Integration tests using Jubilant
- GitHub Actions CI/CD workflow
- Pre-commit hooks configuration
- Security policy documentation
- Tutorial documentation for deployment and usage
- Dependabot configuration for security updates

### Features
- Automatic Mosquitto installation via apt package manager
- Dynamic configuration file generation
- Service management through systemd
- Support for both standard MQTT and MQTT over WebSockets
- Health checks and status monitoring
- Proper file permissions and ownership setup

### Configuration Options
- `port`: MQTT broker port (default: 1883)
- `websockets-port`: WebSocket port (default: 9001, set to 0 to disable)
- `max-connections`: Maximum concurrent connections (default: -1 for unlimited)
- `allow-anonymous`: Allow anonymous client connections (default: false)
- `log-level`: Logging verbosity (default: "notice")
- `persistence`: Enable message persistence (default: true)
- `message-size-limit`: Maximum message size in bytes (default: 268435456)

### Actions
- `restart`: Restart the Mosquitto service
- `get-status`: Get detailed service status information