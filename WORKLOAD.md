# Workload: Eclipse Mosquitto

Research notes on the workload this charm operates. Everything here is about
Mosquitto itself, not about charming — see [DESIGN.md](DESIGN.md) for how the charm
uses it.

Verified on 2026-09-15 against upstream documentation and by unpacking the actual
Ubuntu 24.04 (noble) package.

## 1. What it is

[Eclipse Mosquitto](https://mosquitto.org/) is an open-source MQTT broker
implementing MQTT 5.0, 3.1.1 and 3.1. It is a **single process, single node**
publish/subscribe message broker. It is small (a few MB resident at idle), written in
C, and is the de facto default broker for IoT and edge messaging.

The important structural fact, which drives most of the charm's design: **Mosquitto
does not cluster.** See §7.

## 2. Versions and packaging

| Source | Version | Notes |
| --- | --- | --- |
| Upstream stable | 2.1.2 (2026-02-09) | Current release branch |
| Upstream maintenance | 2.0.23 | Security fixes only |
| **Ubuntu 24.04 `universe`** | **2.0.18-1build3** | **What `apt install mosquitto` gives you** |
| Ubuntu Pro / ESM Apps | 2.0.18-1ubuntu0.1~esm1 | The only patched archive build |
| `ppa:mosquitto-dev/mosquitto-ppa` | 2.1.2 | Upstream PPA, has noble builds |
| Snap `mosquitto` | 2.1.2 | `latest/stable`, strictly confined |

Two things matter about the archive package:

1. It is 2.5 years stale, so it is missing the fixes for **CVE-2024-3935** (crafted
   PUBLISH causing a double free on an outgoing bridge *with incoming topic
   remapping*) and **CVE-2024-10525**, both fixed in 2.0.19, plus the 2.0.21
   SUBSCRIBE memory leak fix.
2. It is in `universe`, so it gets **no standard Ubuntu security support**. The
   patched build exists only in ESM Apps, which requires Ubuntu Pro.

The charm should surface this rather than hide it, and must refuse to configure
bridges on a version older than 2.0.19.

### 1.x vs 2.x

Mosquitto 2.0 changed two defaults in a way that breaks every 1.x config:

- A config with **no** `listener`/`port` line binds to **localhost only** (1.x bound
  to all interfaces).
- `allow_anonymous` defaults to `false` **once any listener is defined**. With no
  listener defined at all, anonymous is still permitted on the loopback listener.

That second subtlety is a live hazard: a user-supplied config fragment that removes
the charm's listener silently re-enables anonymous access.

### 2.0 vs 2.1

2.1 adds `mosquitto --test-config` (a real dry run), `mosquitto_signal` (including
`log-rotate`, which reopens the log *without* re-reading the config), changes the
default `mosquitto_passwd` hash to **argon2id**, and changes the default
`max_packet_size` from unlimited to 2000000. It deprecates `per_listener_settings`,
`acl_file` and `password_file` in favour of the dynamic security plugin, with removal
slated for 3.0.

**An argon2id password file will not load on 2.0.** The charm must therefore pin the
hash algorithm explicitly rather than take the default.

### What the noble deb actually contains

```
/etc/mosquitto/mosquitto.conf              main config (a conffile)
/etc/mosquitto/conf.d/                     *.conf here are included
/etc/mosquitto/{certs,ca_certificates}/     empty, for TLS material
/lib/systemd/system/mosquitto.service
/usr/sbin/mosquitto
/usr/bin/mosquitto_passwd, mosquitto_ctrl
/usr/lib/*/mosquitto_dynamic_security.so
/var/lib/mosquitto/                        persistence, owned by mosquitto
/var/log/mosquitto/
/usr/share/doc/mosquitto/examples/mosquitto.conf   the 40 KB annotated example
```

`mosquitto_pub`, `mosquitto_sub` and `mosquitto_rr` are in a **separate**
`mosquitto-clients` package, which the charm needs for health checks and for the
metrics exporter.

The shipped `mosquitto.conf` sets `persistence true`,
`persistence_location /var/lib/mosquitto/`, `log_dest file
/var/log/mosquitto/mosquitto.log` and `include_dir /etc/mosquitto/conf.d` — and
defines **no listener**.

Runs as system user `mosquitto` (group `mosquitto`, home `/var/lib/mosquitto`,
`nologin`). The broker starts as root, binds, then drops privileges per the `user`
directive.

**There is no AppArmor profile on 24.04.** The postinst reloads
`/etc/apparmor.d/usr.sbin.mosquitto` only *if it exists*, and the noble package does
not ship it, despite what `README.Debian` says. Mosquitto runs unconfined. Use
systemd sandboxing instead (§4.4).

### The shipped systemd unit

```ini
[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/sbin/mosquitto -c /etc/mosquitto/mosquitto.conf
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
ExecStartPre=/bin/mkdir -m 740 -p /var/log/mosquitto
ExecStartPre=/bin/chown mosquitto:mosquitto /var/log/mosquitto
ExecStartPre=/bin/mkdir -m 740 -p /run/mosquitto
ExecStartPre=/bin/chown mosquitto:mosquitto /run/mosquitto
```

- `Type=notify` means `systemctl start` blocks until the broker is genuinely
  listening, and `systemctl is-active` is meaningful. Good.
- `ExecReload` exists, so `systemctl reload mosquitto` is the right way to SIGHUP.
- **No `LimitNOFILE`**, so the broker inherits 1024 soft and dies at roughly 1000
  clients with `Too many open files`. This is the single most common Mosquitto
  production failure. `/etc/security/limits.conf` does nothing for a systemd service;
  it must be a drop-in.
- No sandboxing directives at all.
- `After=network.target` is too weak if binding a specific address.

### logrotate

The shipped fragment rotates daily and runs `invoke-rc.d mosquitto reload` in
`postrotate` — i.e. **a full SIGHUP config reload every night**. So an invalid config
left on disk surfaces at 03:00, not at config-changed time. On 2.1 this can be
replaced with `mosquitto_signal log-rotate`, which does not re-read the config.

## 3. Configuration surface

The directives that actually matter in production, grouped. Full reference:
[mosquitto.conf(5)](https://mosquitto.org/man/mosquitto-conf-5.html).

### Listeners and protocols

`listener <port> [address]`, then per-listener `protocol mqtt|websockets`,
`socket_domain ipv4|ipv6`, `max_connections`, `max_qos`, `mount_point`,
`allow_anonymous` (per-listener form). The bare `port`/`bind_address` pair is the
legacy single-listener form; prefer `listener`.

Websockets support depends on the build (`libwebsockets`); the Ubuntu package has it.

### Security and authentication

`allow_anonymous`, `password_file`, `acl_file`, `psk_file`, `per_listener_settings`,
`plugin`/`global_plugin` (2.x spelling; `auth_plugin` is the deprecated 1.x name).

### TLS

`cafile`/`capath`, `certfile`, `keyfile`, `require_certificate`,
`use_identity_as_username`, `use_subject_as_username`, `tls_version`, `ciphers`,
`ciphers_tls1.3`, `crlfile`, `dhparamfile`.

Since 2.0 the broker **drops to the `mosquitto` user before opening the certificate
files**, so the key must be readable by that user. This is the number one cause of
"the broker won't start after certificate renewal".

### Persistence

`persistence`, `persistence_location`, `persistence_file`, `autosave_interval`
(upstream default 1800 — 30 minutes of potential loss), `autosave_on_changes`,
`persistent_client_expiration` (**upstream default: never expire, which is the
classic unbounded memory growth**).

### Limits

`max_connections`, `max_inflight_messages`, `max_queued_messages`,
`max_queued_bytes`, `message_size_limit`/`max_packet_size`, `memory_limit`,
`max_keepalive`, `retain_available`, `max_topic_alias`, `queue_qos0_messages`.

`receive_maximum` is **not** a broker directive — the broker-side equivalents are
`max_inflight_messages` and `bridge_receive_maximum`.

### Logging

`log_dest file|stdout|stderr|syslog|topic|dlt|none`, `log_type` (`error`, `warning`,
`notice`, `information`, `debug`, `subscribe`, `unsubscribe`, `websockets`, `all`),
`connection_messages`, `log_timestamp`, `log_timestamp_format`.

### Bridges

A `connection <name>` block followed by `address <host>:<port>`, one or more `topic
<pattern> [in|out|both] [local_prefix] [remote_prefix]`, `remote_username`/
`remote_password`, `bridge_cafile`/`bridge_certfile`/`bridge_keyfile`,
`cleansession`, `try_private`, `notifications`, `restart_timeout`,
`bridge_protocol_version`, `remote_clientid`.

### `$SYS`

`sys_interval` (seconds between `$SYS` tree updates; 0 disables).

## 4. Security

In priority order.

1. **Never `allow_anonymous true` in production.** Note the "no listener defined"
   escape hatch above.
2. **File permissions are enforced by the broker.** The binary contains
   `Warning: File %s has world readable permissions. Future versions will refuse to
   load this file.`, plus owner and group variants.

   Verified against 2.0.18 on 24.04: with a `0640 root:mosquitto` password file the
   broker still warns `File ... owner is not mosquitto`. So the target is **`0600`
   owned by `mosquitto:mosquitto`** for the password file, ACL file and TLS keys —
   not `root:mosquitto`. `conf.d` fragments that carry a bridge password get `0640`
   `mosquitto:mosquitto`, and `/var/lib/mosquitto` gets `0700 mosquitto:mosquitto`.
   Re-assert these on every reconfiguration, not only at install.
3. **Pin the password hash explicitly** — `-H sha512-pbkdf2` on 2.0, `-H argon2id` on
   2.1 — because an argon2id file cannot be read by 2.0. Write via a `0600` temporary
   file and `os.replace()` rather than `mosquitto_passwd -b`, which puts the password
   on the command line where `ps` and audit logs will capture it. Never set
   `MOSQUITTO_UNSAFE_ALLOW_SYMLINKS`.
4. **ACL files are deny-by-default.** Syntax:
   ```
   topic [read|write|readwrite|deny] <filter>     # applies to the current context
   user <username>                                # subsequent topic lines apply to this user
   pattern [read|write|readwrite|deny] <filter>   # %u = username, %c = client id
   ```
   Three subtleties that bite people: `deny` always wins regardless of file order;
   `pattern` lines are **global** and apply to every user even when they appear inside
   a `user` block; and `%u`/`%c` must be an entire topic level (`devices/%u/data` is
   valid, `devices/dev-%u/data` is not). Also, `#` does not match `$SYS`, so
   monitoring grants must be explicit.
5. **`per_listener_settings` is a trap.** With it enabled, a durable client carries
   the ACLs of the listener it *last* connected to, which is a genuine privilege
   escalation path (related: CVE-2021-34434). It also makes directive ordering
   load-bearing and is deprecated in 2.1. Leave it `false`.
6. **Add systemd sandboxing**, since there is no AppArmor profile. `NoNewPrivileges`,
   `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`,
   `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`,
   `SystemCallFilter=@system-service`, `RestrictNamespaces`, `LockPersonality`,
   `RestrictSUIDSGID`. Two caveats: `ProtectSystem=strict` breaks the shipped
   `ExecStartPre` mkdirs, so use `StateDirectory=`/`LogsDirectory=`/
   `RuntimeDirectory=` instead; and `MemoryDenyWriteExecute` must be dropped if a
   third-party auth plugin with a JIT is loaded.
7. `libwrap` is linked in, so `/etc/hosts.allow` and `/etc/hosts.deny` still apply.

## 5. Day-2 operations

### Reload vs restart — the critical table

**SIGHUP (`systemctl reload`) is sufficient for:**

`acl_file`, `password_file`, `psk_file`, `allow_anonymous`,
`allow_zero_length_clientid`, `allow_duplicate_messages`, `autosave_interval`,
`autosave_on_changes`, `connection_messages`, `log_dest`, `log_type`,
`log_timestamp*`, `max_inflight_bytes`, `max_inflight_messages`, `max_keepalive`,
`max_packet_size`, `max_queued_bytes`, `max_queued_messages`, `memory_limit`,
`message_size_limit`, `per_listener_settings`, `persistence*`,
`persistent_client_expiration`, `queue_qos0_messages`, `retain_available`,
`set_tcp_nodelay`, `sys_interval`, `upgrade_outgoing_qos`, `global_max_*` — **and
every bridge `connection` block** (bridges are added, removed and restarted live).

SIGHUP also **re-reads the TLS certificate and key file contents** and reopens the
log file. So certificate renewal at unchanged paths needs only a reload.

**A full restart is required for:** `listener` (add/remove/port/address), `port`,
`bind_address`, `bind_interface`, `socket_domain`, `protocol`, `max_connections`,
`max_qos`, `mount_point`, `use_username_as_clientid`, `listener_allow_anonymous`, all
listener TLS option **paths** (`cafile`, `certfile`, `keyfile`, `crlfile`,
`require_certificate`, `use_identity_as_username`, `tls_version`, `ciphers*`, …),
`psk_hint`, `user`, `pid_file`, `plugin`/`global_plugin`/`plugin_opt_*`,
`enable_proxy_protocol`, `http_dir`, `packet_buffer_size`, `websockets_*`.

A reload does **not** drop client connections; a restart drops every one. The
distinction is user-visible and worth getting right.

Note that `systemctl reload` succeeds even when the config is invalid, because the
reload is asynchronous — so always health-check after reloading.

### Config validation

2.1 has `mosquitto --test-config -c <file>`. **2.0 has nothing.** The fallback is
charm-side validation, plus a throwaway `timeout 3 mosquitto -c <candidate> -v` on a
copy with the listener, persistence and log paths rewritten to scratch locations, plus
write-reload-healthcheck-rollback as the safety net.

### Graceful shutdown

`SIGTERM` stops accepting connections, writes the persistence database if
`persistence true`, and exits. There is no drain mode, and Mosquitto does not
implement the MQTT v5 server-redirect DISCONNECT, so a stop is always abrupt from the
client's point of view.

### Backup

What actually needs backing up: `/var/lib/mosquitto/mosquitto.db` (sessions, queued
QoS>0 messages, retained messages), the password file, the ACL file, TLS material,
and the rendered config. The `.db` is written on autosave, so a consistent copy needs
either a stop or an accepted point-in-time skew.

### Health checking

**A TCP connect is not enough.** A broker can accept TCP while wedged, out of memory,
or failing every TLS handshake after a certificate renewal. The correct check is an
MQTT-level round trip: connect, subscribe, publish, receive, at QoS 1, on a dedicated
topic, as a dedicated user whose ACL grants only that topic, with a unique client ID
per check. `mosquitto_rr` is purpose-built for exactly this. **Check the TLS listener
separately** — that is the only way to catch an unreadable key after renewal.

## 6. Metrics

Mosquitto has no Prometheus endpoint. Metrics are published to the `$SYS/broker/#`
topic tree every `sys_interval` seconds. The ones worth alerting on:

| Topic | Meaning |
| --- | --- |
| `$SYS/broker/publish/messages/dropped` | **Direct data loss.** The single most important metric. |
| `$SYS/broker/clients/connected` | Current connections; compare against `max_connections`. |
| `$SYS/broker/clients/disconnected` | Persistent sessions not connected. Unbounded growth is the memory-leak leading indicator. |
| `$SYS/broker/uptime` | Resets reveal unexpected restarts. |
| `$SYS/broker/retained messages/count` | Note the **embedded space** — it trips naive metric-name mangling. |
| `$SYS/broker/heap/current`, `heap/maximum` | Memory. |
| `$SYS/broker/messages/{received,sent}`, `bytes/{received,sent}` | Throughput. |
| `$SYS/broker/load/**` | Moving averages, 1/5/15 min. |
| `$SYS/broker/subscriptions/count` | Subscription cardinality. |

Existing exporters: [`sapcc/mosquitto-exporter`](https://github.com/sapcc/mosquitto-exporter)
is the only one that does the right job (subscribes to `$SYS/#` and exposes
`broker_clients_connected` and friends), and the widely used Grafana dashboard
(grafana.com ID 11542) expects its metric names — but it is effectively dormant
(v0.8.0, Go 1.17 era) and ships only as a Go binary or Docker image, with no deb and
no snap.

`mqtt2prometheus` and `kpetremann/mqtt-exporter` are the wrong tool: they translate
device JSON payloads, not broker `$SYS` metrics.

## 7. Clustering, HA and scaling

**Mosquitto does not cluster.** There is no state replication, no shared sessions, no
shared retained messages, no shared subscriptions across nodes. Two Mosquitto
processes behind a load balancer are two unrelated brokers. The failure mode is
nasty: it appears to work until a client reconnects to the other node and discovers
its retained state has vanished.

The real options are:

- **Bridging.** A `connection` block forwards selected topics between brokers. Good
  for hub-and-spoke and edge-to-central topologies. Key semantics: `try_private true`
  prevents an A→B→A echo (but not longer cycles, so keep the topology a tree);
  `cleansession false` gives store-and-forward across outages; `remote_clientid` must
  be unique per unit or the two ends flap forever; and **raise
  `max_queued_messages` on the remote**, because the 1000 default caps what it queues
  during a WAN outage. That is the most common bridging surprise.
- **Active/passive failover** with shared storage or a VIP (`hacluster`), where the
  standby keeps the service stopped.
- **Use a different broker.** Above roughly 50k connections, or for any genuine HA
  requirement, EMQX, VerneMQ, NanoMQ or HiveMQ are the honest answer.

## 8. Performance

**File descriptors are the binding constraint.** Each client costs one fd. The
shipped unit sets no `LimitNOFILE`, so the ceiling is ~1000 clients. Set
`LimitNOFILE` to at least `max_connections + 1024` via a drop-in.

Sysctls that matter once connection counts are high: `net.core.somaxconn`,
`net.ipv4.tcp_max_syn_backlog`, `net.core.netdev_max_backlog`,
`net.ipv4.ip_local_port_range`, `net.ipv4.tcp_fin_timeout`.

Rough sizing: a few hundred bytes to a few KB of heap per idle connected client, so
tens of thousands of idle clients fit in a couple of GB; throughput is
single-core-bound because the broker is single-threaded.

## 9. Common failure modes

| Symptom | Cause |
| --- | --- |
| `Connection refused: not authorised` after a 1.x → 2.x upgrade | `allow_anonymous` now defaults to false |
| Reachable locally, not remotely | No `listener` line, so 2.x bound to loopback |
| New connections refused at ~1000 clients | `LimitNOFILE` not set |
| Corrupt `mosquitto.db` after power loss | Autosave window; the file is not written atomically |
| Memory grows until OOM | `persistent_client_expiration` unset; disconnected durable sessions accumulate |
| Messages silently disappearing | `max_queued_messages` reached; check `publish/messages/dropped` |
| Bridge flapping or duplicate messages | Shared `remote_clientid`, or a topology cycle without `try_private` |
| Bridge loses messages during a WAN outage | `max_queued_messages` on the *remote* too low |
| Broker won't start after certificate renewal | Key not readable by the `mosquitto` user (2.0 drops privileges before opening it) |
| `not authorised` despite a correct password | ACL deny-by-default, or a `pattern` line applying globally |
