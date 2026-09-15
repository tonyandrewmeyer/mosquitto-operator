# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Managing and interacting with the Mosquitto broker.

This module knows about Mosquitto and about the machine it runs on, and knows nothing
about Juju. It could be used outside the context of a charm, and the parts of it that
render configuration and decide what a change requires are pure functions, so they can
be tested without a broker.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import enum
import grp
import hashlib
import logging
import os
import pathlib
import pwd
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tarfile
import tempfile
import time
from typing import TYPE_CHECKING

from charmlibs import apt, pathops, snap, sysctl, systemd

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

SERVER_PACKAGE = 'mosquitto'
CLIENT_PACKAGE = 'mosquitto-clients'
SNAP_NAME = 'mosquitto'
PPA = 'ppa:mosquitto-dev/mosquitto-ppa'

CHARM_CONFIG_FILENAME = '50-charm.conf'
BRIDGE_CONFIG_FILENAME = '60-charm-bridge.conf'
EXTRA_CONFIG_FILENAME = '99-charm-extra.conf'
EXPORTER_SERVICE = 'mosquitto-charm-exporter'
EXPORTER_INSTALL_PATH = pathlib.Path('/usr/local/lib/mosquitto-charm/exporter.py')
DROPIN_DIR_TEMPLATE = '/etc/systemd/system/{service}.service.d'
DROPIN_FILENAME = '90-charm.conf'

# Usernames the charm reserves for itself. Operators cannot create these, so an
# operator-created user can never inherit the broker-wide `$SYS` read grant.
HEALTH_USER = '_charm_health'
METRICS_USER = '_charm_metrics'

# The first version that carries the fixes for CVE-2024-3935 (a double free reachable
# through an outgoing bridge with incoming topic remapping) and CVE-2024-10525.
MINIMUM_BRIDGE_VERSION = (2, 0, 19)

_VERSION_RE = re.compile(r'\bversion\s+(\d+)\.(\d+)\.(\d+)')
_DIRECTIVE_RE = re.compile(r'^\s*([a-z_0-9]+)\s*(.*?)\s*$')

# Which sysctl values are worth setting for a broker holding many connections. The
# defaults are sized for a general-purpose host, not for tens of thousands of sockets.
# `net.ipv4.ip_local_port_range` is deliberately absent. Its value is two numbers
# separated by whitespace, which charmlibs-sysctl cannot read back, so including it
# makes every hook log an error about tuning that was in fact applied. It is also the
# least useful of the four here: it governs outgoing connections, and a broker accepts
# rather than makes them.
SYSCTL_TUNING = {
    'net.core.somaxconn': '4096',
    'net.ipv4.tcp_max_syn_backlog': '4096',
    'net.core.netdev_max_backlog': '4096',
}

# Directives Mosquitto re-reads on SIGHUP, from the "Reloaded on reload signal"
# annotations in mosquitto.conf(5). A reload does not drop client connections, so
# reaching for one of these rather than a restart is directly visible to users.
RELOAD_SAFE_DIRECTIVES = frozenset(
    {
        'accept_protocol_versions',
        'acl_file',
        'allow_anonymous',
        'allow_duplicate_messages',
        'allow_zero_length_clientid',
        'autosave_interval',
        'autosave_on_changes',
        'connection_messages',
        'enable_control_api',
        'global_max_clients',
        'global_max_connections',
        'log_dest',
        'log_timestamp',
        'log_timestamp_format',
        'log_type',
        'max_inflight_bytes',
        'max_inflight_messages',
        'max_keepalive',
        'max_packet_size',
        'max_queued_bytes',
        'max_queued_messages',
        'memory_limit',
        'message_size_limit',
        'password_file',
        'per_listener_settings',
        'persistence',
        'persistence_file',
        'persistence_location',
        'persistent_client_expiration',
        'psk_file',
        'queue_qos0_messages',
        'retain_available',
        'retain_expiry_interval',
        'set_tcp_nodelay',
        'sys_interval',
        'upgrade_outgoing_qos',
    }
)

# Directives that need the broker restarted. This list exists for documentation and
# for tests; `classify_change` treats anything not in `RELOAD_SAFE_DIRECTIVES` as
# needing a restart, because these lists differ between Mosquitto 2.0 and 2.1 and
# guessing wrong in this direction merely costs a restart, whereas guessing wrong in
# the other direction leaves the broker running a configuration nobody asked for.
RESTART_REQUIRED_DIRECTIVES = frozenset(
    {
        'auth_plugin_deny_special_chars',
        'bind_address',
        'bind_interface',
        'cafile',
        'capath',
        'certfile',
        'ciphers',
        'ciphers_tls1.3',
        'crlfile',
        'dhparamfile',
        'disable_client_cert_date_checks',
        'enable_proxy_protocol',
        'global_plugin',
        'http_dir',
        'keyfile',
        'listener',
        'listener_allow_anonymous',
        'max_connections',
        'max_qos',
        'mount_point',
        'packet_buffer_size',
        'pid_file',
        'plugin',
        'port',
        'protocol',
        'psk_hint',
        'require_certificate',
        'socket_domain',
        'tls_engine',
        'tls_keyform',
        'tls_version',
        'use_identity_as_username',
        'use_subject_as_username',
        'use_username_as_clientid',
        'user',
        'websockets_headers_size',
        'websockets_origin',
    }
)

# The `log_type` values each charm log level expands to. Mosquitto's levels are not
# ordered on their own, so the charm makes them cumulative, which is what operators
# expect from a log level.
LOG_TYPES: Mapping[str, tuple[str, ...]] = {
    'error': ('error',),
    'warning': ('error', 'warning'),
    'notice': ('error', 'warning', 'notice'),
    'information': ('error', 'warning', 'notice', 'information'),
    'debug': ('error', 'warning', 'notice', 'information', 'debug'),
}


class Error(Exception):
    """A Mosquitto operation failed."""


class InstallError(Error):
    """Installing or removing Mosquitto failed."""


class ServiceError(Error):
    """Controlling the Mosquitto service failed."""


class ConfigError(Error):
    """Mosquitto rejected a configuration."""


class Change(enum.IntEnum):
    """What applying a configuration change requires.

    The values are ordered, so `max()` over a set of changes gives the strongest
    action needed.
    """

    NONE = 0
    RELOAD = 1
    RESTART = 2


class Access(enum.StrEnum):
    """An ACL access level, spelt as Mosquitto's ACL file spells it."""

    READ = 'read'
    WRITE = 'write'
    READWRITE = 'readwrite'
    DENY = 'deny'


@dataclasses.dataclass(frozen=True)
class Paths:
    """Where Mosquitto's files live, which depends on how it was installed."""

    config_file: pathlib.Path
    conf_dir: pathlib.Path
    password_file: pathlib.Path
    acl_file: pathlib.Path
    persistence_dir: pathlib.Path
    log_file: pathlib.Path
    certs_dir: pathlib.Path
    backup_dir: pathlib.Path
    service: str
    user: str
    group: str
    bindir: pathlib.Path

    @property
    def passwd_tool(self) -> pathlib.Path:
        """The `mosquitto_passwd` binary."""
        return self.bindir / 'mosquitto_passwd'

    @property
    def rr_tool(self) -> pathlib.Path:
        """The `mosquitto_rr` binary, used for health checks."""
        return self.bindir / 'mosquitto_rr'

    @property
    def sub_tool(self) -> pathlib.Path:
        """The `mosquitto_sub` binary, used to read the `$SYS` tree."""
        return self.bindir / 'mosquitto_sub'

    def managed_files(self) -> tuple[pathlib.Path, ...]:
        """The files the charm writes, in the order a backup should record them."""
        return (
            self.config_file,
            self.conf_dir / CHARM_CONFIG_FILENAME,
            self.conf_dir / BRIDGE_CONFIG_FILENAME,
            self.conf_dir / EXTRA_CONFIG_FILENAME,
            self.password_file,
            self.acl_file,
        )


_DEB_PATHS = Paths(
    config_file=pathlib.Path('/etc/mosquitto/mosquitto.conf'),
    conf_dir=pathlib.Path('/etc/mosquitto/conf.d'),
    password_file=pathlib.Path('/etc/mosquitto/passwd'),
    acl_file=pathlib.Path('/etc/mosquitto/acl'),
    persistence_dir=pathlib.Path('/var/lib/mosquitto'),
    log_file=pathlib.Path('/var/log/mosquitto/mosquitto.log'),
    certs_dir=pathlib.Path('/etc/mosquitto/certs'),
    backup_dir=pathlib.Path('/var/lib/mosquitto/backups'),
    service='mosquitto',
    user='mosquitto',
    group='mosquitto',
    bindir=pathlib.Path('/usr/bin'),
)

