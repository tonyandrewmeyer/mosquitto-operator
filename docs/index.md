# Mosquitto Charm Documentation

Welcome to the documentation for the Mosquitto MQTT broker charm. This documentation follows the [Diátaxis](https://diataxis.fr/) approach, providing four types of documentation to serve different needs.

## Quick Start

New to the Mosquitto charm? Start with our tutorial:

🚀 **[Getting Started Tutorial](tutorial/getting-started.md)** - Learn by deploying your first Mosquitto broker

## Enterprise Features

The Mosquitto charm provides production-ready features:

- **🔒 Enterprise Security**: TLS/SSL encryption, X.509 client certificates, ACL authorization
- **📊 Observability**: Prometheus metrics, OpenTelemetry tracing, comprehensive logging  
- **💾 High Availability**: Juju storage integration, automated backup/restore
- **🔧 Operations**: Service management, certificate generation, status monitoring
- **🌐 Protocol Support**: MQTT 5.0/3.1.1/3.1, WebSockets (plain & TLS)

## Documentation Types

### 📚 Tutorials (Learning-Oriented)

Step-by-step guides that help you learn by doing:

- **[Getting Started](tutorial/getting-started.md)** - Deploy your first Mosquitto broker and test MQTT messaging

*Perfect for newcomers who want to understand what the charm does and how it works.*

### 🛠️ How-To Guides (Problem-Oriented)

Practical guides for accomplishing specific tasks:

- **[Deploy for Production](how-to/deploy-production.md)** - Production deployment with security, monitoring, and HA
- **[Configure TLS Security](how-to/configure-tls.md)** - Set up TLS encryption and client certificates
- **[Set Up Authentication](how-to/setup-authentication.md)** - Configure SASL and ACL-based authorization
- **[Enable Monitoring](how-to/enable-monitoring.md)** - Prometheus metrics and OpenTelemetry tracing
- **[Manage Storage](how-to/manage-storage.md)** - Juju storage configuration and management
- **[Backup and Recovery](how-to/backup-recovery.md)** - Data protection and disaster recovery
- **[Performance Tuning](how-to/performance-tuning.md)** - Optimize for high throughput and connections
- **[Troubleshoot Issues](how-to/troubleshoot.md)** - Diagnose and fix common problems
- **[Scale Deployment](how-to/scale-deployment.md)** - Horizontal and vertical scaling strategies

*Perfect when you need to solve a specific problem or accomplish a particular goal.*

### 💡 Explanation (Understanding-Oriented)

In-depth discussion of key topics and concepts:

- **[Security Model](explanation/security.md)** - Security architecture, threat analysis, and mitigations
- **[Architecture Overview](explanation/architecture.md)** - How the charm works internally
- **[MQTT Protocol Guide](explanation/mqtt-protocol.md)** - Understanding MQTT concepts and features
- **[Charm Design Principles](explanation/charm-design.md)** - Design decisions and patterns
- **[Performance Characteristics](explanation/performance.md)** - Understanding performance factors
- **[Integration Patterns](explanation/integration-patterns.md)** - How to integrate with other services

### 📊 Visual Diagrams

Comprehensive architectural diagrams and visual guides:

- **[Charm Architecture](diagrams/charm-architecture.md)** - Visual overview of charm components and flows
- **[Deployment Patterns](diagrams/deployment-patterns.md)** - Common deployment scenarios and scaling patterns

*Perfect when you need to understand the why behind the charm's design and behavior.*

### 📖 Reference (Information-Oriented)

Precise technical specifications and API documentation:

- **[Configuration Options](reference/configuration.md)** - Complete configuration reference
- **[Actions](reference/actions.md)** - Available charm actions and their usage
- **[Relations](reference/relations.md)** - Integration with other charms
- **[Storage Configuration](reference/storage.md)** - Juju storage options and requirements
- **[Files and Directories](reference/files.md)** - Important file locations
- **[CLI Commands](reference/cli.md)** - Juju command reference for this charm
- **[Metrics Reference](reference/metrics.md)** - Available Prometheus metrics
- **[Tracing Reference](reference/tracing.md)** - OpenTelemetry spans and events

*Perfect when you need to look up specific technical details or syntax.*

## Common Use Cases

### Enterprise IoT Platform
- Deploy secure MQTT broker with TLS and client certificates
- Configure for thousands of concurrent device connections
- Set up comprehensive monitoring and alerting
- Implement topic-based access control

### Real-Time Web Applications  
- Enable MQTT over WebSockets with TLS
- Integrate with browser-based real-time applications
- Configure for high-frequency messaging
- Monitor connection patterns and performance

### Microservices Architecture
- Use MQTT for reliable service-to-service messaging
- Configure topic-based routing and filtering
- Implement event-driven architectures
- Ensure message persistence and delivery guarantees

### Development & Testing
- Quick local MQTT broker setup with debugging
- Test MQTT applications and messaging patterns
- Validate security configurations
- Performance testing and optimization

### Edge Computing
- Deploy resilient MQTT brokers at edge locations
- Configure for intermittent connectivity
- Implement data buffering and synchronization
- Monitor edge device fleets

## Security Features

### Transport Security
- **TLS/SSL Encryption**: Automatic certificate management via Juju relations
- **Multiple TLS Ports**: Separate ports for standard and WebSocket TLS connections
- **Certificate Rotation**: Automated certificate lifecycle management

### Authentication & Authorization
- **Client Certificates**: X.509 certificate-based authentication
- **SASL Integration**: Enterprise authentication via SASL relations
- **ACL System**: Fine-grained topic-level access control
- **Anonymous Access Control**: Configurable with secure defaults

### Operational Security
- **Security Logging**: Comprehensive audit trails
- **Secure Defaults**: Production-ready security configuration
- **Network Isolation**: Juju network spaces support
- **Vulnerability Management**: Regular security updates

## Monitoring & Observability

### Metrics Collection
- **Prometheus Integration**: Built-in metrics endpoint
- **Service Health**: Broker status and availability metrics
- **Connection Metrics**: Active connections and performance data
- **Custom Metrics**: MQTT-specific operational metrics

### Distributed Tracing
- **OpenTelemetry**: Complete tracing integration
- **Charm Operations**: Installation, configuration, and lifecycle events
- **Workload Operations**: Backup, restore, and service management
- **Relation Events**: Certificate management and integration tracking

### Logging
- **Structured Logging**: JSON-formatted logs with context
- **Multiple Log Levels**: Configurable verbosity for debugging
- **Centralized Logs**: Integration with log aggregation systems
- **Security Events**: Audit logging for security-relevant events

## Getting Help

### Documentation Issues
If you find problems with this documentation:
- [Report documentation issues](https://github.com/canonical/mosquitto-operator/issues/new?labels=documentation)
- [Contribute improvements](../CONTRIBUTING.md)

### Charm Issues
For problems with the charm itself:
- [Report bugs](https://github.com/canonical/mosquitto-operator/issues/new?labels=bug)
- [Request features](https://github.com/canonical/mosquitto-operator/issues/new?labels=enhancement)
- [Get community support](https://discourse.charmhub.io/)

### Security Issues
For security vulnerabilities:
- See [Security Policy](../SECURITY.md) for responsible disclosure
- Use GitHub's private vulnerability reporting

## External Resources

### Mosquitto Resources
- [Official Mosquitto Documentation](https://mosquitto.org/documentation/)
- [MQTT 5.0 Specification](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)
- [Eclipse Mosquitto GitHub](https://github.com/eclipse/mosquitto)

### Juju Resources
- [Juju Documentation](https://juju.is/docs/)
- [Charm Development Guide](https://juju.is/docs/sdk)
- [Charmhub](https://charmhub.io/)

### MQTT Learning
- [MQTT Essentials](https://www.hivemq.com/mqtt-essentials/) - Comprehensive MQTT guide
- [MQTT Protocol Tutorial](https://mqtt.org/getting-started/) - Official getting started
- [MQTT Security Fundamentals](https://www.hivemq.com/blog/mqtt-security-fundamentals/)

### Security Resources
- [OWASP IoT Security](https://owasp.org/www-project-internet-of-things/) - IoT security best practices
- [TLS Best Practices](https://wiki.mozilla.org/Security/Server_Side_TLS) - Mozilla TLS guidelines
- [Certificate Management](https://letsencrypt.org/docs/) - Automated certificate management

## Contributing

We welcome contributions to both the charm and documentation:

1. **Documentation**: Help improve these docs by fixing errors, adding examples, or writing new guides
2. **Code**: Contribute to the charm implementation, tests, or tooling
3. **Testing**: Help test the charm in different environments and use cases
4. **Security**: Help identify and fix security issues
5. **Feedback**: Share your experience and suggest improvements

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed guidelines.

---

*This documentation is generated and maintained by the Mosquitto charm team. Last updated: 2025-08-03*