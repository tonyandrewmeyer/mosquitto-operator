# Tutorial: run an MQTT broker with the Mosquitto charm

By the end of this tutorial you will have a working Mosquitto broker running
under Juju, a user with permission to use one branch of the topic tree, real
messages flowing between two MQTT clients, and the broker serving those clients
over TLS with a certificate from a certificate authority charm.

It takes about half an hour, most of which is waiting for packages to install.

The same walkthrough is published in the repository root as
[TUTORIAL.md](../../TUTORIAL.md); the two are kept in step.

## What you need

- A machine with at least 4 GB of free memory and 20 GB of disk.
- [LXD](https://canonical.com/lxd) and [Juju](https://juju.is/) 3.6 or later.
- [Charmcraft](https://canonical-charmcraft.readthedocs-hosted.com/), because
  the charm is not published on Charmhub yet.

If you have none of these, `concierge` installs and configures the lot:

```shell
sudo snap install --classic concierge
sudo concierge prepare -p machine
```

## 1. Bootstrap a controller and create a model

```shell
juju bootstrap localhost lxd
juju add-model mqtt-tutorial
```

Everything from here on happens in the `mqtt-tutorial` model, and step 9 removes
all of it in one command.

## 2. Build and deploy the charm

From a clone of this repository:

```shell
charmcraft pack
juju deploy ./mosquitto_*.charm
```

Watch it settle:

```shell
juju status --watch 5s
```

After a few minutes you should see something like:

```
Model          Controller  Cloud/Region         Version  SLA          Timestamp
mqtt-tutorial  lxd         localhost/localhost  3.6.4    unsupported  11:04:22+13:00

App        Version  Status  Scale  Charm      Channel  Rev  Exposed  Message
mosquitto  2.0.18   active      1  mosquitto             0  no

Unit          Workload  Agent  Machine  Public address  Ports  Message
mosquitto/0*  active    idle   0        10.65.23.104

Machine  State    Address       Inst id        Base          AZ  Message
0        started  10.65.23.104  juju-a1b2c3-0  ubuntu@24.04      Running
```

The version column is the Mosquitto the charm actually installed. `2.0.18` is
Ubuntu 24.04's archive build; see
[Upgrade and change install source](../how-to/upgrade-and-change-install-source.md)
for why you may not want to stay on it.

The broker is listening on port 1883, and anonymous access is off, which means
nothing can connect to it yet. That is the next step.

## 3. Create a user

```shell
juju run mosquitto/0 set-password username=alice
```

```
Running operation 1 with 1 task
  - task 2 on unit-mosquitto-0

Waiting for task 2...
generated: "true"
secret-id: secret:cvh7kruupa1s46bqvuig
username: alice
```

The password is not in the results, on purpose: action results go into the
operation log, where anyone who can read the model can see them. The charm put
the password in a Juju secret instead. Read it with:

```shell
juju show-secret --reveal secret:cvh7kruupa1s46bqvuig
```

```
cvh7kruupa1s46bqvuig:
  revision: 1
  owner: mosquitto
  label: mqtt-user-alice
  created: 2026-09-15T11:06:02Z
  updated: 2026-09-15T11:06:02Z
  content:
    password: kZ2m7Qx1TfR8vN0pLbEc4WdY
    username: alice
```

For the rest of this tutorial it is easier to choose the password yourself, so
that you can paste it into client commands. Set one:

```shell
juju run mosquitto/0 set-password username=alice password=s3cret-alice
```

## 4. Grant Alice a topic

A new user can connect but can do nothing: Mosquitto's ACL file is
deny-by-default, and the charm writes one rule per grant.

```shell
juju run mosquitto/0 grant username=alice topic='sensors/#'
```

```
acl: '[["sensors/#", "readwrite"]]'
username: alice
```

`#` matches the rest of the topic tree below `sensors/`, and `+` matches exactly
one level. The default access is `readwrite`; pass `access=read`, `access=write`
or `access=deny` for anything else.

Check what the broker now knows:

```shell
juju run mosquitto/0 list-users
```

Passwords never appear in that output either.

## 5. Publish and subscribe

The client tools (`mosquitto_sub`, `mosquitto_pub`, `mosquitto_rr`) are
installed on the unit, so you can use the broker without leaving the model.

Open a first terminal and start a subscriber:

```shell
juju ssh mosquitto/0
mosquitto_sub -h 127.0.0.1 -p 1883 -u alice -P 's3cret-alice' -t 'sensors/#' -v
```

It prints nothing and waits. In a second terminal, publish a message:

```shell
juju ssh mosquitto/0
mosquitto_pub -h 127.0.0.1 -p 1883 -u alice -P 's3cret-alice' -t sensors/kitchen/temperature -m 21.5
```

The subscriber prints:

```
sensors/kitchen/temperature 21.5
```

That is a real MQTT round trip through the broker. Press Ctrl+C to stop the
subscriber.

Now try a topic Alice was never granted:

```shell
mosquitto_pub -V mqttv5 -h 127.0.0.1 -p 1883 -u alice -P 's3cret-alice' -t control/valves -m open
```

The broker refuses it, and with MQTT 5 (`-V mqttv5`) it says so rather than
failing silently. Nothing arrives at the subscriber either way.

The `-P` flag puts the password on the command line, where anything that can
read `/proc` on the unit can see it. That is acceptable while you are learning;
the charm itself never does it, and
[Manage users and topic permissions](../how-to/manage-users-and-permissions.md)
shows the option-file form to use in earnest.

## 6. Ask the charm whether the broker is healthy

```shell
juju run mosquitto/0 health-check
```

```
plain: 'ok: 127.0.0.1:1883 answered a QoS 1 round trip'
```

This is not a TCP connect. The charm connects as its own internal user,
subscribes, publishes a message to a private topic and reads it back at QoS 1,
because a broker can accept TCP connections while being unable to serve any of
them.

For a look at what the broker thinks of itself:

```shell
juju run mosquitto/0 broker-stats
```

That returns a snapshot of Mosquitto's `$SYS` tree — connected clients, dropped
messages, heap size and so on. The same tree is what the charm's Prometheus
exporter reads; see
[Integrate with COS](../how-to/integrate-with-cos.md).

## 7. Add TLS

Deploy a certificate authority and integrate it:

```shell
juju deploy self-signed-certificates --channel 1/stable
juju integrate mosquitto:certificates self-signed-certificates
juju status --watch 5s
```

Once both applications are active, the broker has a certificate and the TLS
listener on port 8883 is open. Before the certificate arrived there was no
listener at all: the charm only configures TLS once it has something to serve,
so that losing the authority closes the listener instead of leaving the broker
refusing to start.

Confirm that the TLS listener really serves:

```shell
juju run mosquitto/0 health-check
```

```
plain: 'ok: 127.0.0.1:1883 answered a QoS 1 round trip'
tls: 'ok: 10.65.23.104:8883 answered a QoS 1 round trip'
```

The health check covers the two listeners separately, which is the only way to
notice a certificate renewal that left the key unreadable: the plaintext
listener would go on working perfectly.

To do the same round trip as Alice, over TLS:

```shell
ADDRESS=$(juju status --format=json | jq -r '.applications.mosquitto.units."mosquitto/0"."public-address"')
juju exec --unit mosquitto/0 -- mosquitto_rr \
  -h "$ADDRESS" -p 8883 --cafile /etc/mosquitto/certs/ca.crt \
  -u alice -P 's3cret-alice' \
  -t sensors/tutorial -e sensors/tutorial -m hello -q 1 -W 5
```

```
hello
```

Two details matter there. The certificate names the unit's own addresses, not
`127.0.0.1`, so a TLS client has to connect to one of those or the handshake
fails on the name check. And `juju exec` runs as root, which is necessary
because `/etc/mosquitto/certs` is readable only by the broker's own user.

With TLS working, the plaintext listener is no longer needed:

```shell
juju config mosquitto port=0
```

The broker restarts — a listener change is not something Mosquitto can pick up
on a reload — and from then on only 8883 answers.

Set it back before continuing, because the rest of the tutorial uses it:

```shell
juju config mosquitto port=1883
```

## 8. Change something without disconnecting anybody

Most configuration changes do not need a restart, and the charm works out which
is which by comparing the rendered configuration directive by directive. For
example, `sys-interval` is reload-safe:

```shell
juju exec --unit mosquitto/0 -- systemctl show mosquitto -p MainPID --value
juju config mosquitto sys-interval=20
juju status --watch 5s
juju exec --unit mosquitto/0 -- systemctl show mosquitto -p MainPID --value
```

The process ID is the same on both sides of the change: the broker was sent a
reload signal and every connected client stayed connected. Compare that with the
`port=0` change in step 7, which restarted the broker and disconnected
everything. [The reload-versus-restart design](../explanation/reload-versus-restart.md)
explains where the line falls and why.

## 9. Tidy up

```shell
juju destroy-model mqtt-tutorial --destroy-storage
```

`--destroy-storage` matters: the charm declares a filesystem store at
`/var/lib/mosquitto` for the persistence database, and without the flag Juju
keeps it behind.

## Where to go next

- [How-to guides](../how-to/index.md) for TLS, observability, bridging, backups and tuning.
- [Reference](../reference/index.md) for every config option, action and integration.
- [Explanation](../explanation/index.md) for why the charm is shaped the way it is.
