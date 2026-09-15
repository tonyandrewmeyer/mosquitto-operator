# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Typed Juju configuration and action parameters.

Every Juju config option and every action parameter has a class here, so that the
charm never reaches into an untyped dictionary and every validation failure produces a
message that says what the operator should change.
"""

from __future__ import annotations

import enum
import re
from typing import Annotated, ClassVar

import pydantic

import mqtt

# Directives an operator must not smuggle in through `extra-config`. Each of these is
# managed by the charm, and letting a fragment override one means the charm's model of
# the broker stops matching the broker. `listener` and `allow_anonymous` are the
# dangerous pair: with no listener defined, Mosquitto 2.x permits anonymous access on
# loopback, so removing the charm's listener silently re-enables it.
RESERVED_DIRECTIVES = frozenset(
    {
        'acl_file',
        'allow_anonymous',
        'bind_address',
        'bind_interface',
        'listener',
        'password_file',
        'per_listener_settings',
        'plugin',
        'global_plugin',
        'auth_plugin',
        'port',
        'user',
    }
)

_DURATION_RE = re.compile(r'^\d+[hdwm]$')
_TOPIC_DIRECTIVE_RE = re.compile(r'^topic\s+\S+(\s+(in|out|both)(\s+\S+){0,2})?\s*$')

Port = Annotated[int, pydantic.Field(ge=0, le=65535)]
"""A TCP port, where 0 means "do not listen"."""


class InstallSource(enum.StrEnum):
    """Where the Mosquitto packages come from."""

    ARCHIVE = 'archive'
    PPA = 'ppa'
    SNAP = 'snap'


class LogLevel(enum.StrEnum):
    """How much the broker logs.

    Each level implies the ones above it; the charm expands the chosen level into the
    corresponding set of `log_type` directives.
    """

    ERROR = 'error'
    WARNING = 'warning'
    NOTICE = 'notice'
    INFORMATION = 'information'
    DEBUG = 'debug'


class TLSVersion(enum.StrEnum):
    """The minimum TLS version accepted on the TLS listeners."""

    TLSV1_2 = 'tlsv1.2'
    TLSV1_3 = 'tlsv1.3'


class MosquittoConfig(pydantic.BaseModel):
    """The charm's Juju configuration.

    Attribute names are the Juju option names with dashes replaced by underscores,
    which is the mapping `ops.CharmBase.load_config` applies.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    # Installation.
    install_source: InstallSource = InstallSource.ARCHIVE
    package_channel: str = 'latest/stable'

    # Listeners.
    port: Port = 1883
    tls_port: Port = 8883
    websockets_port: Port = 0
    tls_websockets_port: Port = 0

    # Security.
    allow_anonymous: bool = False
    tls_version: TLSVersion = TLSVersion.TLSV1_2
    require_client_certificate: bool = False
    use_identity_as_username: bool = False
    certificate_common_name: str = ''
    certificate_extra_sans_dns: str = ''
    certificate_organization: str = ''

    # Persistence.
    persistence: bool = True
    autosave_interval: int = pydantic.Field(default=300, ge=0)
    persistent_client_expiration: str = '14d'

    # Limits.
    max_connections: int = pydantic.Field(default=1024, ge=-1)
    max_inflight_messages: int = pydantic.Field(default=20, ge=0)
    max_queued_messages: int = pydantic.Field(default=1000, ge=0)
    max_queued_bytes: int = pydantic.Field(default=0, ge=0)
    max_packet_size: int = pydantic.Field(default=2_000_000, ge=0)
    max_keepalive: int = pydantic.Field(default=65535, ge=0, le=65535)
    memory_limit: int = pydantic.Field(default=0, ge=0)
    retain_available: bool = True
    queue_qos0_messages: bool = False

    # Logging and monitoring.
    log_level: LogLevel = LogLevel.NOTICE
    connection_messages: bool = True
    sys_interval: int = pydantic.Field(default=10, ge=0)
    metrics_port: Port = 9234

    # Tuning.
    open_file_limit: int = pydantic.Field(default=0, ge=0)
    sysctl_tuning: bool = True

    # Escape hatches.
    extra_config: str = ''
    bridge_topics: str = ''

    @pydantic.field_validator('persistent_client_expiration')
    @classmethod
    def _check_expiration(cls, value: str) -> str:
        """Reject durations Mosquitto will not parse."""
        if value and not _DURATION_RE.match(value):
            raise ValueError(
                f'persistent-client-expiration must be a number followed by h, d, w '
                f'or m (for example 14d), or empty to never expire; got {value!r}'
            )
        return value

    @pydantic.field_validator('extra_config')
    @classmethod
    def _check_extra_config(cls, value: str) -> str:
        """Reject directives that would undermine what the charm manages."""
        offenders = sorted(
            {
                directive
                for directive in (
                    line.split()[0].lower() for line in value.splitlines() if line.split()
                )
                if not directive.startswith('#') and directive in RESERVED_DIRECTIVES
            }
        )
        if offenders:
            raise ValueError(
                f'extra-config must not set directives the charm manages: '
                f'{", ".join(offenders)}. Use the matching charm config options '
                f'instead.'
            )
        return value

    @pydantic.field_validator('bridge_topics')
    @classmethod
    def _check_bridge_topics(cls, value: str) -> str:
        """Reject bridge topic lines Mosquitto will not parse."""
        for number, line in enumerate(value.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if not _TOPIC_DIRECTIVE_RE.match(stripped):
                raise ValueError(
                    f'bridge-topics line {number} is not a topic directive: '
                    f'{stripped!r}. Each line must be '
                    f'"topic <pattern> [in|out|both] [local_prefix] [remote_prefix]".'
                )
        return value

    @pydantic.model_validator(mode='after')
    def _check_listeners(self) -> MosquittoConfig:
        """Reject port collisions and configurations with nothing listening."""
        ports = [
            ('port', self.port),
            ('tls-port', self.tls_port),
            ('websockets-port', self.websockets_port),
            ('tls-websockets-port', self.tls_websockets_port),
            ('metrics-port', self.metrics_port),
        ]
        enabled = [(name, value) for name, value in ports if value]
        seen: dict[int, str] = {}
        for name, value in enabled:
            if value in seen:
                raise ValueError(
                    f'{name} and {seen[value]} are both set to {value}; each listener '
                    f'needs its own port'
                )
            seen[value] = name
        if not any(
            value
            for name, value in enabled
            if name in {'port', 'tls-port', 'websockets-port', 'tls-websockets-port'}
        ):
            raise ValueError(
                'every listener is disabled; set at least one of port, tls-port, '
                'websockets-port or tls-websockets-port to a non-zero value'
            )
        return self

    @pydantic.model_validator(mode='after')
    def _check_client_certificates(self) -> MosquittoConfig:
        """Reject `use-identity-as-username` without client certificates."""
        if self.use_identity_as_username and not self.require_client_certificate:
            raise ValueError(
                'use-identity-as-username has no effect without '
                'require-client-certificate, because there is no client certificate '
                'to take an identity from'
            )
        return self

    @property
    def tls_wanted(self) -> bool:
        """Whether any TLS listener is configured."""
        return bool(self.tls_port or self.tls_websockets_port)

    @property
    def extra_sans_dns(self) -> tuple[str, ...]:
        """The additional DNS subject alternative names to request."""
        return tuple(
            name.strip() for name in self.certificate_extra_sans_dns.split(',') if name.strip()
        )

    def file_limit(self) -> int:
        """The file descriptor limit the broker service should run with.

        The packaged unit sets none, so the broker inherits 1024 and stops accepting
        connections at around a thousand clients. Each connection costs one descriptor,
        so the limit has to clear `max-connections` with room for the listening sockets,
        the log, and the persistence database.
        """
        if self.open_file_limit:
            return self.open_file_limit
        if self.max_connections < 0:
            return 65536
        return max(4096, self.max_connections + 1024)


class SetPasswordParams(pydantic.BaseModel):
    """Parameters for the `set-password` action."""

    username: str = pydantic.Field(min_length=1)
    password: str | None = None

    _FORBIDDEN: ClassVar[frozenset[str]] = frozenset({':', '\n', '\r'})

    @pydantic.field_validator('username')
    @classmethod
    def _check_username(cls, value: str) -> str:
        """Reject usernames the password file format cannot represent.

        The password file is colon-separated, one user per line, so a username
        containing a colon or a newline would corrupt it.
        """
        if any(character in value for character in cls._FORBIDDEN):
            raise ValueError('username must not contain a colon or a line break')
        if value.startswith('_'):
            raise ValueError('usernames beginning with an underscore are reserved for the charm')
        return value


class RemoveUserParams(pydantic.BaseModel):
    """Parameters for the `remove-user` action."""

    username: str = pydantic.Field(min_length=1)


class GrantParams(pydantic.BaseModel):
    """Parameters for the `grant` action."""

    username: str = pydantic.Field(min_length=1)
    topic: str = pydantic.Field(min_length=1)
    access: mqtt.Access = mqtt.Access.READWRITE

    @pydantic.field_validator('access')
    @classmethod
    def _check_access(cls, value: mqtt.Access) -> mqtt.Access:
        """Reject the placeholder value, which is not a real access level."""
        if value is mqtt.Access.UNKNOWN:
            raise ValueError('access must be one of read, write, readwrite or deny')
        return value


class RevokeParams(pydantic.BaseModel):
    """Parameters for the `revoke` action."""

    username: str = pydantic.Field(min_length=1)
    topic: str = pydantic.Field(min_length=1)


class Listener(enum.StrEnum):
    """Which listener an action applies to."""

    PLAIN = 'plain'
    TLS = 'tls'
    ALL = 'all'


class HealthCheckParams(pydantic.BaseModel):
    """Parameters for the `health-check` action."""

    listener: Listener = Listener.ALL


class CreateBackupParams(pydantic.BaseModel):
    """Parameters for the `create-backup` action."""

    path: str | None = None


class RestoreBackupParams(pydantic.BaseModel):
    """Parameters for the `restore-backup` action."""

    path: str = pydantic.Field(min_length=1)
