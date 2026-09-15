# Integrations

Every endpoint the charm declares, as defined in
[`charmcraft.yaml`](../../charmcraft.yaml). All four `requires` endpoints are
optional; the broker runs without any of them.

## Provided

### `mqtt` (interface `mqtt`)

Offer MQTT credentials and topic permissions to related applications. Each
related application gets its own user, its own password in a Juju secret, and
only the topic permissions it asked for.

```shell
juju integrate mosquitto:mqtt my-application
```

The requirer publishes the topic filters and access it wants; the charm creates a
user named `<application>-<relation id>`, installs the matching ACL entries, and
publishes the listeners to connect to, the authority certificate when any
endpoint is TLS, and the URI of a secret holding the username and password.
Credentials are never written to a databag. When the relation goes away, the user
and the secret go with it.

One kind of request is always refused: a filter under `$SYS`, which would expose
every client ID and topic count on the broker. The charm grants the rest and the
requirer sees the narrower `granted-permissions` it actually got.

The full contract, including the databag fields on both sides, is in
[`docs/interfaces/mqtt/v0/README.md`](../interfaces/mqtt/v0/README.md).

### `cos-agent` (interface `cos_agent`)

Send metrics, logs, dashboards and alert rules to the Canonical Observability
Stack through a machine subordinate — `opentelemetry-collector`, or the
end-of-life `grafana-agent`.

```shell
juju integrate mosquitto:cos-agent opentelemetry-collector:cos-agent
```

The charm publishes one scrape job for its own exporter on `metrics-port`, the
alert rules from `src/prometheus_alert_rules/`, and the dashboard from
`src/grafana_dashboards/`. The exporter itself only runs while this integration
exists. See [Metrics and alert rules](metrics.md).

## Required

### `certificates` (interface `tls-certificates`, limit 1)

Obtain a server certificate from a certificate authority charm, such as
`self-signed-certificates` or `vault`, to serve the TLS listeners.

```shell
juju integrate mosquitto:certificates self-signed-certificates
```

The certificate is requested per unit, with the unit's fully qualified domain
name as the common name and its hostname and addresses as subject alternative
names, plus anything in `certificate-extra-sans-dns`. Until one is issued, the
TLS listeners do not exist. See [Enable TLS](../how-to/enable-tls.md).

### `upstream` (interface `mqtt`, limit 1)

Bridge this broker to another Mosquitto application, forwarding the topics named
in `bridge-topics`. This is how hub-and-spoke and edge-to-central topologies are
built, since Mosquitto does not cluster.

```shell
juju integrate mosquitto-edge:upstream mosquitto-central:mqtt
```

The charm is the requirer here: it asks the upstream broker for the permissions
implied by `bridge-topics`, and renders a `connection` block using the
credentials it is given. It refuses to configure a bridge on Mosquitto older than
2.0.19. See [Bridge two brokers](../how-to/bridge-two-brokers.md).

### `charm-tracing` (interface `tracing`, limit 1)

Send charm execution traces to a Tempo-backed tracing provider. These are traces
of the charm's own hooks, not of MQTT traffic.

### `receive-ca-cert` (interface `certificate_transfer`, limit 1)

Receive the certificate authority certificate needed to talk to the tracing
endpoint over TLS.

## Peer

### `mosquitto-peers` (interface `mosquitto-peers`)

Not something you integrate. The charm uses the peer relation's application
databag to hold the list of managed users and their permissions, and which
install layout the broker's state is currently in, and the unit databag to record
whether the broker is paused. It is also how the charm notices that a second unit
has been added, which it refuses.

## Ports

The charm does not declare opened ports to Juju, so `juju expose` does not open
the listeners. On a cloud that firewalls machines, open `port`, `tls-port` and
any WebSockets ports yourself if clients connect from outside the model.

## Related

- [Configuration options](configuration.md)
- [The `mqtt` interface](../interfaces/mqtt/v0/README.md)
