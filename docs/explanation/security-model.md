# The security model

What the charm does to keep a broker safe by default, and where it deliberately
stops.

## Authentication: a password file, not the dynamic security plugin

Mosquitto 2.x offers two ways to manage users: the classic `password_file` and
`acl_file` pair, and the dynamic security plugin that upstream intends to replace
them with in 3.0. The charm uses the files.

The reason is that the charm is a reconciler. It computes the desired set of
users and permissions from Juju config, actions and relations, and writes that
state to disk on every event, so that a unit which drifted comes back into line
on its own. The files fit that exactly: they are declarative, they are rewritten
wholesale, and they are re-read on SIGHUP without disconnecting anybody.

The dynamic security plugin is imperative. Changing anything means speaking MQTT
to the broker and issuing commands, its state lives in a JSON file the charm
would not own, and its settings are explicitly *not* re-read on SIGHUP. Mapping a
declarative desired state onto that would mean diffing the broker's live
configuration against the charm's, over an MQTT connection, on every hook.

The cost is that the charm will have to move when `acl_file` and `password_file`
are eventually removed. That is a known, dated problem, which is better than an
unbounded one.

The password file is hashed with `mosquitto_passwd -U` on a private temporary
file that is then moved into place, rather than with `mosquitto_passwd -b`, which
would put every password on a command line where `ps` and the audit log capture
it. The plaintext passwords themselves live in application-owned Juju secrets;
the charm's own copy on disk is only ever the hash.

## Authorisation: deny by default

The ACL file grants nothing to nobody until a `grant` action or an `mqtt`
integration says otherwise. Mosquitto's ACL grammar has three constructs, and the
charm uses two of them:

- `user <name>` followed by `topic <access> <filter>` lines, which is how every
  grant is written;
- rules before the first `user` line, which apply to anonymous clients. The charm
  writes none of these, so `allow-anonymous=true` permits a connection and
  nothing else.

It does **not** emit `pattern` lines. A `pattern` rule applies globally, to every
user, even when it appears inside a `user` block — which is almost never what
anybody means by putting it there, and is a common way to grant far more than
intended.

Two more sharp edges the charm works around rather than exposes: `#` does not
match the `$SYS` tree, so the charm's metrics user is granted `$SYS/#`
explicitly; and requests for `$SYS` over the `mqtt` integration are refused
outright, because that tree exposes every client ID and topic count on the
broker.

## `per_listener_settings` is off, and stays off

Mosquitto can apply security settings per listener. With that on, a durable
client carries the permissions of the listener it *last* connected through, which
is a genuine privilege escalation path — connect once on a permissive listener,
reconnect on a restricted one, keep the permissions. It also makes directive
ordering load-bearing, and it is deprecated in 2.1.

The charm writes `per_listener_settings false` explicitly, and `extra-config`
will not let you set it. One consequence worth knowing: security is broker-wide,
so a user with a permission has it on every listener, plaintext and TLS alike. If
some clients must not reach some topics, that is a matter of ACLs, not of which
port they connect to.

## The charm's own users

Two users exist that you did not create: `_charm_health`, which the health check
authenticates as, and `_charm_metrics`, which the exporter uses. Each has exactly
one grant — `charm/health/#` readwrite, and `$SYS/#` read respectively — so
neither can touch anything else, and neither borrows an operator's credentials.
Usernames beginning with an underscore are reserved, so an operator-created user
can never inherit those grants.

## File permissions

Mosquitto enforces these itself: the binary warns when its password file is world
readable or not owned by the broker's user, and future versions will refuse to
load it. Verified against 2.0.18 on 24.04, even `0640 root:mosquitto` draws a
complaint.

So the charm writes the password file, the ACL file and the private key mode
`0600` owned by `mosquitto:mosquitto`; configuration fragments that may carry a
bridge password `0640`; and `/var/lib/mosquitto` and the certificate directory
`0700`. It re-asserts all of that on every reconciliation rather than only at
install, because the point is to correct drift.

