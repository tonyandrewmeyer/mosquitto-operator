# Eclipse Mosquitto: operational research for a Juju machine charm

Date of research: 2026-09-15. Target platform: Ubuntu 24.04 LTS (noble), machine charm,
systemd-managed. All version and packaging facts below were verified either against the
upstream documentation or by downloading and unpacking the actual Ubuntu noble `.deb`.

Primary sources:

- <https://mosquitto.org/man/mosquitto-conf-5.html> (mosquitto.conf(5), the full directive reference)
- <https://mosquitto.org/man/mosquitto-8.html> (mosquitto(8))
- <https://mosquitto.org/man/mosquitto_passwd-1.html>
- <https://mosquitto.org/man/mosquitto-tls-7.html>
- <https://mosquitto.org/man/mosquitto_signal-1.html>
- <https://mosquitto.org/man/> (index of all man pages)
- <https://mosquitto.org/documentation/migrating-to-2-0/>
- <https://mosquitto.org/documentation/dynamic-security/>
- <https://mosquitto.org/documentation/using-the-snap/>
- <https://mosquitto.org/download/>
- <https://mosquitto.org/security/>
- <https://github.com/eclipse-mosquitto/mosquitto> and `ChangeLog.txt`
- <https://mosquitto.org/blog/2026/01/version-2-1-0-released/>

---

## 1. Versions and packaging

### 1.1 What exists right now

| Channel | Version | Notes |
|---|---|---|
| Upstream current stable | **2.1.2** (2026-02-09), with 2.1.3 in the changelog | <https://mosquitto.org/download/> |
| Upstream maintenance branch | **2.0.23** (2026-01-14) | the 2.0 series is still receiving fixes |
| Ubuntu 24.04 noble, `universe` | **2.0.18-1build3** | the archive version; frozen at the 2023-09-18 upstream release |
| Ubuntu 24.04 noble, ESM Apps | **2.0.18-1ubuntu0.1~esm1** (`noble-apps-security`) | only available with Ubuntu Pro |
| `ppa:mosquitto-dev/mosquitto-ppa` | **2.1.2** for noble (published 2026-02-09) | upstream-maintained PPA |
| Snap `mosquitto` | `latest/stable` **2.1.2** (rev 1134, 2026-02-09); `2.1/stable` 2.1.2; `2.0/stable` **2.0.22**; `1.6/stable` 1.6.15 (2022) | publisher "Mosquitto Team" (verified account `mosquitto**`) |

Two facts that matter a great deal for a charm:

1. **`mosquitto` is in `universe` on Ubuntu.** It is *not* covered by standard Ubuntu
   security maintenance. The only patched build in the archive
   (`2.0.18-1ubuntu0.1~esm1`) lives in `esm.ubuntu.com/apps` and needs an Ubuntu Pro
   token. A charm that installs from the plain archive is deploying a broker whose
   security updates depend on the user having Pro attached. This must be documented,
   and ideally surfaced as a warning in charm status.
2. **noble ships 2.0.18, which is 2.5 years behind upstream.** It is missing
   `CVE-2024-3935` (bridge topic remapping double free) and `CVE-2024-10525`
   (libmosquitto SUBACK OOB read), plus the 2.0.21 "leak on malicious SUBSCRIBE by an
   authenticated client" fix. The ESM build should carry backports of these; the plain
   `universe` build almost certainly does not.

### 1.2 1.x vs 2.x — the differences that matter

From <https://mosquitto.org/documentation/migrating-to-2-0/>:

- **`allow_anonymous` now defaults to `false`.** In 1.x it was effectively `true`. Any
  configured listener now rejects clients unless you configure a `password_file`, an
  `acl_file`, an auth plugin, or explicitly set `allow_anonymous true`. This is the
  single most common "upgraded and everything broke" report.
  - Subtlety: the default is `false` *when a listener is defined*. With **no** config
    file at all, the broker binds to loopback only and permits anonymous access — a
    deliberate "works out of the box but is not exposed" compromise.
- **Default listener binds to loopback.** Without a config file, or with `-p`, the
  listener binds `127.0.0.1` and `::1` only. From mosquitto(8): *"From version 2.0
  onwards, the listeners defined with -p are bound to the loopback interface only, and
  so can only be connected to from the local machine."*
- **`-p` and `-c` can no longer be combined.** *"If both -p is used and a listener is
  defined in a configuration file, then the -p options are IGNORED."*
- **`tls_version` is now a minimum, not an exact version.** TLS v1.0 support removed
  in 2.0; TLS v1.1 support removed in 2.1.
- **Privilege drop happens earlier.** 2.0 drops to the `mosquitto` user immediately
  after reading the config, *before* opening certificates and listeners. Consequence:
  **TLS key/cert files must be readable by the `mosquitto` user**, not just root. This
  breaks naive Let's Encrypt integrations that leave keys root-only.
- **Plugin API v4.** 1.x auth plugins must be recompiled;
  `mosquitto_auth_plugin_version` must return `4`. `auth_plugin` →
  `plugin`, `auth_opt_*` → `plugin_opt_*` (old names still accepted, deprecated).
- **`port` and `bind_address` are deprecated** in favour of `listener <port> [address]`.

### 1.3 2.0 vs 2.1 — what changes if you move to 2.1

From <https://mosquitto.org/blog/2026/01/version-2-1-0-released/> and the changelog:

- **`acl_file`, `password_file` and `per_listener_settings` are deprecated** and
  scheduled for removal in 3.0, in favour of the `mosquitto_acl_file` and
  `mosquitto_password_file` plugins. They still work in 2.1.
- **`max_packet_size` default changed from 0 (256 MB ceiling) to 2000000 bytes.**
  A silent behaviour change on upgrade if you push large payloads.
- Built-in websockets implementation replacing libwebsockets (removes the
  `libwebsockets19t64` dependency and its historical instability).
- `--test-config` command-line flag: **a real config-check mode, new in 2.1**. This is
  a big deal for a charm (see §4.5).
- `-q/--quiet`, `--tls-keylog FILE`.
- `mosquitto_signal(1)`: named signals (`config-reload`, `log-rotate`, `shutdown`,
  `tree-print`, `xtreport`), targeting `-a` (all local brokers) or `-p <pid>`.
- Unix domain socket listeners; PROXY protocol v1/v2 (`enable_proxy_protocol`,
  `proxy_protocol_v2_require_tls`).
- `argon2id` is now the **default** `mosquitto_passwd` hash (2.0 used SHA-512 PBKDF2;
  1.6 used plain SHA-512). Hashes are forward-compatible but not backward: an
  argon2id password file will not load on 2.0.
- systemd watchdog support; kqueue support; ~100× fewer wakeups on an idle broker.
- `retain_expiry_interval`, `global_max_clients`, `global_max_connections`,
  `accept_protocol_versions`, `bind_interface`, `max_qos`, `packet_buffer_size`,
  broker-created topic aliases, `bridge_receive_maximum`,
  `bridge_session_expiry_interval`, `bridge_reload_type`.
- A built-in Web UI / `protocol http_api` listener and `enable_control_api`.
- TLS v1.1 removed.

### 1.4 Which packaging should the charm prefer?

**Recommendation: default to the deb from the Ubuntu archive, with an opt-in to the
upstream PPA. Do not use the snap as the default.**

Reasoning:

| | deb (archive) | deb (PPA) | snap |
|---|---|---|---|
| Version | 2.0.18 | 2.1.2 | 2.1.2 / 2.0.22 |
| Filesystem layout | FHS, `/etc/mosquitto` | same | `/var/snap/mosquitto/common/` **only** |
| Charm can place certs anywhere | yes | yes | **no** |
| systemd unit | `mosquitto.service`, `ExecReload=kill -HUP` | same | `snap.mosquitto.mosquitto.service` |
| Integrates with `tls-certificates`, logrotate, node-exporter textfile, etc. | easily | easily | awkwardly |
| Security updates | Ubuntu Pro / ESM only (universe) | upstream, unsigned-by-Canonical | snap auto-refresh (uncontrollable timing) |
| Unattended restarts | charm-controlled | charm-controlled | **snapd refreshes and restarts on its own schedule** |

The snap's strict confinement is the killer: per
<https://mosquitto.org/documentation/using-the-snap/>, *"only the
`/var/snap/mosquitto/common/` directory is accessible to the broker process"*. Every
TLS certificate, password file, ACL file and persistence file must be inside that one
directory. That is workable but it fights every other charm convention, and it makes
integrating with a `tls-certificates` provider or a Juju storage mount painful. Snap
auto-refresh also means the broker can restart without the charm knowing, which is
unacceptable for a stateful single-node service.

So: `install_source` config option with values `archive` (default), `ppa`, `snap`,
where `ppa` adds `ppa:mosquitto-dev/mosquitto-ppa`. If the charm supports only one,
support the deb.

### 1.5 What the noble deb actually contains

Verified by unpacking `mosquitto_2.0.18-1build3_amd64.deb`:

```
/etc/init.d/mosquitto                          (sysvinit fallback; conffile)
/etc/logrotate.d/mosquitto                     (conffile)
/etc/mosquitto/mosquitto.conf                  (conffile - the main config)
/etc/mosquitto/conf.d/README                   (conffile; *.conf here are included)
/etc/mosquitto/aclfile.example
/etc/mosquitto/pwfile.example
/etc/mosquitto/pskfile.example
/etc/mosquitto/ca_certificates/README
/etc/mosquitto/certs/README
/lib/systemd/system/mosquitto.service
/usr/sbin/mosquitto
/usr/bin/mosquitto_passwd
/usr/bin/mosquitto_ctrl
/usr/lib/x86_64-linux-gnu/mosquitto_dynamic_security.so
/usr/share/doc/mosquitto/examples/mosquitto.conf   (the full 40 KB annotated example)
/usr/share/doc/mosquitto/README-letsencrypt.md
/var/lib/mosquitto/                                (empty, owned by mosquitto)
/var/log/mosquitto/                                (empty)
```

**Clients are a separate package**: `mosquitto-clients` provides `mosquitto_pub`,
`mosquitto_sub`, `mosquitto_rr`. **The charm must install `mosquitto-clients`** — it
is needed for health checks and for `mosquitto_ctrl` over MQTT. `mosquitto_ctrl` and
`mosquitto_passwd` are in the *server* package.

`Depends:` includes `libssl3t64`, `libwebsockets19t64`, `libcjson1`, `libwrap0`
(TCP wrappers — `/etc/hosts.allow` / `/etc/hosts.deny` still apply), `libdlt2`,
`libsystemd0`. `Suggests: apparmor`.

**The shipped `/etc/mosquitto/mosquitto.conf`:**

```
# Place your local configuration in /etc/mosquitto/conf.d/
#
# A full description of the configuration file is at
# /usr/share/doc/mosquitto/examples/mosquitto.conf.example

#pid_file /run/mosquitto/mosquitto.pid

persistence true
persistence_location /var/lib/mosquitto/

log_dest file /var/log/mosquitto/mosquitto.log

include_dir /etc/mosquitto/conf.d
```

Note: it defines **no listener at all**, so out of the box the Debian/Ubuntu package
listens on 1883 on loopback with anonymous access permitted. That is the "no listener
defined" path in 2.0, i.e. it is *not* exposed to the network but *is* anonymous.

**The systemd unit** (`/lib/systemd/system/mosquitto.service`), verbatim:

```ini
[Unit]
Description=Mosquitto MQTT Broker
Documentation=man:mosquitto.conf(5) man:mosquitto(8)
After=network.target
Wants=network.target

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

[Install]
WantedBy=multi-user.target
```

Observations for the charm:

- `Type=notify` — the broker does sd_notify, so `systemctl start` blocks until the
  broker is actually up and listening. `systemctl is-active` is meaningful.
- `ExecReload` exists, so `systemctl reload mosquitto` sends SIGHUP. Use that rather
  than signalling the PID directly.
- `Restart=on-failure` but **no `RestartSec`, no `StartLimitBurst` tuning, and no
  resource limits at all**. Notably **no `LimitNOFILE`**, so the broker inherits
  systemd's `DefaultLimitNOFILE` (1024 soft / 524288 hard on noble). This caps
  practical connections at roughly 1000. The charm *must* add a drop-in (see §7).
- No sandboxing directives whatsoever. The charm should add them (see §3.8).
- `After=network.target` is weak — if the charm binds a specific address, add
  `After=network-online.target` / `Wants=network-online.target` in the drop-in,
  otherwise a listener bound to a specific IP can fail at boot.

**User/group**, from the postinst:

```sh
addgroup --quiet --system mosquitto
adduser --quiet --system --no-create-home --ingroup mosquitto \
        --home /var/lib/mosquitto --shell /usr/sbin/nologin mosquitto
chown mosquitto /var/lib/mosquitto
```

So: system user `mosquitto`, group `mosquitto`, home `/var/lib/mosquitto`, nologin
shell, no password. The broker starts as root (to bind ports < 1024 if asked) and
drops to `mosquitto` per the `user` directive (default `mosquitto`).

**AppArmor:** the postinst contains

```sh
APP_PROFILE="/etc/apparmor.d/usr.sbin.mosquitto"
if [ -f "$APP_PROFILE" ] && aa-status --enabled 2>/dev/null; then
       apparmor_parser -r "$APP_PROFILE" || true
fi
```

…but **the noble package does not ship that profile.** It is not in the file list and
not in `conffiles`. `README.Debian` still refers to "the shipped enforcing profile",
which is stale documentation. In practice, on Ubuntu 24.04 **Mosquitto runs
unconfined by AppArmor**. Do not rely on an AppArmor profile existing; if you want
confinement, the charm must ship its own profile, or (much simpler and more portable)
use systemd sandboxing directives instead (§3.8).

Historically the Debian profile allowed read on `/etc/mosquitto/**`, read/write on
`/var/lib/mosquitto/**`, read/write on `/var/log/mosquitto/**`, `/run/mosquitto/*`,
and network inet/inet6 stream — worth mirroring in a systemd `ReadWritePaths=` set.

**logrotate** (`/etc/logrotate.d/mosquitto`):

