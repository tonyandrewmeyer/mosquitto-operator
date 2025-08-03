# Actions Reference

This reference documents all actions available for the Mosquitto charm.

## Available Actions

### `restart`

Restart the Mosquitto service.

**Usage**:
```bash
juju run mosquitto-operator/0 restart
```

**Description**: 
Gracefully restarts the Mosquitto service using systemctl. This action:
- Stops the current Mosquitto process
- Starts a new Mosquitto process 
- Waits for the service to become active
- Preserves persistent data and configuration

**When to use**:
- After manual configuration changes
- To recover from service issues
- As part of maintenance procedures

**Output**:
```yaml
result: "Mosquitto restarted successfully"
```

**Timing**: Usually completes within 10-30 seconds.

**Error handling**: If the restart fails, the action will report an error and the charm will enter error status.

---

### `get-status`

Get detailed status information about the Mosquitto service.

**Usage**:
```bash
juju run mosquitto-operator/0 get-status
```

**Description**:
Retrieves comprehensive status information about the running Mosquitto service, including:
- Service status (active/inactive/failed)
- Version information
- Process details
- Uptime information

**Output format**:
```yaml
service-status: "active"
version: "2.0.15" 
active-since: "active (running) since Mon 2025-08-03 15:24:42 UTC; 5min ago"
main-pid: "1234 (mosquitto)"
```

**Output fields**:

#### `service-status`
- **Type**: string
- **Values**: `"active"`, `"inactive"`, `"failed"`, `"unknown"`
- **Description**: Current systemd service status

#### `version`
- **Type**: string  
- **Example**: `"2.0.15"`
- **Description**: Mosquitto version currently running

#### `active-since`
- **Type**: string
- **Example**: `"active (running) since Mon 2025-08-03 15:24:42 UTC; 5min ago"`
- **Description**: When the service started and how long it's been running

#### `main-pid`
- **Type**: string
- **Example**: `"1234 (mosquitto)"`
- **Description**: Process ID and name of the main Mosquitto process

**When to use**:
- Health checking and monitoring
- Troubleshooting service issues
- Gathering information for support requests
- Automated monitoring scripts

**Error handling**: If status cannot be retrieved, returns:
```yaml
service-status: "unknown"
error: "Failed to get status"
```

## Action Examples

### Basic Usage

```bash
# Restart the service
juju run mosquitto-operator/0 restart

# Get status
juju run mosquitto-operator/0 get-status
```

### Using Actions in Scripts

```bash
#!/bin/bash

# Check if Mosquitto is healthy
status_output=$(juju run mosquitto-operator/0 get-status --format=json)
service_status=$(echo "$status_output" | jq -r '.results."mosquitto-operator/0".service-status')

if [ "$service_status" != "active" ]; then
    echo "Mosquitto is not active, attempting restart..."
    juju run mosquitto-operator/0 restart
    
    # Wait and check again
    sleep 30
    status_output=$(juju run mosquitto-operator/0 get-status --format=json)
    service_status=$(echo "$status_output" | jq -r '.results."mosquitto-operator/0".service-status')
    
    if [ "$service_status" = "active" ]; then
        echo "Mosquitto successfully restarted"
    else
        echo "Failed to restart Mosquitto"
        exit 1
    fi
else
    echo "Mosquitto is healthy"
fi
```

### Monitoring with Actions

```bash
# Get detailed status for monitoring
juju run mosquitto-operator/0 get-status --format=yaml > mosquitto-status.yaml

# Extract specific values
service_status=$(juju run mosquitto-operator/0 get-status --format=json | jq -r '.results."mosquitto-operator/0".service-status')
version=$(juju run mosquitto-operator/0 get-status --format=json | jq -r '.results."mosquitto-operator/0".version')

echo "Service Status: $service_status"
echo "Version: $version"
```

## Action Output Formats

Actions support multiple output formats via the `--format` flag:

### YAML Format (default)
```bash
juju run mosquitto-operator/0 get-status --format=yaml
```
Output:
```yaml
results:
  mosquitto-operator/0:
    service-status: active
    version: "2.0.15"
    active-since: "active (running) since Mon 2025-08-03 15:24:42 UTC; 5min ago"
    main-pid: "1234 (mosquitto)"
```

### JSON Format
```bash
juju run mosquitto-operator/0 get-status --format=json
```
Output:
```json
{
  "results": {
    "mosquitto-operator/0": {
      "service-status": "active",
      "version": "2.0.15", 
      "active-since": "active (running) since Mon 2025-08-03 15:24:42 UTC; 5min ago",
      "main-pid": "1234 (mosquitto)"
    }
  }
}
```

### Plain Text Format
```bash
juju run mosquitto-operator/0 get-status --format=plain
```
Output:
```
service-status: active
version: 2.0.15
active-since: active (running) since Mon 2025-08-03 15:24:42 UTC; 5min ago
main-pid: 1234 (mosquitto)
```

## Action Limitations

### Concurrency
- Only one action can run per unit at a time
- Actions may be queued if the unit is busy

### Timing
- Actions have a default timeout of 5 minutes
- Long-running operations may timeout

### Permissions
- Actions run with the same permissions as the charm
- Administrative operations are allowed

## Error Handling

Actions may fail for various reasons:

### Common Error Scenarios

1. **Service not responding**:
   ```yaml
   error: "Mosquitto service failed to start within 30 seconds"
   ```

2. **Permission issues**:
   ```yaml
   error: "Permission denied accessing service"
   ```

3. **System resource issues**:
   ```yaml
   error: "Insufficient system resources"
   ```

### Troubleshooting Failed Actions

1. **Check unit logs**:
   ```bash
   juju debug-log --include mosquitto-operator/0
   ```

2. **Check service status directly**:
   ```bash
   juju ssh mosquitto-operator/0 'systemctl status mosquitto'
   ```

3. **Check system resources**:
   ```bash
   juju ssh mosquitto-operator/0 'free -h && df -h'
   ```

## Related Topics

- [Configuration Reference](configuration.md) - Charm configuration options
- [How-to: Monitor Mosquitto](../how-to/monitor-mosquitto.md) - Monitoring setup
- [How-to: Troubleshoot](../how-to/troubleshoot.md) - Troubleshooting guide