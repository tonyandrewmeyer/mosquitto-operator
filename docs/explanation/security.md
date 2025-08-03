# Security

This document outlines the security considerations, risks, and best practices when using the Mosquitto charm.

## Security Model

### Default Security Posture

The Mosquitto charm is designed with security-first defaults:

- **Anonymous access disabled**: Clients must authenticate (future feature)
- **No default credentials**: No built-in usernames or passwords
- **Local binding only**: Services bind to localhost by default
- **Minimal privileges**: Runs as `mosquitto` user, not root
- **Secure file permissions**: Configuration and data files have restricted access

### Trust Boundaries

The charm operates within these trust boundaries:

1. **Juju Controller**: Trusted to manage the charm lifecycle
2. **Local Machine**: Trusted for file system access and process execution  
3. **Network**: Untrusted - all network connections should be validated
4. **MQTT Clients**: Untrusted - require authentication and authorization

## Current Security Features

### Process Security

- **Non-root execution**: Mosquitto runs as dedicated `mosquitto` user
- **Process isolation**: Uses systemd for process management and isolation
- **File permissions**: Configuration files owned by `mosquitto:mosquitto` with 644 permissions
- **Data directory security**: `/var/lib/mosquitto/` owned by `mosquitto` with 755 permissions

### Network Security

- **Port binding**: Services bind to all interfaces (0.0.0.0) for Juju integration
- **Protocol support**: 
  - Standard MQTT on port 1883 (unencrypted)
  - MQTT over WebSockets on port 9001 (unencrypted)
- **Firewall integration**: Juju manages firewall rules automatically

### Configuration Security

- **Anonymous access control**: `allow-anonymous` option (default: false)
- **Configuration validation**: Invalid configurations rejected
- **Secure defaults**: Production-safe default values

## Security Limitations

### Current Limitations

1. **No authentication**: The charm does not yet implement user authentication
2. **No TLS/SSL**: Connections are currently unencrypted
3. **No authorization**: No per-topic or per-user access controls
4. **No certificate management**: No integration with certificate authorities
5. **Limited audit logging**: Basic logging without security event tracking

### Known Security Risks

#### 1. Unencrypted Communications
- **Risk**: MQTT traffic is transmitted in plaintext
- **Impact**: Credentials and message content visible to network eavesdroppers
- **Mitigation**: Deploy on trusted networks or implement network-level encryption

#### 2. No Client Authentication  
- **Risk**: When `allow-anonymous=true`, any client can connect
- **Impact**: Unauthorized access to MQTT broker
- **Mitigation**: Only enable for development; use network controls for production

#### 3. No Message Authorization
- **Risk**: Authenticated clients can access all topics
- **Impact**: Data leakage between applications or tenants
- **Mitigation**: Use topic naming conventions and application-level controls

#### 4. Privilege Escalation Vectors
- **Risk**: Vulnerabilities in Mosquitto could lead to privilege escalation
- **Impact**: Compromise of the host system
- **Mitigation**: Keep Mosquitto updated, monitor security advisories

## Security Best Practices

### Network Security

#### Use Juju Spaces
Deploy Mosquitto in a dedicated network space:

```bash
juju deploy mosquitto-operator --bind "mqtt-space"
```

#### Firewall Configuration
Limit access to necessary ports:

```bash
# Allow only specific CIDR blocks
juju expose mosquitto-operator --to-cidrs 10.0.0.0/8,192.168.0.0/16

# Or expose to specific applications only  
juju integrate mosquitto-operator some-client-app
```

#### VPN/Private Networks
- Deploy on private networks when possible
- Use VPN for remote client access
- Consider network segmentation for multi-tenant deployments

### Deployment Security

#### Secure Configuration
```bash
# Production security settings
juju config mosquitto-operator \
  allow-anonymous=false \
  log-level=notice \
  max-connections=1000
```

#### Resource Limits
```bash
# Prevent resource exhaustion
juju config mosquitto-operator \
  max-connections=10000 \
  message-size-limit=1048576
```

#### Regular Updates
```bash
# Keep the charm updated
juju refresh mosquitto-operator

# Monitor for security updates
juju status --format=json | jq '.applications."mosquitto-operator".version'
```

