# Actions

The twelve actions the charm defines, as declared in
[`charmcraft.yaml`](../../charmcraft.yaml). Run them with:

```shell
juju run mosquitto/0 <action> [param=value …]
```

Actions marked **leader only** change state the whole application shares, and
fail with a message saying so if run on a non-leader unit. With one unit — which
is all this charm allows — that unit is always the leader.

## User and permission management

### `set-password`

Create an MQTT user, or change an existing user's password. **Leader only.**

| Parameter | Type | Required | Meaning |
| --- | --- | --- | --- |
| `username` | string | yes | The MQTT username. |
| `password` | string | no | The password to set. Omit to have one generated. |

| Result | Meaning |
| --- | --- |
| `username` | The user that was created or changed. |
| `secret-id` | The Juju secret holding `{username, password}`. Read it with `juju show-secret --reveal <id>`. |
| `generated` | `true` if the charm generated the password, `false` if you supplied one. |

The password is never in the results, because action results are visible to
anyone who can read the model's operation log. Usernames may not contain a colon
or a line break, and may not begin with an underscore, which is reserved for the
charm's own users. A supplied password may not contain a line break either: the
password file is one user per line, and one the broker cannot parse breaks
authentication for everybody.

### `remove-user`

Remove an MQTT user, all of its topic permissions, and its Juju secret.
**Leader only.**

| Parameter | Type | Required | Meaning |
| --- | --- | --- | --- |
| `username` | string | yes | The MQTT username. |

| Result | Meaning |
| --- | --- |
| `removed` | The user that was removed. |

Fails if there is no such user, and fails for a user that came from an `mqtt`
integration: the request is still on the relation, so the next reconciliation
would create it again. Remove the integration instead.

### `list-users`

List the MQTT users the charm manages and their topic permissions. Passwords are
never returned, and the charm's own internal users are not listed.

No parameters.

| Result | Meaning |
| --- | --- |
| `users` | JSON: each username mapped to its `owner` (`action`, or `relation:<id>`) and its `acl`, a list of `[topic, access]` pairs. |
| `count` | How many users there are. |

### `grant`

Grant a user access to a topic filter. **Leader only.**

| Parameter | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `username` | string | yes | | The MQTT username. |
| `topic` | string | yes | | The topic filter, in MQTT syntax: `+` matches one level, `#` matches the rest. `#` does not match the `$SYS` tree. |
| `access` | string | no | `readwrite` | One of `read`, `write`, `readwrite`, `deny`. |

| Result | Meaning |
| --- | --- |
| `username` | The user that was changed. |
| `acl` | JSON: the user's permissions after the grant. |

Granting a topic the user already has replaces the earlier access rather than
adding a second rule. Fails if there is no such user.

### `revoke`

Remove a topic permission from a user. **Leader only.**

| Parameter | Type | Required | Meaning |
| --- | --- | --- | --- |
| `username` | string | yes | The MQTT username. |
| `topic` | string | yes | The topic filter to stop granting. |

| Result | Meaning |
| --- | --- |
| `username` | The user that was changed. |
| `acl` | JSON: the user's remaining permissions. |

Fails if the user has no permission for that topic.

## Inspection

### `health-check`

Check that the broker is really serving MQTT, by connecting, subscribing,
publishing a message to a private topic and reading it back at QoS 1. A broker
can accept TCP connections while being unable to serve any of them, so this is a
real round trip rather than a port check.

The WebSocket listeners are checked differently: the Mosquitto client tools speak
MQTT over TCP only, so those go as far as the HTTP upgrade Mosquitto answers for
`mqtt` rather than through a round trip. That still catches a build without
WebSocket support, a listener that is not up, and TLS material the broker cannot
read.

Listeners that are not configured are skipped, so `all` on a plaintext-only
deployment checks only the plaintext listener. Asking for a TLS listener that has
no certificate yet fails, rather than passing quietly.

| Parameter | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `listener` | string | no | `all` | Which listener to check: `plain`, `tls`, `websockets`, `websockets-tls` or `all`. |

| Result | Meaning |
| --- | --- |
| `plain` | `ok: …` or `failed: …` for the plaintext listener. |
| `tls` | The same for the TLS listener. |
| `websockets` | The same for the plaintext WebSocket listener. |
| `websockets-tls` | The same for the WebSocket-over-TLS listener. |

Only the listeners that exist are checked: with `all` and no certificate, the
results contain `plain` alone. Asking for `tls` when there is no certificate
fails with a message saying to integrate a certificate authority. The action
fails if any checked listener fails, and the per-listener results say which.

The check runs as the charm's own `_charm_health` user, whose only permission is
the private `charm/health/#` topic, with a fresh client ID each time.

### `broker-stats`

A snapshot of the broker's `$SYS` statistics tree.

No parameters.

| Result | Meaning |
| --- | --- |
| `stats` | JSON: each `$SYS` topic mapped to its latest value. |

Needs the plaintext listener, which it reads over loopback, and fails without it.
Also fails if `sys-interval` is 0, since then nothing is published to `$SYS`.

## Backup

### `create-backup`

Back up the persistence database, password file, ACL file, rendered configuration
fragments and TLS material to a tarball on the unit.

| Parameter | Type | Required | Meaning |
| --- | --- | --- | --- |
| `path` | string | no | Where to write the tarball. Defaults to a timestamped file under `/var/lib/mosquitto/backups/`. |

| Result | Meaning |
| --- | --- |
| `path` | Where the tarball was written. |
| `size` | Its size in bytes. |

The persistence database is written on autosave, so the copy is a point in time
within the last `autosave-interval` seconds.

### `restore-backup`

Restore from a tarball made by `create-backup`. The broker is stopped for the
duration, so **every client is disconnected**. **Leader only.**

| Parameter | Type | Required | Meaning |
| --- | --- | --- | --- |
| `path` | string | yes | The tarball to restore from. |

| Result | Meaning |
| --- | --- |
| `restored` | The tarball that was restored. |

The action refuses a tarball containing a link, or any path outside the broker's
own directories, and fails with the reason rather than putting the unit into an
error state.

## Maintenance

### `force-reconfigure`

Delete the charm's configuration fragments, re-render them, and reconcile the
broker unconditionally, whether or not the charm believes anything has changed.
Use it after editing files on the unit by hand.

No parameters.

| Result | Meaning |
| --- | --- |
| `result` | `reconfigured`. |

### `pause`

Stop the broker without removing the unit, for host maintenance. The unit goes to
maintenance status and stays there, ignoring configuration changes, until
`resume`. The metrics exporter is removed as well.

No parameters.

| Result | Meaning |
| --- | --- |
| `result` | `paused`. |

### `resume`

Start the broker again after `pause`, and reconcile whatever changed while it was
stopped.

No parameters.

| Result | Meaning |
| --- | --- |
| `result` | `resumed`. |

## Related

- [Configuration options](configuration.md)
- [Manage users and topic permissions](../how-to/manage-users-and-permissions.md)
