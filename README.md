# Mosquitto MQTT Broker Charm

[![Charmhub](https://img.shields.io/badge/charmhub-mosquitto-blue.svg)](https://charmhub.io/mosquitto)
[![License](https://img.shields.io/github/license/canonical/mosquitto-operator)](https://github.com/canonical/mosquitto-operator/blob/main/LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-green.svg)](./tests/)
[![Coverage](https://img.shields.io/badge/coverage-93%25-brightgreen.svg)](./tests/)

A [Juju](https://juju.is) charm for deploying and managing [Eclipse Mosquitto](https://mosquitto.org/), the open-source MQTT message broker.

Eclipse Mosquitto is a lightweight MQTT broker that implements the MQTT protocol versions 5.0, 3.1.1, and 3.1. This charm provides automated deployment, configuration, and lifecycle management for Mosquitto in production environments with enterprise features.

## Features

- **Complete MQTT Support**: Full MQTT 5.0, 3.1.1, and 3.1 protocol implementation
- **WebSocket Support**: MQTT over WebSockets for web applications (plain and TLS)
- **Enterprise Security**: TLS/SSL encryption, client certificate authentication, ACL authorization
- **High Availability**: Message persistence with Juju storage integration
- **Backup & Recovery**: Automated backup and restore capabilities
- **Observability**: Prometheus metrics, OpenTelemetry tracing, comprehensive logging
- **Production Ready**: Systemd integration, security hardening, monitoring

## Quick Start

### Prerequisites

- [Juju](https://juju.is/docs/juju) 3.0+ installed and bootstrapped
- A Juju model ready for deployment

### Deploy

Deploy the Mosquitto charm with default settings:

```bash
juju deploy mosquitto
```

Wait for the deployment to complete:

```bash
juju status --watch 1s
```

The charm will be ready when it shows `active` status.

### Test MQTT Connection

Once deployed, test the MQTT broker:

```bash
# Subscribe to a topic (run in one terminal)
juju ssh mosquitto/0 'mosquitto_sub -h localhost -p 1883 -t test/topic'

# Publish a message (run in another terminal)
juju ssh mosquitto/0 'mosquitto_pub -h localhost -p 1883 -t test/topic -m "Hello MQTT!"'
```

## Configuration

The charm provides comprehensive configuration options:

### Basic MQTT Settings

```bash
# Change MQTT port (default: 1883)
juju config mosquitto port=1884

# Configure WebSocket port (default: 9001, set to 0 to disable)
juju config mosquitto websockets-port=9001

# Set maximum concurrent connections (default: unlimited)
juju config mosquitto max-connections=1000
```

### TLS/SSL Configuration

```bash
# Configure TLS ports
juju config mosquitto tls-port=8883
juju config mosquitto tls-websockets-port=9002
```

### Security Settings

```bash
# Allow anonymous connections (default: false)
juju config mosquitto allow-anonymous=false

# Set logging level (default: notice)
juju config mosquitto log-level=debug
```

### Performance Settings

```bash
# Enable/disable message persistence (default: true)
juju config mosquitto persistence=true

# Set maximum message size in bytes (default: 256MB)
juju config mosquitto message-size-limit=134217728
```

### Configuration Options Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `port` | int | 1883 | Standard MQTT broker port |
| `websockets-port` | int | 9001 | WebSocket port (0 to disable) |
| `tls-port` | int | 8883 | TLS-encrypted MQTT port (0 to disable) |
| `tls-websockets-port` | int | 9002 | TLS WebSocket port (0 to disable) |
| `max-connections` | int | -1 | Max concurrent connections (-1 = unlimited) |
| `allow-anonymous` | boolean | false | Allow anonymous client connections |
| `log-level` | string | "notice" | Logging level (error/warning/notice/information/debug) |
| `persistence` | boolean | true | Enable message persistence |
| `message-size-limit` | int | 268435456 | Maximum message size in bytes |

## Relations

### TLS Certificates

Connect to a certificate authority for automatic TLS certificate management:

```bash
juju deploy self-signed-certificates
juju integrate mosquitto:certificates self-signed-certificates:certificates
```

### SASL Authentication

Integrate with SASL for advanced authentication:

```bash
juju deploy sasl
juju integrate mosquitto:sasl sasl:sasl
```

### Prometheus Monitoring

Connect to Prometheus for metrics collection:

```bash
juju deploy prometheus
juju integrate mosquitto:metrics prometheus:prometheus-scrape
```

### OpenTelemetry Tracing

Enable distributed tracing:

```bash
juju deploy jaeger
juju integrate mosquitto:charm-tracing jaeger:tracing
```

## Actions

The charm provides comprehensive operational actions:

### Service Management

```bash
# Restart the Mosquitto service
juju run mosquitto/0 restart

# Get detailed status information
juju run mosquitto/0 get-status
```

### Backup and Recovery

```bash
# Create a backup
juju run mosquitto/0 backup

# Create a named backup
juju run mosquitto/0 backup backup-name=before-upgrade

# Restore from backup
juju run mosquitto/0 restore backup-name=before-upgrade
```

### Certificate Management

```bash
# Generate client certificates (when TLS is configured)
juju run mosquitto/0 generate-client-cert client-name=myapp output-path=/tmp

# Get metrics status
juju run mosquitto/0 get-metrics-status
```

## Storage

The charm supports Juju storage for persistent data:

```bash
# Deploy with custom storage
juju deploy mosquitto --storage persistence=ebs,10G

# Add storage to existing deployment
juju add-storage mosquitto/0 persistence=10G
```

## Use Cases

### IoT Applications

Deploy Mosquitto for IoT with optimized settings:

```bash
juju deploy mosquitto
juju config mosquitto max-connections=10000
juju config mosquitto message-size-limit=1048576  # 1MB limit for IoT devices
```

### Enterprise Deployment

Secure enterprise deployment with TLS and monitoring:

```bash
juju deploy mosquitto
juju deploy self-signed-certificates
juju deploy prometheus

juju integrate mosquitto:certificates self-signed-certificates:certificates
juju integrate mosquitto:metrics prometheus:prometheus-scrape

juju config mosquitto allow-anonymous=false
juju config mosquitto tls-port=8883
```

### Development Environment

Development setup with debugging enabled:

```bash
juju deploy mosquitto
juju config mosquitto allow-anonymous=true
juju config mosquitto log-level=debug
```

## Monitoring and Observability

### Logs

View Mosquitto logs:

```bash
# View service logs
juju ssh mosquitto/0 'journalctl -u mosquitto -f'

# View application logs
juju ssh mosquitto/0 'tail -f /var/log/mosquitto/mosquitto.log'
```

### Metrics

When connected to Prometheus, the charm provides:

- Service health metrics
- Connection count metrics
- Custom MQTT broker metrics

### Tracing

OpenTelemetry tracing provides visibility into:

- Service startup and configuration changes
- Backup and restore operations
- Certificate generation
- Relation lifecycle events

## Security

### Security Features

- **TLS/SSL Encryption**: Automatic certificate management via relations
- **Client Authentication**: X.509 client certificate support
- **Access Control**: ACL-based authorization system
- **Network Isolation**: Juju network spaces support
- **Audit Logging**: Comprehensive security event logging

### Security Best Practices

- Always disable anonymous access in production
- Use TLS encryption for all connections
- Implement proper ACL rules for topic access
- Monitor connection logs for suspicious activity
- Regularly rotate certificates

For security vulnerability reporting, see [SECURITY.md](SECURITY.md).

## Development

### Building the Charm

```bash
# Install charmcraft
sudo snap install charmcraft --classic

# Pack the charm
charmcraft pack
```

### Testing

The charm includes comprehensive tests:

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install tox

# Run all tests
tox

# Run specific test suites
tox -e lint      # Linting and type checking
tox -e unit      # Unit tests (93% coverage)
tox -e integration  # Integration tests
```

### Code Quality

```bash
# Format code
tox -e format

# Check code quality
tox -e lint
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

1. Clone the repository
2. Install development dependencies: `pip install tox`
3. Run tests: `tox`
4. Submit pull requests with tests and documentation

## Documentation

- **Tutorial**: [Getting Started Guide](docs/tutorial.md)
- **How-to Guides**: [Feature-specific guides](docs/how-to/)
- **Reference**: [API and configuration reference](docs/reference/)
- **Explanation**: [Architecture and design](docs/explanation/)

## Resources

- **Mosquitto Documentation**: [mosquitto.org](https://mosquitto.org/documentation/)
- **MQTT Protocol**: [MQTT 5.0 Specification](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)
- **Juju Documentation**: [juju.is/docs](https://juju.is/docs/)
- **Charmhub**: [charmhub.io/mosquitto](https://charmhub.io/mosquitto)

## License

This charm is distributed under the Apache 2.0 license. See [LICENSE](LICENSE) for details.

Mosquitto is distributed under the [Eclipse Public License](https://mosquitto.org/license/).