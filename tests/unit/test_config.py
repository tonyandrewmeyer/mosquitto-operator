# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Tests for the typed Juju configuration and action parameters."""

from __future__ import annotations

import pydantic
import pytest

import config


def make(**overrides: object) -> config.MosquittoConfig:
    """Build a config with the given overrides on top of the defaults."""
    return config.MosquittoConfig(**overrides)  # type: ignore[arg-type]


def test_defaults_are_valid():
    settings = make()
    assert settings.port == 1883
    assert settings.allow_anonymous is False
    assert settings.install_source is config.InstallSource.ARCHIVE


def test_config_is_frozen():
    settings = make()
    with pytest.raises(pydantic.ValidationError):
        settings.port = 1884


@pytest.mark.parametrize('value', ['14d', '1h', '52w', '6m', '0d', ''])
def test_valid_client_expiration(value: str):
    assert make(persistent_client_expiration=value).persistent_client_expiration == value


@pytest.mark.parametrize('value', ['14', 'd14', '14 d', 'forever', '14y', '-1d'])
def test_invalid_client_expiration(value: str):
    with pytest.raises(pydantic.ValidationError, match='persistent-client-expiration'):
        make(persistent_client_expiration=value)


@pytest.mark.parametrize(
    'directive',
    [
        'listener 1884',
        'allow_anonymous true',
        'password_file /tmp/evil',
        'acl_file /tmp/evil',
        'plugin /tmp/evil.so',
        'per_listener_settings true',
        'user root',
        'port 1884',
        'bind_address 0.0.0.0',
    ],
)
def test_extra_config_rejects_managed_directives(directive: str):
    """An operator must not be able to undo the charm's own invariants.

    Removing the listener is the dangerous one: with no listener defined, Mosquitto
    2.x permits anonymous access, so this would silently open the broker.
    """
    with pytest.raises(pydantic.ValidationError, match='must not set directives'):
        make(extra_config=directive)


def test_extra_config_reports_every_offender():
    with pytest.raises(pydantic.ValidationError) as excinfo:
        make(extra_config='listener 1884\nmax_topic_alias 10\nplugin /x.so\n')
    message = str(excinfo.value)
    assert 'listener' in message
    assert 'plugin' in message
    assert 'max_topic_alias' not in message


@pytest.mark.parametrize(
    'value',
    [
        'max_topic_alias 10',
        '# listener 1884',
        '',
        '\n\n',
        'log_timestamp_format %Y-%m-%d',
        'max_topic_alias 10\nallow_duplicate_messages false',
    ],
)
def test_extra_config_allows_unmanaged_directives(value: str):
    assert make(extra_config=value).extra_config == value


@pytest.mark.parametrize(
    'value',
    [
        'topic sensors/#',
        'topic sensors/# out',
        'topic sensors/# both local/ remote/',
        '# a comment\ntopic a/b in',
        '',
    ],
)
def test_valid_bridge_topics(value: str):
    assert make(bridge_topics=value).bridge_topics == value


@pytest.mark.parametrize(
    'value',
    ['sensors/#', 'topic', 'topic sensors/# sideways', 'connection other'],
)
def test_invalid_bridge_topics(value: str):
    with pytest.raises(pydantic.ValidationError, match='bridge-topics'):
        make(bridge_topics=value)


def test_bridge_topics_error_names_the_line():
    with pytest.raises(pydantic.ValidationError, match='line 2'):
        make(bridge_topics='topic a/b\nnot-a-topic\n')


def test_port_collision_is_rejected():
    with pytest.raises(pydantic.ValidationError, match='needs its own port'):
        make(port=1883, tls_port=1883)


def test_metrics_port_collision_is_rejected():
    with pytest.raises(pydantic.ValidationError, match='needs its own port'):
        make(port=9234)


def test_disabled_ports_do_not_collide():
    """Several listeners set to 0 are all disabled, not all on port 0."""
    settings = make(tls_port=0, websockets_port=0, tls_websockets_port=0)
    assert settings.port == 1883


def test_all_listeners_disabled_is_rejected():
    with pytest.raises(pydantic.ValidationError, match='every listener is disabled'):
        make(port=0, tls_port=0, websockets_port=0, tls_websockets_port=0)


def test_identity_without_client_certificates_is_rejected():
    with pytest.raises(pydantic.ValidationError, match='use-identity-as-username'):
        make(use_identity_as_username=True, require_client_certificate=False)


def test_identity_with_client_certificates_is_allowed():
    settings = make(use_identity_as_username=True, require_client_certificate=True)
    assert settings.use_identity_as_username is True


@pytest.mark.parametrize('port', [-1, 65536, 100000])
def test_out_of_range_ports_are_rejected(port: int):
    with pytest.raises(pydantic.ValidationError):
        make(port=port)


