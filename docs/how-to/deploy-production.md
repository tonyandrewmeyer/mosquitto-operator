# How to Deploy Mosquitto for Production

This guide covers deploying Mosquitto in a production environment with proper security, monitoring, and performance considerations.

## Before You Start

Ensure you have:
- Juju 3.0+ with a production controller
- Understanding of your network topology
- Resource requirements planned
- Security policies defined

## Production Deployment Checklist

### 1. Resource Planning

Calculate your resource needs:

```bash
# Deploy with specific constraints
juju deploy mosquitto-operator \
  --constraints "cores=4 mem=8G root-disk=50G" \
  --to zone=production-zone
```

**Recommended minimum resources**:
- **CPU**: 2+ cores for high throughput
- **Memory**: 4GB+ for large connection counts
- **Disk**: 20GB+ for persistence and logs
- **Network**: Dedicated VLAN preferred

### 2. Network Configuration

#### Use Dedicated Network Spaces

Create network spaces for MQTT traffic:

```bash
# Deploy to dedicated network space
juju deploy mosquitto-operator --bind mqtt-space
```

#### Configure Firewall Rules

Expose only necessary ports to specific networks:

```bash
# Expose to specific IP ranges
juju expose mosquitto-operator \
  --to-cidrs 10.0.0.0/8,192.168.1.0/24

# Or expose specific ports
juju expose mosquitto-operator 1883/tcp
juju expose mosquitto-operator 9001/tcp
```

### 3. Security Configuration

#### Apply Security Hardening

```bash
juju config mosquitto-operator \
  allow-anonymous=false \
  log-level=warning \
  max-connections=10000 \
  message-size-limit=1048576
```

#### Monitor Security Settings

```bash
# Verify security configuration
juju config mosquitto-operator | grep -E "(allow-anonymous|log-level)"
```

### 4. Performance Tuning

#### High-Throughput Configuration

```bash
juju config mosquitto-operator \
  max-connections=50000 \
  message-size-limit=65536 \
  persistence=false
```

#### Standard Production Configuration

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

### 5. Storage Configuration

#### Configure Persistent Storage

For message persistence in production:

```bash
# Deploy with specific storage
juju deploy mosquitto-operator \
  --storage persistence=20G,2
```

#### Backup Strategy

Set up regular backups of persistent data:

```bash
#!/bin/bash
# backup-mosquitto.sh

BACKUP_DIR="/backup/mosquitto/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Stop service briefly for consistent backup
juju ssh mosquitto-operator/0 'sudo systemctl stop mosquitto'

# Backup persistent data
juju ssh mosquitto-operator/0 'sudo tar -czf /tmp/mosquitto-data.tar.gz /var/lib/mosquitto/'
juju scp mosquitto-operator/0:/tmp/mosquitto-data.tar.gz "$BACKUP_DIR/"

# Restart service
juju ssh mosquitto-operator/0 'sudo systemctl start mosquitto'

# Cleanup
juju ssh mosquitto-operator/0 'sudo rm /tmp/mosquitto-data.tar.gz'
```

## Monitoring Setup

### 1. Health Monitoring

#### Automated Health Checks

```bash
#!/bin/bash
# mosquitto-healthcheck.sh

check_health() {
    local status
    status=$(juju run mosquitto-operator/0 get-status --format=json | jq -r '.results."mosquitto-operator/0".service-status')
    
    if [ "$status" != "active" ]; then
        echo "CRITICAL: Mosquitto service is $status"
        # Send alert to monitoring system
        curl -X POST "$ALERT_WEBHOOK" -d "service=mosquitto&status=critical&message=Service $status"
        return 1
    else
        echo "OK: Mosquitto service is active"
        return 0
    fi
}

check_health
```

#### Connection Monitoring

```bash
# Monitor connection count
juju ssh mosquitto-operator/0 'ss -tn | grep :1883 | wc -l'

# Monitor resource usage
juju ssh mosquitto-operator/0 'ps aux | grep mosquitto'
```

### 2. Log Management

#### Centralized Logging

Configure log forwarding to your log management system:

```bash
# Configure rsyslog forwarding
juju ssh mosquitto-operator/0 'sudo tee /etc/rsyslog.d/50-mosquitto.conf << EOF
# Forward Mosquitto logs to central server
$ModLoad imfile
$InputFileName /var/log/mosquitto/mosquitto.log
$InputFileTag mosquitto:
$InputFileStateFile stat-mosquitto
$InputFileSeverity info
$InputFileFacility local0
$InputRunFileMonitor

local0.* @@logserver.example.com:514
EOF'

# Restart rsyslog
juju ssh mosquitto-operator/0 'sudo systemctl restart rsyslog'
```

