# Mosquitto Charm Documentation

Welcome to the documentation for the Mosquitto MQTT broker charm. This documentation follows the [Diátaxis](https://diataxis.fr/) approach, providing four types of documentation to serve different needs.

## Quick Start

New to the Mosquitto charm? Start with our tutorial:

🚀 **[Getting Started Tutorial](tutorial/getting-started.md)** - Learn by deploying your first Mosquitto broker

## Documentation Types

### 📚 Tutorials (Learning-Oriented)

Step-by-step guides that help you learn by doing:

- **[Getting Started](tutorial/getting-started.md)** - Deploy your first Mosquitto broker and test MQTT messaging

*Perfect for newcomers who want to understand what the charm does and how it works.*

### 🛠️ How-To Guides (Problem-Oriented)

Practical guides for accomplishing specific tasks:

- **[Deploy for Production](how-to/deploy-production.md)** - Production deployment with security, monitoring, and HA
- **[Performance Tuning](how-to/performance-tuning.md)** - Optimize Mosquitto for your workload
- **[Secure Mosquitto](how-to/secure-mosquitto.md)** - Security hardening and best practices
- **[Monitor Mosquitto](how-to/monitor-mosquitto.md)** - Set up monitoring and alerting
- **[Troubleshoot Issues](how-to/troubleshoot.md)** - Diagnose and fix common problems
- **[Backup and Restore](how-to/backup-restore.md)** - Data protection strategies
- **[Scale Mosquitto](how-to/scale-mosquitto.md)** - Horizontal and vertical scaling

*Perfect when you need to solve a specific problem or accomplish a particular goal.*

### 💡 Explanation (Understanding-Oriented)

In-depth discussion of key topics and concepts:

- **[Security Model](explanation/security.md)** - Security architecture, risks, and mitigations
- **[Architecture Overview](explanation/architecture.md)** - How the charm works internally
- **[MQTT Protocol Guide](explanation/mqtt-protocol.md)** - Understanding MQTT concepts
- **[Charm Design](explanation/charm-design.md)** - Design decisions and patterns
- **[Performance Characteristics](explanation/performance.md)** - Understanding performance factors

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
- **[Files and Directories](reference/files.md)** - Important file locations
- **[CLI Commands](reference/cli.md)** - Juju command reference for this charm

*Perfect when you need to look up specific technical details or syntax.*

## Common Use Cases

### IoT Applications
- Deploy MQTT broker for device communication
- Configure for high connection counts
- Set up monitoring for device fleets

### Web Applications  
- Enable MQTT over WebSockets
- Integrate with real-time web apps
- Configure for browser-based clients

### Microservices
- Use MQTT for service-to-service messaging
- Configure topic-based routing
- Implement event-driven architectures

### Development & Testing
- Quick local MQTT broker setup
- Debug MQTT applications
- Test messaging patterns

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

## Contributing

We welcome contributions to both the charm and documentation:

1. **Documentation**: Help improve these docs by fixing errors, adding examples, or writing new guides
2. **Code**: Contribute to the charm implementation, tests, or tooling
3. **Testing**: Help test the charm in different environments and use cases
4. **Feedback**: Share your experience and suggest improvements

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed guidelines.

---

*This documentation is generated and maintained by the Mosquitto charm team. Last updated: $(date +%Y-%m-%d)*