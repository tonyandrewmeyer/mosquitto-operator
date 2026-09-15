# Reload versus restart

Mosquitto re-reads most of its configuration on SIGHUP, and `systemctl reload
mosquitto` sends exactly that. A reload leaves every client connected. A restart
disconnects all of them.

That difference is user-visible in a way that most charm internals are not, which
is why the charm goes to some trouble to tell the two apart instead of restarting
whenever anything changes.

## What a restart actually costs clients

Mosquitto has no drain mode and does not implement the MQTT 5 server-redirect
DISCONNECT, so a stop is abrupt from every client's point of view. What that
means depends on the client:

- Any message in flight at QoS 0 is gone. There is no acknowledgement and no
  retry.
- Clients with `clean_session` true lose their subscriptions and must resubscribe
  when they reconnect.
- Clients reconnect on their own schedules, and a fleet of them reconnecting at
  once is a thundering herd on a single-threaded broker.
- Every client's last will is published, so anything watching those topics sees a
  wave of spurious "device offline" messages.

None of that is catastrophic, and a restart is sometimes unavoidable. But it is a
real cost, and paying it for a change to the logging level would be silly.

## Where the line falls

Roughly: **security and behaviour are reloadable, sockets are not.**

Reloadable, so no client is disconnected:

- the password file and the ACL file — so every `set-password`, `grant`, `revoke`
  and `remove-user` takes effect immediately without disconnecting anybody;
- `allow_anonymous`;
- persistence settings, including `autosave_interval` and
  `persistent_client_expiration`;
- the queueing and inflight limits, `max_packet_size`, `max_keepalive`,
  `memory_limit`, `retain_available`, `queue_qos0_messages`;
- logging: `log_type`, `log_dest`, `connection_messages`, timestamps;
- `sys_interval`.

SIGHUP also re-reads the *contents* of the TLS certificate and key files. So a
certificate renewal at unchanged paths needs only a reload — which matters,
because renewals happen on the authority's schedule rather than yours.

Needing a restart:

- anything to do with a listener: adding or removing one, changing its port,
  address, protocol or `max_connections`;
- the TLS options themselves — `require_certificate`, `tls_version`,
  `use_identity_as_username` and the certificate file *paths*, as opposed to
  their contents;
- the user the broker runs as, plugins, and the packet buffer size.

So integrating a certificate authority restarts the broker once, when the TLS
listener appears; renewing that certificate afterwards does not.

## The honest caveats

Two of them.

First, `systemctl reload` is asynchronous, and it succeeds even when the broker
then rejects the configuration it was asked to re-read. The return code proves
nothing. The charm therefore health-checks afterwards with a real MQTT round
trip, and reports a blocked unit with the broker's own complaint if that fails.

Second, the charm is more conservative than Mosquitto is. Anything it does not
positively know to be reload-safe is restarted, because the reload-safe list
differs between Mosquitto 2.0 and 2.1 and an unnecessary restart is a much
smaller problem than a broker still running yesterday's configuration while the
charm reports success. The visible consequence is bridges: Mosquitto adds,
removes and restarts bridge connections on a reload, but the charm restarts for
them.

## Seeing it for yourself

The broker's main PID is the tell. A reload keeps it; a restart changes it.

```shell
juju exec --unit mosquitto/0 -- systemctl show mosquitto -p MainPID --value
juju config mosquitto sys-interval=20
juju exec --unit mosquitto/0 -- systemctl show mosquitto -p MainPID --value
```

## Related

- [How the charm decides what a configuration change requires](configuration-changes.md)
- [Configuration options](../reference/configuration.md) — the *Applying it* column