#### Log Rotation

Ensure log rotation is configured:

```bash
juju ssh mosquitto-operator/0 'sudo tee /etc/logrotate.d/mosquitto << EOF
/var/log/mosquitto/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    create 644 mosquitto mosquitto
    postrotate
        systemctl reload mosquitto > /dev/null 2>&1 || true
    endscript
}
EOF'
```

## High Availability Setup

### Active-Passive Configuration

Deploy multiple instances with load balancing:

```bash
# Deploy primary instance
juju deploy mosquitto-operator mosquitto-primary \
  --constraints "cores=4 mem=8G" \
  --to zone=primary

# Deploy secondary instance  
juju deploy mosquitto-operator mosquitto-secondary \
  --constraints "cores=4 mem=8G" \
  --to zone=secondary
```

Configure load balancer to distribute connections:

```bash
# Example HAProxy configuration
juju deploy haproxy
juju integrate mosquitto-primary haproxy
juju integrate mosquitto-secondary haproxy
```

### Data Synchronization

For persistent data synchronization:

```bash
# Set up rsync between instances
#!/bin/bash
# sync-mosquitto-data.sh

PRIMARY="mosquitto-primary/0"
SECONDARY="mosquitto-secondary/0"

# Sync data directory
juju ssh "$PRIMARY" 'sudo rsync -av /var/lib/mosquitto/ backup-server:/backup/mosquitto-primary/'
juju ssh "$SECONDARY" 'sudo rsync -av backup-server:/backup/mosquitto-primary/ /var/lib/mosquitto/'
```

## Performance Optimization

### System Tuning

#### Kernel Parameters

```bash
# Optimize for high connection counts
juju ssh mosquitto-operator/0 'sudo tee -a /etc/sysctl.d/99-mosquitto.conf << EOF
# Increase file descriptor limits
fs.file-max = 100000

# Optimize network stack
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 5000

# TCP tuning
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 120
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
EOF'

# Apply changes
juju ssh mosquitto-operator/0 'sudo sysctl -p /etc/sysctl.d/99-mosquitto.conf'
```

#### Service Limits

```bash
# Increase service limits
juju ssh mosquitto-operator/0 'sudo mkdir -p /etc/systemd/system/mosquitto.service.d'
juju ssh mosquitto-operator/0 'sudo tee /etc/systemd/system/mosquitto.service.d/override.conf << EOF
[Service]
LimitNOFILE=100000
LimitNPROC=32768
EOF'

# Reload systemd
juju ssh mosquitto-operator/0 'sudo systemctl daemon-reload'
juju ssh mosquitto-operator/0 'sudo systemctl restart mosquitto'
```

### Application Tuning

#### Connection Optimization

```bash
# Optimize for connection handling
juju config mosquitto-operator \
  max-connections=50000 \
  message-size-limit=32768
```

#### Memory Optimization

```bash
# For memory-constrained environments
juju config mosquitto-operator \
  persistence=false \
  max-connections=5000 \
  message-size-limit=4096
```

## Disaster Recovery

### Backup Procedures

#### Automated Backup Script

```bash
#!/bin/bash
# mosquitto-backup.sh

BACKUP_ROOT="/backup/mosquitto"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$DATE"

mkdir -p "$BACKUP_DIR"

# Backup configuration
juju ssh mosquitto-operator/0 'sudo cp -r /etc/mosquitto/ /tmp/mosquitto-config'
juju scp mosquitto-operator/0:/tmp/mosquitto-config "$BACKUP_DIR/"

# Backup persistent data
juju ssh mosquitto-operator/0 'sudo tar -czf /tmp/mosquitto-data.tar.gz /var/lib/mosquitto/'
juju scp mosquitto-operator/0:/tmp/mosquitto-data.tar.gz "$BACKUP_DIR/"

# Backup charm configuration
juju config mosquitto-operator > "$BACKUP_DIR/charm-config.yaml"

# Clean up remote files
juju ssh mosquitto-operator/0 'sudo rm -rf /tmp/mosquitto-config /tmp/mosquitto-data.tar.gz'

# Keep only last 30 days of backups
find "$BACKUP_ROOT" -type d -mtime +30 -exec rm -rf {} \;

echo "Backup completed: $BACKUP_DIR"
```

