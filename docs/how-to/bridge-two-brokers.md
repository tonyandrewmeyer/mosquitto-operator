# Bridge two brokers

Mosquitto does not cluster, so a second broker is a second broker, not a second
copy of the first. What it does have is bridging: a connection from one broker to
another that forwards selected topics. This is how edge-to-central and
hub-and-spoke topologies are built, and in this charm it is expressed as an
integration between two Mosquitto applications.

The charm both provides `mqtt` and requires it on `upstream`, so the downstream
broker is an ordinary MQTT client of the upstream one, with its own user,
password and topic permissions.

## Before you start

The bridge needs Mosquitto 2.0.19 or newer on the downstream broker. The charm
refuses to configure one on anything older, because CVE-2024-3935 — a double free
reachable through exactly this feature — was fixed in 2.0.19, and Ubuntu 24.04
ships 2.0.18. Set both applications to the PPA:

```shell
juju config mosquitto-edge install-source=ppa
juju config mosquitto-central install-source=ppa
```

If you skip this, the integration is made and no bridge configuration is written.
The refusal is on the unit status of the application that would carry the bridge
— `ready — …; the bridge is disabled: Mosquitto 2.0.18 is vulnerable to
CVE-2024-3935 …` — as well as in `juju debug-log`.

## Deploy and integrate

```shell
juju deploy ./mosquitto_*.charm mosquitto-edge \
  --config bridge-topics='topic sensors/kitchen/temperature out'
juju deploy ./mosquitto_*.charm mosquitto-central
juju integrate mosquitto-edge:upstream mosquitto-central:mqtt
```

The direction matters: `upstream` on the broker that initiates the connection,
`mqtt` on the one that receives it. The edge broker connects out to the central
one, which is what you want when the edge is behind NAT or a flaky link.

## Say what to forward

A bridge with no topics carries nothing, which looks exactly like a working
bridge with no traffic on it. The charm says so in the unit's status, but you
still have to set it:

```shell
juju config mosquitto-edge bridge-topics='
topic sensors/# out
topic commands/# in
'
```

Each line is a Mosquitto `topic` directive:

```
topic <pattern> [in|out|both] [local_prefix] [remote_prefix]
```

`out` forwards from this broker to the remote, `in` brings messages the other
way, and `both` does each. The default when the direction is omitted is `out`.

The charm derives the permissions to ask the upstream broker for from these
lines: an `out` topic becomes a `write` request, `in` becomes `read`, and `both`
becomes `readwrite`. So a topic you did not list is a topic the bridge user was
never granted, even if you later add it by some other route.

## Check that it actually carries messages

The only test worth running is a message crossing. Publish a retained message on
the edge, then subscribe on the central broker — retained means the subscriber
does not have to be waiting when it is published:

```shell
juju run mosquitto-edge/0 set-password username=sensor password='…'
juju run mosquitto-edge/0 grant username=sensor topic='sensors/#'
juju run mosquitto-central/0 set-password username=reader password='…'
juju run mosquitto-central/0 grant username=reader topic='sensors/#' access=read

juju ssh mosquitto-edge/0 -- mosquitto_pub -V mqttv5 -h 127.0.0.1 -u sensor -P '…' \
  -t sensors/kitchen/temperature -m 21.5 -q 1 -r
juju ssh mosquitto-central/0 -- mosquitto_sub -h 127.0.0.1 -u reader -P '…' \
  -t sensors/kitchen/temperature -C 1 -W 20
```

If nothing arrives, look at the bridge fragment on the edge unit and at the
broker log:

```shell
juju exec --unit mosquitto-edge/0 -- cat /etc/mosquitto/conf.d/60-charm-bridge.conf
juju exec --unit mosquitto-edge/0 -- journalctl -u mosquitto | grep -i bridge
```

## What the charm sets for you

The rendered `connection` block includes several settings that bridges go wrong
without:

- `try_private true`, so a message that arrives from the remote is not sent
  straight back. This breaks two-broker echoes only, so keep the overall topology
  a tree.
- `cleansession false`, so the bridge stores and forwards across an outage
  instead of dropping everything.
- `remote_clientid` derived from the Juju unit name, because two bridge ends
  sharing a client ID disconnect each other for ever.
- `restart_timeout 10 60` and MQTT 5 as the bridge protocol version.

## Keep messages through a WAN outage

The most common bridging surprise is losing messages during an outage even
though `cleansession false` is set. The cap is the *remote* broker's queue, not
the local one, so raise it on the receiving side:

```shell
juju config mosquitto-central max-queued-messages=100000
```

Bear in mind what that means for memory: those messages are held in the broker's
heap until the bridge drains them.

## Remove a bridge

```shell
juju remove-relation mosquitto-edge:upstream mosquitto-central:mqtt
```

The bridge fragment is removed and the broker reconfigured. Mosquitto can add and
remove bridges on a reload, but the charm classifies bridge directives as needing
a restart, so adding or removing a bridge does disconnect the edge broker's own
clients briefly. See
[How the charm decides what a configuration change requires](../explanation/configuration-changes.md).

## Related

- [Why one unit, and what bridging gives you](../explanation/one-unit-and-bridging.md)
- [The `mqtt` interface](../interfaces/mqtt/v0/README.md)
