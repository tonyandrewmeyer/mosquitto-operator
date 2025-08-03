# Mosquitto Charm Development Plan

## Overview
Building a machine charm for Eclipse Mosquitto, an open-source MQTT broker for IoT messaging.

## Charm Architecture

### Charm Type
Machine charm - Mosquitto is traditionally deployed as a system service with excellent package support.

### Key Configuration Options
- `port`: MQTT broker port (default: 1883)
- `websockets-port`: WebSocket port for MQTT over WS (default: 9001) 
- `log-level`: Logging verbosity (debug, info, warning, error, default: warning)
- `persistence`: Enable message persistence (default: true)
- `persistence-location`: Path for persistence data (default: /var/lib/mosquitto)
- `max-connections`: Maximum concurrent connections (default: unlimited)
- `allow-anonymous`: Allow anonymous connections (default: false)
- `keepalive`: Keepalive interval in seconds (default: 60)
- `message-size-limit`: Maximum message size in bytes

### Authentication & Security
- Username/password authentication via password file
- TLS/SSL configuration for secure connections
- Support for client certificates
- Access control lists (ACLs) for topic-based permissions

### Relations
- `certificates`: For TLS certificates (tls-certificates interface)
- `logging`: For centralized logging integration  
- `prometheus-scrape`: For metrics collection
- `mqtt-client`: Provide MQTT broker endpoint to client applications

### Actions
- `get-stats`: Retrieve broker statistics and connection info
- `reload-config`: Reload configuration without service restart
- `add-user`: Add MQTT user with password
- `remove-user`: Remove MQTT user
- `list-users`: List configured users
- `backup-data`: Backup persistence data and configuration
- `restore-data`: Restore from backup

### Storage
- `data`: For persistent message storage and configuration

### Resources
None required - using system packages

### Scaling Strategy
- Single unit deployment (standard MQTT broker setup)
- Future enhancement: Bridge configuration for multi-broker setups

### Workload Management
- Install via `apt` package (`mosquitto` and `mosquitto-clients`)
- Manage via systemd service (`mosquitto.service`)
- Configuration via `/etc/mosquitto/mosquitto.conf`
- User management via `mosquitto_passwd` utility
- Log files in `/var/log/mosquitto/`
- Persistence data in `/var/lib/mosquitto/`

### Health Checks
- Service status monitoring
- Port connectivity checks
- Log file monitoring for errors
- Connection count monitoring

### Security Considerations
- Secure default configuration (no anonymous access)
- TLS encryption support
- Proper file permissions for config and password files
- Network security via firewall rules

## Implementation Priority
1. Basic installation and service management
2. Core configuration options
3. Authentication setup
4. TLS/SSL support
5. Relations and integrations
6. Actions and monitoring
7. Storage and backup functionality