```
/var/log/mosquitto/mosquitto.log {
	rotate 7
	daily
	compress
	delaycompress
	size 100k
	nocreate
	missingok
	postrotate
		if invoke-rc.d mosquitto status > /dev/null 2>&1; then \
			invoke-rc.d mosquitto reload > /dev/null 2>&1; \
		fi;
	endscript
}
```

Note `nocreate` + a **full config reload** on rotate. That means every daily log
rotation sends SIGHUP to the broker, which re-reads the entire config file. If the
charm has written a config that is currently invalid, logrotate will surface it at
03:00 rather than at config-changed time. Two consequences:

1. The charm must never leave an invalid config on disk.
2. On 2.1 you can replace `reload` with `mosquitto_signal log-rotate` (or SIGRTMIN),
   which only reopens the log and does not re-read the config. Consider shipping a
   replacement logrotate fragment that does exactly that. On 2.0 you are stuck with
   SIGHUP.

---

## 2. Configuration surface

Full reference: <https://mosquitto.org/man/mosquitto-conf-5.html>. The annotated
example config is at `/usr/share/doc/mosquitto/examples/mosquitto.conf`.

For each group below: **[expose]** = should be a Juju config option; **[compute]** =
the charm derives it from relations/other config; **[hardcode]** = the charm fixes it
and does not let the user change it.

### 2.1 Listeners and protocols

| Directive | Default | Charm treatment |
|---|---|---|
| `listener <port> [bind address / host / unix socket path]` | — | **[compute]** — build from `port`, `bind_address`, `websockets_port`, `tls_*` config. Never let the user supply a raw listener line. |
| `port <n>` | 1883 | **[hardcode: never emit]** — deprecated in 2.0, use `listener`. |
| `bind_address <addr>` | — | **[hardcode: never emit]** — deprecated, use the `listener` second argument. |
| `bind_interface <dev>` | — | 2.1 only. **[expose]** optionally, for multi-homed machines. |
| `protocol mqtt\|websockets\|http_api` | `mqtt` | **[compute]** — `websockets` on the websockets listener only. `http_api` is 2.1+. |
| `socket_domain ipv4\|ipv6` | both | **[expose]** as `socket_domain` with default unset (both). Useful on IPv4-only clouds where the IPv6 bind fails noisily. |
| `max_connections <n>` | `-1` (unlimited) | **[expose]**, default `-1`, but see §7 — the charm must keep `LimitNOFILE` above it. |
| `global_max_connections` / `global_max_clients` | `-1` | 2.1 only. **[expose]** if on 2.1. |
| `mount_point <prefix>` | — | **[expose]** per-listener for multi-tenant setups; powerful and rarely used. |
| `use_username_as_clientid` | `false` | **[expose]**, default `false`. Setting `true` is a strong anti-spoofing measure but breaks clients that reconnect with a new client ID. |
| `max_qos 0\|1\|2` | `2` | 2.1 only. **[expose]**, default `2`. |
| `max_topic_alias <0-65535>` | `10` | **[expose]**, default `10`. |
| `max_topic_alias_broker <0-65535>` | `10` | 2.1 only. |
| `packet_buffer_size` | 4096 | **[hardcode]**. |
| `websockets_headers_size` | 4096 | **[hardcode]** unless someone needs big JWT headers. |
| `websockets_log_level <bitmask>` | `0` | **[expose]** for debugging only. |
| `websockets_origin <origin>` | — | **[expose]** — CORS-ish origin check for browser clients. |
| `http_dir <dir>` | — | **[hardcode: do not use]** — serving static files from the broker is not a charm's job. |
| `accept_protocol_versions 3,4,5` | all | 2.1 only. **[expose]** — a decent hardening lever (e.g. `5` only). |
| `enable_proxy_protocol 1\|2` | — | 2.1 only. **[expose]** for when the charm sits behind HAProxy. |
| `proxy_protocol_v2_require_tls` | `false` | 2.1 only. |
| `allow_zero_length_clientid` | `true` | **[expose]**, default `true`. |
| `auto_id_prefix` / `listener_auto_id_prefix` | `auto-` | **[hardcode]**. |
| `clientid_prefixes` | — | **[hardcode: do not use]** — deprecated, removal planned. |
| `set_tcp_nodelay` | `false` | **[expose]**, default `true` is a reasonable charm opinion for low-latency workloads; upstream default is `false` (favours throughput). |

Important structural point: **directive order matters**. Options that appear *before*
the first `listener` line are global defaults; options after a `listener` line apply
to that listener. This is the single most common source of "my config is silently
wrong" bugs. The charm's config renderer must emit global options first, then each
listener block, and must never let user-supplied extra config be interleaved
arbitrarily.

### 2.2 Security and authentication

| Directive | Default | Charm treatment |
|---|---|---|
| `allow_anonymous true\|false` | `false` (`true` if no listeners defined) | **[expose]** with default **`false`**, and refuse to set `true` unless the user also sets an explicit `i-know-this-is-insecure`-style flag, or at least emit a blocked/warning status. |
| `password_file <path>` | — | **[compute]** — always `/etc/mosquitto/passwd`, managed by the charm via `mosquitto_passwd`. Deprecated in 2.1. |
| `acl_file <path>` | — | **[compute]** — always `/etc/mosquitto/acl`. Deprecated in 2.1. |
| `psk_file <path>` | — | **[expose]** only if you want PSK-TLS for constrained devices; otherwise skip. |
| `psk_hint <string>` | — | as above. |
| `per_listener_settings true\|false` | `false` | **[expose]**, default **`false`**. See the trap in §3.5. Deprecated in 2.1. |
| `listener_allow_anonymous` | value of `allow_anonymous` | **[compute]** only when `per_listener_settings true`. |
| `plugin <path.so>` | — | **[compute]** — the dynsec plugin path, or a user-specified plugin. |
| `plugin_opt_<name> <value>` | — | **[compute]**. |
| `global_plugin <path.so>` | — | 2.1 only; applies regardless of `per_listener_settings`. |
| `auth_plugin` / `auth_opt_*` | — | **deprecated aliases** for `plugin`/`plugin_opt_*`. Never emit. |
| `auth_plugin_deny_special_chars` | `true` | **[hardcode `true`]**. Blocks `+`/`#` in usernames/client IDs reaching ACL pattern substitution — an injection guard. |
| `enable_control_api` | — | 2.1 only; required for `$CONTROL/` topics used by dynsec. **[compute]**. |

