# Security Policy

## Reporting Security Vulnerabilities

We take the security of the Mosquitto charm seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report security vulnerabilities using GitHub's security advisory feature:

1. Go to the [Security tab](../../security) of this repository
2. Click "Report a vulnerability" 
3. Fill out the security advisory form with details about the vulnerability

Alternatively, you can email the maintainers directly with details about the security issue.

### What to Include

When reporting a security vulnerability, please include:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact of the vulnerability
- Any suggested fixes or mitigations
- Your contact information for follow-up questions

### Response Timeline

We will acknowledge receipt of your vulnerability report within 48 hours and provide a detailed response within 7 days indicating the next steps in handling your submission.

We will keep you informed of the progress throughout the resolution process and may ask for additional information or guidance.

### Disclosure Policy

We follow responsible disclosure practices:

1. We will work to fix reported vulnerabilities promptly
2. We will coordinate with you on the timing of public disclosure
3. We will credit you for the discovery (unless you prefer to remain anonymous)
4. We will publish security advisories for confirmed vulnerabilities

### Security Best Practices

When using this charm in production:

- Keep the charm updated to the latest version
- Disable anonymous MQTT access (`allow-anonymous=false`)
- Use strong passwords for MQTT users
- Enable TLS encryption for production deployments
- Regularly audit MQTT user accounts
- Monitor MQTT broker logs for suspicious activity
- Restrict network access to MQTT ports using firewall rules
- Regularly backup configuration and persistence data

### Supported Versions

We provide security updates for:

- The latest stable release
- The previous stable release (when applicable)

Older versions may not receive security updates. Please upgrade to a supported version.

### Known Security Considerations

- Anonymous access is disabled by default but can be enabled via configuration
- Password files are stored with restricted permissions (600)
- TLS support requires certificate relations to be properly configured
- Log files may contain sensitive information - ensure proper log rotation and access controls

For more information about MQTT security best practices, see:
- [MQTT Security Fundamentals](https://mqtt.org/mqtt-security-fundamentals/)
- [Eclipse Mosquitto Security](https://mosquitto.org/documentation/security/)