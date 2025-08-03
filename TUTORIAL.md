# Mosquitto Charm Tutorial

This tutorial provides a basic guide for deploying and using the Mosquitto MQTT broker charm.

## Prerequisites

- A Juju controller (see [Juju documentation](https://juju.is/docs) for setup)
- Access to a cloud or machine where you can deploy charms

## Deploying Mosquitto

### Basic Deployment

Deploy the Mosquitto charm with default settings:

```bash
juju deploy mosquitto-operator
```

Wait for the deployment to complete:

```bash
juju status --watch 1s
```

The charm should reach `active` status once Mosquitto is running.

### Configuration

Configure the MQTT broker settings:

```bash
# Change the MQTT port
juju config mosquitto-operator port=1884

# Enable anonymous access (not recommended for production)
juju config mosquitto-operator allow-anonymous=true

# Configure WebSocket port
juju config mosquitto-operator websockets-port=9001

# Set maximum connections
juju config mosquitto-operator max-connections=1000

# Configure logging level
juju config mosquitto-operator log-level=debug
```

## Testing the MQTT Broker

### Using Mosquitto Clients

SSH into the unit to test MQTT functionality:

```bash
# Subscribe to a topic (run in one terminal)
juju ssh mosquitto-operator/0 'mosquitto_sub -h localhost -p 1883 -t test/topic'

# Publish a message (run in another terminal)
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 1883 -t test/topic -m "Hello MQTT!"'
```

### Testing WebSocket Connection

If WebSockets are enabled, you can test the WebSocket listener:

```bash
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 9001 -t test/ws -m "WebSocket test"'
```

## Actions

The charm provides several actions for managing the MQTT broker:

### Restart the Service

```bash
juju run mosquitto-operator/0 restart
```

### Get Status Information

```bash
juju run mosquitto-operator/0 get-status
```

This returns detailed status information including:
- Service status
- Version information
- Process details

## Monitoring and Logs

### Check Service Status

```bash
juju ssh mosquitto-operator/0 'systemctl status mosquitto'
```

### View Logs

```bash
juju ssh mosquitto-operator/0 'tail -f /var/log/mosquitto/mosquitto.log'
```

### Check Configuration

```bash
juju ssh mosquitto-operator/0 'cat /etc/mosquitto/mosquitto.conf'
```

## Security Considerations

For production deployments:

1. **Disable anonymous access**: Set `allow-anonymous=false`
2. **Use TLS**: Configure TLS certificates (future feature)
3. **Implement authentication**: Set up user credentials (future feature)
4. **Network security**: Use Juju's network spaces to control access

## Scaling

Mosquitto is a single-instance MQTT broker. For high availability:

1. Deploy multiple independent instances
2. Use a load balancer for client distribution
3. Consider clustering solutions for production workloads

## Removing the Deployment

To remove the Mosquitto deployment:

```bash
juju remove-application mosquitto-operator
```

## Troubleshooting

### Common Issues

1. **Service not starting**: Check logs with `juju debug-log`
2. **Port conflicts**: Ensure configured ports are available
3. **Permission issues**: Check file permissions in `/var/lib/mosquitto`

### Getting Help

- Check the charm status: `juju status mosquitto-operator`
- View recent logs: `juju debug-log --include mosquitto-operator`
- Run status action: `juju run mosquitto-operator/0 get-status`

For more advanced configuration and troubleshooting, refer to the [Mosquitto documentation](https://mosquitto.org/documentation/).