### Operational Security

#### Monitoring and Alerting

1. **Service Monitoring**:
   ```bash
   # Regular health checks
   juju run mosquitto-operator/0 get-status
   ```

2. **Log Monitoring**:
   ```bash
   # Monitor for suspicious activity
   juju ssh mosquitto-operator/0 'tail -f /var/log/mosquitto/mosquitto.log'
   ```

3. **Connection Monitoring**:
   ```bash
   # Monitor active connections
   juju ssh mosquitto-operator/0 'ss -tn | grep :1883'
   ```

#### Incident Response

1. **Isolate the service**:
   ```bash
   juju unexpose mosquitto-operator
   ```

2. **Restart if needed**:
   ```bash
   juju run mosquitto-operator/0 restart
   ```

3. **Collect logs**:
   ```bash
   juju debug-log --include mosquitto-operator > incident-logs.txt
   ```

### Development vs Production

#### Development Environment
```bash
# Relaxed settings for development
juju config mosquitto-operator \
  allow-anonymous=true \
  log-level=debug \
  max-connections=100
```

#### Production Environment
```bash
# Hardened settings for production
juju config mosquitto-operator \
  allow-anonymous=false \
  log-level=warning \
  max-connections=10000 \
  message-size-limit=65536
```

## Future Security Enhancements

### Planned Features

1. **TLS/SSL Support**:
   - X.509 certificate integration
   - TLS-enabled MQTT connections
   - Certificate rotation

2. **Authentication Systems**:
   - Username/password authentication
   - Certificate-based authentication  
   - Integration with external identity providers

3. **Authorization Controls**:
   - Topic-based access control lists (ACLs)
   - Role-based access control (RBAC)
   - Per-client connection limits

4. **Security Monitoring**:
   - Failed authentication logging
   - Connection rate limiting
   - Suspicious activity detection

### Integration Opportunities

1. **TLS Certificate Providers**:
   - Integration with Let's Encrypt charms
   - Support for internal certificate authorities
   - Automatic certificate renewal

2. **Identity and Access Management**:
   - LDAP/Active Directory integration
   - OAuth 2.0 / OpenID Connect support
   - SAML authentication

3. **Security Information and Event Management (SIEM)**:
   - Structured security event logging
   - Integration with log aggregation systems
   - Security metrics and alerting

## Compliance Considerations

### Data Protection

- **Data in transit**: Currently unencrypted (future TLS support planned)
- **Data at rest**: Stored in plaintext in `/var/lib/mosquitto/`
- **Data retention**: Configurable via persistence settings
- **Data deletion**: Automatic on application removal

### Regulatory Compliance

For regulated environments, consider:

1. **GDPR/CCPA**: Implement data retention and deletion policies
2. **HIPAA**: Use network encryption and access controls
3. **SOC 2**: Implement logging, monitoring, and access controls
4. **ISO 27001**: Follow information security management practices

## Security Reporting

### Vulnerability Disclosure

To report security vulnerabilities:

1. **Do not** create public issues for security vulnerabilities
2. Use GitHub's private vulnerability reporting feature
3. Include detailed reproduction steps and impact assessment
4. Allow reasonable time for response and remediation

See [SECURITY.md](../../SECURITY.md) for complete reporting guidelines.

### Security Updates

Security updates are distributed through:

1. **Charm updates**: Via Charmhub using `juju refresh`
2. **Operating system updates**: Via Ubuntu package management
3. **Mosquitto updates**: Via Ubuntu package repositories

Subscribe to security advisories:
- [Ubuntu Security Notices](https://ubuntu.com/security/notices)
- [Mosquitto Security Advisories](https://mosquitto.org/security/)

## Conclusion

While the current Mosquitto charm provides basic security through secure defaults and process isolation, it is designed for trusted network environments. For production deployments requiring strong security:

1. Use network-level controls and VPNs
2. Deploy on private networks
3. Monitor logs and connections actively
4. Plan for future authentication and encryption features

The security model will be significantly enhanced in future versions with TLS support, authentication systems, and authorization controls.