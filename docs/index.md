# Mosquitto charm documentation

[Eclipse Mosquitto](https://mosquitto.org/) is a lightweight open-source MQTT
broker, implementing MQTT 5.0, 3.1.1 and 3.1. This charm installs and operates it
on a machine: it renders the broker configuration from Juju config, manages MQTT
users and topic permissions, obtains TLS certificates from a certificate
authority charm, exports broker metrics to Prometheus, and knows which
configuration changes need only a reload rather than a restart.

Two structural facts shape everything else here, and are worth knowing before you
start:

- **Mosquitto does not cluster**, so the charm runs exactly one unit. More than
  one broker means a bridge between two Mosquitto applications. See
  [Why one unit, and what bridging gives you](explanation/one-unit-and-bridging.md).
- **The default install source is the Ubuntu 24.04 archive**, which carries
  Mosquitto 2.0.18 from `universe` with no standard security support. See
  [Upgrade and change install source](how-to/upgrade-and-change-install-source.md).

## Documentation

| Section | What it is for |
| --- | --- |
| [Tutorial](tutorial/getting-started.md) | A single session, start to finish: deploy, create a user, publish and subscribe, add TLS, tidy up. |
| [How-to guides](how-to/index.md) | Task-focused instructions for a broker you already have. |
| [Reference](reference/index.md) | Config options, actions, integrations, metrics and file layout. |
| [Explanation](explanation/index.md) | Why the charm is shaped the way it is. |

## In the repository

- [`charmcraft.yaml`](../charmcraft.yaml) — the authoritative definitions of every
  config option, action and integration.
- [WORKLOAD.md](../WORKLOAD.md) — research notes on operating Mosquitto itself.
- [DESIGN.md](../DESIGN.md) — the charm's design and the reasoning behind it.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — building, testing and contributing.
- [`docs/interfaces/mqtt/v0/`](interfaces/mqtt/v0/README.md) — the `mqtt` relation
  interface contract.