# The snap is strictly confined, so everything the broker reads or writes has to live
# under its own common directory; nothing in /etc or /var/lib is visible to it.
_SNAP_COMMON = pathlib.Path('/var/snap/mosquitto/common')
_SNAP_PATHS = Paths(
    config_file=_SNAP_COMMON / 'mosquitto.conf',
    conf_dir=_SNAP_COMMON / 'conf.d',
    password_file=_SNAP_COMMON / 'passwd',
    acl_file=_SNAP_COMMON / 'acl',
    persistence_dir=_SNAP_COMMON / 'data',
    log_file=_SNAP_COMMON / 'mosquitto.log',
    certs_dir=_SNAP_COMMON / 'certs',
    backup_dir=_SNAP_COMMON / 'backups',
    service='snap.mosquitto.mosquitto',
    user='root',
    group='root',
    bindir=pathlib.Path('/snap/bin'),
)


def paths(install_source: str) -> Paths:
    """Return the file layout for an install source.

    Args:
        install_source: One of `archive`, `ppa` or `snap`.
    """
    return _SNAP_PATHS if install_source == 'snap' else _DEB_PATHS


@dataclasses.dataclass(frozen=True)
class Listener:
    """One `listener` block in the rendered configuration."""

    port: int
    address: str = ''
    websockets: bool = False
    tls: bool = False


@dataclasses.dataclass(frozen=True)
class TLSMaterial:
    """The certificate, key and authority chain to serve TLS listeners with."""

    certificate: str
    private_key: str
    ca: str


@dataclasses.dataclass(frozen=True)
class Bridge:
    """A bridge to another broker."""

    name: str
    host: str
    port: int
    topics: tuple[str, ...]
    username: str | None = None
    password: str | None = None
    tls_ca: str | None = None
    client_id: str = ''


@dataclasses.dataclass(frozen=True)
class BrokerSettings:
    """Everything the rendered configuration depends on.

    This is deliberately independent of the charm's Juju config: the charm translates
    its options into this, so that rendering can be tested without Juju and so that a
    value the charm computes (a listener that only exists once certificates arrive,
    say) is indistinguishable here from one an operator set.
    """

    listeners: tuple[Listener, ...]
    allow_anonymous: bool = False
    tls: TLSMaterial | None = None
    tls_version: str = 'tlsv1.2'
    require_client_certificate: bool = False
    use_identity_as_username: bool = False
    persistence: bool = True
    autosave_interval: int = 300
    persistent_client_expiration: str = '14d'
    max_connections: int = 1024
    max_inflight_messages: int = 20
    max_queued_messages: int = 1000
    max_queued_bytes: int = 0
    max_packet_size: int = 2_000_000
    max_keepalive: int = 65535
    memory_limit: int = 0
    retain_available: bool = True
    queue_qos0_messages: bool = False
    log_level: str = 'notice'
    connection_messages: bool = True
    sys_interval: int = 10
    extra_config: str = ''


def _quote(value: bool) -> str:  # A rendering helper, not an API.
    """Render a boolean the way mosquitto.conf spells it."""
    return 'true' if value else 'false'


def render_config(settings: BrokerSettings, file_paths: Paths) -> str:
    """Render the charm's main configuration fragment.

    Every directive the charm cares about is written out explicitly, even when the
    value matches Mosquitto's own default. Relying on defaults is how a broker's
    behaviour changes silently across an upgrade — `max_packet_size` alone moved from
    unlimited to 2000000 between 2.0 and 2.1.

    Args:
        settings: The broker configuration to render.
        file_paths: Where Mosquitto's files live.

    Returns:
        The contents of the charm's configuration fragment.
    """
    lines = [
        '# Managed by the mosquitto charm. Do not edit: this file is rewritten on',
        "# every configuration change. Use the charm's `extra-config` option for",
        '# directives the charm does not expose.',
        '',
        '# Per-listener security is deliberately off. With it on, a durable client',
        '# keeps the permissions of whichever listener it last connected through,',
        '# which is a privilege escalation path, and it is deprecated in 2.1.',
        'per_listener_settings false',
        '',
        f'allow_anonymous {_quote(settings.allow_anonymous)}',
        f'password_file {file_paths.password_file}',
        f'acl_file {file_paths.acl_file}',
        '',
    ]

    for listener in settings.listeners:
        lines.append(
            f'listener {listener.port}{" " + listener.address if listener.address else ""}'
        )
        if listener.websockets:
            lines.append('protocol websockets')
        if listener.tls and settings.tls is not None:
            lines.extend(
                [
                    f'cafile {file_paths.certs_dir / "ca.crt"}',
                    f'certfile {file_paths.certs_dir / "server.crt"}',
                    f'keyfile {file_paths.certs_dir / "server.key"}',
                    f'tls_version {settings.tls_version}',
                    f'require_certificate {_quote(settings.require_client_certificate)}',
                ]
            )
            if settings.require_client_certificate:
                lines.append(
                    f'use_identity_as_username {_quote(settings.use_identity_as_username)}'
                )
        lines.append('')

    lines.extend(
        [
            f'persistence {_quote(settings.persistence)}',
            f'persistence_location {file_paths.persistence_dir}/',
            f'autosave_interval {settings.autosave_interval}',
        ]
    )
    if settings.persistent_client_expiration:
        # Left unset, disconnected durable sessions accumulate for ever, which is the
        # usual explanation for a broker whose memory only ever goes up.
        lines.append(f'persistent_client_expiration {settings.persistent_client_expiration}')
    lines.append('')

    lines.extend(
        [
            f'max_connections {settings.max_connections}',
            f'max_inflight_messages {settings.max_inflight_messages}',
            f'max_queued_messages {settings.max_queued_messages}',
            f'max_queued_bytes {settings.max_queued_bytes}',
            f'max_packet_size {settings.max_packet_size}',
            f'max_keepalive {settings.max_keepalive}',
            f'memory_limit {settings.memory_limit}',
            f'retain_available {_quote(settings.retain_available)}',
            f'queue_qos0_messages {_quote(settings.queue_qos0_messages)}',
            '',
            f'log_dest file {file_paths.log_file}',
        ]
    )
    # `log_dest file` rather than syslog, because the COS collectors scrape
    # /var/log/**/*log directly and opentelemetry-collector has no journald receiver.
    lines.extend(f'log_type {log_type}' for log_type in LOG_TYPES[settings.log_level])
    lines.extend(
        [
            f'connection_messages {_quote(settings.connection_messages)}',
            'log_timestamp true',
            '',
            f'sys_interval {settings.sys_interval}',
            '',
        ]
    )

    return '\n'.join(lines).rstrip() + '\n'


def render_bridge_config(bridge: Bridge, file_paths: Paths) -> str:
    """Render a bridge `connection` block.

    Args:
        bridge: The bridge to render.
        file_paths: Where Mosquitto's files live.

    Returns:
        The contents of the charm's bridge configuration fragment.

    Raises:
        ValueError: If a value that came from the far side of the relation could not be
            written out safely.
    """
    # Belt and braces: `mqtt.Endpoint` and `mqtt.UserSecret` validate these at the
    # relation boundary, but the host and the credentials are the only values here that
    # a *remote* charm chooses, and the fragment is a line-oriented file the broker
    # includes. A line break in any of them would be extra directives rather than a
    # broken bridge.
    for what, value in (
        ('host', bridge.host),
        ('username', bridge.username),
        ('password', bridge.password),
    ):
        if value is not None and any(character in value for character in '\n\r\x00'):
            raise ValueError(f'refusing to write a bridge {what} containing a line break')

    lines = [
        '# Managed by the mosquitto charm.',
        '',
        f'connection {bridge.name}',
        f'address {bridge.host}:{bridge.port}',
        # A shared client id makes both ends fight for the same session, and they
        # flap for ever. Juju gives us a unique unit name, so use it.
        f'remote_clientid {bridge.client_id or bridge.name}',
        # Without this, a message that arrives from the remote is sent straight back,
        # and a pair of brokers echoes for ever. It only breaks two-broker cycles, so
        # bridged topologies still need to be trees.
        'try_private true',
        # Store and forward across an outage rather than dropping everything.
        'cleansession false',
        'notifications false',
        'restart_timeout 10 60',
        'bridge_protocol_version mqttv50',
        # The remote's own max_queued_messages caps what it will hold for us while we
        # are away; this is our side of the same problem.
        'bridge_max_packet_size 0',
    ]
    if bridge.username:
        lines.append(f'remote_username {bridge.username}')
    if bridge.password:
        lines.append(f'remote_password {bridge.password}')
    if bridge.tls_ca:
        lines.append(f'bridge_cafile {file_paths.certs_dir / "bridge-ca.crt"}')
    lines.append('')
    lines.extend(bridge.topics)
    return '\n'.join(lines).rstrip() + '\n'


