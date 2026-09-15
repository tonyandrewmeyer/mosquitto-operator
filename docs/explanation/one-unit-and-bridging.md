# Why one unit, and what bridging gives you

`juju add-unit mosquitto` puts the application into blocked status, with a
message saying that Mosquitto does not cluster and pointing at the `upstream`
integration. That is deliberate, and it is the most consequential decision in the
charm.

## Mosquitto does not cluster

There is no state replication between Mosquitto processes. No shared sessions, no
shared retained messages, no shared subscriptions, no shared queues. Two
Mosquitto processes behind a load balancer are two unrelated brokers that happen
to share an address.

The failure mode is what makes this worth refusing rather than documenting. Such
a deployment appears to work: clients connect, messages flow, `juju status` is
green. It breaks the first time a client reconnects and lands on the other node,
discovers that its durable session does not exist there, and finds that the
retained message it depends on has never been published on that broker. That can
be weeks after deployment, under load, and it looks like a client bug.

A charm that let you scale out would be offering something it cannot deliver. So
the charm checks the peer relation for other units and refuses up front, where
the cost is a confusing five minutes rather than a confusing month.

## What bridging is, and is not

Bridging is Mosquitto's own answer to more than one broker: a `connection` block
that forwards selected topics to or from another broker. In this charm it is an
integration between two Mosquitto applications, because the charm both provides
`mqtt` and requires it on `upstream` — the downstream broker is an ordinary
authenticated client of the upstream one.

That gives you real topologies:

- **Edge to central.** Each site runs its own broker, which keeps working when
  the link is down, and forwards telemetry upward when it is up. This is the
  common case, and it is why Mosquitto is on so many gateways.
- **Hub and spoke.** One central broker, many edges, each forwarding its own
  topic subtree.

What it does not give you is high availability. A bridge is not a replica. If the
central broker is lost, the topics that were forwarded to it are lost with it,
and the edge brokers go on as before with a dead connection. `cleansession false`
means the bridge stores and forwards across an outage, which covers a flaky WAN
link, not a failed broker.

Nor does it scale a single broker's capacity. Every client is still connected to
exactly one broker, which is still a single-threaded process on one machine.

Bridged topologies must also be trees. `try_private true` stops a two-broker echo
— a message coming back to the broker that sent it — but it does nothing about a
longer cycle, and a cycle in a bridged topology is a message loop that will
saturate every link in it.

## When to use something else

Above roughly 50,000 connections, or where a broker failure must not interrupt
service, Mosquitto is the wrong tool and no amount of charming will change that.
EMQX, VerneMQ, NanoMQ and HiveMQ all cluster properly. Saying so is more useful
than pretending otherwise.

Between those extremes there is one more option this charm does not implement:
active/passive failover, with shared storage or a virtual IP and a standby that
keeps the service stopped. That is a plausible future addition; it is not here
now.

## Removing an extra unit

If you do add a second unit, both go to blocked and the message tells you to remove
the extra one. Two things about that are worth knowing.

Each unit has the `data` storage attached, so plain `juju remove-unit mosquitto/1`
waits on that storage indefinitely rather than telling you why. Use:

```
juju remove-unit mosquitto/1 --destroy-storage
```

And on **Juju 4.0.14** the surviving unit stays blocked afterwards. That is not the
charm: verified by hand, `relation-list` on the surviving unit still returns the
removed unit twenty-five minutes later, and the peer `relation-departed` event never
fires. The peer relation is the only way a charm can ask how many units exist, so
there is nothing for it to act on. Juju 3.6 cleans up correctly and the unit returns
to active by itself.

If you hit this on 4.0, `juju resolve` will not help either — the status is accurate
about what the charm can see. Removing and redeploying the application is the way out.

## Related

- [Bridge two brokers](../how-to/bridge-two-brokers.md)
- [Tune for many connections](../how-to/tune-for-many-connections.md)
