# Configuration Reference

This reference documents all configuration options available for the Mosquitto charm.

## Configuration Options

### Network Settings

#### `port`
- **Type**: `int`
- **Default**: `1883`
- **Description**: The network port that the MQTT broker will listen on for standard MQTT connections.
- **Valid Range**: 1-65535
- **Example**: 
  ```bash
  juju config mosquitto-operator port=1884
  ```

#### `websockets-port`
- **Type**: `int` 
- **Default**: `9001`
- **Description**: The network port for MQTT over WebSockets. Set to 0 to disable WebSocket support.
- **Valid Range**: 0, 1-65535 (0 disables)
- **Example**:
  ```bash
  # Enable WebSockets on port 8080
  juju config mosquitto-operator websockets-port=8080
  
  # Disable WebSockets
  juju config mosquitto-operator websockets-port=0
  ```

### Connection Settings

#### `max-connections`
- **Type**: `int`
- **Default**: `-1`
- **Description**: The maximum number of concurrent client connections. Set to -1 for unlimited connections.
- **Valid Range**: -1, 1-2147483647 (-1 = unlimited)
- **Example**:
  ```bash
  # Limit to 1000 concurrent connections
  juju config mosquitto-operator max-connections=1000
  
  # Allow unlimited connections
  juju config mosquitto-operator max-connections=-1
  ```

#### `message-size-limit`
- **Type**: `int`
- **Default**: `268435456` (256 MB)
- **Description**: Maximum message size in bytes. Set to 0 for unlimited message size.
- **Valid Range**: 0, 1-2147483647 (0 = unlimited)
- **Example**:
  ```bash
  # Limit messages to 1MB
  juju config mosquitto-operator message-size-limit=1048576
  
  # Allow unlimited message size
  juju config mosquitto-operator message-size-limit=0
  ```

### Security Settings

#### `allow-anonymous`
- **Type**: `boolean`
- **Default**: `false`
- **Description**: Whether to allow clients to connect without providing credentials.
- **Valid Values**: `true`, `false`
- **Security Note**: Setting to `true` allows unauthenticated access. Only recommended for development or secured internal networks.
- **Example**:
  ```bash
  # Allow anonymous connections (development only)
  juju config mosquitto-operator allow-anonymous=true
  
  # Require authentication (production)
  juju config mosquitto-operator allow-anonymous=false
  ```

### Logging Settings

#### `log-level`
- **Type**: `string`
- **Default**: `"notice"`
- **Description**: The logging level for Mosquitto.
- **Valid Values**: 
  - `"error"`: Only error messages
  - `"warning"`: Error and warning messages  
  - `"notice"`: Error, warning, and notice messages (default)
  - `"information"`: Error, warning, notice, and info messages
  - `"debug"`: All messages including debug output
- **Example**:
  ```bash
  # Enable debug logging
  juju config mosquitto-operator log-level=debug
  
  # Production logging
  juju config mosquitto-operator log-level=notice
  
  # Minimal logging
  juju config mosquitto-operator log-level=error
  ```

### Storage Settings

#### `persistence`
- **Type**: `boolean`
- **Default**: `true`
- **Description**: Whether to enable message persistence to disk.
- **Valid Values**: `true`, `false`
- **Details**: When enabled, messages are stored in `/var/lib/mosquitto/` and survive broker restarts.
- **Example**:
  ```bash
  # Enable persistence (recommended)
  juju config mosquitto-operator persistence=true
  
  # Disable persistence (testing only)
  juju config mosquitto-operator persistence=false
  ```

## Configuration Examples

### Production Setup

Recommended configuration for production deployments:

```bash
juju config mosquitto-operator \
  port=1883 \
  websockets-port=9001 \
  max-connections=10000 \
  allow-anonymous=false \
  log-level=notice \
  persistence=true \
  message-size-limit=1048576
```

### Development Setup

Configuration for development and testing:

```bash
juju config mosquitto-operator \
  port=1883 \
  websockets-port=9001 \
  max-connections=100 \
  allow-anonymous=true \
  log-level=debug \
  persistence=true \
  message-size-limit=1048576
```

### High-Performance Setup

Configuration for high-throughput scenarios:

```bash
juju config mosquitto-operator \
  port=1883 \
  websockets-port=0 \
  max-connections=50000 \
  allow-anonymous=false \
  log-level=warning \
  persistence=false \
  message-size-limit=65536
```

### IoT Edge Setup

Configuration for IoT edge deployments:

```bash
juju config mosquitto-operator \
  port=1883 \
  websockets-port=9001 \
  max-connections=1000 \
  allow-anonymous=false \
  log-level=notice \
  persistence=true \
  message-size-limit=4096
```

## Configuration Management

### Viewing Current Configuration

```bash
# View all configuration options
juju config mosquitto-operator

# View specific option
juju config mosquitto-operator port
```

### Applying Configuration Changes

Configuration changes are applied automatically:

```bash
# Single option
juju config mosquitto-operator log-level=debug

# Multiple options
juju config mosquitto-operator \
  port=1884 \
  log-level=debug \
  max-connections=5000
```

### Configuration Change Process

When configuration is changed:

1. Charm receives the config-changed event
2. Mosquitto configuration file is regenerated 
3. Mosquitto service is restarted
4. Charm reports active status when complete

This process typically takes 10-30 seconds.

### Resetting to Defaults

To reset an option to its default value:

```bash
# Reset specific option
juju config --reset mosquitto-operator log-level

# Reset multiple options  
juju config --reset mosquitto-operator log-level,max-connections
```

## Configuration Files

The charm generates the following configuration files:

### `/etc/mosquitto/mosquitto.conf`

Primary Mosquitto configuration file generated from charm config:

```bash
# View generated configuration
juju ssh mosquitto-operator/0 'cat /etc/mosquitto/mosquitto.conf'
```

Example generated content:
```
# Mosquitto configuration file generated by Juju charm

port 1883
log_dest file /var/log/mosquitto/mosquitto.log
log_type notice
persistence true
persistence_location /var/lib/mosquitto/
allow_anonymous false

listener 9001
protocol websockets
```

### Data Directories

- **Configuration**: `/etc/mosquitto/`
- **Persistent Data**: `/var/lib/mosquitto/`
- **Logs**: `/var/log/mosquitto/`

## Validation

The charm validates configuration values:

- **Port numbers**: Must be valid TCP ports (1-65535)
- **Log levels**: Must be one of the accepted values
- **Boolean values**: Must be `true` or `false`
- **Integer ranges**: Must be within specified limits

Invalid configuration will cause the charm to enter an error state with a descriptive message.

## Related Topics

- [Actions Reference](actions.md) - Available charm actions
- [How-to: Secure Mosquitto](../how-to/secure-mosquitto.md) - Security configuration
- [How-to: Performance Tuning](../how-to/performance-tuning.md) - Optimize for your use case