### Recovery Procedures

#### Restore from Backup

```bash
#!/bin/bash
# mosquitto-restore.sh

BACKUP_DIR="$1"

if [ -z "$BACKUP_DIR" ]; then
    echo "Usage: $0 <backup-directory>"
    exit 1
fi

# Stop service
juju ssh mosquitto-operator/0 'sudo systemctl stop mosquitto'

# Restore data
juju scp "$BACKUP_DIR/mosquitto-data.tar.gz" mosquitto-operator/0:/tmp/
juju ssh mosquitto-operator/0 'sudo tar -xzf /tmp/mosquitto-data.tar.gz -C /'

# Restore configuration
juju scp "$BACKUP_DIR/mosquitto-config" mosquitto-operator/0:/tmp/
juju ssh mosquitto-operator/0 'sudo cp -r /tmp/mosquitto-config/* /etc/mosquitto/'

# Restore charm configuration
juju config mosquitto-operator --file "$BACKUP_DIR/charm-config.yaml"

# Fix permissions
juju ssh mosquitto-operator/0 'sudo chown -R mosquitto:mosquitto /var/lib/mosquitto /etc/mosquitto'

# Start service
juju ssh mosquitto-operator/0 'sudo systemctl start mosquitto'

echo "Restore completed from: $BACKUP_DIR"
```

## Maintenance Procedures

### Regular Maintenance Tasks

#### Weekly Tasks

```bash
#!/bin/bash
# mosquitto-weekly-maintenance.sh

# Check service health
juju run mosquitto-operator/0 get-status

# Check log file sizes
juju ssh mosquitto-operator/0 'du -sh /var/log/mosquitto/*'

# Check disk usage
juju ssh mosquitto-operator/0 'df -h /var/lib/mosquitto'

# Rotate logs if needed
juju ssh mosquitto-operator/0 'sudo logrotate /etc/logrotate.d/mosquitto'

# Check for security updates
juju ssh mosquitto-operator/0 'sudo apt list --upgradable | grep mosquitto'
```

#### Monthly Tasks

```bash
#!/bin/bash
# mosquitto-monthly-maintenance.sh

# Full backup
./mosquitto-backup.sh

# Performance analysis
juju ssh mosquitto-operator/0 'sudo iotop -a -o -d 1 -n 60' > performance-$(date +%Y%m).log

# Connection statistics
juju ssh mosquitto-operator/0 'ss -s' > connections-$(date +%Y%m).log

# Security audit
juju ssh mosquitto-operator/0 'sudo lynis audit system --quick' > security-audit-$(date +%Y%m).log
```

### Update Procedures

#### Charm Updates

```bash
# Check for updates
juju refresh --dry-run mosquitto-operator

# Apply updates
juju refresh mosquitto-operator

# Verify update
juju status mosquitto-operator
juju run mosquitto-operator/0 get-status
```

#### Operating System Updates

```bash
# Update OS packages
juju ssh mosquitto-operator/0 'sudo apt update && sudo apt upgrade -y'

# Reboot if kernel updated
juju ssh mosquitto-operator/0 'sudo reboot'

# Verify service after reboot
sleep 60
juju run mosquitto-operator/0 get-status
```

## Troubleshooting

### Common Production Issues

1. **High Connection Count**:
   ```bash
   # Check current connections
   juju ssh mosquitto-operator/0 'ss -tn | grep :1883 | wc -l'
   
   # Increase limits if needed
   juju config mosquitto-operator max-connections=20000
   ```

2. **Memory Issues**:
   ```bash
   # Check memory usage
   juju ssh mosquitto-operator/0 'free -h'
   
   # Check for memory leaks
   juju ssh mosquitto-operator/0 'ps aux | grep mosquitto'
   ```

3. **Disk Space**:
   ```bash
   # Check disk usage
   juju ssh mosquitto-operator/0 'df -h'
   
   # Clean old logs
   juju ssh mosquitto-operator/0 'sudo find /var/log/mosquitto -name "*.gz" -mtime +7 -delete'
   ```

For more troubleshooting guidance, see [How-to: Troubleshoot Common Issues](troubleshoot.md).

## Related Topics

- [Security Guide](../explanation/security.md) - Security considerations
- [Configuration Reference](../reference/configuration.md) - All configuration options
- [Performance Tuning](performance-tuning.md) - Optimize for your workload