There is one specific failure this prevents. Since 2.0 the broker drops
privileges to its own user *before* opening the certificate and key, so a key
that only root can read is the usual reason a broker will not start after a
certificate renewal.

### The bridge password is on disk in the clear

One credential cannot be protected any further than that, and it is worth naming.
When the charm bridges to an upstream broker it writes `60-charm-bridge.conf` in
the fragment directory (`/etc/mosquitto/conf.d/` on a package install), and that
file contains a `remote_password` line in plain text. Mosquitto has no other way
to be given a bridge password: there is no credential file, no environment
variable and no keyring it will read. The password reaches the unit in a Juju
secret on the `upstream` integration, and then has to be written out in the clear.

So the charm does what it can — the fragment is `0640` `mosquitto:mosquitto`, and
nothing logs it — and the accepted risk is that anyone who can read files as
`root` or as the `mosquitto` user on the unit can read the upstream broker's
password. The upstream charm gives the bridge a user of its own, granted only the
bridged topics, so what a reader gets is scoped to the bridge rather than to the
whole upstream broker. A backup tarball contains this fragment, which is one of
the reasons the tarball is `0600`.

## systemd sandboxing instead of AppArmor

Ubuntu 24.04 ships no AppArmor profile for Mosquitto. The package's `postinst`
reloads `/etc/apparmor.d/usr.sbin.mosquitto` only if it exists, and it does not,
despite what the package's own `README.Debian` says. Mosquitto therefore runs
unconfined out of the box.

The charm's systemd drop-in supplies the confinement instead: `NoNewPrivileges`,
`PrivateTmp`, `PrivateDevices`, `ProtectHome`, `ProtectKernelTunables`,
`ProtectKernelModules`, `ProtectControlGroups`, `ProtectClock`,
`ProtectHostname`, `RestrictNamespaces`, `RestrictRealtime`, `RestrictSUIDSGID`,
`LockPersonality`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`,
`SystemCallArchitectures=native` and `SystemCallFilter=@system-service`.

Two of those choices are not the obvious ones:

- `ProtectSystem=full`, not `strict`. `strict` makes the whole filesystem
  read-only, which breaks the packaged unit's own `ExecStartPre` `mkdir` and
  `chown` before the broker even runs. `full` protects `/usr`, `/boot` and
  `/efi`, which is the part that matters, and the drop-in names the persistence
  and log directories as `ReadWritePaths`.
- `SystemCallFilter=~@privileged` is **not** set. Mosquitto starts as root so
  that it can bind a privileged port, then calls `setuid` and `setgid` to drop
  to its own user. Both are in `@privileged`, so filtering it kills the broker
  with SIGSYS part-way through starting.

The exporter gets its own, tighter sandbox: `DynamicUser`, `ProtectSystem=strict`
and no address families beyond IPv4 and IPv6. Its MQTT password reaches it as a
systemd credential — read by systemd as root, exposed only to that service —
rather than as an argument or an environment variable.

On a snap install none of this applies: snapd owns the generated unit, and the
snap's strict confinement does the same job.

## What the charm does not do

- **It does not expose the application for you.** The charm *does* declare its
  listeners to Juju with `unit.set_ports()`, so `juju expose mosquitto` opens
  exactly the MQTT and WebSocket ports that are configured and no others — but it
  never exposes the application itself. The metrics port is deliberately left out
  of that declaration: it is bound to loopback, for the collector beside it.
- **It does not manage `/etc/hosts.allow`.** Mosquitto is linked against
  `libwrap`, so those rules still apply if you write them.
- **It does not stop you turning safety off.** `allow-anonymous=true` works, and
  the unit says so for as long as it is set — though an anonymous client is
  granted no topics, so it can connect and do nothing else.

## Related

- [Manage users and topic permissions](../how-to/manage-users-and-permissions.md)
- [Enable TLS](../how-to/enable-tls.md)
- [File layout on the unit](../reference/file-layout.md)
