# Getting Started with Mosquitto Charm

This tutorial will walk you through deploying and using the Mosquitto MQTT broker charm. By the end, you'll have a working MQTT broker and understand how to configure and use it.

## What You'll Learn

- How to deploy the Mosquitto charm
- How to configure basic MQTT settings
- How to test MQTT messaging
- How to monitor your deployment

## Prerequisites

Before starting, ensure you have:

- [Juju](https://juju.is/docs/juju) 3.0+ installed
- Access to a Juju controller
- A model ready for deployment (we'll use "default")

### Verify Your Setup

Check that Juju is working:

```bash
juju status
```

You should see your current model status. If you need to create a model:

```bash
juju add-model tutorial
juju switch tutorial
```

## Step 1: Deploy Mosquitto

Deploy the Mosquitto charm with default settings:

```bash
juju deploy mosquitto-operator
```

This command:
- Downloads the charm from Charmhub
- Creates a new application called "mosquitto-operator"
- Provisions a machine and installs Mosquitto

Watch the deployment progress:

```bash
juju status --watch 1s
```

Press `Ctrl+C` to stop watching. The deployment is complete when you see:
- Machine status: `started`
- Application status: `active`
- Unit status: `active`

This usually takes 2-5 minutes.

## Step 2: Verify the Deployment

Check that Mosquitto is running:

```bash
juju ssh mosquitto-operator/0 'systemctl status mosquitto'
```

You should see output showing the service is "active (running)".

Check what ports are listening:

```bash
juju ssh mosquitto-operator/0 'ss -tlnp | grep -E ":(1883|9001)"'
```

You should see:
- Port 1883: Standard MQTT
- Port 9001: MQTT over WebSockets

## Step 3: Test MQTT Messaging

Now let's test the MQTT functionality. We'll use the built-in Mosquitto client tools.

### Subscribe to a Topic

In one terminal, subscribe to a test topic:

```bash
juju ssh mosquitto-operator/0 'mosquitto_sub -h localhost -p 1883 -t tutorial/messages -v'
```

The `-v` flag shows the topic name with each message. Leave this running.

### Publish a Message

In another terminal, publish a message:

```bash
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 1883 -t tutorial/messages -m "Hello from Mosquitto!"'
```

You should see the message appear in your subscriber terminal:
```
tutorial/messages Hello from Mosquitto!
```

### Test Multiple Messages

Try sending several messages:

```bash
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 1883 -t tutorial/messages -m "Message 1"'
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 1883 -t tutorial/messages -m "Message 2"'
juju ssh mosquitto-operator/0 'mosquitto_pub -h localhost -p 1883 -t tutorial/messages -m "Message 3"'
```

All messages should appear in your subscriber.

Stop the subscriber with `Ctrl+C`.

## Step 4: Configure Mosquitto

Let's modify some basic settings to understand charm configuration.

### Change the Log Level

Increase logging verbosity to see more details:

```bash
juju config mosquitto-operator log-level=debug
```

Wait for the configuration change to apply (usually 10-30 seconds):

```bash
juju status --watch 1s
```

### View the Logs

Check the debug logs:

```bash
juju ssh mosquitto-operator/0 'tail -20 /var/log/mosquitto/mosquitto.log'
```

You should see more detailed log entries.

### Reset Log Level

Return to normal logging:

```bash
juju config mosquitto-operator log-level=notice
```

## Step 5: Test WebSocket Support

Mosquitto also supports MQTT over WebSockets for web applications.

### Check WebSocket Port

Verify the WebSocket listener is active:

```bash
juju ssh mosquitto-operator/0 'ss -tlnp | grep :9001'
```

### Test WebSocket Connection

While we can't easily test WebSockets from the command line, you can verify the configuration:

```bash
juju ssh mosquitto-operator/0 'grep -A2 "listener 9001" /etc/mosquitto/mosquitto.conf'
```

You should see:
```
listener 9001
protocol websockets
```

## Step 6: Monitor Your Deployment

### Check Service Status

Use the charm's built-in status action:

```bash
juju run mosquitto-operator/0 get-status
```

This returns detailed information about the service, including version and process details.

### View Configuration

Check the current charm configuration:

```bash
juju config mosquitto-operator
```

### Monitor Logs

View live logs:

```bash
juju ssh mosquitto-operator/0 'tail -f /var/log/mosquitto/mosquitto.log'
```

Press `Ctrl+C` to stop following logs.

## Step 7: Clean Up (Optional)

If this was just for learning, you can remove the deployment:

```bash
juju remove-application mosquitto-operator
```

Wait for removal to complete:

```bash
juju status --watch 1s
```

## What You've Learned

Congratulations! You've successfully:

✅ Deployed the Mosquitto MQTT broker charm  
✅ Verified the deployment is working  
✅ Tested MQTT pub/sub messaging  
✅ Modified charm configuration  
✅ Monitored the service  
✅ Understood WebSocket support  

## Next Steps

Now that you have the basics, you might want to:

- **Production Setup**: Learn about security configuration in [How-to: Secure Mosquitto](../how-to/secure-mosquitto.md)
- **Advanced Config**: Explore all configuration options in [Reference: Configuration](../reference/configuration.md)
- **Integration**: Connect applications to your MQTT broker
- **Monitoring**: Set up monitoring and alerting

## Troubleshooting

If something didn't work:

1. **Check Status**: `juju status` should show "active" for all components
2. **Check Logs**: `juju debug-log --include mosquitto-operator`
3. **Verify Service**: `juju ssh mosquitto-operator/0 'systemctl status mosquitto'`
4. **Check Ports**: `juju ssh mosquitto-operator/0 'ss -tlnp | grep 1883'`

For more help, see [How-to: Troubleshoot Common Issues](../how-to/troubleshoot.md).