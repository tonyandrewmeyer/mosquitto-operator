# Metrics and alert rules

Mosquitto has no Prometheus endpoint; it publishes statistics to the
`$SYS/broker/#` topic tree every `sys-interval` seconds. The charm ships a small
Python exporter that subscribes to that tree and serves it as Prometheus text on
`metrics-port` (9234 by default), bound to `127.0.0.1`.

Loopback is where it is scraped from: the COS machine collector is a subordinate
on the same machine, and the scrape target the `cos_agent` library builds for it
is `localhost:<metrics-port>`. Nothing off the unit has any business reading the
`$SYS` tree, which names every client id and every topic count on the broker.

The metric names are those of
[`sapcc/mosquitto-exporter`](https://github.com/sapcc/mosquitto-exporter), so
dashboards written for that exporter work unchanged.

The exporter runs only while the `cos-agent` integration exists, `sys-interval`
is not 0, and the plaintext listener is enabled — it reads `$SYS` over loopback,
authenticating as the charm's `_charm_metrics` user, whose only permission is
`read $SYS/#`.

## Counters

Monotonic totals since the broker started, so these are the ones to use with
`rate()` and `increase()`.

| Metric | `$SYS` topic | Meaning |
| --- | --- | --- |
| `broker_bytes_received` | `bytes/received` | Bytes received. |
| `broker_bytes_sent` | `bytes/sent` | Bytes sent. |
| `broker_messages_received` | `messages/received` | MQTT messages of any type received. |
| `broker_messages_sent` | `messages/sent` | MQTT messages of any type sent. |
| `broker_publish_bytes_received` | `publish/bytes/received` | PUBLISH bytes received. |
| `broker_publish_bytes_sent` | `publish/bytes/sent` | PUBLISH bytes sent. |
| `broker_publish_messages_received` | `publish/messages/received` | PUBLISH messages received. |
| `broker_publish_messages_sent` | `publish/messages/sent` | PUBLISH messages sent. |
| `broker_publish_messages_dropped` | `publish/messages/dropped` | PUBLISH messages dropped for inflight or queueing limits. **Any non-zero rate is data loss.** |
| `broker_uptime` | `uptime` | Seconds since the broker started. A reset means it restarted. |
| `broker_clients_maximum` | `clients/maximum` | The most clients connected simultaneously. |
| `broker_clients_total` | `clients/total` | Connected and disconnected clients the broker knows about. |

## Gauges

| Metric | `$SYS` topic | Meaning |
| --- | --- | --- |
| `broker_clients_connected` | `clients/connected` | Currently connected clients. Compare with `max-connections`. |
| `broker_clients_disconnected` | `clients/disconnected` | Disconnected persistent clients whose session is still held. Steady growth is the memory-leak leading indicator. |
| `broker_clients_expired` | `clients/expired` | Sessions expired and removed through `persistent-client-expiration`. |
| `broker_messages_stored` | `messages/stored` | Messages in the message store. |
| `broker_store_messages_count` | `store/messages/count` | Messages in the message store. |
| `broker_store_messages_bytes` | `store/messages/bytes` | Bytes held by message payloads in the store. |
| `broker_retained_messages_count` | `retained messages/count` | Retained messages. Note the space in the topic name; it is not a typo. |
| `broker_subscriptions_count` | `subscriptions/count` | Active subscriptions. |
| `broker_shared_subscriptions_count` | `shared_subscriptions/count` | Active shared subscription groups. |
| `broker_heap_current` | `heap/current` | Heap in use, in bytes. |
| `broker_heap_maximum` | `heap/maximum` | The largest heap used so far, in bytes. |

## Load averages

For each of `messages_received`, `messages_sent`, `publish_received`,
`publish_sent`, `publish_dropped`, `bytes_received`, `bytes_sent`, `connections`
and `sockets`, in `1min`, `5min` and `15min` variants:

```
broker_load_<family>_<window>
```

For example `broker_load_publish_dropped_5min` and
`broker_load_connections_1min`. These are moving averages per minute. The window
is part of the name rather than a label, because that is what sapcc's exporter
does and what existing dashboards expect.

## The exporter's own metrics

| Metric | Meaning |
| --- | --- |
| `mosquitto_up` | 1 while `$SYS` messages are arriving, 0 once nothing has arrived for three `sys-interval` periods (60 seconds at the default, and never less). |
| `mosquitto_broker_info` | Always 1, carrying the broker version in a `version` label. |
| `mosquitto_bridge_state` | Per bridge, from `$SYS/broker/connection/<name>/state`: 1 up, 0 down, with the bridge name in a `bridge` label. |
| `mosquitto_exporter_build_info` | Always 1, carrying the exporter version in a `version` label. |
| `mosquitto_max_connections` | The configured `max-connections`, so that alerts can be written against the limit in force rather than against a number. Absent when `max-connections` is -1. |

Deliberately not exported: `$SYS/broker/timestamp` (a build string),
`$SYS/broker/clients/active` and `$SYS/broker/clients/inactive` (deprecated
aliases that would double-count), and the `$SYS/broker/log/` subtree (free text,
which belongs in Loki).

## Alert rules

Shipped in `src/prometheus_alert_rules/mosquitto.rules.yaml` and published over
`cos-agent`. COS injects the Juju topology labels, so the expressions carry no
model or application matchers.

| Alert | Expression | For | Severity |
| --- | --- | --- | --- |
| `MosquittoMessagesDropped` | `rate(broker_publish_messages_dropped[5m]) > 0` | 5m | critical |
| `MosquittoDown` | `mosquitto_up == 0` | 2m | critical |
| `MosquittoExporterDown` | `up == 0` | 5m | warning |
| `MosquittoRestarted` | `resets(broker_uptime[15m]) > 0` | 5m | warning |
| `MosquittoConnectionsNearLimit` | `broker_clients_connected / mosquitto_max_connections > 0.85` | 10m | warning |
| `MosquittoDisconnectedSessionsGrowing` | `deriv(broker_clients_disconnected[6h]) > 0.01 and broker_clients_disconnected > 1000` | 1h | warning |
| `MosquittoRetainedMessagesGrowing` | `deriv(broker_retained_messages_count[24h]) > 0.05 and broker_retained_messages_count > 10000` | 2h | warning |
| `MosquittoHeapGrowing` | `deriv(broker_heap_current[6h]) > 1e4 and broker_heap_current > 5e8` | 30m | warning |
| `MosquittoBridgeDown` | `mosquitto_bridge_state == 0` | 5m | critical |

Each rule's annotations say what to do about it. One threshold still assumes a
default and wants retuning if you change it: `MosquittoHeapGrowing` assumes a
broker whose normal heap is well under 500 MB. `MosquittoConnectionsNearLimit`
follows `max-connections` on its own, because the exporter publishes the
configured limit alongside the connection count.

`MosquittoMessagesDropped` is the one that matters most: it is the only metric
that directly means data has been lost, rather than that something might go wrong
later.

## Dashboard

One Grafana dashboard is shipped in `src/grafana_dashboards/mosquitto.json` and
published over the same integration, rather than relying on a community
dashboard fetched by ID.

## Related

- [Integrate with COS](../how-to/integrate-with-cos.md)
- [Tune for many connections](../how-to/tune-for-many-connections.md)
