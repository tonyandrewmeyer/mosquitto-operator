# Mosquitto Charm Tutorial

This tutorial will guide you through deploying and using the Mosquitto MQTT broker charm with Juju.

## Prerequisites

- Juju controller set up and ready
- Access to a Juju model
- Basic familiarity with MQTT concepts

## Step 1: Deploy the Charm

First, build and deploy the Mosquitto charm:

```bash
# Build the charm
charmcraft pack

# Deploy to your Juju model
juju deploy ./mosquitto_ubuntu-22.04-amd64.charm
```

Wait for the deployment to complete:

```bash
juju status --watch 1s
```

You should see the unit reach `Active` status.

## Step 2: Basic Configuration

Configure the broker for your use case:

```bash
# Set a custom MQTT port (optional)
juju config mosquitto port=1883

# Disable anonymous access for security
juju config mosquitto allow-anonymous=false

# Set logging level
juju config mosquitto log-level=info
```

## Step 3: Create MQTT Users

Since we disabled anonymous access, we need to create user accounts:

```bash
# Add your first user
juju run mosquitto/0 add-user username=iot-user password=secure-password

# Add another user for applications
juju run mosquitto/0 add-user username=app-client password=another-secure-password

# List all users to verify
juju run mosquitto/0 list-users
```

## Step 4: Test the MQTT Broker

Get the broker's IP address:

```bash
juju status mosquitto --format=json | jq -r '.applications.mosquitto.units | to_entries[0].value["public-address"]'
```

Test the connection using mosquitto client tools:

```bash
# Subscribe to a test topic (run this in one terminal)
mosquitto_sub -h <broker-ip> -p 1883 -t "tutorial/messages" -u iot-user -P secure-password

# Publish a message (run this in another terminal)
mosquitto_pub -h <broker-ip> -p 1883 -t "tutorial/messages" -m "Hello from Mosquitto!" -u iot-user -P secure-password
```

You should see the message appear in the subscriber terminal.

## Step 5: Enable WebSocket Support

The charm includes WebSocket support for web-based MQTT clients:

```bash
# WebSockets are enabled by default on port 9001
# Test with a web-based MQTT client or use websockets directly
```

Example JavaScript code for web clients:

```javascript
// Using the Paho MQTT JavaScript client
const client = new Paho.MQTT.Client("ws://<broker-ip>:9001/mqtt", "web-client-" + Math.random());

client.onConnectionLost = function(responseObject) {
    console.log("Connection lost: " + responseObject.errorMessage);
};

client.onMessageArrived = function(message) {
    console.log("Message arrived: " + message.payloadString);
};

client.connect({
    userName: "iot-user",
    password: "secure-password",
    onSuccess: function() {
        console.log("Connected!");
        client.subscribe("tutorial/messages");
        
        // Send a test message
        const message = new Paho.MQTT.Message("Hello from web client!");
        message.destinationName = "tutorial/messages";
        client.send(message);
    }
});
```

## Step 6: Add Persistent Storage

For production use, add persistent storage:

```bash
# Add storage for persistence
juju add-storage mosquitto/0 data=10G

# Verify storage attachment
juju storage --filesystem
```

## Step 7: Monitor the Broker

Get broker statistics and status:

```bash
# Get detailed broker stats
juju run mosquitto/0 get-stats

# View logs
juju debug-log --include=mosquitto

# Check Juju status
juju status mosquitto
```

## Step 8: Secure with TLS (Optional)

For production deployments, enable TLS encryption:

```bash
# Deploy certificate provider
juju deploy self-signed-certificates

# Create certificate relation
juju relate mosquitto:certificates self-signed-certificates:certificates

# Wait for relation to establish
juju status --watch 1s
```

After TLS is configured, you can connect securely:

```bash
# Subscribe with TLS (adjust port if needed)
mosquitto_sub -h <broker-ip> -p 8883 --cafile ca.crt -t "secure/messages" -u iot-user -P secure-password
```

## Step 9: Scale and Integrate

### Connect Applications

Create relations with client applications:

```bash
# Deploy an application that needs MQTT
juju deploy my-iot-app

# Relate to mosquitto
juju relate my-iot-app:mqtt mosquitto:mqtt
```

### Add Monitoring

Integrate with Prometheus for monitoring:

```bash
# Deploy Prometheus
juju deploy prometheus2

# Create monitoring relation
juju relate mosquitto:prometheus-scrape prometheus2:scrape
```

## Step 10: Backup and Maintenance

### Create Backups

```bash
# Create a backup
juju run mosquitto/0 backup-data

# The action will return the backup file path
```

### User Management

```bash
# List all users
juju run mosquitto/0 list-users

# Remove a user
juju run mosquitto/0 remove-user username=old-user

# Add new users as needed
juju run mosquitto/0 add-user username=new-user password=new-password
```

### Configuration Updates

```bash
# Update configuration
juju config mosquitto max-connections=5000
juju config mosquitto message-size-limit=2097152  # 2MB

# Reload configuration without restart
juju run mosquitto/0 reload-config
```

## Common Use Cases

### IoT Sensor Network

```bash
juju deploy ./mosquitto_ubuntu-22.04-amd64.charm iot-broker
juju config iot-broker allow-anonymous=false
juju config iot-broker max-connections=1000
juju config iot-broker log-level=warning

# Create device users
juju run iot-broker/0 add-user username=sensor-01 password=device-secret-01
juju run iot-broker/0 add-user username=sensor-02 password=device-secret-02
```

### Development Environment

```bash
juju deploy ./mosquitto_ubuntu-22.04-amd64.charm dev-mqtt
juju config dev-mqtt allow-anonymous=true
juju config dev-mqtt log-level=debug
juju config dev-mqtt max-connections=100
```

### High-Availability Setup

```bash
# Deploy with storage and monitoring
juju deploy ./mosquitto_ubuntu-22.04-amd64.charm --storage data=50G
juju deploy prometheus2
juju deploy grafana
juju relate mosquitto:prometheus-scrape prometheus2:scrape
juju relate prometheus2:grafana-source grafana:grafana-source
```

## Troubleshooting

### Connection Issues

```bash
# Check service status
juju run mosquitto/0 get-stats

# Test basic connectivity
mosquitto_pub -h <broker-ip> -p 1883 -t "test" -m "test"
```

### Authentication Problems

```bash
# Verify users exist
juju run mosquitto/0 list-users

# Check if anonymous access is enabled
juju config mosquitto allow-anonymous
```

### Performance Issues

```bash
# Check resource usage
juju ssh mosquitto/0 'htop'

# Review logs for errors
juju debug-log --include=mosquitto --level=WARNING
```

## Next Steps

- Explore advanced MQTT features like retained messages and QoS levels
- Implement MQTT topic-based access control
- Set up bridge connections to other MQTT brokers
- Integrate with IoT platforms and applications
- Configure clustering for high availability (future enhancement)

## Additional Resources

- [MQTT.org](https://mqtt.org/) - MQTT protocol documentation
- [Eclipse Mosquitto](https://mosquitto.org/) - Official Mosquitto documentation
- [Juju Documentation](https://juju.is/docs) - Juju usage guides
- [MQTT Security Best Practices](https://mqtt.org/mqtt-security-fundamentals/)

This tutorial covered the basics of deploying and using the Mosquitto charm. For advanced configurations and production deployments, refer to the full documentation in [README.md](README.md).