# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Ensure local charm path starts with ./ for juju deploy command
- Update integration tests to use jubilant temp_model for proper isolation
- Fix deploy method parameter from application_name to app for Jubilant compatibility
- Update tox configuration to include type checking in lint environment
- Replace pyright with ty check for type checking
- Fix unit test issues with ops.testing framework
- Resolve linting issues with unused variables and line length

### Changed
- Move type checking from static to lint environment in tox configuration
- Update integration tests to use Jubilant instead of pytest-operator
- Integration tests now use temp_model utility for automatic model lifecycle
- Improved test isolation with helper methods

## [1.0.0] - 2025-08-03

### Added
- **Complete Mosquitto MQTT broker charm implementation**
- **Machine charm approach** for Ubuntu 22.04 deployment
- **Comprehensive configuration options**:
  - `port`: MQTT broker port (default: 1883)
  - `websockets-port`: WebSocket port (default: 9001, set to 0 to disable)
  - `max-connections`: Maximum concurrent connections (default: -1 for unlimited)
  - `allow-anonymous`: Allow anonymous client connections (default: false)
  - `log-level`: Logging verbosity (default: "notice")
  - `persistence`: Enable message persistence (default: true)
  - `message-size-limit`: Maximum message size in bytes (default: 268435456)
- **Actions for service management**:
  - `restart`: Restart the Mosquitto service
  - `get-status`: Get detailed service status and version information
- **Comprehensive test suite**:
  - Unit tests using ops.testing framework (19 tests, 93% coverage)
  - Integration tests using Jubilant for real Juju testing
  - Parametrized tests for configuration validation
- **Quality assurance**:
  - GitHub Actions CI/CD workflow
  - Pre-commit hooks with ruff formatting and linting
  - Zizmor security analysis for GitHub Actions
  - Dependabot configuration for security updates
- **Documentation**:
  - Comprehensive README with usage examples
  - Security policy for vulnerability reporting
  - Tutorial for deployment and configuration
  - Contributing guidelines

### Features
- **Automatic installation** via apt package manager
- **Dynamic configuration generation** based on charm config
- **Service management** through systemd integration
- **Dual protocol support**: Standard MQTT and MQTT over WebSockets
- **Message persistence** with configurable storage location
- **Health monitoring** and status reporting
- **Proper security defaults** with anonymous access disabled
- **Production-ready logging** with configurable levels
- **File permission management** for mosquitto user

### Architecture
- **Machine charm design** for direct system integration
- **APT package installation** for reliable dependency management
- **Systemd service management** for lifecycle control
- **Configuration files** in `/etc/mosquitto/`
- **Persistent data storage** in `/var/lib/mosquitto/`
- **Application logging** to `/var/log/mosquitto/`

### Development Infrastructure
- **Modern Python practices**: Type hints, dataclasses, absolute imports
- **Quality toolchain**: ruff for formatting/linting, ty for type checking
- **Testing best practices**: ops.testing for unit tests, Jubilant for integration
- **CI/CD pipeline**: Automated testing, linting, and security checks
- **Conventional commits**: Structured commit messages for changelog generation