# Tune for many connections

Mosquitto is a single-threaded process and each connected client costs one file
descriptor. Two limits bite long before the broker runs out of memory: the file
descriptor ceiling, and the kernel's socket backlogs. The charm manages both, but
the defaults are sized for a broker with a thousand clients, not tens of
thousands.

## Raise the connection limit

```shell
juju config mosquitto max-connections=20000
```

The default is 1024; `-1` means unlimited. This is a `max_connections` change,
which Mosquitto cannot pick up on a reload, so the broker restarts and every
client reconnects. Plan it accordingly.

Raising `max-connections` raises the file descriptor limit with it: with
`open-file-limit` left at its default of 0, the charm computes
`max-connections + 1024`, with a floor of 4096, and 65536 when `max-connections`
is `-1`. It writes that as a systemd drop-in, which is the only thing that works
for a service — `/etc/security/limits.conf` has no effect on one.

This matters more than it sounds. The packaged unit sets no `LimitNOFILE` at all,
so an untuned Mosquitto inherits 1024 and starts refusing connections at around a
thousand clients with `Too many open files`. It is the single most common
Mosquitto production failure.

To pin the limit yourself, for instance because something else on the host
constrains it:

```shell
juju config mosquitto open-file-limit=65536
```

Check what the service actually has:

```shell
juju exec --unit mosquitto/0 -- systemctl show mosquitto -p LimitNOFILE --value
```

## Kernel networking

`sysctl-tuning` is on by default and sets four values sized for a broker holding
many sockets:

| Parameter | Value |
| --- | --- |
| `net.core.somaxconn` | 4096 |
| `net.ipv4.tcp_max_syn_backlog` | 4096 |
| `net.core.netdev_max_backlog` | 4096 |

These are host-wide, so on a machine shared with other workloads you may not want
them:

```shell
juju config mosquitto sysctl-tuning=false
```

That also removes the charm's existing settings.

Inside an unprivileged container the kernel namespace usually forbids the write.
The charm logs a warning and carries on rather than failing the hook: the broker
works, it simply will not reach the connection counts the tuning is for. You will
see this in `juju debug-log` on LXD.

## Queues, memory and dropped messages

Connection count is only half of it. The other half is what the broker holds for
clients that are slow or away:

| Option | Default | What it caps |
| --- | --- | --- |
| `max-inflight-messages` | 20 | QoS 1 and 2 messages in flight to one client. |
| `max-queued-messages` | 1000 | Messages queued per client while it is disconnected or over its inflight limit. |
| `max-queued-bytes` | 0 (off) | A byte ceiling on the same queue. |
| `memory-limit` | 0 (off) | A ceiling on the broker's heap. |
| `max-packet-size` | 2000000 | The largest packet accepted. |

Messages beyond `max-queued-messages` are **dropped**, and that is real data
loss. Watch `broker_publish_messages_dropped`; the charm ships an alert on it.
Raising the limits moves the problem into memory rather than solving it, so find
the slow subscriber first.

All five of these are reload-safe, so changing them does not disconnect anybody.

## Expire sessions you will never see again

```shell
juju config mosquitto persistent-client-expiration=14d
```

This is the charm's default, and it differs from Mosquitto's, which is never to
expire. A fleet of clients that connect with a fresh client ID each time and
`clean_session` false leaves a durable session behind every time, each holding
subscriptions and queued messages for ever. That is the classic Mosquitto memory
leak, and `broker_clients_disconnected` climbing steadily is its leading
indicator.

The value is a number followed by `h`, `d`, `w` or `m`. An empty string means
never expire.

## Rough sizing

An idle connected client costs a few hundred bytes to a few kilobytes of heap, so
tens of thousands of idle clients fit in a couple of gigabytes. Throughput is
bounded by a single core, because the broker is single-threaded. Above roughly
50,000 connections, a broker that scales horizontally — EMQX, VerneMQ, NanoMQ —
is the honest answer; see
[Why one unit](../explanation/one-unit-and-bridging.md).

## Related

- [Configuration reference](../reference/configuration.md)
- [Metrics and alert rules](../reference/metrics.md)
