# Upgrade and change install source

There are two different things called an upgrade here: upgrading the charm, and
changing which Mosquitto the charm installs.

## The three install sources

| `install-source` | Version on 24.04 | Security support |
| --- | --- | --- |
| `archive` (default) | 2.0.18, from `universe` | None as standard. Patched builds only through Ubuntu Pro (ESM Apps). |
| `ppa` | Current 2.1.x, from `ppa:mosquitto-dev/mosquitto-ppa` | Upstream's own builds; no Ubuntu security process. |
| `snap` | Current 2.1.x, strictly confined | Upstream's own builds, auto-updating unless held — the charm holds it. |

The archive build is 2.5 years old. It lacks the fixes for CVE-2024-3935 and
CVE-2024-10525 (both fixed in 2.0.19) and the 2.0.21 SUBSCRIBE memory leak fix.
The charm refuses to configure a bridge on anything older than 2.0.19 for exactly
that reason.

If you want to stay on the archive, attach Ubuntu Pro to the machine, whose ESM
Apps stream carries `2.0.18-1ubuntu0.1~esm1`. The charm does not manage Pro
attachment; do it on the machine, or with the `ubuntu-advantage` subordinate
charm.

The unit status says so while it applies: a deployment running an archive build
without the ESM revision reports the package version and what to do about it,
alongside whatever else it has to say. The two builds carry the same upstream
version, so this is read from the Debian revision rather than from
`mosquitto -h`.

## Change the install source

```shell
juju config mosquitto install-source=ppa
```

The charm installs from the new source, migrates the broker's state to the new
layout if it differs, and restarts the broker. Expect a few minutes of package
work and one disconnection of all clients.

Two things happen that are worth knowing about:

- **The password file is discarded and rewritten.** Mosquitto 2.1 hashes
  passwords with argon2id, which 2.0 cannot read, so carrying the file across a
  version change can leave a broker that rejects every login. The charm holds
  every password in a Juju secret, so it throws the file away and writes a fresh
  one. Nothing you need to do, and no password changes.
- **Moving back to `archive` removes the PPA.** While the PPA is configured its
  2.1.x build stays the candidate version, so the charm removes the source list
  as part of the change; otherwise you would be running 2.1 while the charm
  reported the archive.

Check what you ended up with:

```shell
juju status mosquitto
```

The `Version` column is the Mosquitto version the charm found after installing.

## The snap

```shell
juju config mosquitto install-source=snap
juju config mosquitto package-channel=latest/stable
```

`package-channel` is only read when `install-source` is `snap`.

Strict confinement moves everything: the configuration, password file, ACL file,
certificates, persistence database and backups all live under
`/var/snap/mosquitto/common/` rather than the usual paths. See
[File layout on the unit](../reference/file-layout.md) before you go looking for
a file.

The charm also **holds** the snap, so snapd will not refresh the broker outside a
maintenance window of your choosing. To take a newer build, change
`package-channel`, or `juju refresh` the charm.

Changing `package-channel` refreshes the held snap onto the new channel there and
then, and restarts the broker: every client is disconnected, exactly as for a
change of `install-source`. Setting it to the channel the snap is already on does
nothing, so a `juju config` that does not change it costs nothing either.

Two things the charm does not do for a snap install: it writes no systemd
drop-in, because snapd owns and regenerates those units — so `open-file-limit`
has no effect — and it relies on the snap's own confinement instead of the
sandboxing it adds to the deb service.

The broker log moves too, to `/var/snap/mosquitto/common/mosquitto.log`, which is
outside the `/var/log` trees the COS machine collectors scrape. **Broker logs are
not forwarded to Loki on a snap install.** The broker cannot write to `/var/log`
from inside strict confinement, so there is no charm-side fix; if you need the
logs in Loki, use `install-source=ppa`, or collect the file yourself. Metrics,
dashboards and alert rules are unaffected — the exporter is a charm-side service
either way.

## Upgrade the charm

```shell
juju refresh mosquitto --path ./mosquitto_*.charm
```

On upgrade the charm reinstalls the workload for the configured source and
reconciles. If nothing about the rendered configuration changed, nothing is
applied and no client is disconnected.

## Upgrade Mosquitto without changing source

Within a source, the charm installs whatever the candidate version is at the time
it runs. To pick up a new PPA or archive build:

```shell
juju run mosquitto/0 force-reconfigure
```

That re-renders the configuration and reconciles unconditionally, but it does not
by itself run `apt upgrade`. For the package itself, either refresh the charm,
which reinstalls, or update the package on the machine and then run
`force-reconfigure` so the charm's view matches.

## Before and after any of this

```shell
juju run mosquitto/0 create-backup
# … make the change …
juju run mosquitto/0 health-check
```

The health check is a real MQTT round trip, so it catches a broker that is
running but not serving — which is what a bad upgrade usually looks like.

## Related

- [Back up and restore](back-up-and-restore.md)
- [File layout on the unit](../reference/file-layout.md)