def parse_directives(text: str) -> list[tuple[str, str]]:
    """Parse a configuration into (directive, value) pairs.

    Comments and blank lines are dropped, and surrounding whitespace is normalised, so
    that reformatting the file does not look like a change.

    Args:
        text: The configuration text.

    Returns:
        The directives in file order. Order is preserved because `listener` blocks are
        positional: the directives after a `listener` line belong to that listener.
    """
    directives: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        match = _DIRECTIVE_RE.match(stripped)
        if match is None:
            continue
        directives.append((match.group(1), ' '.join(match.group(2).split())))
    return directives


def classify_change(old: str, new: str) -> Change:
    """Decide what applying a configuration change requires.

    A reload leaves every client connected; a restart disconnects all of them and
    loses any QoS 0 traffic in flight. So the distinction matters to users, and is
    worth making at the level of individual directives rather than by comparing the
    files as text.

    Anything not known to be reload-safe is treated as needing a restart. The
    reload-safe list differs between Mosquitto 2.0 and 2.1, and an unnecessary restart
    is a much smaller problem than a broker still running the old configuration while
    the charm reports success.

    Args:
        old: The configuration currently on disk.
        new: The configuration about to be written.

    Returns:
        The strongest action the change requires.
    """
    old_directives = parse_directives(old)
    new_directives = parse_directives(new)
    if old_directives == new_directives:
        return Change.NONE

    changed = set(old_directives).symmetric_difference(new_directives)
    # A reordering with no changed pairs still matters, because listener blocks are
    # positional.
    if not changed:
        return Change.RESTART

    names = {name for name, _ in changed}
    if names <= RELOAD_SAFE_DIRECTIVES:
        return Change.RELOAD
    return Change.RESTART


def render_password_file(users: Mapping[str, str]) -> str:
    """Render a plaintext password file, ready to be hashed in place.

    Args:
        users: Usernames mapped to plaintext passwords.

    Returns:
        The file contents, one `username:password` pair per line.
    """
    return ''.join(f'{username}:{password}\n' for username, password in sorted(users.items()))


def render_acl_file(rules: Mapping[str, Sequence[tuple[str, str]]]) -> str:
    """Render an ACL file.

    Args:
        rules: Usernames mapped to their (topic filter, access) pairs.

    Returns:
        The file contents.
    """
    for username, permissions in rules.items():
        for topic, access in permissions:
            # Belt and braces: the callers validate this, but the ACL file is line
            # oriented and a topic with a line break in it would silently become extra
            # rules rather than a broken one.
            if any(character in f'{username}{topic}{access}' for character in '\n\r\x00'):
                raise ValueError(
                    f'refusing to write an ACL entry containing a line break: {username}/{topic}'
                )

    lines = ['# Managed by the mosquitto charm. Do not edit.', '']
    # Nothing is written before the first `user` line, and rules before that line are
    # the only ones anonymous clients get: with `allow-anonymous` set they can connect,
    # and then neither publish nor subscribe to anything. There is no way to ask the
    # charm for more, which is deliberate -- a grant to unauthenticated clients is a
    # grant to everyone who can reach the port.
    #
    # `pattern` lines would be the other way to write a global grant, but they apply to
    # every user, including inside a `user` block, which is rarely what anyone means.
    for username, permissions in sorted(rules.items()):
        lines.append(f'user {username}')
        for topic, access in permissions:
            lines.append(f'topic {access} {topic}')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def generate_password(length: int = 24) -> str:
    """Generate a password.

    Args:
        length: How many characters to generate.

    Returns:
        A URL-safe password with no colons, which the password file format cannot
        represent.
    """
    return secrets.token_urlsafe(length)[:length]


