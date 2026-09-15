# Mosquitto

[Eclipse Mosquitto](https://mosquitto.org/) is a lightweight open-source MQTT
broker. This charm installs and operates Mosquitto on a machine: it renders
`mosquitto.conf` from Juju config, manages MQTT users and topic permissions,
obtains TLS certificates from a certificate authority charm, exports broker
metrics to Prometheus, and distinguishes a change that needs a reload from one
that needs a restart, so most reconfiguration does not drop a client connection.

## Two things to know before you adopt it

**Mosquitto does not cluster, so this charm runs exactly one unit.** There is no
state replication between Mosquitto processes: no shared sessions, no shared
retained messages, no shared subscriptions. Two units would be two unrelated
brokers, and a client that reconnected to the other one would find its session
and retained state gone. `juju add-unit` therefore puts the application into
blocked status. Where you need more than one broker, integrate two Mosquitto
applications with each other to build a **bridge**, which forwards selected
topics between them — that is how hub-and-spoke and edge-to-central topologies
are built. Above roughly 50,000 connections, or where you need genuine high
availability, a clustering broker such as EMQX or VerneMQ is the honest answer.
See [Why one unit](docs/explanation/one-unit-and-bridging.md).

**The default `install-source: archive` gives you Ubuntu 24.04's Mosquitto
2.0.18, from `universe`, which has no standard Ubuntu security support.** The
archive build is missing the fixes for CVE-2024-3935 and CVE-2024-10525, and the
charm refuses to configure a bridge on it for that reason. There are two
answers: set `install-source: ppa` to install current 2.1.x releases from
`ppa:mosquitto-dev/mosquitto-ppa`, or attach **Ubuntu Pro** to the machine, whose
ESM Apps stream carries the patched 2.0.18 build. See
[Upgrade and change install source](docs/how-to/upgrade-and-change-install-source.md).

## Get started

You need a Juju 3.6 or later controller on a machine cloud (LXD is enough), and
`charmcraft` to build the charm. The charm is not published on Charmhub yet, so
build it from this repository:

```shell
charmcraft pack
juju deploy ./mosquitto_*.charm
juju run mosquitto/0 set-password username=alice
```

That gives you a broker listening on port 1883 with anonymous access off, and
one user whose generated password is returned as a Juju secret. Grant it a topic
and it is ready to use:

```shell
juju run mosquitto/0 grant username=alice topic='sensors/#'
juju run mosquitto/0 health-check
```

The [tutorial](TUTORIAL.md) walks through the same ground in full, including
publishing and subscribing for real and adding TLS.

## Integrations

| Endpoint | Interface | Role | Purpose |
| --- | --- | --- | --- |
| `mqtt` | `mqtt` | provides | Give a related application its own MQTT user, password and topic permissions. |
| `cos-agent` | `cos_agent` | provides | Send metrics, logs, dashboards and alert rules to the Canonical Observability Stack. |
| `certificates` | `tls-certificates` | requires | Obtain a server certificate, which enables the TLS listeners. |
| `upstream` | `mqtt` | requires | Bridge this broker to another Mosquitto application. |
| `charm-tracing` | `tracing` | requires | Send charm execution traces to Tempo. |
| `receive-ca-cert` | `certificate_transfer` | requires | The authority certificate for talking to the tracing endpoint over TLS. |

All four `requires` endpoints are optional. The full definitions, with the
config options and actions, are in [`charmcraft.yaml`](charmcraft.yaml).

## Learn more

- [Documentation](docs/index.md) — tutorial, how-to guides, reference and explanation
- [Tutorial](TUTORIAL.md)
- [`charmcraft.yaml`](charmcraft.yaml) — the authoritative config, action and integration definitions
- [WORKLOAD.md](WORKLOAD.md) — what we learnt about operating Mosquitto itself
- [DESIGN.md](DESIGN.md) — the charm's shape, and why
- [Mosquitto documentation](https://mosquitto.org/documentation/)
- [Juju documentation](https://documentation.ubuntu.com/juju/)

## Project and community

- [Issues](https://github.com/tonyandrewmeyer/mosquitto-operator/issues)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Code of conduct](.github/CODE_OF_CONDUCT.md)

## Licence

The charm is licensed under Apache-2.0; see [LICENSE](LICENSE). Mosquitto itself
is distributed under the Eclipse Public License 2.0 and the Eclipse Distribution
License 1.0. Eclipse and Mosquitto are trademarks of the Eclipse Foundation.
