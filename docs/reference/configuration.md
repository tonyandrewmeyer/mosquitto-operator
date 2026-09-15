# Configuration options

Every option the charm accepts, as defined in
[`charmcraft.yaml`](../../charmcraft.yaml). Set them with `juju config`:

```shell
juju config mosquitto max-connections=20000
juju config mosquitto extra-config='
max_topic_alias 12
'
```

Invalid configuration puts the unit into blocked status with a message naming the
option, and the broker keeps running on its previous configuration until the
problem is fixed.

The **restart** column says what applying a change to that option costs:
*reload* leaves every client connected, *restart* disconnects all of them, and
*install* means package work as well. See
[Reload versus restart](../explanation/reload-versus-restart.md).

## Installation

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `install-source` | string | `archive` | install | Where Mosquitto comes from: `archive` (Ubuntu 24.04's 2.0.18, from `universe`, no standard security support), `ppa` (current 2.1.x from `ppa:mosquitto-dev/mosquitto-ppa`), or `snap` (current 2.1.x, strictly confined). Changing it migrates the broker's state to the new layout and restarts. |
| `package-channel` | string | `latest/stable` | install | The snap channel. Read only when `install-source` is `snap`. |

## Listeners

At least one listener must be enabled; a configuration where all four ports are 0
is rejected. No two of them, nor `metrics-port`, may share a port.

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `port` | int | `1883` | restart | The unencrypted MQTT port. 0 disables it, which is the right thing to do once TLS is in place — but the metrics exporter and the `broker-stats` action both need it. |
| `tls-port` | int | `8883` | restart | The MQTT-over-TLS port. 0 disables it. The listener only opens once the `certificates` integration has provided a certificate. |
| `websockets-port` | int | `0` | restart | MQTT over unencrypted WebSockets. 0 disables it. |
| `tls-websockets-port` | int | `0` | restart | MQTT over WebSockets with TLS. 0 disables it. Also waits for a certificate. |

## Security

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `allow-anonymous` | boolean | `false` | reload | Whether clients may connect without credentials. Leave it false. When true the charm still runs, but says so in the unit's status for as long as it is set. |
| `tls-version` | string | `tlsv1.2` | restart | The minimum TLS version accepted on the TLS listeners: `tlsv1.2` or `tlsv1.3`. |
| `require-client-certificate` | boolean | `false` | restart | Whether TLS clients must present a certificate signed by the same authority as the broker's own (mutual TLS). |
| `use-identity-as-username` | boolean | `false` | restart | Take the MQTT username from the client certificate's common name rather than from the CONNECT packet. Rejected without `require-client-certificate`, because there would be no certificate to take an identity from. |
| `certificate-common-name` | string | `""` | reload | The common name to request in the broker's certificate. Empty means the unit's fully qualified domain name. |
| `certificate-extra-sans-dns` | string | `""` | reload | Comma-separated additional DNS subject alternative names, on top of the unit's own hostname and addresses. Set this to the name clients actually connect to, where that differs. Changing any of the three makes the charm request a new certificate; writing the new one needs only a reload. |
| `certificate-organization` | string | `""` | reload | The organization name to request in the certificate. |

## Persistence

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `persistence` | boolean | `true` | reload | Whether sessions, queued messages and retained messages are written to disk so that they survive a restart. |
| `autosave-interval` | int | `300` | reload | Seconds between writes of the persistence database. Mosquitto's own default is 1800, which risks half an hour of messages on an unclean stop. |
| `persistent-client-expiration` | string | `14d` | reload | How long a disconnected persistent session is kept, as a number followed by `h`, `d`, `w` or `m`. Empty means never expire, which is Mosquitto's default and the usual cause of unbounded memory growth. |

## Limits

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `max-connections` | int | `1024` | restart | Concurrent client connections, or -1 for unlimited. Raises the service's file descriptor limit with it; see `open-file-limit`. |
| `max-inflight-messages` | int | `20` | reload | QoS 1 and 2 messages in flight to a single client at once. 0 means unlimited. |
| `max-queued-messages` | int | `1000` | reload | Outgoing QoS 1 and 2 messages queued per client while it is disconnected or over its inflight limit. Messages beyond this are dropped. |
| `max-queued-bytes` | int | `0` | reload | A byte ceiling on the per-client queue, alongside `max-queued-messages`. 0 disables the byte limit. |
| `max-packet-size` | int | `2000000` | reload | The largest MQTT packet accepted, in bytes. 0 means unlimited. Always written out explicitly, so moving between Mosquitto 2.0 and 2.1 does not silently change it. |
| `max-keepalive` | int | `65535` | reload | The largest keepalive interval, in seconds, a client may request. |
| `memory-limit` | int | `0` | reload | A ceiling on the broker's heap, in bytes. 0 means no limit. |
| `retain-available` | boolean | `true` | reload | Whether clients may set the retain flag on published messages. |
| `queue-qos0-messages` | boolean | `false` | reload | Whether QoS 0 messages are queued for disconnected clients. Off by default, matching MQTT's own expectations for QoS 0. |

## Logging and monitoring

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `log-level` | string | `notice` | reload | One of `error`, `warning`, `notice`, `information`, `debug`. Each level includes the ones above it; the charm expands it into the corresponding `log_type` directives. |
| `connection-messages` | boolean | `true` | reload | Whether each client connection and disconnection is logged. Useful, but noisy with many short-lived clients. |
| `sys-interval` | int | `10` | reload | Seconds between updates of the `$SYS` statistics tree. 0 disables `$SYS`, which also stops the metrics exporter. |
| `metrics-port` | int | `9234` | — | The port the charm's Prometheus exporter listens on. It binds to the unit's private address, and only runs while the `cos-agent` integration exists. Changing it restarts the exporter, not the broker. |

## Tuning

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `open-file-limit` | int | `0` | restart | The file descriptor limit for the broker service, as a systemd drop-in. 0 means the charm computes it: `max-connections + 1024`, with a floor of 4096, or 65536 when `max-connections` is -1. The packaged unit sets no limit at all, so an untuned broker refuses connections at around a thousand clients. Has no effect on a snap install, where snapd owns the unit. |
| `sysctl-tuning` | boolean | `true` | — | Whether to tune `net.core.somaxconn`, `net.ipv4.tcp_max_syn_backlog` and `net.core.netdev_max_backlog` for many connections. Where the kernel namespace forbids the write, which is common in containers, the charm logs a warning and carries on. Set it false on a host shared with other workloads. |

## Escape hatches

| Option | Type | Default | Applying it | Meaning |
| --- | --- | --- | --- | --- |
| `extra-config` | string | `""` | depends | Additional `mosquitto.conf` directives, one per line, written to a fragment the charm owns. What applying them costs depends on the directives: anything the charm does not know to be reload-safe is treated as needing a restart. |
| `bridge-topics` | string | `""` | restart | Topic directives for the bridge to the broker on the `upstream` integration, one per line: `topic <pattern> [in\|out\|both] [local_prefix] [remote_prefix]`. Ignored when `upstream` is not integrated. Empty means the bridge forwards nothing, and the unit's status says so. |

### Directives `extra-config` will not accept

The charm rejects a fragment that sets any directive it manages itself, and the
unit goes to blocked rather than running a configuration the charm cannot reason
about:

`acl_file`, `allow_anonymous`, `auth_plugin`, `bind_address`, `bind_interface`,
`global_plugin`, `listener`, `password_file`, `per_listener_settings`, `plugin`,
`port`, `user`.

The dangerous pair is `listener` and `allow_anonymous`: with no listener defined
at all, Mosquitto 2.x permits anonymous access on loopback, so a fragment that
removed the charm's listener would silently re-enable it. Use the matching charm
options instead.

## Related

- [Actions](actions.md)
- [How the charm decides what a configuration change requires](../explanation/configuration-changes.md)
