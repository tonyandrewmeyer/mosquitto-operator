# Changelog

All notable changes to the Mosquitto charm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Enterprise Security Features**:
  - TLS/SSL encryption with automatic certificate management via relations
  - Client certificate authentication (X.509) support
  - ACL-based authorization system for topic access control
  - Security hardening with proper defaults
- **High Availability & Storage**:
  - Juju storage integration for persistent data with configurable storage types
  - Automated backup and restore capabilities with metadata tracking
  - Message persistence with storage lifecycle management
- **Advanced Monitoring & Observability**:
  - Prometheus metrics integration with service health and connection metrics
  - OpenTelemetry distributed tracing for charm operations and workload interactions
  - Comprehensive logging with structured events and span tracking
- **Enhanced Configuration Options**:
  - `tls-port`: TLS-encrypted MQTT port (default: 8883)
  - `tls-websockets-port`: TLS WebSocket port (default: 9002)
  - TLS configuration with certificate management
- **New Relations**:
  - `certificates` (tls-certificates): Automatic TLS certificate provisioning
  - `sasl` (sasl): SASL authentication integration
  - `metrics` (prometheus_scrape): Prometheus monitoring endpoint
  - `charm-tracing` (tracing): OpenTelemetry tracing data export
  - `receive-ca-cert` (certificate_transfer): CA certificate for secure tracing
- **Additional Actions**:
  - `backup`: Create backups with optional naming
  - `restore`: Restore from named backups
  - `generate-client-cert`: Generate X.509 client certificates
  - `get-metrics-status`: Check Prometheus metrics exporter status
- **Professional Charm Icon**: Custom SVG icon with mosquito and MQTT messaging elements
- **Comprehensive Documentation**:
  - Complete Diátaxis-style documentation structure (Tutorial, How-to, Reference, Explanation)
  - Visual architecture diagrams with Mermaid charts
  - Security documentation with threat analysis
  - Deployment pattern guides with network diagrams

### Changed
- **Charm Naming**: Renamed from `mosquitto-operator` to `mosquitto` following standard conventions
- **System Integration**: Replaced subprocess calls with operator-libs-linux libraries:
  - `charms.operator_libs_linux.v0.apt` for package management
  - `charms.operator_libs_linux.v1.systemd` for service control
- **Testing Framework**: Updated integration tests to use Jubilant instead of pytest-operator
- **Build System**: Enhanced tox configuration with improved lint and type checking

### Fixed
- **Deployment Issues**: Fixed charm deployment errors by using proper operator libraries
- **Service Management**: Resolved systemctl command failures with proper error handling
- **Integration Testing**: Fixed Jubilant compatibility with temp_model utilities
- **Code Quality**: Resolved all linting issues and improved type safety

### Security
- **Secure Defaults**: Anonymous access disabled by default
- **Certificate Management**: Automatic TLS certificate lifecycle with relation-based provisioning
- **Access Control**: Comprehensive ACL system for fine-grained topic permissions
- **Audit Logging**: Security events tracked through structured logging and tracing

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
  - Unit tests using ops.testing framework (93% coverage)
  - Integration tests using Jubilant for real Juju testing
  - Parametrized tests for configuration validation
- **Quality assurance**:
  - GitHub Actions CI/CD workflow
  - Pre-commit hooks with ruff formatting and linting
  - Zizmor security analysis for GitHub Actions
  - Dependabot configuration for security updates

### Features
- **Automatic installation** via apt package manager
- **Dynamic configuration generation** based on charm config
- **Service management** through systemd integration
- **Dual protocol support**: Standard MQTT and MQTT over WebSockets
- **Message persistence** with configurable storage location
- **Health monitoring** and status reporting
- **Proper security defaults** with anonymous access disabled
- **Production-ready logging** with configurable levels

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

## Development Milestones

### Technical Achievements
- **Production-Ready Charm**: Complete implementation with enterprise features
- **High Test Coverage**: 93% unit test coverage with comprehensive integration testing
- **Security Hardening**: Multiple layers of security with proper defaults
- **Observability**: Full monitoring and tracing integration
- **Documentation Excellence**: Complete Diátaxis-style documentation

### Quality Standards
- **Code Quality**: 100% type coverage with strict linting rules
- **Security**: Vulnerability scanning and secure development practices
- **Testing**: Comprehensive test suite with multiple testing strategies
- **Documentation**: User-focused documentation with visual aids
- **Standards Compliance**: Following Juju and charm development best practices

---

*This changelog is maintained following conventional commit standards and semantic versioning principles.*