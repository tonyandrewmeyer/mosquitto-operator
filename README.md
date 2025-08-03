# Mosquitto MQTT Broker Charm

[![Charmhub](https://img.shields.io/badge/charmhub-mosquitto--operator-blue.svg)](https://charmhub.io/mosquitto-operator)
[![License](https://img.shields.io/github/license/canonical/mosquitto-operator)](https://github.com/canonical/mosquitto-operator/blob/main/LICENSE)
[![Tests](https://img.shields.io/badge/tests-19%20passed-green.svg)](./tests/)
[![Coverage](https://img.shields.io/badge/coverage-93%25-brightgreen.svg)](./tests/)

A [Juju](https://juju.is) charm for deploying and managing [Eclipse Mosquitto](https://mosquitto.org/), the open-source MQTT message broker.

Eclipse Mosquitto is a lightweight MQTT broker that implements the MQTT protocol versions 5.0, 3.1.1, and 3.1. This charm provides automated deployment, configuration, and lifecycle management for Mosquitto in production environments.

## Features

- **Complete MQTT Support**: Full MQTT 5.0, 3.1.1, and 3.1 protocol implementation
- **WebSocket Support**: MQTT over WebSockets for web applications
- **Configurable Security**: Anonymous access control, authentication ready
- **Message Persistence**: Reliable message storage and delivery
- **Production Ready**: Systemd integration, logging, and monitoring
- **Actions**: Service restart and status checking
- **High Observability**: Comprehensive logging and status reporting

## Quick Start

### Prerequisites

- [Juju](https://juju.is/docs/juju) 3.0+ installed and bootstrapped
- A Juju model ready for deployment

### Deploy

Deploy the Mosquitto charm with default settings:

```bash
juju deploy mosquitto-operator
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
juju ssh mosquitto-operator/0 'mosquitto_sub -h localhost -p 1883 -t test/topic'

# Publish a message (run in another terminal)
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 1883 -t test/topic -m "Hello MQTT!"'
```

## Configuration

The charm provides several configuration options to customize Mosquitto behavior:

### MQTT Settings

```bash
# Change MQTT port (default: 1883)
juju config mosquitto-operator port=1884

# Configure WebSocket port (default: 9001, set to 0 to disable)
juju config mosquitto-operator websockets-port=9001

# Set maximum concurrent connections (default: unlimited)
juju config mosquitto-operator max-connections=1000
```

### Security Settings

```bash
# Allow anonymous connections (default: false, not recommended for production)
juju config mosquitto-operator allow-anonymous=true

# Set logging level (default: notice)
juju config mosquitto-operator log-level=debug
```

### Performance Settings

```bash
# Enable/disable message persistence (default: true)
juju config mosquitto-operator persistence=true

# Set maximum message size in bytes (default: 256MB)
juju config mosquitto-operator message-size-limit=134217728
```

### Configuration Options Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `port` | int | 1883 | MQTT broker port |
| `websockets-port` | int | 9001 | WebSocket port (0 to disable) |
| `max-connections` | int | -1 | Max concurrent connections (-1 = unlimited) |
| `allow-anonymous` | boolean | false | Allow anonymous client connections |
| `log-level` | string | "notice" | Logging level (error/warning/notice/information/debug) |
| `persistence` | boolean | true | Enable message persistence |
| `message-size-limit` | int | 268435456 | Maximum message size in bytes |

## Actions

The charm provides actions for operational tasks:

### Restart Service

```bash
juju run mosquitto-operator/0 restart
```

### Get Status Information

```bash
juju run mosquitto-operator/0 get-status
```

This returns detailed information including:
- Service status
- Version information  
- Process details
- Active since timestamp

## Use Cases

### IoT Applications

Mosquitto is ideal for Internet of Things (IoT) deployments:

```bash
# Deploy for IoT with optimized settings
juju deploy mosquitto-operator
juju config mosquitto-operator max-connections=10000
juju config mosquitto-operator message-size-limit=1048576  # 1MB limit
```

### Web Applications

For web applications using MQTT over WebSockets:

```bash
# Ensure WebSocket support is enabled
juju config mosquitto-operator websockets-port=9001
```

Access MQTT from web applications using the WebSocket endpoint on port 9001.

### Development Environment

For development with relaxed security:

```bash
# Development setup (NOT for production)
juju config mosquitto-operator allow-anonymous=true
juju config mosquitto-operator log-level=debug
```

## Monitoring and Observability

### Logs

View Mosquitto logs:

```bash
# View service logs
juju ssh mosquitto-operator/0 'journalctl -u mosquitto -f'

# View application logs
juju ssh mosquitto-operator/0 'tail -f /var/log/mosquitto/mosquitto.log'
```

### Status Monitoring

Monitor charm and service status:

```bash
# Check charm status
juju status mosquitto-operator

# Get detailed status
juju run mosquitto-operator/0 get-status

# Check service health
juju ssh mosquitto-operator/0 'systemctl status mosquitto'
```

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
sudo apt install tox

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
2. Install development dependencies: `sudo apt install tox python3-dev`
3. Run tests: `tox`
4. Submit pull requests with tests and documentation

### Testing Guidelines

- Unit tests are required for all new functionality
- Integration tests should cover end-to-end scenarios
- All tests must pass before merging
- Maintain or improve code coverage

## Security

Please see [SECURITY.md](SECURITY.md) for information about reporting security vulnerabilities.

### Security Considerations

- **Anonymous Access**: Disabled by default for security
- **Network Security**: Use Juju network spaces to control access
- **Authentication**: Plan to add TLS and authentication support
- **Logging**: Sensitive information is not logged

## Architecture

This is a **machine charm** that:

- Installs Mosquitto via APT packages
- Manages configuration files in `/etc/mosquitto/`
- Uses systemd for service lifecycle management
- Stores persistent data in `/var/lib/mosquitto/`
- Logs to `/var/log/mosquitto/`

## Resources

- **Charm Documentation**: [Tutorial](TUTORIAL.md) | [Contributing](CONTRIBUTING.md)
- **Mosquitto Documentation**: [mosquitto.org](https://mosquitto.org/documentation/)
- **MQTT Protocol**: [MQTT 5.0 Specification](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)
- **Juju Documentation**: [juju.is/docs](https://juju.is/docs/)
- **Charmhub**: [charmhub.io/mosquitto-operator](https://charmhub.io/mosquitto-operator)

## License

This charm is distributed under the Apache 2.0 license. See [LICENSE](LICENSE) for details.

Mosquitto is distributed under the [Eclipse Public License](https://mosquitto.org/license/).