def _run(
    command: Sequence[str | pathlib.Path],
    *,
    timeout: int = 60,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command, logging whatever it said.

    Never invoked through a shell, and always with an absolute path, so that neither
    the operator's environment nor a topic name can change which program runs.
    """
    try:
        result = subprocess.run(
            [str(part) for part in command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=dict(env) if env is not None else None,
        )
    except subprocess.TimeoutExpired as e:
        # Raised as this module's own error so that callers which already handle
        # `Error` — every install path in particular — report it rather than ending the
        # hook in a traceback. Reaching Launchpad or the archive is not something the
        # charm can promise, and a slow mirror should not need `juju resolve`.
        raise Error(
            f'{pathlib.Path(str(command[0])).name} did not finish within {timeout}s'
        ) from e
    for line in result.stderr.splitlines():
        logger.debug('%s: %s', pathlib.Path(str(command[0])).name, line)
    if check and result.returncode:
        raise Error(
            f'{pathlib.Path(str(command[0])).name} exited {result.returncode}: '
            f'{result.stderr.strip() or result.stdout.strip()}'
        )
    return result


def install(install_source: str, channel: str = 'latest/stable') -> None:
    """Install Mosquitto and the client tools.

    Args:
        install_source: One of `archive`, `ppa` or `snap`.
        channel: The snap channel, used only when installing from the snap.

    Raises:
        InstallError: If the packages could not be installed.
    """
    if install_source == 'snap':
        try:
            snap.ensure_installed(SNAP_NAME, channel=channel)
            # snapd would otherwise refresh the broker whenever it felt like it,
            # restarting a stateful service outside any maintenance window. The charm
            # takes that decision back.
            snap.hold(SNAP_NAME)
        except snap.Error as e:
            raise InstallError(f'could not install the {SNAP_NAME} snap: {e}') from e
        return

    try:
        if install_source == 'ppa':
            # Talks to Launchpad, which is regularly slower than the default.
            _run(['/usr/bin/add-apt-repository', '--yes', '--no-update', PPA], timeout=300)
        else:
            _remove_ppa()
        apt.update()
        # The client tools are a separate package, and the charm needs them for health
        # checks and for reading the $SYS tree.
        #
        # Install the *candidate* version rather than calling `add_package`, which is a
        # no-op once the package is present at any version. Without this, switching
        # install-source from the archive to the PPA leaves 2.0.18 in place and quietly
        # does nothing.
        for package in (SERVER_PACKAGE, CLIENT_PACKAGE):
            candidate = apt.DebianPackage.from_apt_cache(package)
            candidate.ensure(apt.PackageState.Present)
    except (apt.Error, Error) as e:
        raise InstallError(f'could not install Mosquitto from the {install_source}: {e}') from e


def _remove_ppa() -> None:
    """Drop the upstream PPA, so that moving back to the archive really moves back.

    While the PPA is still configured its 2.1.x build remains the candidate, and the
    charm would keep 2.1 installed while reporting that it is using the archive.
    """
    for pattern in ('mosquitto-dev-ubuntu-mosquitto-ppa-*.list', 'mosquitto-dev-*.sources'):
        for path in pathlib.Path('/etc/apt/sources.list.d').glob(pattern):
            logger.info('Removing the Mosquitto PPA source %s.', path)
            path.unlink()


def different_packaging(one: str, other: str) -> bool:
    """Whether two install sources put the broker on the machine in different ways.

    The archive and the PPA are the same Debian package from different suites, so moving
    between them upgrades or downgrades in place. The snap is a second broker.

    Args:
        one: One of `archive`, `ppa` or `snap`.
        other: The same.

    Returns:
        True if moving from one to the other leaves the first one's package installed.
    """
    return (one == 'snap') != (other == 'snap')


def uninstall(install_source: str) -> None:
    """Remove Mosquitto, leaving its data behind.

    Args:
        install_source: One of `archive`, `ppa` or `snap`.
    """
    if install_source == 'snap':
        with contextlib.suppress(snap.Error):
            snap.remove(SNAP_NAME)
        return
    with contextlib.suppress(apt.Error):
        apt.remove_package([SERVER_PACKAGE, CLIENT_PACKAGE])


def get_version(install_source: str = 'archive') -> str | None:
    """Return the running Mosquitto version.

    Args:
        install_source: One of `archive`, `ppa` or `snap`.

    Returns:
        The version as a dotted string, or None if Mosquitto is not installed.
    """
    binary = (
        pathlib.Path('/snap/bin/mosquitto')
        if install_source == 'snap'
        else pathlib.Path('/usr/sbin/mosquitto')
    )
    if not binary.exists():
        return None
    try:
        result = _run([binary, '-h'], timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        logger.warning('Could not run %s to determine the Mosquitto version.', binary)
        return None
    match = _VERSION_RE.search(result.stdout + result.stderr)
    return match.group(0).split()[-1] if match else None


def version_tuple(version: str | None) -> tuple[int, int, int]:
    """Parse a version string into comparable parts.

    Args:
        version: A dotted version string, or None.

    Returns:
        The version as a three-part tuple, or zeroes if it could not be parsed.
    """
    if not version:
        return (0, 0, 0)
    parts = version.split('.')[:3]
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return (0, 0, 0)
    return (*numbers, 0, 0, 0)[:3]  # type: ignore[return-value]


def supports_bridging(version: str | None) -> bool:
    """Whether this version is new enough to configure a bridge safely.

    Mosquitto before 2.0.19 is vulnerable to CVE-2024-3935, a double free reachable
    through an outgoing bridge with incoming topic remapping. Ubuntu 24.04 ships
    2.0.18, so this is not a theoretical concern.

    Args:
        version: The running Mosquitto version.

    Returns:
        Whether bridging should be permitted.
    """
    return version_tuple(version) >= MINIMUM_BRIDGE_VERSION


def _chown(path: pathlib.Path, user: str, group: str, mode: int) -> None:
    """Set ownership and permissions, tolerating a user that does not exist yet."""
    try:
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        logger.warning('User %s or group %s does not exist; leaving %s as is.', user, group, path)
        return
    os.chown(path, uid, gid)
    path.chmod(mode)


def ensure_directories(file_paths: Paths) -> None:
    """Create the directories Mosquitto needs, with the permissions it insists on.

    Args:
        file_paths: Where Mosquitto's files live.
    """
    for directory, mode in (
        (file_paths.conf_dir, 0o755),
        (file_paths.persistence_dir, 0o700),
        (file_paths.certs_dir, 0o700),
        (file_paths.backup_dir, 0o700),
        (file_paths.log_file.parent, 0o755),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        _chown(directory, file_paths.user, file_paths.group, mode)

    # Since 2.0 the broker drops to its own user before opening the log, so a log file
    # owned by root means it silently logs nothing -- and the only sign is a line in
    # the journal at startup that nobody reads.
    file_paths.log_file.touch(exist_ok=True)
    _chown(file_paths.log_file, file_paths.user, file_paths.group, 0o640)


def unpatched_archive_build(install_source: str) -> str | None:
    """Whether the installed broker is an archive build with no security support.

    Mosquitto is in `universe` on Ubuntu 24.04, so `apt install mosquitto` gives a
    2.0.18 build that receives no standard security updates and is missing the fixes
    for CVE-2024-3935 and CVE-2024-10525. The patched build of the same upstream
    version exists only in ESM Apps, and is distinguishable only by its Debian
    revision, so the upstream version this module reports elsewhere cannot answer this.

    Args:
        install_source: One of `archive`, `ppa` or `snap`.

    Returns:
        The installed package version when it is an unsupported archive build, and None
        when the deployment is patched, is not from the archive, or could not be
        determined.
    """
    if install_source != 'archive':
        return None
    try:
        package = apt.DebianPackage.from_installed_package(SERVER_PACKAGE)
    except (apt.Error, OSError, subprocess.SubprocessError) as e:
        # Only ever used to decorate a status, so an answer that cannot be had is not
        # worth a warning on every update-status.
        logger.debug('Could not determine the installed Mosquitto package version: %s', e)
        return None
    version = str(package.version)
    return None if 'esm' in version else version


def supports_test_config(version: str | None) -> bool:
    """Whether this version can check a configuration without running it.

    `mosquitto --test-config` arrived in 2.1. On 2.0 there is no dry run at all, so
    the charm has to fall back on validating its own inputs and on health-checking
    after the change.

    Args:
        version: The running Mosquitto version.

    Returns:
        Whether `--test-config` is available.
    """
    return version_tuple(version) >= (2, 1, 0)


def check_config(file_paths: Paths, version: str | None) -> str | None:
    """Ask Mosquitto whether it would accept what is on disk.

    Returns:
        None if the configuration is acceptable or cannot be checked, otherwise the
        broker's own complaint about it.
    """
    if not supports_test_config(version):
        return None
    binary = (
        pathlib.Path('/snap/bin/mosquitto')
        if file_paths.service.startswith('snap.')
        else pathlib.Path('/usr/sbin/mosquitto')
    )
    try:
        result = _run(
            [binary, '--test-config', '-c', file_paths.config_file], timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning('Could not check the configuration: %s', e)
        return None
    if not result.returncode:
        return None
    errors = [
        line.split(': ', 1)[-1]
        for line in (result.stdout + result.stderr).splitlines()
        if 'Error' in line
    ]
    return '; '.join(errors) or 'the broker rejected the configuration'


def snapshot_fragments(file_paths: Paths) -> dict[str, str | None]:
    """Record the charm's configuration fragments, so they can be put back.

    Args:
        file_paths: Where Mosquitto's files live.

    Returns:
        Each fragment's filename mapped to its contents, or None where it is absent.
    """
    snapshot: dict[str, str | None] = {}
    for name in (CHARM_CONFIG_FILENAME, BRIDGE_CONFIG_FILENAME, EXTRA_CONFIG_FILENAME):
        path = file_paths.conf_dir / name
        snapshot[name] = path.read_text() if path.exists() else None
    return snapshot


def restore_fragments(file_paths: Paths, snapshot: Mapping[str, str | None]) -> None:
    """Put the configuration fragments back as they were.

    Leaving a rejected configuration on disk is not harmless: the packaged logrotate
    fragment sends the broker a SIGHUP every night, so a broker that is running happily
    on its old in-memory configuration dies at 03:00, hours after the operator walked
    away from a blocked unit. A reboot does the same.

    Args:
        file_paths: Where Mosquitto's files live.
        snapshot: The fragments as `snapshot_fragments` recorded them.
    """
    for name, contents in snapshot.items():
        path = file_paths.conf_dir / name
        if contents is None:
            path.unlink(missing_ok=True)
        else:
            pathops.ensure_contents(
                path, contents, mode=0o640, user=file_paths.user, group=file_paths.group
            )


def write_config(
    file_paths: Paths,
    *,
    main: str,
    bridge: str | None = None,
    extra: str = '',
) -> Change:
    """Write the charm's configuration fragments and say what applying them needs.

    Args:
        file_paths: Where Mosquitto's files live.
        main: The main configuration fragment.
        bridge: The bridge fragment, or None to remove any existing one.
        extra: The operator's additional directives.

    Returns:
        The strongest action the change requires.
    """
    ensure_directories(file_paths)

    changes = [
        _write_main_config(file_paths),
        _write_fragment(file_paths, CHARM_CONFIG_FILENAME, main, file_paths),
        _write_fragment(file_paths, BRIDGE_CONFIG_FILENAME, bridge, file_paths),
        _write_fragment(
            file_paths,
            EXTRA_CONFIG_FILENAME,
            (f'# Managed by the mosquitto charm from the extra-config option.\n{extra}\n')
            if extra.strip()
            else None,
            file_paths,
        ),
    ]
    return max(changes)


def _write_fragment(file_paths: Paths, name: str, contents: str | None, target: Paths) -> Change:
    """Write or remove one configuration fragment, classifying the difference."""
    path = file_paths.conf_dir / name
    old = path.read_text() if path.exists() else ''
    if contents is None:
        if not old:
            return Change.NONE
        path.unlink()
        return classify_change(old, '')
    change = classify_change(old, contents)
    # Fragments can carry bridge credentials, so they are never world readable.
    pathops.ensure_contents(path, contents, mode=0o640, user=target.user, group=target.group)
    return change


def _write_main_config(file_paths: Paths) -> Change:
    """Take ownership of the main configuration file.

    The charm cannot simply append to the packaged `/etc/mosquitto/mosquitto.conf`,
    because that file already sets `persistence`, `persistence_location` and
    `log_dest` — and Mosquitto refuses to start when a directive is set twice, in any
    file. So the main config becomes nothing but an include of the charm's fragment
    directory, and everything real lives in fragments the charm owns outright.

    The original is kept alongside, once, so that removing the charm leaves the
    operator something to go back to.
    """
    contents = (
        '# Managed by the mosquitto charm. Do not edit.\n'
        '#\n'
        '# The charm owns every directive, and writes them into the fragments in the\n'
        '# directory below. The packaged configuration this replaced was saved as\n'
        f'# {file_paths.config_file.name}.charm-orig.\n'
        '\n'
        f'include_dir {file_paths.conf_dir}\n'
    )
    backup = file_paths.config_file.with_suffix(file_paths.config_file.suffix + '.charm-orig')
    if file_paths.config_file.exists() and not backup.exists():
        existing = file_paths.config_file.read_text()
        if existing != contents:
            logger.info('Saving the packaged configuration as %s.', backup)
            backup.write_text(existing)
    changed = pathops.ensure_contents(
        file_paths.config_file, contents, mode=0o644, user='root', group='root'
    )
    # The main config is read only at startup, so replacing it means a restart.
    return Change.RESTART if changed else Change.NONE


def write_password_file(file_paths: Paths, users: Mapping[str, str]) -> Change:
    """Write and hash the password file.

    The passwords are written to a private temporary file and hashed in place with
    `mosquitto_passwd -U`, rather than passed to `mosquitto_passwd -b`, which would put
    every password on a command line where `ps` and the audit log would capture it.

    Args:
        file_paths: Where Mosquitto's files live.
        users: Usernames mapped to plaintext passwords.

    Returns:
        Whether the broker needs to re-read the file. The password file is reload-safe.

    Raises:
        Error: If hashing failed.
    """
    plaintext = render_password_file(users)
    # The hashes are salted, so hashing the same passwords twice gives different files
    # and the written file can never be compared against the desired one. Keep a digest
    # of the desired plaintext alongside it instead.
    #
    # Comparing usernames is not good enough, and getting that wrong is silent: an
    # operator changes a password, the username set is unchanged, the charm decides
    # nothing has happened, and the broker keeps accepting only the old password while
    # the action reports success and hands over the new one.
    digest = hashlib.sha256(plaintext.encode()).hexdigest()
    digest_file = file_paths.password_file.with_suffix(
        file_paths.password_file.suffix + '.charm-digest'
    )
    if file_paths.password_file.exists() and digest_file.exists():
        try:
            if digest_file.read_text().strip() == digest:
                return Change.NONE
        except OSError:
            logger.debug('Could not read %s; rewriting the password file.', digest_file)

    with tempfile.NamedTemporaryFile(
        'w', dir=file_paths.password_file.parent, prefix='.passwd-', delete=False
    ) as handle:
        temporary = pathlib.Path(handle.name)
        handle.write(plaintext)
    try:
        temporary.chmod(0o600)
        if users:
            _run([file_paths.passwd_tool, '-U', temporary])
        # Mosquitto drops to its own user before reading this, and warns (and in
        # future will refuse) if it is not owned by that user or is readable by others.
        _chown(temporary, file_paths.user, file_paths.group, 0o600)
        os.replace(temporary, file_paths.password_file)
        temporary = file_paths.password_file
    finally:
        if temporary.exists() and temporary != file_paths.password_file:
            temporary.unlink()
    pathops.ensure_contents(
        digest_file, f'{digest}\n', mode=0o600, user=file_paths.user, group=file_paths.group
    )
    return Change.RELOAD


def write_acl_file(file_paths: Paths, rules: Mapping[str, Sequence[tuple[str, str]]]) -> Change:
    """Write the ACL file.

    Args:
        file_paths: Where Mosquitto's files live.
        rules: Usernames mapped to their (topic filter, access) pairs.

    Returns:
        Whether the broker needs to re-read the file. The ACL file is reload-safe.
    """
    contents = render_acl_file(rules)
    changed = pathops.ensure_contents(
        file_paths.acl_file,
        contents,
        mode=0o600,
        user=file_paths.user,
        group=file_paths.group,
    )
    return Change.RELOAD if changed else Change.NONE


def write_tls_material(file_paths: Paths, material: TLSMaterial) -> Change:
    """Write the certificate, key and authority chain.

    Args:
        file_paths: Where Mosquitto's files live.
        material: The TLS material to write.

    Returns:
        Whether the broker needs to re-read the files.

        Since Mosquitto 2.0 the broker drops to its own user before opening these, so
        the key must be readable by that user — getting this wrong is the usual reason
        a broker fails to start after a certificate renewal. Renewal at unchanged paths
        only needs a reload, because SIGHUP re-reads the file contents.
    """
    ensure_directories(file_paths)
    changed = [
        pathops.ensure_contents(
            file_paths.certs_dir / 'ca.crt',
            material.ca,
            mode=0o644,
            user=file_paths.user,
            group=file_paths.group,
        ),
        pathops.ensure_contents(
            file_paths.certs_dir / 'server.crt',
            material.certificate,
            mode=0o644,
            user=file_paths.user,
            group=file_paths.group,
        ),
        pathops.ensure_contents(
            file_paths.certs_dir / 'server.key',
            material.private_key,
            mode=0o600,
            user=file_paths.user,
            group=file_paths.group,
        ),
    ]
    return Change.RELOAD if any(changed) else Change.NONE


def remove_tls_material(file_paths: Paths) -> Change:
    """Delete the certificate, key and authority chain.

    The broker stops referencing these as soon as the TLS listeners go, so this is not
    what keeps a listener working. It is about not leaving a private key on a machine
    that no longer serves TLS — and not sweeping it into every later backup.

    Args:
        file_paths: Where Mosquitto's files live.

    Returns:
        Whether the broker needs to be restarted to stop using them.
    """
    removed = False
    for name in ('ca.crt', 'server.crt', 'server.key'):
        path = file_paths.certs_dir / name
        if path.exists():
            path.unlink()
            removed = True
    # A restart rather than a reload: `certfile` and `keyfile` are restart-required
    # directives, and the listener they belong to has gone with them.
    return Change.RESTART if removed else Change.NONE


def remove_bridge_ca(file_paths: Paths) -> Change:
    """Delete the certificate authority used to verify the upstream broker.

    Args:
        file_paths: Where Mosquitto's files live.

    Returns:
        Whether the broker needs to be restarted to stop using it.
    """
    path = file_paths.certs_dir / 'bridge-ca.crt'
    if not path.exists():
        return Change.NONE
    path.unlink()
    return Change.RESTART


def write_bridge_ca(file_paths: Paths, ca: str) -> Change:
    """Write the certificate authority used to verify the upstream broker.

    Args:
        file_paths: Where Mosquitto's files live.
        ca: The PEM-encoded authority certificate.

    Returns:
        Whether the broker needs to re-read the file.
    """
    changed = pathops.ensure_contents(
        file_paths.certs_dir / 'bridge-ca.crt',
        ca,
        mode=0o644,
        user=file_paths.user,
        group=file_paths.group,
    )
    # A restart, not a reload: Mosquitto builds a bridge's TLS context when the bridge
    # connection is established and does not re-read `bridge_cafile` on SIGHUP the way
    # it re-reads a listener's certificate. Reloading would leave the bridge on the old
    # authority until it happened to reconnect, and then fail to verify — a bridge that
    # silently stops carrying traffic.
    return Change.RESTART if changed else Change.NONE


def write_service_overrides(file_paths: Paths, *, file_limit: int) -> bool:
    """Write the systemd drop-in for the broker service.

    The packaged unit sets no file descriptor limit, so the broker inherits 1024 and
    refuses new connections at around a thousand clients. `limits.conf` has no effect
    on a systemd service, so this has to be a drop-in. The same drop-in adds the
    sandboxing the package omits, since Ubuntu 24.04 ships no AppArmor profile for
    Mosquitto despite what its README says.

    Args:
        file_paths: Where Mosquitto's files live.
        file_limit: The file descriptor limit to set.

    Returns:
        Whether the unit changed, and so whether systemd needs a `daemon-reload`.
    """
    if file_paths.service.startswith('snap.'):
        # snapd owns its generated units and regenerates them; a drop-in would be
        # fragile, and the snap's confinement already covers most of the sandboxing.
        logger.debug('Not writing service overrides for a snap-managed service.')
        return False

    dropin_dir = pathlib.Path(DROPIN_DIR_TEMPLATE.format(service=file_paths.service))
    dropin_dir.mkdir(parents=True, exist_ok=True)
    contents = f"""\
# Managed by the mosquitto charm. Do not edit.
[Unit]
# The packaged unit only waits for network.target, which is not enough when a
# listener binds to a specific address.
After=network-online.target
Wants=network-online.target

# The packaged unit inherits systemd's default rate limit, so a handful of quick
# failures latches the unit into "start request repeated too quickly" and it then
# refuses to start even once the configuration is fixed.
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
LimitNOFILE={file_limit}
Restart=on-failure
RestartSec=5s

# Ubuntu 24.04 ships no AppArmor profile for Mosquitto, so this is the confinement.
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallArchitectures=native
SystemCallFilter=@system-service

# `full` rather than `strict`: strict makes the whole filesystem read-only, which
# breaks the packaged unit's own ExecStartPre mkdir and chown before the broker even
# runs. `full` protects /usr, /boot and /efi, which is the part that matters.
ProtectSystem=full
ReadWritePaths={file_paths.persistence_dir} {file_paths.log_file.parent}

# Deliberately *not* set: SystemCallFilter=~@privileged. Mosquitto starts as root so
# that it can bind a privileged port, then calls setuid and setgid to drop to its own
# user -- both of which are in @privileged, so filtering it kills the broker with
# SIGSYS before it finishes starting.
"""
    changed = pathops.ensure_contents(
        dropin_dir / DROPIN_FILENAME, contents, mode=0o644, user='root', group='root'
    )
    if changed:
        # systemd will not read a drop-in it has not been told about, and refuses to
        # act on the unit at all until it has been reloaded.
        systemd.daemon_reload()
    return changed


def apply_sysctl(*, enabled: bool) -> None:
    """Tune kernel networking parameters, or remove the charm's tuning.

    Where the kernel namespace forbids the write — which is the normal case inside an
    unprivileged container — this logs and carries on rather than failing the hook.
    The broker works fine without it; it just will not reach its ceiling.

    Args:
        enabled: Whether the tuning should be in place.
    """
    config = sysctl.Config(name='mosquitto')
    if not enabled:
        with contextlib.suppress(sysctl.Error):
            config.remove()
        return
    try:
        config.configure(SYSCTL_TUNING)
    except sysctl.Error as e:
        logger.warning(
            'Could not apply kernel network tuning (%s). The broker will run, but will '
            'not reach the connection counts the tuning is for. Set sysctl-tuning=false '
            'to stop trying.',
            e,
        )


def install_exporter(
    source: pathlib.Path,
    file_paths: Paths,
    *,
    broker_host: str,
    broker_port: int,
    username: str,
    password: str,
    listen_address: str,
    listen_port: int,
    stale_after: int,
    max_connections: int,
) -> bool:
    """Install and configure the metrics exporter service.

    Args:
        source: The exporter script in the charm's source directory.
        file_paths: Where Mosquitto's files live.
        broker_host: The address the exporter connects to.
        broker_port: The port the exporter connects to.
        username: The MQTT user the exporter authenticates as.
        password: That user's password.
        listen_address: The address the exporter serves metrics on.
        listen_port: The port the exporter serves metrics on.
        stale_after: How long the exporter may go without a `$SYS` message before it
            reports the broker as down.
        max_connections: The broker's connection ceiling, exported so that alerts can
            be written against the configured limit rather than against a fixed number.
            Negative for no limit, in which case nothing is exported.

    Returns:
        Whether anything changed, and so whether the service needs restarting.
    """
    EXPORTER_INSTALL_PATH.parent.mkdir(parents=True, exist_ok=True)
    script_changed = pathops.ensure_contents(
        EXPORTER_INSTALL_PATH, source.read_text(), mode=0o755, user='root', group='root'
    )

    # The service runs as a systemd DynamicUser, so it cannot read a root-owned file.
    # Hand the password over as a systemd credential instead: systemd reads the file as
    # root and exposes it to the service alone, under $CREDENTIALS_DIRECTORY.
    password_file = EXPORTER_INSTALL_PATH.parent / 'exporter.password'
    password_changed = pathops.ensure_contents(
        password_file, password, mode=0o600, user='root', group='root'
    )

    unit = f"""\
# Managed by the mosquitto charm. Do not edit.
[Unit]
Description=Mosquitto $SYS metrics exporter for Prometheus
After={file_paths.service}.service
Wants={file_paths.service}.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 {EXPORTER_INSTALL_PATH} \\
    --broker-host {broker_host} --broker-port {broker_port} \\
    --username {username} --password-file %d/mqtt-password \\
    --listen-address {listen_address} --listen-port {listen_port} \\
    --stale-after {stale_after} --max-connections {max_connections} \\
    --mosquitto-sub-path {file_paths.sub_tool}
LoadCredential=mqtt-password:{password_file}
Restart=always
RestartSec=5s
DynamicUser=yes
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_INET AF_INET6
SystemCallArchitectures=native
SystemCallFilter=@system-service

[Install]
WantedBy=multi-user.target
"""
    unit_changed = pathops.ensure_contents(
        pathlib.Path(f'/etc/systemd/system/{EXPORTER_SERVICE}.service'),
        unit,
        mode=0o644,
        user='root',
        group='root',
    )
    if unit_changed:
        systemd.daemon_reload()
    return script_changed or password_changed or unit_changed


def remove_exporter() -> None:
    """Stop and remove the metrics exporter service, and the credentials it used."""
    unit = pathlib.Path(f'/etc/systemd/system/{EXPORTER_SERVICE}.service')
    if unit.exists():
        with contextlib.suppress(systemd.SystemdError):
            systemd.service_stop(EXPORTER_SERVICE)
            systemd.service_disable(EXPORTER_SERVICE)
        unit.unlink()
        systemd.daemon_reload()
    # The password is a live broker credential, so it goes with the service rather than
    # staying on a machine the charm may no longer be on. This is outside the `exists`
    # check above on purpose: an interrupted install can leave the password without the
    # unit file.
    shutil.rmtree(EXPORTER_INSTALL_PATH.parent, ignore_errors=True)


def exporter_running() -> bool:
    """Whether the metrics exporter is running."""
    try:
        return systemd.service_running(EXPORTER_SERVICE)
    except systemd.SystemdError:
        return False


def start_exporter() -> None:
    """Start and enable the metrics exporter service.

    Raises:
        ServiceError: If the service would not start.
    """
    try:
        systemd.service_enable(EXPORTER_SERVICE)
        systemd.service_restart(EXPORTER_SERVICE)
    except systemd.SystemdError as e:
        raise ServiceError(f'could not start the metrics exporter: {e}') from e


def apply(file_paths: Paths, change: Change) -> None:
    """Apply a pending configuration change to the running broker.

    Args:
        file_paths: Where Mosquitto's files live.
        change: What the change requires.

    Raises:
        ServiceError: If the broker would not reload or restart.
    """
    if change is Change.NONE:
        return
    if not is_running(file_paths):
        logger.debug('Broker is not running; nothing to apply.')
        return
    if change is Change.RESTART:
        reset_failed(file_paths)
    try:
        if change is Change.RELOAD:
            logger.info('Reloading Mosquitto; client connections are unaffected.')
            # Note that a reload is asynchronous and succeeds even for a configuration
            # the broker then rejects, which is why the caller health-checks after.
            systemd.service_reload(file_paths.service)
        else:
            logger.info('Restarting Mosquitto; all clients will be disconnected.')
            systemd.service_restart(file_paths.service)
    except systemd.SystemdError as e:
        raise ServiceError(f'could not {change.name.lower()} Mosquitto: {e}') from e


def reset_failed(file_paths: Paths) -> None:
    """Clear a latched systemd failure, so the unit can be started again."""
    with contextlib.suppress(Error, OSError, subprocess.SubprocessError):
        _run(['/usr/bin/systemctl', 'reset-failed', file_paths.service], timeout=15, check=False)


def last_log(file_paths: Paths, lines: int = 20) -> str:
    """Return the tail of the broker's logs, for reporting why it would not start.

    Both the journal and the log file: the broker is configured with `log_dest file`, so
    everything after it opens that file goes there and not to the journal, while a
    failure to parse the configuration happens before there is a file to write to.

    Args:
        file_paths: Where Mosquitto's files live.
        lines: How many lines to take from each source.

    Returns:
        The lines, or an empty string if neither source could be read.
    """
    collected: list[str] = []
    try:
        result = _run(
            ['/usr/bin/journalctl', '-u', file_paths.service, '-n', str(lines), '--no-pager'],
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    else:
        collected.extend(result.stdout.splitlines())
    try:
        # The log can be large, and this runs on the path where the broker is already
        # refusing to start, so read the tail rather than the file.
        with file_paths.log_file.open('rb') as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 8192))
            tail = log.read().decode('utf-8', errors='replace')
    except OSError:
        pass
    else:
        collected.extend(tail.splitlines()[-lines:])
    return '\n'.join(collected)


def start(file_paths: Paths) -> None:
    """Start and enable the broker.

    Raises:
        ServiceError: If the broker would not start.
    """
    reset_failed(file_paths)
    try:
        systemd.service_enable(file_paths.service)
        systemd.service_start(file_paths.service)
    except systemd.SystemdError as e:
        raise ServiceError(f'could not start Mosquitto: {e}') from e


def pause(file_paths: Paths) -> None:
    """Stop the broker and stop it coming back at the next boot.

    `stop` on its own leaves the unit enabled, so a reboot during the host maintenance
    the operator paused for would start the broker again while the charm went on
    reporting that it was paused.

    Raises:
        ServiceError: If the broker would not stop.
    """
    stop(file_paths)
    try:
        systemd.service_disable(file_paths.service)
    except systemd.SystemdError as e:
        raise ServiceError(f'could not disable Mosquitto: {e}') from e


def stop(file_paths: Paths) -> None:
    """Stop the broker.

    Raises:
        ServiceError: If the broker would not stop.
    """
    try:
        systemd.service_stop(file_paths.service)
    except systemd.SystemdError as e:
        raise ServiceError(f'could not stop Mosquitto: {e}') from e


def is_running(file_paths: Paths) -> bool:
    """Whether the broker is running.

    The packaged unit is `Type=notify`, so systemd only considers the service active
    once the broker is genuinely listening.
    """
    try:
        return systemd.service_running(file_paths.service)
    except systemd.SystemdError:
        return False


@contextlib.contextmanager
def _client_config(file_paths: Paths, password: str) -> Generator[Mapping[str, str]]:
    """Yield an environment that gives the Mosquitto client tools a password.

    The client tools read default options from `$XDG_CONFIG_HOME/mosquitto_<tool>`.
    Using that rather than `-P` keeps the password out of the process table, the audit
    log, and anything else that reads command lines.
    """
    with tempfile.TemporaryDirectory(prefix='mosquitto-charm-') as directory:
        base = pathlib.Path(directory)
        for tool in ('mosquitto_rr', 'mosquitto_sub', 'mosquitto_pub'):
            option_file = base / tool
            option_file.write_text(f'-P {password}\n')
            option_file.chmod(0o600)
        yield {
            'XDG_CONFIG_HOME': str(base),
            'HOME': str(base),
            'PATH': f'{file_paths.bindir}:/usr/bin:/bin',
        }


def health_check(
    file_paths: Paths,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    cafile: pathlib.Path | None = None,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Check that the broker is really serving MQTT.

    A TCP connect proves almost nothing: a broker can accept connections while out of
    memory, wedged, or failing every TLS handshake because it cannot read its own key.
    This does a full round trip — connect, subscribe, publish, receive — at QoS 1, so a
    success means a client could actually use the broker.

    Args:
        file_paths: Where Mosquitto's files live.
        host: The broker address to connect to.
        port: The broker port to connect to.
        username: The MQTT user to authenticate as.
        password: That user's password.
        cafile: The authority certificate, when checking a TLS listener.
        timeout: How long to wait for the round trip, in seconds.

    Returns:
        Whether the check passed, and a message describing the outcome.
    """
    # A unique client id per check, because two clients sharing an id disconnect each
    # other, and a health check that fights the previous health check is worse than no
    # health check at all.
    topic = f'{HEALTH_TOPIC_PREFIX}/{secrets.token_hex(8)}'
    command: list[str | pathlib.Path] = [
        file_paths.rr_tool,
        '-h', host,
        '-p', str(port),
        '-u', username,
        '-i', f'charm-health-{secrets.token_hex(4)}',
        '-t', topic,
        '-e', topic,
        '-m', 'ping',
        '-q', '1',
        '-W', str(timeout),
    ]  # fmt: skip
    if cafile is not None:
        command.extend(['--cafile', cafile])
    try:
        with _client_config(file_paths, password) as env:
            result = _run(command, timeout=timeout + 5, env=env, check=False)
    except subprocess.TimeoutExpired:
        return False, f'no response from {host}:{port} within {timeout}s'
    except OSError as e:
        return False, f'could not run {file_paths.rr_tool}: {e}'
    if result.returncode:
        return False, (result.stderr.strip() or result.stdout.strip() or 'round trip failed')
    return True, f'{host}:{port} answered a QoS 1 round trip'


HEALTH_TOPIC_PREFIX = 'charm/health'
"""The topic prefix health checks use, and the only thing the health user may touch."""


def websocket_check(
    *,
    host: str,
    port: int,
    tls: bool = False,
    cafile: pathlib.Path | None = None,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Check that a WebSocket listener is serving MQTT.

    The Mosquitto client tools speak MQTT over TCP only, so this cannot be the same
    QoS 1 round trip `health_check` does. It goes as far as anything without an MQTT
    WebSocket client can: open the connection, complete the TLS handshake where there
    is one, and perform the HTTP upgrade Mosquitto answers for `mqtt`. That covers the
    failures that actually happen here — a build without WebSocket support, a listener
    that is not up, and TLS material the broker cannot read.

    Args:
        host: The broker address to connect to.
        port: The broker port to connect to.
        tls: Whether to connect over TLS.
        cafile: The authority certificate, when checking a TLS listener.
        timeout: How long to wait for the upgrade, in seconds.

    Returns:
        Whether the check passed, and a message describing the outcome.
    """
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    request = (
        # Mosquitto serves MQTT over WebSockets at the root path.
        f'GET / HTTP/1.1\r\n'
        f'Host: {host}:{port}\r\n'
        f'Upgrade: websocket\r\n'
        f'Connection: Upgrade\r\n'
        f'Sec-WebSocket-Key: {key}\r\n'
        f'Sec-WebSocket-Version: 13\r\n'
        f'Sec-WebSocket-Protocol: mqtt\r\n'
        f'\r\n'
    ).encode()
    try:
        connection = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        return False, f'could not connect to {host}:{port}: {e}'
    try:
        if tls:
            context = ssl.create_default_context(cafile=str(cafile) if cafile else None)
            connection = context.wrap_socket(connection, server_hostname=host)
        connection.sendall(request)
        response = connection.recv(4096).decode('utf-8', errors='replace')
    except OSError as e:
        # `ssl.SSLError` is an `OSError`, so a handshake the broker cannot complete --
        # an unreadable key, an expired certificate -- lands here too.
        return False, f'the WebSocket upgrade on {host}:{port} failed: {e}'
    finally:
        connection.close()
    status = response.split('\r\n', 1)[0].strip()
    if '101' not in status.split():
        return False, f'{host}:{port} did not upgrade: {status or "no response"}'
    if 'mqtt' not in response.lower():
        return False, f'{host}:{port} upgraded without accepting the mqtt subprotocol'
    return True, f'{host}:{port} completed a WebSocket upgrade for mqtt'


def sys_snapshot(
    file_paths: Paths,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: int = 10,
) -> dict[str, str]:
    """Read the broker's `$SYS` statistics tree.

    Args:
        file_paths: Where Mosquitto's files live.
        host: The broker address to connect to.
        port: The broker port to connect to.
        username: The MQTT user to authenticate as.
        password: That user's password.
        timeout: How long to collect for, in seconds.

    Returns:
        `$SYS` topics mapped to their latest values.
    """
    command: list[str | pathlib.Path] = [
        file_paths.sub_tool,
        '-h', host,
        '-p', str(port),
        '-u', username,
        '-i', f'charm-stats-{secrets.token_hex(4)}',
        '-t', '$SYS/#',
        '-F', '%t\t%p',
        '-W', str(timeout),
    ]  # fmt: skip
    try:
        with _client_config(file_paths, password) as env:
            result = _run(command, timeout=timeout + 5, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning('Could not read the $SYS tree: %s', e)
        return {}
    snapshot: dict[str, str] = {}
    for line in result.stdout.splitlines():
        topic, _, value = line.partition('\t')
        if topic:
            snapshot[topic] = value
    return snapshot


def create_backup(file_paths: Paths, destination: pathlib.Path | None = None) -> pathlib.Path:
    """Back up everything that would be needed to rebuild this broker.

    Args:
        file_paths: Where Mosquitto's files live.
        destination: Where to write the tarball. Defaults to a timestamped file in the
            backup directory.

    Returns:
        The path of the tarball.

    Raises:
        Error: If the backup could not be written.
    """
    ensure_directories(file_paths)
    if destination is None:
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        destination = file_paths.backup_dir / f'mosquitto-{stamp}.tar.gz'
    destination.parent.mkdir(parents=True, exist_ok=True)

    sources: list[pathlib.Path] = [path for path in file_paths.managed_files() if path.exists()]
    # The persistence database is written on autosave, so this copy is a point in time
    # somewhere in the last `autosave_interval` seconds rather than exactly now.
    database = file_paths.persistence_dir / 'mosquitto.db'
    if database.exists():
        sources.append(database)
    certs = sorted(file_paths.certs_dir.glob('*'))
    sources.extend(certs)

    # The tarball holds password hashes and, on a TLS unit, the private key, so it is
    # created private rather than created at the umask and chmodded afterwards --
    # which would leave a window in which anyone could read it.
    #
    # `O_EXCL | O_NOFOLLOW` rather than `O_TRUNC`: the action checks that the
    # destination does not exist, but that check and this open are two syscalls with a
    # gap between them, and the backup runs as root. Refusing outright to write through
    # a symlink, or to a file that appeared in the gap, closes it.
    try:
        handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with open(handle, 'wb') as raw, tarfile.open(fileobj=raw, mode='w:gz') as archive:
            for path in sources:
                archive.add(path, arcname=str(path).lstrip('/'))
    except (OSError, tarfile.TarError) as e:
        raise Error(f'could not write the backup to {destination}: {e}') from e
    logger.info('Wrote a backup of %d files to %s.', len(sources), destination)
    return destination


def restore_backup(file_paths: Paths, source: pathlib.Path) -> None:
    """Restore from a tarball made by `create_backup`.

    The caller is responsible for stopping the broker first: restoring the persistence
    database under a running broker would be overwritten at the next autosave.

    Args:
        file_paths: Where Mosquitto's files live.
        source: The tarball to restore from.

    Raises:
        Error: If the tarball is missing, unreadable, or contains paths outside the
            directories the charm manages.
    """
    if not source.is_file():
        raise Error(f'{source} is not a file')
    permitted = (
        file_paths.config_file.parent,
        file_paths.conf_dir,
        file_paths.persistence_dir,
        file_paths.certs_dir,
    )
    try:
        with tarfile.open(source, 'r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                # `pathlib` does not normalise `..`, so `etc/mosquitto/../../tmp/x` is
                # "relative to" /etc/mosquitto and would pass a naive containment check
                # — an arbitrary file write as root, from a path an operator supplies to
                # the restore-backup action. tarfile's `data` filter does not help here
                # either, because extracting to `/` makes its own containment check
                # vacuous. Normalise first, and compare the normalised path.
                target = pathlib.Path(os.path.normpath(pathlib.Path('/') / member.name))
                # A tarball is attacker-controlled input as far as this charm is
                # concerned: refuse anything that would write outside the broker's own
                # directories, whether by absolute path, `..`, or a symlink.
                if member.issym() or member.islnk():
                    raise Error(f'{source} contains a link ({member.name}), which is not allowed')
                if not any(target.is_relative_to(directory) for directory in permitted):
                    raise Error(f'{source} contains an unexpected path: {member.name}')
            archive.extractall('/', members=members, filter='data')
    except tarfile.TarError as e:
        raise Error(f'could not read the backup {source}: {e}') from e
    except OSError as e:
        raise Error(f'could not restore the backup {source}: {e}') from e

    # tarfile's `data` filter deliberately discards ownership, so everything lands
    # owned by root. Since 2.0 the broker drops to its own user before opening its key
    # and its persistence database, so without this it cannot read what was restored,
    # and the next start fails.
    for path in file_paths.managed_files():
        if path.exists():
            _chown(
                path,
                file_paths.user,
                file_paths.group,
                # The password and ACL files name every user and everything each may
                # do, and are written 0o600; a restore must not widen that.
                0o640 if path.name.endswith('.conf') else 0o600,
            )
    database = file_paths.persistence_dir / 'mosquitto.db'
    if database.exists():
        _chown(database, file_paths.user, file_paths.group, 0o600)
    if file_paths.certs_dir.exists():
        for certificate in file_paths.certs_dir.glob('*'):
            _chown(
                certificate,
                file_paths.user,
                file_paths.group,
                0o600 if certificate.suffix == '.key' else 0o644,
            )
    logger.info('Restored %s.', source)


def migrate_state(old: Paths, new: Paths) -> None:
    """Move broker state from one install layout to another.

    Changing `install-source` moves everything the broker owns, because a strictly
    confined snap cannot see /etc/mosquitto and a deb-installed broker has no reason to
    look in /var/snap.

    Args:
        old: The layout the state is currently in.
        new: The layout to move it to.
    """
    if old == new:
        return
    # Nothing else stops the previous broker, and the deb and the snap both bind the
    # same port: leaving the old one enabled means two brokers fighting over 1883, the
    # new one crash-looping, and a blocked unit with no hint as to why.
    if is_running(old):
        logger.info('Stopping the previous Mosquitto (%s) before migrating.', old.service)
        with contextlib.suppress(ServiceError, systemd.SystemdError):
            stop(old)
    with contextlib.suppress(systemd.SystemdError):
        systemd.service_disable(old.service)
    ensure_directories(new)
    for source, target in (
        (old.password_file, new.password_file),
        (old.acl_file, new.acl_file),
        (old.persistence_dir / 'mosquitto.db', new.persistence_dir / 'mosquitto.db'),
    ):
        if source.exists() and not target.exists():
            logger.info('Migrating %s to %s.', source, target)
            shutil.copy2(source, target)
            _chown(target, new.user, new.group, 0o600)
    if old.certs_dir.exists():
        for certificate in old.certs_dir.glob('*'):
            target = new.certs_dir / certificate.name
            if not target.exists():
                shutil.copy2(certificate, target)
                _chown(
                    target, new.user, new.group, 0o600 if certificate.suffix == '.key' else 0o644
                )


def listeners_for(
    *,
    port: int,
    tls_port: int,
    websockets_port: int,
    tls_websockets_port: int,
    have_certificates: bool,
) -> tuple[Listener, ...]:
    """Work out which listeners to configure.

    TLS listeners are only opened once a certificate is available, so that relating a
    certificate authority turns them on and losing it does not leave the broker
    refusing to start.

    Args:
        port: The plaintext MQTT port, or 0 for none.
        tls_port: The MQTT-over-TLS port, or 0 for none.
        websockets_port: The plaintext WebSockets port, or 0 for none.
        tls_websockets_port: The WebSockets-over-TLS port, or 0 for none.
        have_certificates: Whether TLS material is available.

    Returns:
        The listeners to render, in a stable order.
    """
    listeners: list[Listener] = []
    if port:
        listeners.append(Listener(port=port))
    if websockets_port:
        listeners.append(Listener(port=websockets_port, websockets=True))
    if have_certificates and tls_port:
        listeners.append(Listener(port=tls_port, tls=True))
    if have_certificates and tls_websockets_port:
        listeners.append(Listener(port=tls_websockets_port, websockets=True, tls=True))
    return tuple(listeners)


def merge_changes(changes: Iterable[Change]) -> Change:
    """Return the strongest of several changes.

    Args:
        changes: The changes to combine.

    Returns:
        The strongest action required, or `Change.NONE` if there were none.
    """
    return max(changes, default=Change.NONE)
