# File layout on the unit

Where the charm puts things, per install source. The layout differs because the
snap is strictly confined and cannot see `/etc/mosquitto` or `/var/lib/mosquitto`
at all.

Files the charm manages are rewritten on every reconciliation, so editing them on
the unit achieves nothing lasting. Use `juju config` and the actions, or the
`extra-config` option for directives the charm does not expose. If you have
edited something by hand and want the charm's view back, run
`juju run mosquitto/0 force-reconfigure`.

## `archive` and `ppa` (deb)

| Path | What it is |
| --- | --- |
| `/etc/mosquitto/mosquitto.conf` | Replaced by the charm with nothing but an `include_dir` line. |
| `/etc/mosquitto/mosquitto.conf.charm-orig` | The packaged configuration this replaced, saved once. |
| `/etc/mosquitto/conf.d/50-charm.conf` | The charm's main fragment: listeners, TLS, limits, persistence, logging. |
| `/etc/mosquitto/conf.d/60-charm-bridge.conf` | The bridge `connection` block, when `upstream` is integrated. |
| `/etc/mosquitto/conf.d/99-charm-extra.conf` | Whatever is in `extra-config`. |
| `/etc/mosquitto/passwd` | The hashed password file, mode `0600`, owned by `mosquitto`. |
| `/etc/mosquitto/acl` | The ACL file, mode `0600`, owned by `mosquitto`. |
| `/etc/mosquitto/certs/` | `ca.crt`, `server.crt`, `server.key` and `bridge-ca.crt`. Mode `0700`, owned by `mosquitto`; the key is `0600`. |
| `/var/lib/mosquitto/` | The `data` storage: the persistence database. Mode `0700`. |
| `/var/lib/mosquitto/mosquitto.db` | Sessions, queued messages and retained messages. |
| `/var/lib/mosquitto/backups/` | Where `create-backup` writes by default. |
| `/var/log/mosquitto/mosquitto.log` | The broker log, which the COS collector scrapes. |
| `/etc/systemd/system/mosquitto.service.d/90-charm.conf` | The charm's drop-in: `LimitNOFILE`, restart policy and sandboxing. |
| `/usr/local/lib/mosquitto-charm/exporter.py` | The metrics exporter, when `cos-agent` is integrated. |
| `/usr/local/lib/mosquitto-charm/exporter.password` | Its credentials, handed to the service as a systemd credential. |
| `/etc/systemd/system/mosquitto-charm-exporter.service` | The exporter's unit. |

Services: `mosquitto` and, when metrics are being collected,
`mosquitto-charm-exporter`. The broker runs as the `mosquitto` user and group.

Binaries: `/usr/sbin/mosquitto`, and the client tools `/usr/bin/mosquitto_pub`,
`/usr/bin/mosquitto_sub`, `/usr/bin/mosquitto_rr` and
`/usr/bin/mosquitto_passwd`, from the separate `mosquitto-clients` package the
charm also installs.

## `snap`

Everything moves under the snap's own common directory:

| Path | What it is |
| --- | --- |
| `/var/snap/mosquitto/common/mosquitto.conf` | The main configuration. |
| `/var/snap/mosquitto/common/conf.d/` | The same three charm fragments. |
| `/var/snap/mosquitto/common/passwd` | The password file. |
| `/var/snap/mosquitto/common/acl` | The ACL file. |
| `/var/snap/mosquitto/common/certs/` | TLS material. |
| `/var/snap/mosquitto/common/data/` | The persistence database. |
| `/var/snap/mosquitto/common/mosquitto.log` | The broker log. Outside `/var/log`, so the COS collector does not scrape it. |
| `/var/snap/mosquitto/common/backups/` | Backups. |

The service is `snap.mosquitto.mosquitto` and the binaries are under
`/snap/bin/`. The broker runs as root inside the snap's confinement.

Two things the charm does not do here: it writes no systemd drop-in, because
snapd owns and regenerates those units — so `open-file-limit` has no effect — and
it holds the snap, so snapd will not refresh the broker outside a maintenance
window of your choosing.

## Reading files on the unit

`/etc/mosquitto/certs` and `/var/lib/mosquitto` are mode `0700` and owned by the
broker's user, so `juju ssh` as the default user cannot read them. `juju exec`
runs as root:

```shell
juju exec --unit mosquitto/0 -- cat /etc/mosquitto/conf.d/50-charm.conf
juju exec --unit mosquitto/0 -- journalctl -u mosquitto -n 50 --no-pager
```

## Related

- [Upgrade and change install source](../how-to/upgrade-and-change-install-source.md)
- [The security model](../explanation/security-model.md)
