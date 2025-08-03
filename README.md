# Mosquitto MQTT Broker Charm

A Juju charm for deploying and managing Eclipse Mosquitto, an open-source MQTT broker for IoT messaging.

## Overview

Eclipse Mosquitto is a lightweight, open-source MQTT broker that implements the MQTT protocol versions 5.0, 3.1.1 and 3.1. It provides efficient publish/subscribe messaging suitable for Internet of Things applications, from single board computers to full servers.

This charm provides:
- Automated installation and configuration of Mosquitto
- User management with password authentication
- TLS/SSL support (via certificate relations)
- Persistence configuration
- WebSocket support for web-based MQTT clients
- Monitoring and metrics integration
- Backup and restore capabilities

## Features

### Configuration Options

- **port**: MQTT broker port (default: 1883)
- **websockets-port**: WebSocket port for MQTT over WS (default: 9001)
- **log-level**: Logging verbosity (debug, info, warning, error)
- **persistence**: Enable message persistence (default: true)
- **max-connections**: Maximum concurrent connections
- **allow-anonymous**: Allow anonymous connections (default: false)
- **keepalive**: Keepalive interval in seconds
- **message-size-limit**: Maximum message size in bytes

### Actions

- **get-stats**: Retrieve broker statistics and connection info
- **reload-config**: Reload configuration without service restart
- **add-user**: Add MQTT user with password
- **remove-user**: Remove MQTT user
- **list-users**: List configured users
- **backup-data**: Backup persistence data and configuration
- **restore-data**: Restore from backup

### Relations

- **mqtt**: Provides MQTT broker endpoint for client applications
- **certificates**: TLS certificates for secure connections (optional)
- **logging**: Centralized logging integration (optional)
- **prometheus-scrape**: Metrics collection (optional)

## Quick Start

### Deploy the charm

```bash
juju deploy ./mosquitto.charm
```

### Configure the broker

```bash
# Set custom port
juju config mosquitto port=1884

# Disable anonymous access (recommended)
juju config mosquitto allow-anonymous=false

# Set log level for debugging
juju config mosquitto log-level=debug
```

### Manage users

```bash
# Add a new MQTT user
juju run mosquitto/0 add-user username=myuser password=mypassword

# List all users
juju run mosquitto/0 list-users

# Remove a user
juju run mosquitto/0 remove-user username=myuser
```

### Monitor the broker

```bash
# Get broker statistics
juju run mosquitto/0 get-stats

# Check service status
juju status mosquitto
```

### Connect with TLS certificates

```bash
# Deploy a certificate provider
juju deploy self-signed-certificates

# Add relation for TLS support
juju relate mosquitto:certificates self-signed-certificates:certificates
```

## Configuration Examples

### Basic IoT Setup
```bash
juju deploy ./mosquitto.charm
juju config mosquitto allow-anonymous=false
juju config mosquitto max-connections=1000
juju run mosquitto/0 add-user username=iot-device password=secure-password
```

### High-Traffic Setup
```bash
juju deploy ./mosquitto.charm
juju config mosquitto port=1883
juju config mosquitto websockets-port=9001
juju config mosquitto max-connections=10000
juju config mosquitto message-size-limit=1048576  # 1MB
juju config mosquitto log-level=warning
```

### Development Setup
```bash
juju deploy ./mosquitto.charm
juju config mosquitto allow-anonymous=true
juju config mosquitto log-level=debug
```

## Storage

The charm supports persistent storage for message persistence:

```bash
# Deploy with storage
juju deploy ./mosquitto.charm --storage data=20G

# Or add storage later
juju add-storage mosquitto/0 data=20G
```

## Backup and Restore

### Create a backup
```bash
juju run mosquitto/0 backup-data
```

### Restore from backup
```bash
juju run mosquitto/0 restore-data backup-path=/path/to/backup.tar.gz
```

## Integration Examples

### With Prometheus monitoring
```bash
juju deploy prometheus2
juju relate mosquitto:prometheus-scrape prometheus2:scrape
```

### With centralized logging
```bash
juju deploy loki
juju relate mosquitto:logging loki:logging
```

## Testing MQTT Connectivity

### Using mosquitto_pub/sub clients

```bash
# Subscribe to a topic
mosquitto_sub -h <broker-ip> -p 1883 -t "test/topic" -u <username> -P <password>

# Publish a message
mosquitto_pub -h <broker-ip> -p 1883 -t "test/topic" -m "Hello MQTT" -u <username> -P <password>
```

### Using WebSocket connection

```bash
# WebSocket connection (typically for web applications)
# Connect to ws://<broker-ip>:9001/mqtt
```

## Security Considerations

- **Disable anonymous access** in production environments
- **Use TLS certificates** for secure communication
- **Implement proper user management** with strong passwords
- **Configure firewall rules** to restrict access
- **Regular backup** of configuration and persistence data

## Troubleshooting

### Check service status
```bash
juju status mosquitto
juju run mosquitto/0 get-stats
```

### View logs
```bash
juju debug-log --include=mosquitto
```

### Test connectivity
```bash
# Test basic connectivity
mosquitto_pub -h <broker-ip> -p 1883 -t "test" -m "test message"
```

### Common issues
- **Connection refused**: Check if the service is running and firewall allows the port
- **Authentication failed**: Verify user credentials with `list-users` action
- **Permission denied**: Check file permissions in `/var/lib/mosquitto` and `/var/log/mosquitto`

## Development

### Building the charm

```bash
charmcraft pack
```

### Running tests

```bash
tox -e unit
tox -e integration
```

### Code formatting and linting

```bash
tox -e format
tox -e lint
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This charm is distributed under the Apache License 2.0. See [LICENSE](LICENSE) for more information.

## Links

- [Eclipse Mosquitto](https://mosquitto.org/)
- [MQTT Protocol](https://mqtt.org/)
- [Juju Documentation](https://juju.is/docs)
- [Charm Development Guide](https://juju.is/docs/sdk)