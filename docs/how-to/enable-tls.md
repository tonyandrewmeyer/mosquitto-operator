# Enable TLS

The charm does not generate certificates. It asks a certificate authority charm
for one over the `certificates` integration, and configures the TLS listeners
only once it has been issued one. Until then `tls-port` is configuration with no
listener behind it — which is deliberate, so that losing the authority closes the
listener rather than leaving the broker refusing to start.

## Integrate a certificate authority

Any charm that implements the `tls-certificates` interface will do.
`self-signed-certificates` is the usual choice for a test model, and `vault` for
anything real.

```shell
juju deploy self-signed-certificates --channel 1/stable
juju integrate mosquitto:certificates self-signed-certificates
```

When the certificate arrives the charm writes it to the unit, opens the listener
on `tls-port` (8883 by default), restarts the broker, and publishes the authority
certificate to every application related on `mqtt` so that clients can verify it.

Check it really serves, rather than merely that the file changed:

```shell
juju run mosquitto/0 health-check
```

```
plain: 'ok: 127.0.0.1:1883 answered a QoS 1 round trip'
tls: 'ok: 10.65.23.104:8883 answered a QoS 1 round trip'
```

The two listeners are checked separately on purpose. A certificate renewal that
leaves the key unreadable breaks only the TLS listener, and a check that used the
plaintext one would report everything as fine.

## Name the broker correctly in the certificate

The charm requests a certificate whose common name is the unit's fully qualified
domain name, and whose subject alternative names cover the unit's hostname and
its addresses on the `mqtt` binding. If clients reach the broker under some other
name — a load balancer, a DNS alias, a public name — the handshake will fail the
name check unless you say so:

```shell
juju config mosquitto certificate-extra-sans-dns='mqtt.example.com,mqtt.internal'
juju config mosquitto certificate-common-name='mqtt.example.com'
juju config mosquitto certificate-organization='Example Ltd'
```

Changing any of these makes the charm request a new certificate.

## Turn the plaintext listener off

Once TLS works, the unencrypted listener is a liability:

```shell
juju config mosquitto port=0
```

This restarts the broker, because a listener change is not something Mosquitto
can pick up on a reload. Note two consequences: the metrics exporter needs the
plaintext listener to read `$SYS` over loopback and will not run without it, and
the `broker-stats` action will fail for the same reason.

At least one listener must be enabled; the charm rejects a configuration where
`port`, `tls-port`, `websockets-port` and `tls-websockets-port` are all zero.

## Require client certificates

For mutual TLS, where a client must present a certificate signed by the same
authority as the broker's own:

```shell
juju config mosquitto require-client-certificate=true
```

To take the MQTT username from the client certificate's common name rather than
from the CONNECT packet, add:

```shell
juju config mosquitto use-identity-as-username=true
```

That option has no effect without `require-client-certificate`, and the charm
refuses the combination rather than pretending it did something.

## Raise the minimum TLS version

`tls-version` defaults to `tlsv1.2`. Where every client is modern:

```shell
juju config mosquitto tls-version=tlsv1.3
```

## WebSockets over TLS

Browser clients speak MQTT over WebSockets. Both listeners are off by default:

```shell
juju config mosquitto websockets-port=8080 tls-websockets-port=8081
```

As with `tls-port`, the encrypted one only opens once a certificate exists.

## Renewal

Renewal is handled by the certificate authority charm and needs nothing from you.
When a new certificate arrives at the same paths, the charm writes it and reloads
the broker: SIGHUP re-reads the certificate and key contents, so renewal does not
disconnect clients.

The charm writes the private key mode `0600` owned by the broker's own user,
because since Mosquitto 2.0 the broker drops privileges *before* opening the key.
A key only root can read is the usual reason a broker will not start after a
renewal.

## Removing the authority

```shell
juju remove-relation mosquitto:certificates self-signed-certificates
```

The TLS listeners close, the broker keeps running on whatever plaintext listeners
remain, and the unit's status says that a certificate authority is needed for
TLS. Make sure `port` is not 0 first, or there will be nothing left listening.

## Related

- [Configuration reference](../reference/configuration.md)
- [The security model](../explanation/security-model.md)