**Dynamic security plugin** (<https://mosquitto.org/documentation/dynamic-security/>):

```
per_listener_settings false
plugin /usr/lib/x86_64-linux-gnu/mosquitto_dynamic_security.so
plugin_opt_config_file /var/lib/mosquitto/dynamic-security.json
```

Bootstrap, offline, once:

```
mosquitto_ctrl dynsec init /var/lib/mosquitto/dynamic-security.json admin
```

Then, over MQTT (the plugin listens on `$CONTROL/dynamic-security/v1`):

```
mosquitto_ctrl -u admin -P <pw> -h localhost dynsec createClient alice
mosquitto_ctrl ... dynsec setClientPassword alice
mosquitto_ctrl ... dynsec createRole sensors
mosquitto_ctrl ... dynsec addRoleACL sensors subscribePattern 'sensors/#' allow 1
mosquitto_ctrl ... dynsec addRoleACL sensors publishClientSend 'sensors/%u/#' allow 1
mosquitto_ctrl ... dynsec createGroup fleet
mosquitto_ctrl ... dynsec addGroupRole fleet sensors 1
mosquitto_ctrl ... dynsec addGroupClient fleet alice 1
```

ACL types: `publishClientSend`, `publishClientReceive`, `subscribeLiteral`,
`subscribePattern`, `unsubscribeLiteral`, `unsubscribePattern`. Default ACL access is
`publishClientSend` deny, `publishClientReceive` allow, `subscribe` deny,
`unsubscribe` allow — i.e. deny-by-default for the things that matter.

In 2.1 the plugin auto-generates the JSON on first start if absent, creating roles
`broker-admin`, `client`, `dynsec-admin`, `super-admin`, `sys-notify`, `sys-observe`,
`topic-observe`. Initial admin password comes from `plugin_opt_password_init_file`,
the `MOSQUITTO_DYNSEC_PASSWORD` environment variable, or a **plaintext**
`<config-file>.pw` file that you must delete.

Charm recommendation: **support both modes.** Default to `password_file` + `acl_file`
because it is declarative, reproducible, and fits Juju's config-as-truth model —
the charm owns the files and rewrites them from config/relations. Offer dynsec as an
`auth_backend: dynsec` option for users who want runtime user management via
`mosquitto_ctrl`, and then make the charm *not* manage users (it becomes out-of-band
state, which conflicts with Juju's model). Be explicit about that trade-off in the
docs: with dynsec, `dynamic-security.json` becomes charm-owned-but-not-charm-authored
state that must be backed up.

The two are mutually exclusive in practice. Mixing `password_file` and dynsec on the
same listener produces confusing results; dynsec is intended as a replacement.

### 2.3 TLS

| Directive | Default | Charm treatment |
|---|---|---|
| `certfile <path>` | — | **[compute]** from the `tls-certificates` relation or user-supplied config. |
| `keyfile <path>` | — | **[compute]**. Must be mode `0640 root:mosquitto` or `0600 mosquitto:mosquitto` — see the 2.0 privilege-drop change. |
| `cafile <path>` | — | **[compute]** — needed for `require_certificate true`. |
| `capath <dir>` | — | alternative to `cafile`; needs `c_rehash`. Prefer `cafile`. |
| `crlfile <path>` | — | **[expose]**. Note: Mosquitto does not auto-reload CRLs on expiry; a CRL that has passed `nextUpdate` causes OpenSSL verification failures. A charm action to refresh the CRL + restart is worth having. |
| `dhparamfile <path>` | — | **[hardcode: do not emit]**. Only needed for classic-DH ciphersuites, which you should not be using. |
| `require_certificate true\|false` | `false` | **[expose]**, default `false`; `true` enables mTLS. |
| `use_identity_as_username true\|false` | `false` | **[expose]** — with `require_certificate true`, sets the MQTT username from the client cert CN, so your `acl_file` `user`/`%u` entries work off the certificate. This is the clean mTLS pattern. |
| `use_subject_as_username true\|false` | `false` | full DN instead of CN. Ugly in ACL files; prefer `use_identity_as_username`. |
| `disable_client_cert_date_checks` | `false` | **[hardcode `false`]**. |
| `tls_version tlsv1.2\|tlsv1.3` | both | **[expose]**, default **`tlsv1.2`** (meaning "1.2 or better" in 2.x). Recommend `tlsv1.3` where the client fleet allows. |
| `ciphers <openssl list>` | OpenSSL default | **[expose]**, default empty (inherit the distro's OpenSSL policy). If you must set one: `ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256`. |
| `ciphers_tls1.3 <list>` | OpenSSL default | **[expose]**, default empty. `TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256` if set. |
| `tls_engine`, `tls_keyform`, `tls_engine_kpass_sha1` | — | **[hardcode: do not use]** unless an HSM is in play. |
| `bridge_require_ocsp` | — | OCSP is available for *bridge* (outbound) connections only. There is **no OCSP stapling on the listener side** in Mosquitto — do not promise it. |

Cert generation guidance is in <https://mosquitto.org/man/mosquitto-tls-7.html>. The
important warning verbatim: *"It is important to use different certificate subject
parameters for your CA, server and clients."* Identical-looking subjects make
troubleshooting impossible and can break verification.

The server certificate CN (or better, a SAN) **must** match the hostname clients use.
For a charm this means the cert must cover the unit's public address and any
configured `external_hostname` — feed both into the CSR sent over the
`tls-certificates` relation.

`/usr/share/doc/mosquitto/README-letsencrypt.md` in the deb documents the Let's
Encrypt pattern. The essential point is the 2.0 privilege drop: the renewal hook must
`chown`/`chgrp` the new key to be readable by `mosquitto` **and** then reload, or the
broker will fail to start after renewal.

### 2.4 Persistence

| Directive | Default | Charm treatment |
|---|---|---|
| `persistence true\|false` | `false` (deb sets `true`) | **[expose]**, default **`true`**. |
| `persistence_location <dir>` | cwd (deb: `/var/lib/mosquitto/`) | **[compute]** — the Juju storage mount point if storage is attached, else `/var/lib/mosquitto/`. Must end with a `/` or be treated as a directory. |
| `persistence_file <name>` | `mosquitto.db` | **[hardcode]**. |
| `autosave_interval <s>` | `1800` | **[expose]**, default **`300`**. 1800 s means up to 30 minutes of retained-message and queued-message loss on an unclean stop. 300 s is a much better default for a managed service. |
| `autosave_on_changes true\|false` | `false` | **[expose]**, default `false`. When `true`, `autosave_interval` is reinterpreted as "save after N changes" rather than "after N seconds". Setting it `true` with a small interval will hammer the disk. |
| `persistent_client_expiration <duration>` | never | **[expose]**, default **`14d`**. Without this, every durable (clean-session-false / non-zero-session-expiry) client that never comes back keeps its queued messages forever. This is the classic slow memory leak. Units: `s`, `h`, `d`, `w`, `m`, `y` — e.g. `2w`, `14d`. |
| `queue_qos0_messages true\|false` | `false` | **[expose]**, default `false`. `true` queues QoS 0 messages for disconnected durable clients — usually a mistake, it turns a fire-and-forget channel into an unbounded queue. |
| `retain_available true\|false` | `true` | **[expose]**, default `true`. |
| `retain_expiry_interval <minutes>` | off | 2.1 only. **[expose]** — very useful for stopping retained-message accumulation. |
| `check_retain_source true\|false` | `true` | **[hardcode `true`]** — verifies the ACL of the original publisher when redelivering retained messages. |
| `upgrade_outgoing_qos` | `false` | **[hardcode `false`]** — non-standard behaviour. |
| `allow_duplicate_messages` | `true` | deprecated, removal planned. **Never emit.** |

**The persistence file is written on a timer, not on every change.** That is central
to backup (§4.4) and to the corruption failure mode (§8.4).

### 2.5 Limits and resource control

| Directive | 2.0 default | 2.1 default | Charm treatment |
|---|---|---|---|
| `max_inflight_messages <n>` | `20` | `20` | **[expose]**, default `20`. `0` = unlimited (dangerous). This is the broker's MQTT v5 Receive Maximum toward clients. |
| `max_inflight_bytes <n>` | `0` (unlimited) | `0` | **[expose]**, default `0`. |
| `max_queued_messages <n>` | `1000` | `1000` | **[expose]**, default `1000`. Per-client queue for QoS>0 to disconnected/slow durable clients. |
| `max_queued_bytes <n>` | `0` (unlimited) | `0` | **[expose]**, default **`0`** but strongly recommend setting it when payloads are large; it is a per-client byte cap and is checked *in addition to* `max_queued_messages` (whichever trips first). |
| `message_size_limit <bytes>` | `0` (unlimited) | `0` | **[expose]**, default `0`. Limits the PUBLISH *payload*. Superseded conceptually by `max_packet_size`. |
| `max_packet_size <bytes>` | `0` (→ 256 MB) | `2000000` | **[expose]**, default **`2000000`** regardless of version, so behaviour is identical across 2.0 and 2.1. Limits the whole MQTT packet and is advertised to v5 clients in CONNACK, so clients self-limit. Much better than `message_size_limit`. |
| `memory_limit <bytes>` | `0` (unlimited) | `0` | **[expose]**, default `0`. Sets an RLIMIT-like soft cap; when exceeded, the broker starts refusing to allocate (and will drop connections) rather than being OOM-killed. Consider computing it as ~70% of unit RAM. |
| `max_keepalive <0-65535>` | `65535` | `0` | **[expose]**, default `65535`. Caps the keepalive a v5 client may request; `0` = no limit. A low `max_keepalive` (e.g. `120`) means dead TCP connections are detected faster, at the cost of more PINGREQ traffic. There is no `min_keepalive` in mainline. |
| `receive_maximum` | — | — | **Not a broker directive.** It is the MQTT v5 property; the broker side is controlled by `max_inflight_messages` and, for bridges, `bridge_receive_maximum` (2.1). Do not expose a `receive_maximum` config option — it does not exist and users will file bugs. |
| `sys_interval <s>` | `10` | `10` | **[expose]**, default `10`. `0` disables `$SYS` entirely — do not do that, monitoring depends on it. |
| `global_max_connections`, `global_max_clients` | — | `-1` | 2.1 only. **[expose]** on 2.1. |

### 2.6 Logging

| Directive | Default | Charm treatment |
|---|---|---|
| `log_dest stdout\|stderr\|syslog\|topic\|file <path>\|dlt\|none` | `stderr` (deb: `file /var/log/mosquitto/mosquitto.log`) | **[expose]** as an enum. Recommend **`file /var/log/mosquitto/mosquitto.log`** as the default (matches the deb and logrotate) with an option for `stdout` so `journalctl -u mosquitto` works and COS log shipping is trivial. Multiple `log_dest` lines are allowed and are additive. |
| `log_type debug\|error\|warning\|notice\|information\|subscribe\|unsubscribe\|websockets\|none\|all` | `error, warning, notice, information` | **[expose]**, default `error warning notice information`. Multiple lines are additive. **Never default to `all` or `debug`** — on a busy broker `subscribe`/`unsubscribe`/`debug` logging is a self-inflicted DoS. |
| `connection_messages true\|false` | `true` | **[expose]**, default **`false`** for brokers with churning clients. Each connect and disconnect writes two log lines; with 10 000 flapping IoT clients this dominates disk I/O. Default `true` is fine for small deployments — make it a config option and document the trade-off. |
| `log_timestamp true\|false` | `true` | **[hardcode `true`]** for file logging; set `false` when `log_dest stdout` under systemd (journald adds its own timestamps). |
| `log_timestamp_format <strftime>` | seconds since epoch | **[expose]**, default `%Y-%m-%dT%H:%M:%S` — epoch seconds are unreadable and most log parsers dislike them. |
| `log_facility local0..local7` | `daemon` | **[expose]** only when `log_dest syslog`. |
| `websockets_log_level <bitmask>` | `0` | debugging only. |

`log_dest topic` republishes logs to `$SYS/broker/log/<level>` (`E`, `W`, `N`, `I`,
`D`, `M/subscribe`, `M/unsubscribe`, `WS`). Handy for remote debugging but it is
a privilege-escalation-ish information leak — anyone who can subscribe to `$SYS/#`
sees connection details. Gate it behind an ACL that only an admin user can read.

### 2.7 Bridges

Full set, from mosquitto.conf(5). A bridge block starts with `connection` and every
subsequent bridge directive applies to it until the next `connection`.

```
connection <name>                       # required, starts the block; must be unique
address <host>[:<port>] [<host>[:<port>] ...]   # or `addresses`; multiple = failover list
topic <pattern> [in|out|both] [qos] [local-prefix] [remote-prefix]
```

`topic` is repeatable and is the workhorse. Direction is from the perspective of the
local broker: `out` = publish local messages to the remote; `in` = subscribe on the
remote and republish locally; `both` = both (the default). QoS defaults to 0.
Prefixes let you remap: `topic sensors/# out 1 local/ remote/` takes
`local/sensors/#` locally and publishes to `remote/sensors/#`.

| Directive | Default | Notes / charm treatment |
|---|---|---|
| `bridge_protocol_version mqttv31\|mqttv311\|mqttv50` | `mqttv311` | **[expose]**, default **`mqttv50`** when both ends are 2.x — you get session expiry and receive maximum. |
| `remote_clientid <id>` | `<name>.<hostname>` | **[compute]** — make it deterministic and unique per unit, e.g. `<app>-<unit>-<connection>`. Two bridges sharing a client ID will endlessly disconnect each other. |
| `local_clientid <id>` | `local.<remote_clientid>` | **[compute]**. |
| `remote_username` / `remote_password` | — | **[expose]** via a Juju secret. |
| `local_username` / `local_password` | — | **[compute]** — the bridge's own local identity, which must exist in the password file and have ACLs. |
| `cleansession true\|false` | `false` | **[expose]**, default **`false`**. `false` means the *remote* keeps the bridge's session and queues messages while the bridge is down — essential for store-and-forward. `true` loses everything on disconnect. |
| `local_cleansession` | value of `cleansession` | **[expose]** — lets you have a durable remote session but a clean local one. |
| `keepalive_interval <s>` (≥5) | `60` | **[expose]**, default `60`. |
| `start_type automatic\|lazy\|once` | `automatic` | **[expose]**, default `automatic`. `lazy` connects on demand and disconnects after `idle_timeout`; `once` connects once and does not retry on failure. |
| `idle_timeout <s>` | `60` | only with `start_type lazy`. |
| `threshold <n>` | `10` | with `lazy`: number of queued messages that triggers a connect. |
| `restart_timeout <base> <cap> [stable]` or `<constant>` | `5 60` with jitter | **[expose]**, default `5 60`. Exponential backoff with jitter. |
| `round_robin true\|false` | `false` | **[expose]**, default `false`. With multiple `address` entries, `false` = the first address is primary and the bridge fails back to it when it returns; `true` = stay wherever you land. For an HA pair you usually want `false`. |
| `notifications true\|false` | `true` | **[expose]**, default `true`. Publishes bridge connection state as a retained message. |
| `notifications_local_only true\|false` | `false` | **[expose]**, default **`true`** — otherwise the bridge's state messages leak onto the remote broker. |
| `notification_topic <topic>` | `$SYS/broker/connection/<remote_clientid>/state` | **[compute]** — publish to a non-`$SYS` topic if you want ordinary clients to see it. Payload is `1` (connected) / `0` (disconnected). |
| `try_private true\|false` | `true` | **[expose]**, default **`true`**. Critical — see §6.2. Tells the remote broker "I am a bridge", so it will not echo a message back down the same connection. Prevents infinite loops between two Mosquitto brokers. Non-Mosquitto brokers may reject the CONNECT; set `false` for those. |
| `bridge_attempt_unsubscribe true\|false` | `true` | **[hardcode `true`]**. |
| `bridge_bind_address <ip>` | — | **[expose]** on multi-homed hosts. |
| `bridge_max_packet_size <bytes>` | `0` | **[expose]**. |
| `bridge_max_topic_alias` | `10` | 2.1. |
| `bridge_outgoing_retain true\|false` | `true` | **[expose]**, default `true`. `false` strips the retain flag on messages sent to the remote — useful to stop retained state propagating across a federation. |
| `bridge_receive_maximum <1-65535>` | `max_inflight_messages` | 2.1 only. |
| `bridge_session_expiry_interval <s>` or `0xFFFFFFFF` | `0` | 2.1, v5 only. `0xFFFFFFFF` = never expire. Pair with `cleansession false`. |
| `bridge_tcp_keepalive <idle> <interval> <count>` | disabled | **[expose]** — genuinely useful over NAT/firewalls that drop idle flows silently. e.g. `60 10 3`. |
| `bridge_tcp_user_timeout <ms>` | — | 2.1. |
| `bridge_reload_type lazy\|immediate` | `lazy` | 2.1. `immediate` reconnects the bridge on SIGHUP; `lazy` leaves an already-connected bridge alone. |
| `bridge_cafile` / `bridge_capath` | — | **[compute]**. |
| `bridge_tls_use_os_certs true\|false` | `false` | **[expose]** — set `true` when bridging to a public broker with a WebPKI cert; avoids shipping a CA bundle. |
| `bridge_certfile` / `bridge_keyfile` | — | **[compute]** — client cert for mTLS to the remote. |
| `bridge_insecure true\|false` | `false` | **[hardcode `false`]**. Disables hostname verification. The broker even logs `Warning: Bridge %s using insecure mode.` Never expose this without a scary name. |
| `bridge_require_ocsp` | — | **[expose]**. |
| `bridge_tls_version` | `tlsv1.2` | **[expose]**. |
| `bridge_ciphers` / `bridge_ciphers_tls1.3` | — | **[expose]**. |
| `bridge_identity` / `bridge_psk` | — | PSK-TLS bridging. |
| `bridge_alpn <string>` | — | needed when bridging through an ALPN-multiplexed endpoint. |

**Bridges ARE reloaded on SIGHUP** — one of the few complex subsystems that is. New
bridges are started and removed bridges are stopped without a restart.

### 2.8 `$SYS`

`sys_interval <seconds>` (default `10`) controls how often the `$SYS/broker/#` tree is
republished. `0` disables it. **[expose]**, default `10`. Do not go below ~5 s; the
broker recomputes the whole tree each time.

### 2.9 Miscellaneous

| Directive | Default | Charm treatment |
|---|---|---|
| `user <username>` | `mosquitto` | **[hardcode `mosquitto`]**. Not reloadable. Verbatim from the man page: *"When run as root, change to this user and its primary group on startup. If mosquitto is unable to change to this user and group, it will exit."* |
| `pid_file <path>` | — | **[hardcode]** — leave unset under `Type=notify` systemd; the deb ships it commented out. |
| `include_dir <dir>` | — | **[hardcode `/etc/mosquitto/conf.d`]**. Files are read in **alphabetical order**, only `*.conf`, **non-recursively**. Beware: a stale `.conf` left by a previous charm revision will still be read. The charm must own that directory and delete files it no longer manages. |

---

## 3. Security hardening — a prioritised checklist

### 3.1 Never `allow_anonymous true` in production (priority 1)

Default in 2.x is already `false`. The charm should keep it `false` and treat `true`
as an explicit, loudly-flagged decision. Combine with a `BlockedStatus` or at minimum
an `ActiveStatus` message such as `active (anonymous access enabled — insecure)`.

Note the asymmetry: a config file with **no** `listener` line makes anonymous access
the default. Since the charm always writes a `listener`, this does not bite, but a
user-supplied extra-config blob that removes the listener would silently re-enable it.

### 3.2 Password file (priority 1)

Generate with `mosquitto_passwd` — never hand-write.

```sh
# create (overwrites!):
mosquitto_passwd -c -b /etc/mosquitto/passwd alice 's3cr3t'
# add/update (no -c):
mosquitto_passwd -b /etc/mosquitto/passwd bob 'hunter2'
# delete:
mosquitto_passwd -D /etc/mosquitto/passwd bob
# upgrade a plaintext file in place:
mosquitto_passwd -U /etc/mosquitto/passwd
# choose hash explicitly:
mosquitto_passwd -H sha512-pbkdf2 -b /etc/mosquitto/passwd alice 's3cr3t'
```

Hashing (<https://mosquitto.org/man/mosquitto_passwd-1.html>):

- **2.1 default: `argon2id`.**
- **2.0 default: `sha512-pbkdf2`** (PBKDF2-HMAC-SHA512, salted, ~100k iterations,
  base64-encoded, `$7$...` prefix).
- `-H sha512` produces the legacy 1.6-compatible salted SHA-512 (`$6$...` — you can
  see this format in the shipped `pwfile.example`).

Choose the hash **explicitly** in the charm (`-H sha512-pbkdf2` on 2.0,
`-H argon2id` on 2.1) so the file is reproducible and so you know whether it will
survive a downgrade. An argon2id file **will not load on 2.0**.

`-b` puts the password on the command line, where it is visible in `ps` and shell
history. In a charm that is acceptable *only* if you use `subprocess` with an argv
list (no shell) and the machine is not shared — but the better pattern is to write to
stdin in interactive mode, or to write the file atomically yourself once you know the
format. The safest charm implementation is: `mosquitto_passwd -c -b <tmpfile> user pw`
in a `0600` temp file under `/etc/mosquitto/`, then `chmod 0640`, `chown
root:mosquitto`, then `os.replace()` onto `/etc/mosquitto/passwd`.

**Permissions.** Mosquitto checks and warns. The exact strings, extracted from the
2.0.18 binary:

```
Warning: File %s has world readable permissions. Future versions will refuse to load this file.
Warning: File %s owner is not %s. Future versions will refuse to load this file.To fix this, use `chown %s %s`.
Warning: File %s group is not %s. Future versions will refuse to load this file.
```

These are warnings in 2.0 but the intent is clear, and 2.1+ tightens them. So:

```
/etc/mosquitto/passwd   0640 root:mosquitto     (or 0600 mosquitto:mosquitto)
/etc/mosquitto/acl      0640 root:mosquitto
/etc/mosquitto/certs/*.key  0640 root:mosquitto
/etc/mosquitto/*.conf   0644 root:root          (no secrets in the config!)
/var/lib/mosquitto      0700 mosquitto:mosquitto
/var/log/mosquitto      0740 mosquitto:mosquitto
```

Also: `mosquitto_passwd` refuses to follow symlinks unless
`MOSQUITTO_UNSAFE_ALLOW_SYMLINKS` is set (added in 2.1.1). Never set that.

**Secrets in config:** `remote_password` for a bridge sits in a config file. Put
bridge config in a separate `/etc/mosquitto/conf.d/50-bridge.conf` with mode
`0640 root:mosquitto` rather than in the world-readable main config.

### 3.3 ACL file syntax, in full

From mosquitto.conf(5), verbatim on the essentials:

```
topic [read|write|readwrite|deny] <topic>
user <username>
pattern [read|write|readwrite|deny] <topic>
```

Rules:

- *"If this parameter is defined then only the topics listed will have access."*
  i.e. an `acl_file` is **deny by default**.
- The access type is optional (*unless `<topic>` contains a space*), and defaults to
  `readwrite`. **Always write it explicitly** — a topic containing a space silently
  changes parsing.
- `<topic>` may contain `+` and `#` wildcards, as in subscriptions.
- *"The 'deny' option can be used to explicitly deny access to a topic that would
  otherwise be granted by a broader read/write/readwrite statement. Any 'deny' topics
  are handled before topics that grant read/write access."* So `deny` always wins
  regardless of file order.
- *"The first set of topics are applied to anonymous clients, assuming
  `allow_anonymous` is true."* — everything before the first `user` line is the
  anonymous ACL.
- `user <username>` starts a per-user section. *"The username referred to here is the
  same as in `password_file`. It is not the clientid."*
- `pattern` supports substitution: **`%c`** = client ID, **`%u`** = username.
  *"The substitution pattern must be the only text for that level of hierarchy."*
  So `pattern write devices/%u/data` is valid; `pattern write devices/dev-%u/data`
  is **not**.
- *"Pattern ACLs apply to all users even if the 'user' keyword has previously been
  given."* — i.e. `pattern` lines are global, not scoped to the preceding `user`.
  A common mistake is writing `pattern` lines under a `user` block expecting them to
  apply only to that user. They do not.
- Read/write direction is from the *client's* perspective: `read` = the client may
  subscribe and receive; `write` = the client may publish.

Worked example the charm could generate:

```
# --- anonymous clients: nothing ---

# --- per-client isolation ---
pattern read  $SYS/broker/connection/%c/state
pattern write devices/%u/up
pattern read  devices/%u/down

# --- the monitoring user ---
user prometheus
topic read $SYS/#

# --- the bridge's local identity ---
user bridge-local
topic readwrite #

# --- an application ---
user app
topic readwrite app/#
topic deny app/internal/#
```

Note also that `$SYS/#` is **not** matched by `#`. A subscription to `#` does not
return `$SYS` topics — you must subscribe to `$SYS/#` explicitly. The same applies in
ACLs, so `topic read #` does not grant `$SYS` access. Good: it means the monitoring
grant must be deliberate.

### 3.4 TLS and client-certificate authentication (priority 1 for anything off-host)

Minimum viable production listener:

```
listener 8883 0.0.0.0
protocol mqtt
cafile   /etc/mosquitto/ca_certificates/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile  /etc/mosquitto/certs/server.key
tls_version tlsv1.2
```

mTLS, with certificate CN as the MQTT username:

```
require_certificate true
use_identity_as_username true
```

With `use_identity_as_username true`, `password_file` is not consulted for that
listener — the certificate *is* the credential — but the `acl_file` `user` and `%u`
entries still work, keyed on the CN. This is the cleanest pattern for a fleet with a
device PKI, and it plays well with Juju's `tls-certificates` interface.

Do not run 1883 and 8883 both exposed unless you have to. If you must (legacy
clients), use `per_listener_settings true` to give 1883 a stricter ACL, and accept the
trap in §3.5.

### 3.5 The `per_listener_settings` trap (priority 2)

Verbatim from mosquitto.conf(5):

> If `true`, then authentication and access control settings will be controlled on a
> per-listener basis. The following options are affected: `password_file`, `acl_file`,
> `psk_file`, `allow_anonymous`, `allow_zero_length_clientid`, `auto_id_prefix`,
> `plugin`, `plugin_opt_*`. Note that if set to `true`, then a durable client (i.e.
> with clean session set to `false`) that has disconnected will use the ACL settings
> defined for the listener that it was most recently connected to. The default
> behaviour is for this to be set to `false`.

The traps, concretely:

1. **Durable sessions carry their listener's ACLs with them.** A client that connects
   once on the permissive listener and then reconnects on the strict one retains the
   *old* listener's ACL until its session is cleaned. This is a real privilege
   escalation path. (2.0.23 fixed a related bug in per-listener handling of
   disconnected sessions — another reason 2.0.18 is a poor base.)
2. **Directive placement becomes load-bearing.** With `per_listener_settings true`,
   `password_file`/`acl_file`/`allow_anonymous` *must* appear after the `listener` line
   they belong to. If they appear before the first `listener`, they are global
   defaults; a config that "worked" with `false` can silently change meaning when
   flipped to `true`.
3. **`per_listener_settings` itself must appear before any `listener` line.**
4. **The dynamic security plugin wants `per_listener_settings false`.** The upstream
   dynsec docs say so explicitly.
5. It is **deprecated in 2.1** and slated for removal in 3.0.

Charm recommendation: **default `false`, and if you expose it at all, make the charm
refuse to enable it together with dynsec**, and validate that every affected directive
is emitted in the right block. Better still: do not expose it in v1 of the charm.

### 3.6 Run unprivileged

Already the default (`user mosquitto`). The only reason to run as root is binding a
port below 1024, which you should not do — MQTT's registered ports are 1883 and 8883,
both above 1024. If someone insists on port 443 for websockets, use
`AmbientCapabilities=CAP_NET_BIND_SERVICE` in a systemd drop-in rather than running as
root.

### 3.7 File permission enforcement

See §3.2. In addition: `/etc/mosquitto/conf.d/` must be `0755 root:root` and files in
it must not be world-writable. The charm should assert permissions on every
`config-changed`, not just on install — users do poke at these.

### 3.8 systemd sandboxing that is safe to add

The shipped unit has none. A charm-owned drop-in
(`/etc/systemd/system/mosquitto.service.d/10-charm.conf`) can safely add:

```ini
[Service]
# --- resource limits (see §7) ---
LimitNOFILE=65536

# --- restart behaviour ---
Restart=always
RestartSec=5s

# --- ordering ---
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
# --- sandboxing, verified safe for Mosquitto ---
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_CHOWN CAP_NET_BIND_SERVICE
UMask=0027

ReadWritePaths=/var/lib/mosquitto /var/log/mosquitto /run/mosquitto
ReadOnlyPaths=/etc/mosquitto
```

Caveats, learned the hard way:

- `ProtectSystem=strict` makes `/etc`, `/usr` and `/boot` read-only, so the
  `ExecStartPre=/bin/mkdir -m 740 -p /var/log/mosquitto` lines in the shipped unit
  would fail. Either add `/var/log` to `ReadWritePaths` (as above, the specific
  directory is enough since it already exists) or replace the `ExecStartPre` lines
  with `LogsDirectory=mosquitto` / `RuntimeDirectory=mosquitto` /
  `StateDirectory=mosquitto`, which is the modern idiom and also handles ownership.
- `PrivateDevices=true` is fine — Mosquitto needs only `/dev/urandom`, which is in
  the private `/dev`.
- `MemoryDenyWriteExecute=true` breaks **plugin loading via dlopen only if the plugin
  needs W^X**; the dynsec plugin does not. But if the user loads an arbitrary
  third-party auth plugin (e.g. one embedding a JIT or a Go runtime), drop this.
  Make it conditional on `plugin` being unset or being the dynsec plugin.
- `SystemCallFilter=@system-service` is fine for the broker. If you enable the
  systemd watchdog (2.1), no extra syscalls are needed.
- `CAP_SETUID`/`CAP_SETGID`/`CAP_CHOWN` are required because the broker starts as
  root and drops to `mosquitto`. If you instead set `User=mosquitto` in the drop-in
  and remove the `user` directive concern, you can drop those capabilities entirely —
  but then the `ExecStartPre` chowns must go too. Cleanest: `User=mosquitto`,
  `Group=mosquitto`, `StateDirectory=mosquitto`, `LogsDirectory=mosquitto`,
  `RuntimeDirectory=mosquitto`, `CapabilityBoundingSet=` (empty), and no
  `AmbientCapabilities`. Only viable if you never bind below 1024.
- `Restart=always` + `RestartSec=5s`: also add `StartLimitIntervalSec=0` or a
  generous `StartLimitBurst`, otherwise a crash loop leaves the unit in `failed` and
  systemd stops trying — which is sometimes what you want (so the charm can report
  `BlockedStatus`), and sometimes not. I would keep the limit and have the charm
  detect `failed` and report it.

### 3.9 Firewall and ports

- 1883/tcp — plain MQTT. Open only if you truly need it. Prefer localhost-only.
- 8883/tcp — MQTT over TLS. The one to expose.
- 8080/tcp, 8081/tcp — conventional plain/TLS websockets. Nothing is registered;
  9001 is also common.
- 9234/tcp — `sapcc/mosquitto-exporter` default. Bind to the Juju private address or
  localhost, never `0.0.0.0` — `$SYS` metrics leak client counts and traffic volumes.

For a Juju charm: `open-port` only the listeners actually configured, and close them
when disabled. Do not `open-port 1883` if only TLS is enabled.

TCP wrappers still work (the deb links `libwrap0`): `/etc/hosts.allow` with
`mosquitto: 10.0.0.0/8` is a crude but effective extra layer. Probably not worth the
charm managing it.

### 3.10 Known CVEs

Source: <https://mosquitto.org/security/> plus the upstream `ChangeLog.txt` and NVD.

| CVE | Affects | Fixed in | Summary |
|---|---|---|---|
| CVE-2024-10525 | 1.3.2 – 2.0.18 | 2.0.19 | Malicious **broker** sends a SUBACK with no reason codes → out-of-bounds read in libmosquitto's `on_subscribe` callback. Affects *clients*/bridges, not the broker as server. Relevant if the charm bridges to an untrusted broker. |
| CVE-2024-3935 | 2.0.0 – 2.0.18 | 2.0.19 | Outgoing bridge with **incoming topic remapping**: a crafted PUBLISH causes a double free and broker crash. Directly relevant to any charm that configures bridges with local/remote prefixes. |
| CVE-2023-0809 | 1.5.0 – 2.0.15 | 2.0.16 | Excessive memory allocated from a malicious initial (non-CONNECT) packet — pre-auth memory exhaustion DoS. |
| CVE-2023-3592 | 1.6.0 – 2.0.15 | 2.0.16 | Memory leak on v5 CONNECT with invalid will-property types. |
| CVE-2023-28366 | 1.3.2 – 2.0.15 | 2.0.16 | Memory leak from unacknowledged QoS 2 messages with duplicate message IDs. Further hardened in **2.0.21** ("fix leak on malicious SUBSCRIBE by authenticated client"). |
| CVE-2021-34434 | 2.0.0 – 2.0.11 | 2.0.12 | ACL bypass: when using a plugin with `per_listener_settings`, the ACL check could be skipped. |
| CVE-2021-28166 | 2.0.0 – 2.0.9 | 2.0.10 | Crash (NULL deref) on a v5 CONNECT with a zero-length username property. |
| CVE-2019-11779 | 1.5 – 1.6.5 | 1.6.6, 1.5.9 | Crafted SUBSCRIBE with a very large topic hierarchy → stack overflow. |
| CVE-2019-11778 | 1.6 – 1.6.4 | 1.6.5 | Payload/packet handling crash. |
| CVE-2018-20145 | 1.5 – 1.5.4 | 1.5.5 | ACL bypass on `#` subscriptions with pattern ACLs. |
| CVE-2018-12543 | 1.5 – 1.5.2 | 1.5.3 | Crafted packet DoS. |
| CVE-2017-7650 / 7651 / 7652 / 7653 / 7654 / 7655 / 9868 | 0.15 – 1.4.x | 1.4.12–1.5 | Pattern ACL bypass with `+`/`#` in username/client ID (7650 — hence `auth_plugin_deny_special_chars`), memory leaks, DoS, and a persistence-file permissions issue. |

**Implication for the charm:** 2.0.18 (noble's `universe` build) is vulnerable to
CVE-2024-3935 and CVE-2024-10525 and lacks the 2.0.21 SUBSCRIBE leak fix, unless the
ESM Apps build backports them. The charm should:

- report the installed version in status;
- refuse (or loudly warn) to configure bridges on < 2.0.19 because of CVE-2024-3935;
- prefer/document the PPA (2.1.2) or Ubuntu Pro ESM.

---

## 4. Day-2 operations

### 4.1 SIGHUP semantics — exactly what is and is not reloaded

This is the critical decision table for the charm. Compiled directly from the
"Reloaded on reload signal" / "Not reloaded on reload signal" annotations in
mosquitto.conf(5).

**Reload (SIGHUP) is sufficient for:**

```
acl_file                    autosave_interval           autosave_on_changes
allow_anonymous             allow_duplicate_messages    allow_zero_length_clientid
connection_messages         enable_control_api*         global_max_clients*
global_max_connections*     log_dest                    log_timestamp
log_timestamp_format        log_type                    max_inflight_bytes
max_inflight_messages       max_keepalive               max_packet_size
max_queued_bytes            max_queued_messages         memory_limit
message_size_limit          password_file               per_listener_settings
persistence                 persistence_file            persistence_location
persistent_client_expiration                            psk_file
queue_qos0_messages         retain_available            retain_expiry_interval*
set_tcp_nodelay             sys_interval                upgrade_outgoing_qos
accept_protocol_versions*
ALL bridge configuration (connection blocks) — bridges are added/removed/restarted
```
(`*` = 2.1 only.)

SIGHUP also **re-reads the TLS certificate and key files from disk** and **closes and
reopens the log file** (per mosquitto(8)). So certificate *renewal* — same paths, new
file contents — needs only a reload. Changing the *paths* does not.

**A full restart is required for:**

```
listener  (adding, removing, or changing port/bind address)
port, bind_address, bind_interface
socket_domain
protocol
max_connections            (per-listener)
max_qos                    (per-listener)
mount_point
use_username_as_clientid
listener_allow_anonymous
ALL listener TLS options: cafile, capath, certfile, keyfile, crlfile, dhparamfile,
  require_certificate, use_identity_as_username, use_subject_as_username,
  tls_version, ciphers, ciphers_tls1.3, tls_engine, tls_keyform,
  disable_client_cert_date_checks
  (the *paths*; the file *contents* are re-read on SIGHUP)
psk_hint
user
pid_file
plugin, global_plugin, plugin_opt_*   ("Not currently reloaded")
auth_plugin_deny_special_chars
enable_proxy_protocol, proxy_protocol_v2_require_tls
http_dir
packet_buffer_size, websockets_headers_size, websockets_origin
```

Plus, obviously: a package upgrade, and any change to the systemd unit (which needs
`daemon-reload` first).

**Charm implementation.** Render the new config to a temp file, diff it against the
current one at the *directive* level (not textually — comment and ordering churn
should not trigger restarts), classify each changed directive against the two lists
above, and then:

- no changes → do nothing;
- only reload-safe changes → `systemctl reload mosquitto` (i.e. `kill -HUP`);
- any restart-only change → `systemctl restart mosquitto`.

Encode the lists as two explicit Python sets in the charm, with a **default of
"restart" for any directive not in either set**. That fail-safe matters because the
lists change between 2.0 and 2.1.

A SIGHUP **does not drop client connections**. A restart drops every connection;
clients with `cleansession false` / non-zero session expiry will get their queued
QoS>0 messages on reconnect, but QoS 0 traffic in flight is lost and every client
sees a disconnect. So the reload/restart distinction is genuinely user-visible and
worth getting right.

On 2.1, `mosquitto_signal config-reload` / `-a` is an alternative to `kill -HUP`, and
`mosquitto_signal log-rotate` (SIGRTMIN) reopens the log **without** re-reading the
config — use that for logrotate.

### 4.2 Graceful shutdown

`SIGTERM` (what `systemctl stop` sends) makes the broker: stop accepting new
connections, write the persistence database to disk if `persistence true`, and exit.
There is no "drain" mode and no way to tell clients to go elsewhere (Mosquitto does
not implement the MQTT v5 server-redirect DISCONNECT). So a stop is always abrupt from
the client's perspective.

Give the unit a generous `TimeoutStopSec` (say `30s`) so a large persistence write is
not SIGKILLed halfway — that is one of the ways `mosquitto.db` gets corrupted.

`SIGUSR1` forces an immediate persistence write without stopping. **The charm should
send SIGUSR1 before any backup and before any restart or upgrade.**

`SIGUSR2` dumps the subscription tree and retained messages to the log. Debug only;
on a large broker it produces an enormous amount of output. Expose it as a charm
action (`dump-tree`) with a warning, not as anything automatic.

### 4.3 What changes require a restart

See §4.1. In practice for a charm: port changes, TLS enable/disable, cert path
changes, plugin changes (dynsec on/off), `user`, and package upgrades. Everything else
— users, ACLs, limits, logging, bridges — is reloadable.

### 4.4 Backup and restore

**What actually needs backing up:**

| Path | What it is | Backup? |
|---|---|---|
| `/var/lib/mosquitto/mosquitto.db` | retained messages, durable session state, queued QoS>0 messages, subscriptions | **yes** (with care, below) |
| `/etc/mosquitto/passwd` | hashed credentials | **yes** — irreplaceable, and hashes cannot be regenerated from Juju config if passwords were user-supplied |
| `/etc/mosquitto/acl` | ACLs | yes (usually regenerable from charm config) |
| `/var/lib/mosquitto/dynamic-security.json` | dynsec users/roles/groups, if dynsec is in use | **yes** — this is *the* authoritative store in dynsec mode and contains password hashes |
| `/etc/mosquitto/certs/`, `/etc/mosquitto/ca_certificates/` | TLS material | yes, unless issued by a `tls-certificates` provider that can reissue |
| `/etc/mosquitto/mosquitto.conf`, `/etc/mosquitto/conf.d/*.conf` | config | nice to have; regenerable from Juju config |
| `/var/log/mosquitto/` | logs | no (ship them instead) |

**The safe way to back up `mosquitto.db`.** The file is only written on
`autosave_interval` (default 1800 s), on SIGUSR1, and on clean shutdown. It is written
as `mosquitto.db.new` and then renamed over `mosquitto.db`, so a naive copy can catch
a partially-written `.new` or a stale `.db`. The correct sequence:

```sh
kill -USR1 "$(systemctl show -p MainPID --value mosquitto)"   # force a write
sleep 2                                                        # let it complete
cp -a /var/lib/mosquitto/mosquitto.db "$BACKUP/mosquitto.db"
```

Better still, on a filesystem that supports it, take an LVM/ZFS/cloud snapshot after
the SIGUSR1. Best of all for a charm: a `create-backup` action that stops the broker,
copies everything, and starts it again — accepting a few seconds of downtime in
exchange for a guaranteed-consistent copy. Offer both (`--consistent` flag).

**Restore:** stop the broker, replace the files, `chown mosquitto:mosquitto
/var/lib/mosquitto/mosquitto.db`, `chmod 0600`, start. Restoring a `mosquitto.db`
from a *different major version* is not supported — the persistence file format has a
version field and the broker will refuse ("Unable to restore persistent database.
Unrecognised file format."). Downgrades in particular will fail.

The charm should expose actions: `create-backup`, `restore-backup`,
`force-persist` (SIGUSR1), `list-backups`.

### 4.5 Config validation before applying

**On 2.1+: `mosquitto --test-config -c /path/to/candidate.conf`** — parses the config,
reports errors, exits without starting the broker. Introduced in 2.1. This is exactly
the dry run a charm wants.

**On 2.0 there is no `--test-config`.** Options, in decreasing order of goodness:

1. Start a throwaway broker on a scratch config with a listener on a free high port
   bound to `127.0.0.1`, with `persistence false`, `log_dest stdout`, and a short
   timeout; if it reaches "mosquitto version X starting" / "Opening ipv4 listen socket"
   without an error, the config parses. Then kill it. Roughly:
   ```sh
   timeout 3 mosquitto -c "$CANDIDATE" -v 2>&1 | tee /tmp/check.log
   grep -qE '^Error:|Unable to|unknown' /tmp/check.log && exit 1
   ```
   Pitfalls: you must rewrite `listener`/`persistence_location`/`log_dest`/`pid_file`
   in the candidate so it does not collide with the running broker or touch its state.
   This is fiddly but it is the only real pre-flight on 2.0.
2. Validate in the charm itself: the charm generates the config, so it can validate
   its own inputs (port ranges, file existence, enum values, mutually-exclusive
   settings) before writing anything. **This is the main line of defence** and you
   should do it regardless of version.
3. Keep the previous config and roll back: write the new config, reload/restart,
   check `systemctl is-active` and an MQTT-level health check (§5.2); if it fails,
   restore the previous config, restart, and set `BlockedStatus` describing the
   failure. This safety net is cheap and catches everything, including semantic errors
   a parse check would miss (e.g. a cert the `mosquitto` user cannot read).

Note that a broker with `Type=notify` will cause `systemctl start`/`restart` to fail
cleanly if the config is bad, which makes detection easy — but `systemctl reload` will
**not** fail, because the reload is asynchronous. After a reload, check the log for
errors and verify with a health check.

### 4.6 Upgrade procedure

```
1. juju config <app> ... (no changes) ; ensure status is active
2. Run the backup action (or SIGUSR1 + copy).
3. Note the current version (mosquitto -h | head -1, or dpkg-query).
4. apt-get update && apt-get install --only-upgrade mosquitto mosquitto-clients
   (or snap refresh mosquitto --channel=<track>)
5. The deb postinst restarts the service automatically via deb-systemd-invoke.
   The charm should not assume it is still stopped.
6. Re-assert file permissions (a package upgrade can reset /etc conffiles).
7. Re-render and validate the config (new version may deprecate directives).
8. Health-check (§5.2). If it fails, roll back the package and restore the backup.
```

Version-specific gotchas:

- **2.0 → 2.1:** `max_packet_size` default changes 0 → 2 000 000. If the charm always
  emits an explicit value, this is a non-event — another argument for the charm
  emitting explicit values for every directive it cares about rather than relying on
  defaults.
- **2.0 → 2.1:** `mosquitto_passwd` default hash changes to argon2id. Existing files
  keep working; newly added users get argon2id and the file can no longer be read by
  2.0. Pin the hash explicitly.
- **2.1 → future 3.0:** `acl_file`, `password_file` and `per_listener_settings` are
  slated for removal. Plan the migration path to the file plugins / dynsec now.
- **1.x → 2.x:** the `allow_anonymous` and listener-binding changes (§1.2). The charm
  always writes an explicit `allow_anonymous` and an explicit `listener`, so it is
  immune — but a user migrating hand-rolled config into the charm is not.
- **Never downgrade** across a persistence-format change.

---

## 5. Health, monitoring and metrics

### 5.1 The complete `$SYS/broker/#` tree

Extracted directly from the 2.0.18 broker binary, so this is exhaustive for 2.0.
Republished every `sys_interval` seconds (default 10). All values are the retained
payload of the topic as an ASCII string.

**Static / identity**

| Topic | Meaning |
|---|---|
| `$SYS/broker/version` | Broker version string, e.g. `mosquitto version 2.0.18`. Use for an `up`-style info metric and to drive version alerts. |
| `$SYS/broker/uptime` | Seconds since start, as `"NNN seconds"`. **Alert on a sudden drop — it means the broker restarted.** |
| `$SYS/broker/timestamp` | Build timestamp. Static. (Present in some builds; the exporter reads it.) |

**Clients**

| Topic | Meaning |
|---|---|
| `$SYS/broker/clients/connected` | Currently connected clients. **The key capacity metric.** |
| `$SYS/broker/clients/disconnected` | Registered (durable, persistent) clients that are not currently connected. **Alert if this grows without bound — it is queued state you are paying for.** |
| `$SYS/broker/clients/total` | connected + disconnected (i.e. all known sessions). |
| `$SYS/broker/clients/maximum` | High-water mark of simultaneous connections since start. **Compare against `max_connections` and `LimitNOFILE`.** |
| `$SYS/broker/clients/expired` | Sessions removed by `persistent_client_expiration`. A non-zero, growing value tells you the expiration setting is doing work. |
| `$SYS/broker/clients/active` | **Deprecated** alias of `connected`. |
| `$SYS/broker/clients/inactive` | **Deprecated** alias of `disconnected`. |

**Traffic counters** (monotonic since start — use `rate()`)

| Topic | Meaning |
|---|---|
| `$SYS/broker/bytes/received` / `bytes/sent` | All bytes, all MQTT packet types. |
| `$SYS/broker/messages/received` / `messages/sent` | All MQTT *packets* of any type (including PINGREQ/PINGRESP, SUBSCRIBE, etc.). |
| `$SYS/broker/publish/messages/received` / `publish/messages/sent` | PUBLISH packets only. **This is your actual message throughput.** |
| `$SYS/broker/publish/bytes/received` / `publish/bytes/sent` | PUBLISH bytes only. |
| `$SYS/broker/publish/messages/dropped` | **PUBLISH messages dropped because of inflight/queue limits. The single most important error metric. Any non-zero rate means you are losing messages.** |

**Storage / memory**

| Topic | Meaning |
|---|---|
| `$SYS/broker/messages/stored` | Messages currently held by the broker (retained + queued). Alias of `store/messages/count`. **Unbounded growth = leak.** |
| `$SYS/broker/store/messages/count` | Same as above, explicit name. |
| `$SYS/broker/store/messages/bytes` | Bytes held. **Alert on this against `memory_limit`/RAM.** |
| `$SYS/broker/retained messages/count` | Retained-message count. Note the **space in the topic name** — it will trip naive metric-name mangling. **Growth here is the classic "retained messages never expire" leak.** |
| `$SYS/broker/subscriptions/count` | Total active subscriptions. |
| `$SYS/broker/shared_subscriptions/count` | Shared-subscription groups. |
| `$SYS/broker/heap/current` | Current heap usage in bytes (only if built with memory tracking, which the Debian build is). **Primary memory alert.** |
| `$SYS/broker/heap/maximum` | Peak heap since start. |

**Load averages** — moving averages over 1/5/15 minutes, in units per minute. Each of
the following has `/1min`, `/5min`, `/15min` variants:

```
$SYS/broker/load/messages/received/{1,5,15}min
$SYS/broker/load/messages/sent/{1,5,15}min
$SYS/broker/load/publish/received/{1,5,15}min
$SYS/broker/load/publish/sent/{1,5,15}min
$SYS/broker/load/publish/dropped/{1,5,15}min
$SYS/broker/load/bytes/received/{1,5,15}min
$SYS/broker/load/bytes/sent/{1,5,15}min
$SYS/broker/load/connections/{1,5,15}min
$SYS/broker/load/sockets/{1,5,15}min
```

`load/connections` = MQTT CONNECT packets per minute (**a high value indicates client
flapping**). `load/sockets` = new TCP sockets per minute; if `sockets` far exceeds
`connections`, something is opening TCP connections without completing MQTT CONNECT —
a scanner, a broken client, or a failing TLS handshake.

**Log republishing** (only when `log_dest topic` is set)

```
$SYS/broker/log/E   errors
$SYS/broker/log/W   warnings
$SYS/broker/log/N   notices
$SYS/broker/log/I   information
$SYS/broker/log/D   debug
$SYS/broker/log/M/subscribe
$SYS/broker/log/M/unsubscribe
$SYS/broker/log/WS  websockets
```

**Bridge state**

```
$SYS/broker/connection/<remote_clientid>/state    payload "1" (up) or "0" (down), retained
```

**Alert-worthy, in priority order:** `publish/messages/dropped` rate > 0;
`clients/connected` approaching `max_connections`; `uptime` resetting;
`heap/current` or `store/messages/bytes` growing monotonically;
`retained messages/count` growing monotonically; `clients/disconnected` growing
monotonically; `load/connections/1min` spiking (flapping); any
`$SYS/broker/connection/*/state` == 0.

### 5.2 How to health-check properly

**TCP connect is not enough.** A broker can accept TCP while being wedged, out of
memory, unable to authenticate anyone, or refusing every CONNECT with "not
authorised". It can also accept TCP while the TLS handshake fails because a renewed
certificate is unreadable.

The right check is a **full MQTT round trip**: CONNECT → SUBSCRIBE → PUBLISH →
receive own message → DISCONNECT, on a topic reserved for the purpose.

```sh
# On the unit, using mosquitto-clients.
TOPIC="\$SYS/../charm/healthcheck"   # better: a plain topic the ACL restricts
TOPIC="charm/health/$(hostname)"
NONCE="$(date +%s%N)"

# mosquitto_rr does exactly this: publish, then wait for a response.
timeout 5 mosquitto_sub \
    -h 127.0.0.1 -p 1883 \
    -u "$HEALTH_USER" -P "$HEALTH_PASS" \
    -i "charm-health-$$" \
    -t "$TOPIC" -C 1 -W 5 -q 1 &
SUB=$!
sleep 0.3
mosquitto_pub -h 127.0.0.1 -p 1883 \
    -u "$HEALTH_USER" -P "$HEALTH_PASS" \
    -i "charm-health-pub-$$" \
    -t "$TOPIC" -m "$NONCE" -q 1
wait $SUB
```

Neater, using `mosquitto_rr(1)`, which is purpose-built for request/response and
exists precisely for this:

```sh
timeout 5 mosquitto_rr -h 127.0.0.1 -p 1883 \
    -u "$HEALTH_USER" -P "$HEALTH_PASS" \
    -t charm/health/req -e charm/health/req -m ping -q 1
```

Design notes for the charm:

- Create a dedicated `_charm_health` user in the password file, with an ACL granting
  **only** `readwrite charm/health/#`. Never health-check as an admin user.
- Use QoS 1 so you exercise the PUBACK path, not just fire-and-forget.
- Use a unique client ID per check so you never collide with a stuck previous check.
- Check the **TLS listener** too if TLS is enabled, with `--cafile` — this is the only
  way to catch an unreadable or expired server key after a renewal.
- Optionally also read `$SYS/broker/uptime` in the same connection; it gives you
  version/uptime for status output essentially free.
- Run it on `update-status` and after every reload/restart. Feed the result into
  `ActiveStatus` / `BlockedStatus`.
- Do **not** use `$SYS` topics for the round-trip itself — clients cannot publish to
  `$SYS`.

### 5.3 Prometheus exporters

| Project | What it does | Packaging | Maintenance | Verdict |
|---|---|---|---|---|
| **[sapcc/mosquitto-exporter](https://github.com/sapcc/mosquitto-exporter)** | Connects as an MQTT client, subscribes to `$SYS/#`, exposes every `$SYS` value as a Prometheus counter/gauge named from the topic (`$SYS/broker/` stripped, `/` → `_`). Flags: `--endpoint` (default `tcp://127.0.0.1:1883`), `--bind-address` (default `0.0.0.0:9234`), `--user`, `--pass`, `--cert`, `--key`, `--client-id`. Env vars `BROKER_ENDPOINT`, `BIND_ADDRESS`, `MQTT_USER`, `MQTT_PASS`. Apache-2.0. | Go static binary from GitHub releases; Docker `sapcc/mosquitto-exporter`. **No deb, no snap.** | Latest release **v0.8.0** (Go 1.17 era, ~2021/22). Low activity, ~148 stars. Functional but effectively dormant. | **Recommended, with reservations.** It is the only thing that does the right job (broker metrics from `$SYS`) with no configuration. Vendor the binary in the charm, or better, write the equivalent yourself — see below. |
| **[hikhvar/mqtt2prometheus](https://github.com/hikhvar/mqtt2prometheus)** | Translates *arbitrary JSON payloads published by devices* on MQTT topics into Prometheus metrics, driven by a YAML mapping. | Go binary, Docker, Helm. Actively maintained. | Active. | **Wrong tool.** It monitors the *fleet*, not the *broker*. It will not give you `clients/connected` or `publish/messages/dropped` without you writing a mapping for every `$SYS` topic by hand. Do not ship it as the broker exporter. |
| **[kpetremann/mqtt-exporter](https://github.com/kpetremann/mqtt-exporter)** | Same category as mqtt2prometheus — generic MQTT-payload-to-Prometheus for IoT. | Python, Docker, Helm. | Active. | Wrong tool, same reason. |
| **[tyriis/node.prometheus-mosquitto-exporter](https://github.com/tyriis/node.prometheus-mosquitto-exporter)** | Node.js `$SYS` exporter. | npm/Docker. | Low activity. | Adds a Node runtime dependency to a machine charm. No. |
| **[uhlig-it/mosquitto-prometheus-exporter](https://github.com/uhlig-it/mosquitto-prometheus-exporter)** | Another `$SYS` exporter. | Binary. | Low activity. | Marginal. |
| **Roll your own inside the charm** | The charm already needs an MQTT client for health checks. Subscribing to `$SYS/#` and writing a `.prom` file for `node_exporter`'s textfile collector, or serving `/metrics` from a small thread, is maybe 150 lines of Python. | Part of the charm. | You maintain it. | **Seriously consider this.** It removes a dormant third-party binary from the supply chain, needs no extra port, no extra credentials plumbed through, and integrates cleanly with COS via `grafana-agent`'s textfile collector or the charm's own `metrics_endpoint`. |

**Recommendation:** ship `sapcc/mosquitto-exporter` as the default (it is the de facto
standard and the metric names are what existing dashboards expect), pinned to a
vendored release binary, running as its own systemd unit bound to the Juju private
address on 9234, authenticating with a dedicated `_prometheus` user that has
`topic read $SYS/#` and nothing else. Expose `enable_metrics` (default `true`) and
`metrics_port` (default `9234`). But design the charm's metrics integration so that
swapping to an in-charm `$SYS` scraper later does not break the relation contract —
i.e. relate via `prometheus_scrape` / `COSAgentProvider` rather than hard-coding the
exporter.

Metric names produced by sapcc (topic with `$SYS/` stripped, `/` → `_`):
`broker_clients_connected`, `broker_clients_disconnected`, `broker_clients_maximum`,
`broker_clients_total`, `broker_clients_expired`, `broker_messages_received`,
`broker_messages_sent`, `broker_messages_stored`, `broker_publish_messages_received`,
`broker_publish_messages_sent`, `broker_publish_messages_dropped`,
`broker_publish_bytes_received`, `broker_publish_bytes_sent`, `broker_bytes_received`,
`broker_bytes_sent`, `broker_uptime`, `broker_heap_current`, `broker_heap_maximum`,
`broker_subscriptions_count`, `broker_retained_messages_count`, plus the
`broker_load_*` family. Confirm exact spellings against the running exporter before
writing alert rules — the `retained messages` topic with its embedded space is the
one to check.

### 5.4 Grafana dashboards

- Grafana.com dashboard **ID 11542** ("Mosquitto MQTT Broker") is the most widely used
  one for `sapcc/mosquitto-exporter` metrics.
- Grafana.com **ID 13233** and **ID 16745** are other community Mosquitto dashboards.
- There is no official upstream dashboard. Mosquitto 2.1 ships its own built-in Web UI
  (`protocol http_api`), which is a different thing — useful for ad-hoc inspection,
  not a replacement for Grafana, and an extra listener to secure.

For a charm targeting COS, the right move is to **ship your own dashboard JSON** in
`src/grafana_dashboards/` via `COSAgentProvider`/`GrafanaDashboardProvider`, built
around the metric names above, with rows for: connections, throughput, drops, storage,
bridges. Do not depend on a community dashboard ID being fetchable at deploy time.

### 5.5 Alert rules worth shipping

```yaml
groups:
- name: mosquitto
  rules:

  # The broker is gone.
  - alert: MosquittoDown
    expr: up{juju_charm="mosquitto"} == 0
    for: 2m
    labels: {severity: critical}
    annotations:
      summary: "Mosquitto broker on {{ $labels.juju_unit }} is not responding"

  # Messages are being thrown away. This is data loss.
  - alert: MosquittoMessagesDropped
    expr: rate(broker_publish_messages_dropped[5m]) > 0
    for: 5m
    labels: {severity: critical}
    annotations:
      summary: "Mosquitto is dropping PUBLISH messages on {{ $labels.juju_unit }}"
      description: >-
        {{ $value | printf "%.2f" }} msg/s dropped. Raise max_queued_messages /
        max_inflight_messages, or find the slow subscriber.

  # Unexpected restart (uptime counter went backwards).
  - alert: MosquittoRestarted
    expr: broker_uptime < 300 and (broker_uptime offset 10m) > 300
    labels: {severity: warning}
    annotations:
      summary: "Mosquitto on {{ $labels.juju_unit }} restarted in the last 5 minutes"

  # Approaching the connection ceiling.
  - alert: MosquittoConnectionsNearLimit
    expr: broker_clients_connected / on(juju_unit) mosquitto_max_connections > 0.85
    for: 10m
    labels: {severity: warning}
    annotations:
      summary: "Mosquitto at {{ $value | humanizePercentage }} of max_connections"
  # (If you have no max_connections metric, use an absolute threshold derived from
  #  the charm's configured value, or compare against LimitNOFILE from node_exporter:
  #  broker_clients_connected > 0.85 * process_max_fds{job="mosquitto"} )

  # Memory creeping up — usually retained messages or abandoned durable sessions.
  - alert: MosquittoHeapGrowth
    expr: |
      broker_heap_current > 1.5e9
      or deriv(broker_heap_current[6h]) > 1e5
    for: 30m
    labels: {severity: warning}
    annotations:
      summary: "Mosquitto heap on {{ $labels.juju_unit }} growing steadily"

  # Stored message backlog.
  - alert: MosquittoStoredMessagesHigh
    expr: broker_messages_stored > 100000
    for: 15m
    labels: {severity: warning}

  # Retained messages accumulating without bound.
  - alert: MosquittoRetainedMessagesGrowth
    expr: deriv(broker_retained_messages_count[24h]) > 10
    for: 2h
    labels: {severity: warning}
    annotations:
      summary: "Retained message count growing ~{{ $value | printf "%.1f" }}/s — consider retain_expiry_interval"

  # Abandoned durable sessions accumulating.
  - alert: MosquittoDisconnectedSessionsHigh
    expr: broker_clients_disconnected > 5000
    for: 1h
    labels: {severity: warning}
    annotations:
      summary: "Many persistent sessions with no connected client — set persistent_client_expiration"

  # Clients flapping.
  - alert: MosquittoClientFlapping
    expr: broker_load_connections_1min > 5 * broker_clients_connected
    for: 15m
    labels: {severity: warning}
    annotations:
      summary: "Connection rate far exceeds steady-state client count — clients are reconnecting in a loop"

  # TCP connections that never become MQTT sessions (scanners, TLS failures).
  - alert: MosquittoSocketConnectMismatch
    expr: broker_load_sockets_1min > 3 * broker_load_connections_1min and broker_load_sockets_1min > 60
    for: 15m
    labels: {severity: warning}

  # A bridge is down.  (Requires exporting $SYS/broker/connection/+/state;
  #  sapcc does export it as broker_connection_<id>_state.)
  - alert: MosquittoBridgeDown
    expr: mosquitto_bridge_state == 0
    for: 5m
    labels: {severity: critical}

  # TLS certificate expiry — from a blackbox_exporter probe of 8883, not from $SYS.
  - alert: MosquittoCertExpiringSoon
    expr: probe_ssl_earliest_cert_expiry{job="mosquitto-tls"} - time() < 14*24*3600
    labels: {severity: warning}
```

Two of those deserve emphasis: **`publish/messages/dropped` is the only metric that
directly means "you lost data"**, and **`clients/disconnected` growing without bound**
is the leading indicator of the slow memory leak that eventually takes the broker out.

---

## 6. Clustering, HA and scaling — the honest truth

### 6.1 Mosquitto does not cluster. Full stop.

There is no state replication, no shared subscription state across nodes, no leader
election, no consensus, no shared session store. A Mosquitto broker is a single
process holding all retained messages, all subscriptions and all session state in its
own memory, flushed periodically to one local file. Two Mosquitto processes are two
independent brokers.

Anyone who tells you otherwise is describing either (a) bridging, (b) a commercial
product built on Mosquitto (Cedalo Pro Mosquitto, which adds "Full Sync" active/passive
and "Dynamic-Security Sync" active/active clustering —
<https://www.cedalo.com/pro-mosquitto/high-availability>), or (c) a different broker.

### 6.2 What the real options are

**(a) Bridging.** Two or more independent brokers linked by `connection` blocks.
Messages flow, but **sessions, retained messages and subscriptions do not
synchronise**. A client that reconnects to the other broker gets a fresh session.
Retained messages propagate only for the topics the bridge is configured to carry, and
only going forward — a bridge coming up does not back-fill the peer's existing
retained set (unless the peer re-publishes).

Topologies:

- **Hub and spoke.** Edge brokers bridge `out` to a central broker. The standard IoT
  pattern; no loops by construction. Use `cleansession false` on the spoke so edge
  data queues during a WAN outage.
- **Full mesh.** Every broker bridges to every other. Loops are the danger.
- **Tree / hierarchy.** Site → region → central. Loop-free, scales, and lets you use
  `mount_point` or topic prefixes to namespace each site.

**Loop avoidance.** The mechanism is `try_private true` (the default). The bridge
tells the remote broker "I am a bridge" in the CONNECT; a Mosquitto remote then will
not echo a message back down the connection it arrived on. This prevents the trivial
A→B→A loop. It does **not** prevent a longer cycle A→B→C→A. For anything beyond a
pair, you must design a loop-free topology (tree) or use `mount_point`/topic prefixes
so that each hop's messages land in a distinct namespace.

`try_private` must be `false` when bridging to a non-Mosquitto broker that rejects the
private-bridge CONNECT flag (some brokers reject the whole connection). The charm
should expose it, default `true`, and document the symptom.

Bridge QoS and session semantics:

- `topic <pat> <dir> <qos>` — QoS defaults to **0**. For anything you care about, set
  `1` or `2` explicitly. A bridge at QoS 0 silently drops during reconnects.
- `cleansession false` (the default) → the **remote** broker keeps the bridge's
  session and queues QoS>0 messages while the bridge is down. This is what gives you
  store-and-forward over a flaky WAN. Its cost is that the remote's
  `max_queued_messages` (default 1000!) caps how much it will hold — **raise it on the
  remote for bridge users, or you will lose messages during an outage of more than a
  few minutes.** This is the single most common bridging footgun.
- `local_cleansession` controls the local side independently.
- On 2.1 with `bridge_protocol_version mqttv50`, use
  `bridge_session_expiry_interval 0xFFFFFFFF` alongside `cleansession false`.

**(b) Active/passive failover.** Two units, a VIP (keepalived / a cloud load
balancer / `hacluster`), shared or replicated storage for `/var/lib/mosquitto`, and
only ever **one broker running at a time**. On failover the standby starts, reads
`mosquitto.db`, and clients reconnect to the VIP.

This actually works, with caveats:

- The persistence file must not be written by two brokers. Shared block storage with a
  proper fencing/STONITH story, or a cold copy on failover. **Never** put
  `/var/lib/mosquitto` on NFS shared read-write between two running brokers.
- Failover loses up to `autosave_interval` of state (set it low, e.g. 60 s, in an
  active/passive pair, and accept the I/O).
- Clients see a disconnect and must reconnect. QoS 0 in flight is lost.
- Recovery time = VIP failover + broker start + persistence restore, typically a few
  seconds for a small `.db`, tens of seconds for a large one.

**(c) Load balancer in front of N independent brokers.** Works *only* if your topic
space is partitioned such that publishers and subscribers for a given topic always
land on the same broker, or if all brokers are fully bridged. With full bridging you
get message delivery but still no shared retained/session state, and you get N copies
of every message on the wire. It is a trap for the unwary. Sticky sessions by client
ID help but do not solve retained messages.

**(d) Use a different broker.** Be honest with users. Tell them to move to:

- **EMQX** — Erlang, real clustering (Mnesia/RLOG), horizontal scale to millions of
  connections, built-in rule engine, dashboard, Kubernetes operator. The default
  answer for "I need a clustered MQTT broker".
- **VerneMQ** — Erlang, clustered, good at very high connection counts, plugin system.
- **NanoMQ** — tiny, extremely fast, edge-focused; not clustered in the same sense
  (it has bridging and a "NanoMQ + NNG" story), but excellent for edge gateways.
- **HiveMQ** — commercial, clustered, strong enterprise support and MQTT 5 compliance.
- **RabbitMQ with the MQTT plugin** — if you already run RabbitMQ and MQTT is a
  secondary protocol. Clustered, but MQTT semantics are approximated.
- **Cedalo Pro Mosquitto** — if the user specifically wants Mosquitto and is prepared
  to pay for HA.

The honest guidance: **Mosquitto is the right choice when you need one broker, up to
tens of thousands of connections, with minimal operational surface. It is the wrong
choice when you need HA with session continuity.**

### 6.3 What this means for the Juju charm

**Recommendation: build a single-unit charm. Do not support `juju add-unit` as
"scale out". Support it only as an explicitly-configured bridged federation or
active/passive pair, or not at all in v1.**

Concretely, I would ship it like this:

1. **v1: single unit only.** If `juju add-unit` is run, the additional units go
   `BlockedStatus("Mosquitto does not support clustering; see the `bridge` config
   option or deploy separate applications")`. This is honest, it is what the software
   actually does, and it prevents a user from believing they have HA when they have
   two brokers with divergent retained state and a load balancer in front.
   - Implement by having the charm elect a leader and have non-leaders block.
   - Do **not** silently let all units run — that is the worst outcome, because it
     "works" until a client reconnects to the other unit and its retained messages
     have vanished.

2. **Bridging as first-class config, not as units.** Expose bridges either as a
   config option (a YAML/JSON blob of bridge definitions) or, better, as a Juju
   **relation between two Mosquitto applications** — a `mqtt-bridge` peer-ish
   interface where one side is `bridge-provider` and the other `bridge-requirer`, and
   the charms exchange addresses, credentials and topic patterns. That gives you
   `juju relate mosquitto-edge:bridge mosquitto-central:bridge`, which is a genuinely
   good Juju experience and matches the hub-and-spoke reality.

3. **Optional active/passive via a peer relation**, if you want to go further:
   - peer relation `mosquitto-peers`, leader election picks the active unit;
   - Juju storage for `/var/lib/mosquitto`, plus either shared storage or periodic
     replication of `mosquitto.db` from active to standby;
   - standby units keep `mosquitto.service` stopped and report
     `ActiveStatus("standby")`;
   - relate to `hacluster` for the VIP;
   - a `promote` action for manual failover.
   This is a meaningful amount of work and you should only do it if users ask. Even
   then, be explicit in the docs that failover loses in-flight QoS 0 messages and up
   to `autosave_interval` of state.

4. **Document the ceiling.** In the charm README: single node, no clustering,
   ~50k connections on a well-tuned 8-core/16 GB machine, and a pointer to EMQX for
   anything larger or HA.

---

## 7. Performance tuning

### 7.1 File descriptors — the number one limiter

Every client connection is one file descriptor. Plus listeners, the persistence file,
the log file, and bridge connections. The shipped systemd unit sets **no
`LimitNOFILE`**, so the broker inherits systemd's `DefaultLimitNOFILE`, which on
Ubuntu 24.04 is **1024 soft / 524288 hard**. Mosquitto uses the *soft* limit.

Result: an untuned Mosquitto on noble tops out at roughly **1015 concurrent clients**,
and the symptom is `Error: Too many open files` in the log plus new connections being
refused while existing ones work fine. This catches people constantly.

`/etc/security/limits.conf` and `ulimit` **do not apply** to systemd-started services.
Only the unit's `LimitNOFILE=` matters. So the charm must write a drop-in:

```ini
[Service]
LimitNOFILE=65536
```

Sizing rule: `LimitNOFILE >= max_connections + 1024` (headroom for listeners, bridges,
the persistence file, the log, and epoll internals). If `max_connections` is `-1`
(unlimited), `LimitNOFILE` *is* your real connection limit.

**The charm should compute this.** If the user sets `max_connections: 20000`, the
charm writes `LimitNOFILE=24576` and restarts (unit changes require
`daemon-reload` + restart). If `max_connections` is `-1`, use a configurable
`open_file_limit` with a default of `65536`. Emit a warning if the user's
`max_connections` exceeds `LimitNOFILE`.

System-wide ceilings, for very large deployments:

```
fs.file-max = 2097152          # system-wide FD ceiling
fs.nr_open  = 2097152          # per-process hard ceiling; LimitNOFILE cannot exceed this
```

### 7.2 Sysctl values that matter

```conf
# /etc/sysctl.d/60-mosquitto.conf   (charm-managed)

# Accept-queue depth. The default (4096 on modern kernels) is usually fine, but
# on older kernels or containers it may be 128. Mosquitto's listen() backlog is
# capped by this. Too low => SYN drops and connection timeouts during a
# thundering-herd reconnect.
net.core.somaxconn = 16384

# Half-open connection queue. Must be raised alongside somaxconn for reconnect
# storms (e.g. when 20k IoT devices all reconnect after a WAN blip).
net.ipv4.tcp_max_syn_backlog = 16384

# Per-CPU backlog of packets waiting for the network stack.
net.core.netdev_max_backlog = 16384

# Source port range — only matters for the broker as a *client* (bridges) or for
# a load balancer, not for inbound connections. Widen it if the unit makes many
# outbound bridge connections.
net.ipv4.ip_local_port_range = 1024 65535

# How long a socket stays in FIN-WAIT-2. Default 60. Lowering to 15-30 frees
# resources faster during heavy churn. Do not go below ~10.
net.ipv4.tcp_fin_timeout = 15

# Reuse TIME_WAIT sockets for new outbound connections. Safe for the client side.
# (tcp_tw_recycle was removed from the kernel; never set it.)
net.ipv4.tcp_tw_reuse = 1

# Socket buffer ceilings. Raise for high-throughput brokers; each connection's
# buffers come out of these, so raising them hard with 50k connections costs
# real memory.
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Detect dead peers faster. Relevant when clients use long MQTT keepalives.
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# Conntrack, if a firewall is loaded (nf_conntrack must be loaded for these to exist).
net.netfilter.nf_conntrack_max = 1048576
```

Important caveat for a Juju charm: **sysctl changes are machine-global.** On a machine
shared with other charms (or a LXD container where some of these are not namespaced),
writing these can be antisocial or simply fail. Make sysctl tuning an **opt-in config
option** (`tune_sysctl`, default `false` or `auto`), write to a dedicated
`/etc/sysctl.d/60-mosquitto-charm.conf`, apply with `sysctl --system`, and tolerate
failures gracefully (in an unprivileged LXD container, most of these are read-only —
log and carry on, do not go `BlockedStatus`).

`somaxconn` in particular: Mosquitto calls `listen(fd, 100)` internally in older
versions, so raising `somaxconn` beyond that has no effect on 2.0 — verify against
your version before promising anything. The `tcp_max_syn_backlog` and
`netdev_max_backlog` values do help regardless.

### 7.3 Relating the layers

The effective connection limit is:

```
min( max_connections (per listener),
     global_max_connections (2.1, if set),
     LimitNOFILE - overhead,
     fs.file-max / (other users),
     available RAM / per-connection memory )
```

If the charm gets this wrong in either direction the symptoms are ugly:
`max_connections` above `LimitNOFILE` gives `Too many open files` and refused
connections with no clear cause; `LimitNOFILE` far above available RAM gives an
OOM kill.

**Charm behaviour:** compute `LimitNOFILE` from `max_connections`, compute
`memory_limit` from machine RAM, and validate the combination at `config-changed`,
reporting `BlockedStatus` on an impossible combination rather than letting the broker
fall over later.

### 7.4 Realistic expectations

Mosquitto is single-threaded for message handling (it uses epoll in one loop; there is
no per-connection threading and it will not use more than about one core for the
broker loop, with TLS handshakes being the main extra work). So **more cores buy you
very little beyond ~2-4**; clock speed and RAM matter more.

Rough, honest figures for idle-to-lightly-loaded MQTT clients (small, infrequent
messages), on Ubuntu 24.04 with the tuning above:

| Machine | Realistic concurrent connections | Throughput (QoS 0, small payloads) |
|---|---|---|
| 1 vCPU / 1 GB | ~1 000 – 2 000 | ~10–20k msg/s |
| 2 vCPU / 4 GB | ~10 000 | ~30–60k msg/s |
| 4 vCPU / 8 GB | ~30 000 | ~60–100k msg/s |
| 8 vCPU / 16 GB | ~50 000 – 80 000 | ~100–200k msg/s (single-core bound) |
| 16 vCPU / 32 GB | ~100 000 (diminishing returns) | still ~100–200k msg/s |

Memory per connection, empirically: **roughly 5–15 KB of broker heap for an idle
connection** with no queued messages, plus kernel socket buffers (a few KB each, more
if you raise `tcp_rmem`/`tcp_wmem`), plus **TLS session state of ~30–60 KB per
connection** when TLS is in use. So TLS roughly quadruples per-connection memory. A
rule of thumb:

```
RAM ≈ 512 MB (base + OS)
    + connections × 20 KB          (plain MQTT)
    + connections × 60 KB          (if TLS)
    + max_queued_messages × avg_payload_size × durable_clients   (the dangerous term)
    + retained_message_count × avg_payload_size
```

That fourth term is the one that kills brokers. With the defaults
(`max_queued_messages 1000`, no `max_queued_bytes`, no `persistent_client_expiration`)
and 10 000 durable clients publishing 1 KB messages, the theoretical worst case is
10 GB of queued messages. **Always set `persistent_client_expiration` and consider
`max_queued_bytes`.**

Throughput notes:

- QoS 1 roughly halves throughput versus QoS 0 (two packets per message); QoS 2
  roughly quarters it (four packets).
- Retained messages are cheap to store but expensive on a wildcard subscribe: a client
  subscribing to `#` on a broker with 100 000 retained messages triggers 100 000
  immediate publishes.
- Persistence (`autosave_interval`) causes a periodic write of the entire in-memory
  store — a stop-the-world pause proportional to the store size. With a large store
  and `autosave_interval 60` you can see periodic latency spikes. Put
  `/var/lib/mosquitto` on SSD/NVMe. Prefer `autosave_interval 300` as a compromise.
- `connection_messages false` and a conservative `log_type` are worth real throughput
  on brokers with high client churn.
- `set_tcp_nodelay true` reduces latency at the cost of more, smaller packets.

**Charm sizing guidance to document:** "for more than ~50 000 concurrent connections
or any HA requirement, use EMQX rather than Mosquitto."

---

## 8. Common failure modes and their fixes

### 8.1 "Connection refused: not authorised" after upgrading from 1.x

**Symptom:** every client fails with reason code 5 / `not authorised` immediately
after a 1.x → 2.x upgrade.
**Cause:** `allow_anonymous` now defaults to `false`.
**Fix:** configure `password_file` + `acl_file` (correct) or set `allow_anonymous true`
(quick, insecure). The charm should never hit this because it always writes an
explicit value — but a user importing legacy config will.

### 8.2 "I can connect from the machine but not from anywhere else"

**Symptom:** `mosquitto_sub -h localhost` works; `mosquitto_sub -h <ip>` times out.
**Cause:** no `listener` line, so 2.x bound to loopback only. Or the `listener` has a
bind address of `127.0.0.1`. Or `open-port` was never called / the security group
blocks 1883.
**Fix:** `listener 1883 0.0.0.0` (or the unit's private address) plus `open-port`.
**Diagnostic:** `ss -ltnp | grep mosquitto` shows exactly what is bound.

### 8.3 `Error: Too many open files` / new connections refused at ~1000 clients

**Cause:** `LimitNOFILE` default of 1024. See §7.1.
**Fix:** a systemd drop-in with `LimitNOFILE=65536`, `systemctl daemon-reload`,
`systemctl restart mosquitto`.
**Confirm:** `cat /proc/$(pidof mosquitto)/limits | grep 'open files'`.
**Note:** editing `/etc/security/limits.conf` does nothing for a systemd service.
This is the single most common Mosquitto production failure.

### 8.4 Corrupt `mosquitto.db` after power loss / SIGKILL

**Symptom:** the broker refuses to start:
`Unable to restore persistent database. Unrecognised file format.` or
`Error: Couldn't open database.` The file often contains only NUL bytes.
**Cause:** the broker was killed part-way through writing the persistence file, or the
filesystem lost the write. Upstream issues
[#2639](https://github.com/eclipse-mosquitto/mosquitto/issues/2639),
[#1214](https://github.com/eclipse-mosquitto/mosquitto/issues/1214),
[#3159](https://github.com/eclipse-mosquitto/mosquitto/issues/3159).
**Fix:**
1. If `/var/lib/mosquitto/mosquitto.db.new` exists and is non-empty, rename it over
   `mosquitto.db` — it is very often the good copy.
2. Otherwise restore from backup.
3. Last resort: delete `mosquitto.db` and start clean. You lose retained messages and
   all durable sessions; clients will reconnect and re-subscribe.
**Prevention:** `TimeoutStopSec=30s` so a shutdown write is not SIGKILLed;
`autosave_interval` low enough that you lose little; regular backups (§4.4); avoid
running persistence on an unreliable SD card (a very common Raspberry Pi failure).
**Charm:** a `recover-persistence` action that tries `.new`, then backup, then (with
an explicit `--force`) a clean slate, is genuinely valuable.

### 8.5 Memory grows until the OOM killer fires

**Symptom:** RSS climbs for days/weeks, then the kernel kills the broker;
`broker_heap_current` and `broker_messages_stored` trend upwards without bound.
**Causes, in order of likelihood:**
1. **Durable clients that never return.** Every `cleansession false` client that
   disconnects keeps a session and a queue. With no `persistent_client_expiration`,
   forever. Watch `$SYS/broker/clients/disconnected`.
2. **Retained messages accumulating.** Devices publishing retained messages on
   unique topics (e.g. `telemetry/<uuid>/status`) leave a permanent entry each.
   Watch `$SYS/broker/retained messages/count`.
3. **`max_queued_messages 0`** (unlimited) or a very large value combined with a slow
   subscriber.
**Fixes:** `persistent_client_expiration 14d`; `retain_expiry_interval` (2.1);
`max_queued_bytes`; `memory_limit` as a backstop so the broker sheds load rather
than being OOM-killed; educate publishers not to use retain on unbounded topic spaces.

### 8.6 Messages silently disappearing

**Symptom:** subscribers miss messages; `$SYS/broker/publish/messages/dropped` is
climbing.
**Causes:** `max_queued_messages` (default 1000) exceeded for a slow or disconnected
subscriber; `max_inflight_messages` (default 20) throttling a high-rate QoS 1/2
stream; `max_queued_bytes` exceeded; QoS 0 to a disconnected client (always dropped
unless `queue_qos0_messages true`).
**Fixes:** raise `max_queued_messages`, raise `max_inflight_messages` (to 100+ for
high-throughput bridge/backhaul clients), or — better — fix the slow subscriber.
Monitor the drop counter; it is the canary.

### 8.7 Bridge flapping / duplicate messages / infinite loops

**Symptoms:** `$SYS/broker/connection/<id>/state` toggling; the same message arriving
repeatedly and multiplying.
**Causes:**
- Two bridges (or a bridge and a client) sharing a **client ID** — each connection
  kicks the other off, forever. Make `remote_clientid` explicitly unique per unit.
- `try_private false` plus a bidirectional `topic ... both` between two brokers → an
  infinite echo loop. Keep `try_private true` between Mosquitto brokers.
- A cycle in a mesh of three or more brokers that `try_private` cannot break. Use a
  tree topology or `mount_point`/topic prefixes.
- `cleansession true` on the bridge → the remote discards the session and re-sends
  retained messages on every reconnect, which looks like duplicates.
**Fixes:** unique client IDs; `try_private true`; loop-free topology;
`cleansession false`; `restart_timeout 5 60` so a flapping bridge backs off.

### 8.8 Bridge loses messages during a WAN outage

**Symptom:** a long disconnect, then only the last ~1000 messages arrive.
**Cause:** the **remote** broker's `max_queued_messages` (default 1000) caps what it
queues for the bridge's durable session.
**Fix:** raise `max_queued_messages` on the *remote* broker (per-listener if it has a
dedicated bridge listener), and set `max_queued_bytes` to bound the memory cost.
Also confirm `cleansession false` and a non-zero `topic` QoS.

### 8.9 TLS: broker fails to start or clients fail the handshake after cert renewal

**Symptom:** `Error: Unable to load server key file` / `Error: Problem setting TLS
options: File not found.` after a Let's Encrypt renewal, or after the charm writes new
certs.
**Cause:** the 2.0 privilege-drop change — the broker drops to `mosquitto` *before*
opening the certificate files, so a key that is `0600 root:root` is unreadable.
**Fix:** `chown root:mosquitto` + `chmod 0640` on the key (or
`chown mosquitto:mosquitto` + `0600`), on every renewal. See
`/usr/share/doc/mosquitto/README-letsencrypt.md`.
**Charm:** re-assert permissions on every certificate write, and health-check the TLS
listener specifically after a cert change. Remember that SIGHUP re-reads cert *file
contents*, so renewal needs only a reload — but only if the permissions are right.

### 8.10 Clients rejected with "not authorised" despite a correct password

**Causes:**
- `acl_file` is set, and the ACL is deny-by-default. The user authenticates fine but
  has no topic grant. Distinguishable in the log: authentication succeeds, the
  SUBSCRIBE or PUBLISH is what fails (a v5 client sees reason code 135 on SUBACK; a
  v3.1.1 client sees a *silent* failure on PUBLISH, which is maddening).
- `per_listener_settings true` with `password_file`/`acl_file` in the wrong block.
- A `pattern` ACL using `%u` for a client that has no username.
- `use_identity_as_username true` and the client cert CN does not match the ACL
  `user` name.
- The password file was edited but the broker was never reloaded — `password_file` *is*
  reloadable, so `systemctl reload mosquitto` fixes it. **This is the fix people miss:
  `mosquitto_passwd` writes the file, but the broker holds it in memory.**
**Diagnostic:** temporarily add `log_type all` (or `-v`) and watch; mosquitto logs
`Denied PUBLISH from <client> (...)` at debug level.

### 8.11 A client subscribing to `#` gets nothing from `$SYS`

Not a bug. `$SYS` is excluded from `#` and `+` matching by the MQTT spec convention.
Subscribe to `$SYS/#` explicitly. Same for ACLs.

### 8.12 Log file grows without bound / disk fills

**Cause:** `log_type all` or `log_type debug` left on after debugging, or
`connection_messages true` with tens of thousands of flapping clients.
**Fix:** revert `log_type`; set `connection_messages false`; confirm
`/etc/logrotate.d/mosquitto` exists and that `logrotate` is running. Note the shipped
fragment uses `size 100k` + `daily`, so it rotates aggressively — but `rotate 7` with
heavy logging can still be a lot of disk.
**Charm:** never default to verbose logging; expose a `log-level` action for temporary
debug that reverts on the next `config-changed`.

### 8.13 The broker restarts and every client reconnects at once (thundering herd)

**Symptom:** after a restart, a spike of `load/connections/1min`, SYN drops, and slow
recovery.
**Causes/fixes:** raise `net.ipv4.tcp_max_syn_backlog` and `net.core.somaxconn`;
ensure clients use randomised reconnect backoff (a client-side fix, but worth
documenting); minimise restarts by preferring reload (§4.1). Note that a restart also
means every durable client's queued messages are delivered at once — a second herd.

### 8.14 `include_dir` surprises

**Symptom:** a config change has no effect, or an old setting persists.
**Causes:** `include_dir` reads `*.conf` in alphabetical order, non-recursively, and a
later file silently overrides an earlier one for single-valued directives. A stale
file from a previous charm revision (or a user's hand-edit) is still read. Files
without a `.conf` extension are silently ignored — including `foo.conf.bak`, which is
ignored, and `foo.bak.conf`, which is **not**.
**Fix:** the charm must own `/etc/mosquitto/conf.d/` entirely: enumerate the files it
manages, delete anything else it put there previously, and warn (in status) if it
finds unexpected `.conf` files.

### 8.15 systemd restarts the broker in a loop, then gives up

**Symptom:** `systemctl status mosquitto` shows `failed` with
`start request repeated too quickly`.
**Cause:** `Restart=on-failure` with the default `StartLimitBurst=5` /
`StartLimitIntervalSec=10s`, plus a config error that makes the broker exit
immediately.
**Fix:** fix the config; `systemctl reset-failed mosquitto` before retrying.
**Charm:** always `systemctl reset-failed` before a start attempt, and surface the
journal's last error lines in `BlockedStatus`.

### 8.16 Snap-specific: "cannot open config file" / certs not found

**Cause:** strict confinement. Only `/var/snap/mosquitto/common/` is readable.
**Fix:** move everything there. Or use the deb. (Another argument for the deb.)

---

## 9. Concrete recommendations for the charm

### 9.1 Config options and defaults

```yaml
options:
  # --- packaging ---
  install-source:        {type: string,  default: "archive"}   # archive|ppa|snap
  snap-channel:          {type: string,  default: "2.1/stable"}

  # --- listeners ---
  port:                  {type: int,     default: 1883}
  bind-address:          {type: string,  default: ""}          # "" => unit private addr
  enable-plain-listener: {type: boolean, default: true}
  tls-port:              {type: int,     default: 8883}
  enable-tls:            {type: boolean, default: false}
  websockets-port:       {type: int,     default: 0}           # 0 => disabled
  websockets-tls:        {type: boolean, default: false}
  socket-domain:         {type: string,  default: ""}          # ""|ipv4|ipv6
  max-connections:       {type: int,     default: -1}

  # --- security ---
  allow-anonymous:       {type: boolean, default: false}
  auth-backend:          {type: string,  default: "password-file"}  # password-file|dynsec
  users:                 {type: string,  default: ""}          # via a Juju secret
  acl-rules:             {type: string,  default: ""}          # YAML blob
  password-hash:         {type: string,  default: "auto"}      # auto|argon2id|sha512-pbkdf2|sha512
  use-identity-as-username: {type: boolean, default: false}
  require-client-certificate: {type: boolean, default: false}
  tls-version:           {type: string,  default: "tlsv1.2"}
  ciphers:               {type: string,  default: ""}
  ciphers-tls13:         {type: string,  default: ""}

  # --- persistence ---
  persistence:                  {type: boolean, default: true}
  autosave-interval:            {type: int,     default: 300}
  autosave-on-changes:          {type: boolean, default: false}
  persistent-client-expiration: {type: string,  default: "14d"}
  queue-qos0-messages:          {type: boolean, default: false}
  retain-available:             {type: boolean, default: true}

  # --- limits ---
  max-inflight-messages: {type: int, default: 20}
  max-queued-messages:   {type: int, default: 1000}
  max-queued-bytes:      {type: int, default: 0}
  max-packet-size:       {type: int, default: 2000000}
  message-size-limit:    {type: int, default: 0}
  memory-limit:          {type: int, default: 0}     # 0 => charm computes 70% of RAM
  max-keepalive:         {type: int, default: 65535}
  max-topic-alias:       {type: int, default: 10}
  sys-interval:          {type: int, default: 10}

  # --- logging ---
  log-dest:              {type: string,  default: "file"}       # file|stdout|syslog
  log-types:             {type: string,  default: "error,warning,notice,information"}
  connection-messages:   {type: boolean, default: true}
  log-timestamp-format:  {type: string,  default: "%Y-%m-%dT%H:%M:%S"}

  # --- tuning ---
  open-file-limit:       {type: int,     default: 0}   # 0 => computed from max-connections
  tune-sysctl:           {type: boolean, default: false}
  systemd-hardening:     {type: boolean, default: true}

  # --- observability ---
  enable-metrics:        {type: boolean, default: true}
  metrics-port:          {type: int,     default: 9234}

  # --- escape hatch ---
  extra-config:          {type: string,  default: ""}   # appended as 99-extra.conf
```

`extra-config` is worth having but must be clearly documented as unsupported, must be
written as the **last** file in `conf.d` so it can override, and must be included in
the reload-vs-restart classification (default: restart, since the charm cannot know).

### 9.2 Files the charm owns

```
/etc/mosquitto/mosquitto.conf                     0644 root:root  (rewritten: minimal, include_dir only)
/etc/mosquitto/conf.d/10-listeners.conf           0644 root:root
/etc/mosquitto/conf.d/20-security.conf            0640 root:mosquitto
/etc/mosquitto/conf.d/30-limits.conf              0644 root:root
/etc/mosquitto/conf.d/40-persistence.conf         0644 root:root
/etc/mosquitto/conf.d/50-logging.conf             0644 root:root
/etc/mosquitto/conf.d/60-bridges.conf             0640 root:mosquitto   (has passwords)
/etc/mosquitto/conf.d/99-extra.conf               0640 root:mosquitto
/etc/mosquitto/passwd                             0640 root:mosquitto
/etc/mosquitto/acl                                0640 root:mosquitto
/etc/mosquitto/certs/server.{crt,key}             0644 / 0640 root:mosquitto
/etc/mosquitto/ca_certificates/ca.crt             0644 root:root
/etc/systemd/system/mosquitto.service.d/10-charm.conf
/etc/sysctl.d/60-mosquitto-charm.conf             (opt-in)
/etc/logrotate.d/mosquitto                        (optionally replaced on 2.1)
```

### 9.3 Actions

`set-password`, `delete-user`, `list-users`, `create-backup`, `restore-backup`,
`force-persist` (SIGUSR1), `reload`, `restart`, `validate-config`, `health-check`,
`dump-tree` (SIGUSR2, with a warning), `show-sys-metrics`, `rotate-logs`.