@pytest.mark.parametrize(
    ('max_connections', 'open_file_limit', 'expected'),
    [
        (1024, 0, 4096),  # Below the floor, so the floor wins.
        (100, 0, 4096),  # The floor, because a handful of clients still needs headroom.
        (4096, 0, 5120),
        (64000, 0, 65024),
        (-1, 0, 65536),  # Unlimited connections gets a large but finite limit.
        (1024, 12345, 12345),  # An explicit limit always wins.
        (-1, 999, 999),
    ],
)
def test_file_limit(max_connections: int, open_file_limit: int, expected: int):
    """The packaged unit sets no limit, so the charm always computes one.

    Each connection costs a file descriptor, so the limit has to clear
    `max-connections` with room for the listeners, log and persistence database.
    """
    settings = make(max_connections=max_connections, open_file_limit=open_file_limit)
    assert settings.file_limit() == expected


@pytest.mark.parametrize(
    ('tls_port', 'tls_websockets_port', 'expected'),
    [(8883, 0, True), (0, 9002, True), (8883, 9002, True), (0, 0, False)],
)
def test_tls_wanted(tls_port: int, tls_websockets_port: int, expected: bool):
    settings = make(tls_port=tls_port, tls_websockets_port=tls_websockets_port)
    assert settings.tls_wanted is expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('', ()),
        ('a.example.com', ('a.example.com',)),
        ('a.example.com,b.example.com', ('a.example.com', 'b.example.com')),
        (' a.example.com , b.example.com ', ('a.example.com', 'b.example.com')),
        ('a.example.com,,', ('a.example.com',)),
    ],
)
def test_extra_sans_dns(value: str, expected: tuple[str, ...]):
    assert make(certificate_extra_sans_dns=value).extra_sans_dns == expected


@pytest.mark.parametrize('source', ['archive', 'ppa', 'snap'])
def test_install_sources(source: str):
    assert make(install_source=source).install_source == source


def test_unknown_install_source_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        make(install_source='tarball')


def test_unknown_log_level_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        make(log_level='verbose')


@pytest.mark.parametrize('username', ['alice', 'a', 'user.name', 'user-name+1'])
def test_valid_usernames(username: str):
    assert config.SetPasswordParams(username=username).username == username


@pytest.mark.parametrize('username', ['has:colon', 'has\nnewline', 'has\rreturn'])
def test_usernames_that_would_corrupt_the_password_file(username: str):
    """The password file is colon separated, one user per line."""
    with pytest.raises(pydantic.ValidationError, match='colon or a line break'):
        config.SetPasswordParams(username=username)


@pytest.mark.parametrize('username', ['_charm_health', '_charm_metrics', '_anything'])
def test_reserved_usernames_are_rejected(username: str):
    with pytest.raises(pydantic.ValidationError, match='reserved for the charm'):
        config.SetPasswordParams(username=username)


def test_empty_username_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        config.SetPasswordParams(username='')


def test_set_password_without_a_password():
    assert config.SetPasswordParams(username='alice').password is None


@pytest.mark.parametrize('access', ['read', 'write', 'readwrite', 'deny'])
def test_grant_access_levels(access: str):
    # Action parameters arrive as strings, so validate from a mapping rather than
    # constructing with an already-typed enum member.
    params = config.GrantParams.model_validate({'username': 'a', 'topic': 't', 'access': access})
    assert str(params.access) == access


def test_grant_defaults_to_readwrite():
    params = config.GrantParams(username='alice', topic='sensors/#')
    assert str(params.access) == 'readwrite'


def test_grant_rejects_the_unknown_placeholder():
    """UNKNOWN exists so a newer peer's value deserialises; it is not a real level."""
    with pytest.raises(pydantic.ValidationError, match='read, write, readwrite or deny'):
        config.GrantParams.model_validate({'username': 'alice', 'topic': 't', 'access': 'UNKNOWN'})


def test_grant_rejects_an_invented_access_level():
    with pytest.raises(pydantic.ValidationError):
        config.GrantParams.model_validate({'username': 'alice', 'topic': 't', 'access': 'admin'})


@pytest.mark.parametrize('listener', ['plain', 'tls', 'all'])
def test_health_check_listeners(listener: str):
    assert (
        str(config.HealthCheckParams.model_validate({'listener': listener}).listener) == listener
    )


def test_health_check_defaults_to_all():
    assert config.HealthCheckParams().listener is config.Listener.ALL


def test_restore_backup_requires_a_path():
    with pytest.raises(pydantic.ValidationError):
        config.RestoreBackupParams(path='')


def test_create_backup_path_is_optional():
    assert config.CreateBackupParams().path is None
