# Manage users and topic permissions

The charm keeps two files for the broker: a password file, and an ACL file that
says which topic filters each user may read or write. Both are written from the
charm's own record of the users, so editing them on the unit achieves nothing
lasting — the next reconciliation overwrites them.

There are two ways a user comes into being: an operator runs the `set-password`
action, or an application integrates on the `mqtt` endpoint and is given one
automatically.

## Create a user

```shell
juju run mosquitto/0 set-password username=alice
```

With no `password` parameter the charm generates one and stores it in an
application-owned Juju secret. The action returns the secret ID, never the
password itself, because action results are visible to anyone who can read the
model's operation log.

```shell
juju show-secret --reveal secret:cvh7kruupa1s46bqvuig
```

To set a password you have chosen, pass it:

```shell
juju run mosquitto/0 set-password username=alice password='…'
```

The same action changes an existing user's password. Usernames may not contain a
colon or a line break, because the password file cannot represent them, and may
not begin with an underscore: `_charm_health` and `_charm_metrics` are the
charm's own users, and that prefix is reserved so that an operator-created user
can never inherit their grants.

## Grant and revoke topics

A new user can authenticate but can do nothing. Mosquitto's ACL file is
deny-by-default.

```shell
juju run mosquitto/0 grant username=alice topic='sensors/#'
juju run mosquitto/0 grant username=alice topic='control/+/state' access=read
juju run mosquitto/0 revoke username=alice topic='sensors/#'
```

`access` is one of `read`, `write`, `readwrite` (the default) or `deny`. In a
topic filter, `+` matches exactly one level and `#` matches the remainder of the
tree. Two things about that grammar regularly surprise people:

- `#` does **not** match the `$SYS` tree, so a grant for broker statistics has to
  name `$SYS/#` explicitly.
- `deny` wins over any other rule for the same user, whatever order the rules are
  in.

Granting the same topic twice replaces the earlier access rather than adding a
second rule, so `grant` is safe to re-run.

Both actions take effect immediately: the ACL file is reload-safe, so the charm
sends the broker a reload signal and no client is disconnected.

## See what exists

```shell
juju run mosquitto/0 list-users
```

The results contain each user, whether it came from an action or from a relation,
and its permissions. Passwords are never included, and the charm's own internal
users are not listed.

## Remove a user

```shell
juju run mosquitto/0 remove-user username=alice
```

That removes the user, all of its topic permissions, and its Juju secret.

## Give an application its own credentials

Prefer this to handing an application an operator-created password. An
application that implements the requirer side of the [`mqtt`
interface](../interfaces/mqtt/v0/README.md) asks for the topic filters it wants:

```shell
juju integrate mosquitto:mqtt my-application
```

The charm then creates a user named after the relation, installs exactly the
permissions the application asked for, puts the credentials in a Juju secret
granted to that relation, and publishes the endpoints to connect to. When the
relation goes away, so do the user and the secret.

One request is always refused: a filter under `$SYS`. The statistics tree exposes
every client ID and topic count on the broker, and an application asking for it
is almost always asking by accident. The charm logs the refusal and grants the
rest of the request; the application sees the narrower `granted-permissions` it
actually got.

## Use the credentials without leaking them

The obvious `-P <password>` flag on `mosquitto_pub` and friends puts the password
in the process table, where anything that can read `/proc` on that host can see
it. The client tools read default options from
`$XDG_CONFIG_HOME/mosquitto_<tool>` instead, which is what the charm itself does:

```shell
juju ssh mosquitto/0
mkdir -p ~/.config && umask 077
printf -- '-P %s\n' 'the-password' > ~/.config/mosquitto_sub
mosquitto_sub -h 127.0.0.1 -p 1883 -u alice -t 'sensors/#' -v
```

Each tool reads its own file, so `mosquitto_pub` and `mosquitto_rr` need their
own copies.

## Anonymous access

`allow-anonymous` defaults to `false` and should stay there. Setting it to `true`
leaves the charm working, but the unit's status says so, permanently: an
anonymous broker reachable beyond its own host is an open relay.

## Related

- [Actions reference](../reference/actions.md)
- [The security model](../explanation/security-model.md)
