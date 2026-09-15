# Integrate with COS for metrics, logs and dashboards

Mosquitto has no Prometheus endpoint. It publishes its statistics to the
`$SYS/broker/#` topic tree every `sys-interval` seconds instead. The charm ships
a small exporter that subscribes to that tree and serves it as Prometheus text,
and sends the scrape job, alert rules and a dashboard to the Canonical
Observability Stack through a collector subordinate.

## Deploy a collector alongside the broker

The subordinate is `opentelemetry-collector`; the machine `grafana-agent` charm
it replaced is end of life. Either works, because the charm's side of the
`cos_agent` interface is the same.

```shell
juju deploy opentelemetry-collector --channel 0.130/stable
juju integrate mosquitto:cos-agent opentelemetry-collector:cos-agent
```

The collector stays blocked until it has somewhere to send telemetry, which is
the next step. The broker itself goes active regardless.

## Point the collector at COS

COS normally lives in its own model, so integrate across the model boundary:

```shell
juju switch cos
juju offer prometheus:receive-remote-write
juju offer loki:logging
juju offer grafana:grafana-dashboard

juju switch mqtt
juju integrate opentelemetry-collector cos.prometheus
juju integrate opentelemetry-collector cos.loki
juju integrate opentelemetry-collector cos.grafana
```

Adjust the application names to match your COS deployment. The Juju documentation
covers [cross-model
relations](https://documentation.ubuntu.com/juju/latest/howto/manage-relations/)
in full.

## What you get

- **Metrics.** The exporter publishes the `$SYS` tree under the metric names
  `sapcc/mosquitto-exporter` uses, so dashboards written for that exporter work
  unchanged. See [Metrics and alert rules](../reference/metrics.md).
- **Logs.** The broker logs to `/var/log/mosquitto/mosquitto.log`, which the
  collector scrapes. The charm deliberately does not log to syslog:
  `opentelemetry-collector` has no journald receiver.
- **Alert rules.** Nine rules, led by one on `broker_publish_messages_dropped`,
  which is the only metric that directly means lost data.
- **A dashboard**, shipped with the charm rather than fetched from
  grafana.com.

## When the exporter runs

The charm starts the exporter only when all three of these hold, and removes it
otherwise:

- there is a `cos-agent` integration;
- `sys-interval` is not 0, so there is something to read; and
- `port` is not 0, because the exporter reads `$SYS` over the plaintext listener
  on loopback.

It authenticates as the charm's own `_charm_metrics` user, whose only permission
is `read $SYS/#`, and binds to `127.0.0.1` on `metrics-port` (9234 by default) —
which is where the collector scrapes it from, being a subordinate on the same
machine, and the only place the `$SYS` tree should be readable. The password
reaches it as a systemd credential, not as a command-line argument.

Check it:

```shell
juju exec --unit mosquitto/0 -- systemctl is-active mosquitto-charm-exporter
juju exec --unit mosquitto/0 -- curl -sS http://localhost:9234/metrics | head
```

`curl` to `localhost` only works if the exporter happens to have bound there; use
the unit's address from `juju status` otherwise.

## Without COS

For an occasional look at the same numbers, with nothing deployed:

```shell
juju run mosquitto/0 broker-stats
```

That returns the whole `$SYS` tree as JSON, read through the same user.

## Tracing

The charm's own execution traces go to a Tempo-backed provider:

```shell
juju integrate mosquitto:charm-tracing tempo
juju integrate mosquitto:receive-ca-cert tempo
```

The second integration supplies the authority certificate needed to reach the
tracing endpoint over TLS. These are traces of the charm, not of MQTT traffic.

## Related

- [Metrics and alert rules](../reference/metrics.md)
- [Integrations reference](../reference/integrations.md)
