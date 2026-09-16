# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Tests for the workload module.

These cover the pure parts: rendering configuration, deciding whether a change needs a
reload or a restart, and generating the password and ACL files. Anything that touches
apt, systemd or a real broker is covered by the functional tests instead.
"""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import inspect
import pathlib
import socket
import subprocess
import threading

import pytest

import mosquitto

DEB = mosquitto.paths('archive')
SNAP = mosquitto.paths('snap')


def settings(**overrides: object) -> mosquitto.BrokerSettings:
    """Build broker settings with one plaintext listener by default."""
    values: dict[str, object] = {'listeners': (mosquitto.Listener(port=1883),)}
    values.update(overrides)
    return mosquitto.BrokerSettings(**values)  # type: ignore[arg-type]


def directives(text: str) -> dict[str, list[str]]:
    """Group a rendered configuration by directive name."""
    grouped: dict[str, list[str]] = {}
    for name, value in mosquitto.parse_directives(text):
        grouped.setdefault(name, []).append(value)
    return grouped


# --- Paths -------------------------------------------------------------------


@pytest.mark.parametrize('source', ['archive', 'ppa'])
def test_deb_paths(source: str):
    assert mosquitto.paths(source) is DEB
    assert DEB.config_file == pathlib.Path('/etc/mosquitto/mosquitto.conf')
    assert DEB.service == 'mosquitto'
    assert DEB.user == 'mosquitto'


def test_snap_paths_are_confined():
    """A strictly confined snap can only see its own common directory."""
    assert SNAP.service == 'snap.mosquitto.mosquitto'
    for path in (
        SNAP.config_file,
        SNAP.password_file,
        SNAP.acl_file,
        SNAP.persistence_dir,
        SNAP.certs_dir,
        SNAP.log_file,
    ):
        assert path.is_relative_to('/var/snap/mosquitto/common'), path


def test_tool_paths():
    assert DEB.passwd_tool == pathlib.Path('/usr/bin/mosquitto_passwd')
    assert DEB.rr_tool == pathlib.Path('/usr/bin/mosquitto_rr')
    assert SNAP.sub_tool == pathlib.Path('/snap/bin/mosquitto_sub')


# --- Parsing -----------------------------------------------------------------


def test_parse_directives_ignores_comments_and_blanks():
    parsed = mosquitto.parse_directives('# a comment\n\nport 1883\n\n   # indented\n')
    assert parsed == [('port', '1883')]


def test_parse_directives_normalises_whitespace():
    assert mosquitto.parse_directives('  port    1883   ') == [('port', '1883')]
    assert mosquitto.parse_directives('log_dest  file   /var/log/x') == [
        ('log_dest', 'file /var/log/x')
    ]


def test_parse_directives_keeps_order():
    """Listener blocks are positional: what follows a listener belongs to it."""
    text = 'listener 1883\nprotocol mqtt\nlistener 9001\nprotocol websockets\n'
    assert mosquitto.parse_directives(text) == [
        ('listener', '1883'),
        ('protocol', 'mqtt'),
        ('listener', '9001'),
        ('protocol', 'websockets'),
    ]


def test_parse_directives_handles_valueless_directives():
    assert mosquitto.parse_directives('persistence\n') == [('persistence', '')]


# --- Reload versus restart ---------------------------------------------------


def test_identical_config_needs_nothing():
    assert mosquitto.classify_change('port 1883\n', 'port 1883\n') is mosquitto.Change.NONE


def test_comment_and_whitespace_churn_needs_nothing():
    """Reformatting must not disconnect every client."""
    old = '# old comment\nport  1883\n\n'
    new = '# a completely different comment\nport 1883\n'
    assert mosquitto.classify_change(old, new) is mosquitto.Change.NONE


@pytest.mark.parametrize(
    'directive',
    [
        'acl_file /etc/mosquitto/acl2',
        'password_file /etc/mosquitto/pw2',
        'allow_anonymous true',
        'autosave_interval 600',
        'log_type debug',
        'max_queued_messages 2000',
        'max_packet_size 1000',
        'persistent_client_expiration 7d',
        'sys_interval 30',
        'memory_limit 1000',
        'retain_available false',
    ],
)
def test_reload_safe_changes(directive: str):
    """A reload leaves every client connected, so it is worth reaching for."""
    assert mosquitto.classify_change('port 1883\n', f'port 1883\n{directive}\n') is (
        mosquitto.Change.RELOAD
    )


@pytest.mark.parametrize(
    'directive',
    [
        'listener 1884',
        'port 1884',
        'protocol websockets',
        'max_connections 2048',
        'certfile /etc/mosquitto/certs/server.crt',
        'keyfile /etc/mosquitto/certs/server.key',
        'cafile /etc/mosquitto/certs/ca.crt',
        'tls_version tlsv1.3',
        'require_certificate true',
        'user mosquitto',
        'plugin /usr/lib/x.so',
    ],
)
def test_restart_required_changes(directive: str):
    assert mosquitto.classify_change('port 1883\n', f'port 1883\n{directive}\n') is (
        mosquitto.Change.RESTART
    )


def test_unknown_directives_default_to_restart():
    """The reload-safe list differs between 2.0 and 2.1, so guess in the safe direction.

    An unnecessary restart costs a reconnect; the other mistake leaves the broker
    running a configuration nobody asked for while the charm reports success.
    """
    assert mosquitto.classify_change('', 'some_future_directive 1\n') is mosquitto.Change.RESTART


def test_mixed_changes_take_the_stronger_action():
    old = 'port 1883\nacl_file /a\n'
    new = 'port 1884\nacl_file /b\n'
    assert mosquitto.classify_change(old, new) is mosquitto.Change.RESTART


def test_reordering_needs_a_restart():
    """Two listeners swapping order changes which options belong to which."""
    old = 'listener 1883\nmax_qos 2\nlistener 9001\nmax_qos 1\n'
    new = 'listener 9001\nmax_qos 1\nlistener 1883\nmax_qos 2\n'
    assert mosquitto.classify_change(old, new) is mosquitto.Change.RESTART


def test_removing_a_reload_safe_directive_reloads():
    assert mosquitto.classify_change('port 1883\nsys_interval 10\n', 'port 1883\n') is (
        mosquitto.Change.RELOAD
    )


def test_reload_and_restart_sets_do_not_overlap():
    assert not (mosquitto.RELOAD_SAFE_DIRECTIVES & mosquitto.RESTART_REQUIRED_DIRECTIVES)


@pytest.mark.parametrize(
    ('changes', 'expected'),
    [
        ((), mosquitto.Change.NONE),
        ((mosquitto.Change.NONE,), mosquitto.Change.NONE),
        ((mosquitto.Change.NONE, mosquitto.Change.RELOAD), mosquitto.Change.RELOAD),
        (
            (mosquitto.Change.RELOAD, mosquitto.Change.RESTART, mosquitto.Change.NONE),
            mosquitto.Change.RESTART,
        ),
    ],
)
def test_merge_changes(changes: tuple[mosquitto.Change, ...], expected: mosquitto.Change):
    assert mosquitto.merge_changes(changes) is expected


# --- Rendering ---------------------------------------------------------------


def test_render_config_sets_the_security_basics():
    rendered = directives(mosquitto.render_config(settings(), DEB))
    assert rendered['allow_anonymous'] == ['false']
    # Per-listener security lets a durable client keep the permissions of whichever
    # listener it last used, which is a privilege escalation path.
    assert rendered['per_listener_settings'] == ['false']
    assert rendered['password_file'] == [str(DEB.password_file)]
    assert rendered['acl_file'] == [str(DEB.acl_file)]


def test_render_config_writes_every_managed_default_explicitly():
    """Relying on Mosquitto's defaults is how behaviour changes across an upgrade.

    `max_packet_size` alone moved from unlimited to 2000000 between 2.0 and 2.1.
    """
    rendered = directives(mosquitto.render_config(settings(), DEB))
    for directive in (
        'max_connections',
        'max_inflight_messages',
        'max_queued_messages',
        'max_queued_bytes',
        'max_packet_size',
        'max_keepalive',
        'memory_limit',
        'retain_available',
        'queue_qos0_messages',
        'persistence',
        'autosave_interval',
        'sys_interval',
    ):
        assert directive in rendered, directive


def test_render_config_logs_to_a_file_not_syslog():
    """The COS collectors scrape /var/log/**/*log; otelcol has no journald receiver."""
    rendered = directives(mosquitto.render_config(settings(), DEB))
    assert rendered['log_dest'] == [f'file {DEB.log_file}']


@pytest.mark.parametrize(
    ('level', 'expected'),
    [
        ('error', ['error']),
        ('warning', ['error', 'warning']),
        ('notice', ['error', 'warning', 'notice']),
        ('debug', ['error', 'warning', 'notice', 'information', 'debug']),
    ],
)
def test_log_levels_are_cumulative(level: str, expected: list[str]):
    """Mosquitto's log types are not ordered, so the charm makes them behave as if."""
    rendered = directives(mosquitto.render_config(settings(log_level=level), DEB))
    assert rendered['log_type'] == expected


def test_client_expiration_is_omitted_when_empty():
    rendered = directives(mosquitto.render_config(settings(persistent_client_expiration=''), DEB))
    assert 'persistent_client_expiration' not in rendered


def test_client_expiration_is_set_by_default():
    """Left unset, disconnected durable sessions accumulate for ever."""
    rendered = directives(mosquitto.render_config(settings(), DEB))
    assert rendered['persistent_client_expiration'] == ['14d']


def test_render_config_with_websockets():
    listeners = (mosquitto.Listener(port=1883), mosquitto.Listener(port=9001, websockets=True))
    parsed = mosquitto.parse_directives(
        mosquitto.render_config(settings(listeners=listeners), DEB)
    )
    index = parsed.index(('listener', '9001'))
    assert parsed[index + 1] == ('protocol', 'websockets')


def test_render_config_without_tls_omits_tls_directives():
    rendered = directives(mosquitto.render_config(settings(), DEB))
    for directive in ('cafile', 'certfile', 'keyfile', 'tls_version', 'require_certificate'):
        assert directive not in rendered


def test_render_config_with_tls():
    material = mosquitto.TLSMaterial(certificate='cert', private_key='key', ca='ca')
    listeners = (mosquitto.Listener(port=1883), mosquitto.Listener(port=8883, tls=True))
    rendered = directives(
        mosquitto.render_config(settings(listeners=listeners, tls=material), DEB)
    )
    assert rendered['certfile'] == [str(DEB.certs_dir / 'server.crt')]
    assert rendered['keyfile'] == [str(DEB.certs_dir / 'server.key')]
    assert rendered['cafile'] == [str(DEB.certs_dir / 'ca.crt')]
    assert rendered['tls_version'] == ['tlsv1.2']
    assert rendered['require_certificate'] == ['false']


def test_identity_is_only_rendered_with_client_certificates():
    material = mosquitto.TLSMaterial(certificate='c', private_key='k', ca='a')
    listeners = (mosquitto.Listener(port=8883, tls=True),)
    without = directives(
        mosquitto.render_config(
            settings(listeners=listeners, tls=material, use_identity_as_username=True), DEB
        )
    )
    assert 'use_identity_as_username' not in without

    with_certs = directives(
        mosquitto.render_config(
            settings(
                listeners=listeners,
                tls=material,
                require_client_certificate=True,
                use_identity_as_username=True,
            ),
            DEB,
        )
    )
    assert with_certs['use_identity_as_username'] == ['true']


def test_render_config_uses_the_snap_layout():
    rendered = directives(mosquitto.render_config(settings(), SNAP))
    assert rendered['password_file'] == [str(SNAP.password_file)]
    assert rendered['persistence_location'] == [f'{SNAP.persistence_dir}/']


def test_rendered_config_is_stable():
    """Rendering twice must not look like a change."""
    first = mosquitto.render_config(settings(), DEB)
    assert first == mosquitto.render_config(settings(), DEB)
    assert mosquitto.classify_change(first, first) is mosquitto.Change.NONE


# --- Listeners ---------------------------------------------------------------


@pytest.mark.parametrize(
    ('kwargs', 'expected_ports'),
    [
        ({}, [1883]),
        ({'websockets_port': 9001}, [1883, 9001]),
        # TLS listeners stay closed until a certificate exists, so that losing the
        # authority does not leave the broker refusing to start.
        ({'tls_port': 8883, 'have_certificates': False}, [1883]),
        ({'tls_port': 8883, 'have_certificates': True}, [1883, 8883]),
        (
            {
                'websockets_port': 9001,
                'tls_port': 8883,
                'tls_websockets_port': 9002,
                'have_certificates': True,
            },
            [1883, 9001, 8883, 9002],
        ),
        ({'port': 0, 'tls_port': 8883, 'have_certificates': True}, [8883]),
        ({'port': 0}, []),
    ],
)
def test_listeners_for(kwargs: dict[str, object], expected_ports: list[int]):
    defaults: dict[str, object] = {
        'port': 1883,
        'tls_port': 0,
        'websockets_port': 0,
        'tls_websockets_port': 0,
        'have_certificates': False,
    }
    defaults.update(kwargs)
    listeners = mosquitto.listeners_for(**defaults)  # type: ignore[arg-type]
    assert [listener.port for listener in listeners] == expected_ports


# --- Password and ACL files --------------------------------------------------


def test_render_password_file():
    rendered = mosquitto.render_password_file({'bob': 'two', 'alice': 'one'})
    assert rendered == 'alice:one\nbob:two\n'


def test_render_password_file_is_sorted_for_stability():
    assert mosquitto.render_password_file({'b': '1', 'a': '2'}) == (
        mosquitto.render_password_file({'a': '2', 'b': '1'})
    )


def test_render_password_file_when_empty():
    assert mosquitto.render_password_file({}) == ''


def test_render_acl_file():
    rendered = mosquitto.render_acl_file(
        {
            'alice': [('sensors/#', 'readwrite')],
            'bob': [('sensors/#', 'read'), ('control/#', 'deny')],
        }
    )
    assert 'user alice' in rendered
    assert 'topic readwrite sensors/#' in rendered
    assert 'topic deny control/#' in rendered


def test_render_acl_file_never_emits_pattern_lines():
    """`pattern` lines are global and apply inside every user block too.

    That is almost never what anyone means, so the charm does not emit them.
    """
    rendered = mosquitto.render_acl_file({'alice': [('a/%u', 'read')]})
    assert 'pattern' not in rendered


def test_render_acl_file_grants_anonymous_clients_nothing():
    """Rules before the first `user` line are the ones anonymous clients get.

    The charm writes none, so `allow-anonymous` lets a client connect and then do
    nothing at all. A grant to unauthenticated clients is a grant to everyone who can
    reach the port, so there is deliberately no way to ask for one.
    """
    rendered = mosquitto.render_acl_file({'alice': [('a/#', 'read')]})
    body = rendered.split('user alice')[0]
    assert 'topic' not in body


def test_render_acl_file_is_sorted_for_stability():
    first = mosquitto.render_acl_file({'b': [('x', 'read')], 'a': [('y', 'read')]})
    second = mosquitto.render_acl_file({'a': [('y', 'read')], 'b': [('x', 'read')]})
    assert first == second


def test_render_acl_file_when_empty():
    assert 'Managed by the mosquitto charm' in mosquitto.render_acl_file({})


# --- Bridges -----------------------------------------------------------------


def bridge(**overrides: object) -> mosquitto.Bridge:
    values: dict[str, object] = {
        'name': 'edge-upstream',
        'host': '10.0.0.1',
        'port': 1883,
        'topics': ('topic sensors/# out',),
    }
    values.update(overrides)
    return mosquitto.Bridge(**values)  # type: ignore[arg-type]


def test_render_bridge_config_avoids_the_known_footguns():
    rendered = directives(mosquitto.render_bridge_config(bridge(client_id='mosquitto-0'), DEB))
    # Without try_private, a message from the remote is sent straight back and the
    # pair echoes for ever.
    assert rendered['try_private'] == ['true']
    # Store and forward across a WAN outage rather than dropping everything.
    assert rendered['cleansession'] == ['false']
    # A shared client id makes both ends fight over one session, and they flap.
    assert rendered['remote_clientid'] == ['mosquitto-0']
    assert rendered['address'] == ['10.0.0.1:1883']


def test_render_bridge_config_includes_topics():
    rendered = mosquitto.render_bridge_config(
        bridge(topics=('topic a/# out', 'topic b/# in')), DEB
    )
    assert 'topic a/# out' in rendered
    assert 'topic b/# in' in rendered


def test_render_bridge_config_omits_credentials_when_absent():
    rendered = directives(mosquitto.render_bridge_config(bridge(), DEB))
    assert 'remote_username' not in rendered
    assert 'remote_password' not in rendered
    assert 'bridge_cafile' not in rendered


def test_render_bridge_config_with_credentials():
    rendered = directives(
        mosquitto.render_bridge_config(
            bridge(username='edge', password='secret', tls_ca='ca-pem'), DEB
        )
    )
    assert rendered['remote_username'] == ['edge']
    assert rendered['remote_password'] == ['secret']
    assert rendered['bridge_cafile'] == [str(DEB.certs_dir / 'bridge-ca.crt')]


@pytest.mark.parametrize(
    'field',
    ['host', 'username', 'password'],
)
def test_render_bridge_config_refuses_an_injected_directive(field: str):
    """The host and the credentials are the values a *remote* charm chooses.

    `mqtt.Endpoint` and `mqtt.UserSecret` reject these at the relation boundary; this is
    the second line of defence, at the point where they would become directives in a
    file the broker includes.
    """
    injection = 'x\nlistener 1884\nallow_anonymous true'

    with pytest.raises(ValueError, match='line break'):
        mosquitto.render_bridge_config(bridge(**{field: injection}), DEB)


# --- Logs --------------------------------------------------------------------


def test_last_log_reads_the_log_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """`log_dest file` means the journal is not the whole story.

    Anything that goes wrong after the broker opens its log file is in the file alone,
    which is most of what an operator needs when a reload was rejected.
    """

    def no_journal(*args: object, **kwargs: object) -> object:
        raise OSError('no journalctl here')

    monkeypatch.setattr(mosquitto, '_run', no_journal)
    log_file = tmp_path / 'mosquitto.log'
    log_file.write_text(''.join(f'line {number}\n' for number in range(100)))
    paths = dataclasses.replace(DEB, log_file=log_file)

    assert mosquitto.last_log(paths, lines=3).splitlines() == ['line 97', 'line 98', 'line 99']


def test_last_log_survives_a_missing_log_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    def no_journal(*args: object, **kwargs: object) -> object:
        raise OSError('no journalctl here')

    monkeypatch.setattr(mosquitto, '_run', no_journal)
    paths = dataclasses.replace(DEB, log_file=tmp_path / 'nothing-here.log')

    assert mosquitto.last_log(paths) == ''


# --- Versions ----------------------------------------------------------------


@pytest.mark.parametrize(
    ('version', 'expected'),
    [
        ('2.0.18', (2, 0, 18)),
        ('2.1.2', (2, 1, 2)),
        ('2.1', (2, 1, 0)),
        ('2', (2, 0, 0)),
        (None, (0, 0, 0)),
        ('', (0, 0, 0)),
        ('not-a-version', (0, 0, 0)),
        ('2.0.18-1build3', (0, 0, 0)),
    ],
)
def test_version_tuple(version: str | None, expected: tuple[int, int, int]):
    assert mosquitto.version_tuple(version) == expected


@pytest.mark.parametrize(
    ('version', 'expected'),
    [
        # 24.04 ships 2.0.18, which is vulnerable to CVE-2024-3935 through bridge
        # topic remapping, so the charm must refuse to configure a bridge on it.
        ('2.0.18', False),
        ('2.0.19', True),
        ('2.0.23', True),
        ('2.1.2', True),
        ('1.6.9', False),
        (None, False),
    ],
)
def test_supports_bridging(version: str | None, expected: bool):
    assert mosquitto.supports_bridging(version) is expected


# --- Passwords ---------------------------------------------------------------


def test_generated_passwords_are_unique():
    assert len({mosquitto.generate_password() for _ in range(100)}) == 100


def test_generated_passwords_fit_the_password_file_format():
    """The file is colon separated, one user per line."""
    for _ in range(50):
        password = mosquitto.generate_password()
        assert ':' not in password
        assert '\n' not in password
        assert len(password) >= 16


# --- Managed files -----------------------------------------------------------


def test_managed_files_are_all_under_the_layout():
    for path in DEB.managed_files():
        assert path.is_absolute()
    for path in SNAP.managed_files():
        assert path.is_relative_to('/var/snap/mosquitto/common')


def test_a_timed_out_command_becomes_a_module_error(monkeypatch: pytest.MonkeyPatch):
    """Every caller handles this module's own error; none handles TimeoutExpired.

    Reaching Launchpad or the archive is not something the charm can promise, and a
    slow mirror that raised out of `subprocess` ended the hook in a traceback and left
    the unit needing `juju resolve`.
    """

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=['/bin/true'], timeout=60)

    monkeypatch.setattr(mosquitto.subprocess, 'run', timeout)

    with pytest.raises(mosquitto.Error, match='did not finish within'):
        mosquitto._run(['/bin/true'])


def test_adding_the_ppa_is_given_longer_than_the_default():
    """`add-apt-repository` reaches Launchpad, which regularly takes over a minute."""
    source = inspect.getsource(mosquitto.install)
    assert 'add-apt-repository' in source
    line = next(line for line in source.splitlines() if 'add-apt-repository' in line)
    assert 'timeout=' in line, 'adding the PPA runs with the default 60s timeout'


# --- Removing relation-owned material ----------------------------------------


def layout(root: pathlib.Path) -> mosquitto.Paths:
    """The archive layout, rebased under a temporary directory."""
    return dataclasses.replace(
        DEB,
        config_file=root / 'mosquitto.conf',
        conf_dir=root / 'conf.d',
        password_file=root / 'passwd',
        acl_file=root / 'acl',
        persistence_dir=root / 'data',
        log_file=root / 'log' / 'mosquitto.log',
        certs_dir=root / 'certs',
        backup_dir=root / 'backups',
    )


def test_removing_tls_material_takes_every_file(tmp_path: pathlib.Path):
    """A private key outlives the integration that put it there unless something goes.

    It is not what keeps a listener working — the broker stops referencing it as soon
    as the TLS listeners go — but it is a key on a machine that no longer serves TLS,
    and every later backup would carry it.
    """
    paths = layout(tmp_path)
    paths.certs_dir.mkdir(parents=True)
    for name in ('ca.crt', 'server.crt', 'server.key'):
        (paths.certs_dir / name).write_text('material')

    change = mosquitto.remove_tls_material(paths)

    assert change is mosquitto.Change.RESTART
    assert not list(paths.certs_dir.iterdir())


def test_removing_tls_material_that_is_not_there_changes_nothing(tmp_path: pathlib.Path):
    paths = layout(tmp_path)
    paths.certs_dir.mkdir(parents=True)

    assert mosquitto.remove_tls_material(paths) is mosquitto.Change.NONE


def test_removing_tls_material_leaves_the_bridge_authority(tmp_path: pathlib.Path):
    """The two are written by different integrations and go separately."""
    paths = layout(tmp_path)
    paths.certs_dir.mkdir(parents=True)
    (paths.certs_dir / 'server.key').write_text('key')
    bridge = paths.certs_dir / 'bridge-ca.crt'
    bridge.write_text('upstream authority')

    mosquitto.remove_tls_material(paths)

    assert bridge.exists()


def test_removing_the_bridge_authority(tmp_path: pathlib.Path):
    paths = layout(tmp_path)
    paths.certs_dir.mkdir(parents=True)
    (paths.certs_dir / 'bridge-ca.crt').write_text('upstream authority')

    assert mosquitto.remove_bridge_ca(paths) is mosquitto.Change.RESTART
    assert not (paths.certs_dir / 'bridge-ca.crt').exists()


def test_removing_a_bridge_authority_that_is_not_there(tmp_path: pathlib.Path):
    paths = layout(tmp_path)
    paths.certs_dir.mkdir(parents=True)

    assert mosquitto.remove_bridge_ca(paths) is mosquitto.Change.NONE


# --- Backups -----------------------------------------------------------------


def test_a_backup_refuses_to_write_through_a_symlink(tmp_path: pathlib.Path):
    """The backup is written as root, and the action's own check is a syscall earlier.

    An operator who can run actions but not `juju ssh` could otherwise point the
    destination at a symlink and have root follow it.
    """
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)
    target = tmp_path / 'somewhere-else'
    link = tmp_path / 'backup.tar.gz'
    link.symlink_to(target)

    with pytest.raises(mosquitto.Error, match='could not write the backup'):
        mosquitto.create_backup(paths, link)

    assert not target.exists()


def test_a_backup_refuses_a_destination_that_appeared(tmp_path: pathlib.Path):
    """`O_EXCL`, so the gap between the action's check and this open is not a window."""
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)
    destination = tmp_path / 'backup.tar.gz'
    destination.write_text('someone got here first')

    with pytest.raises(mosquitto.Error, match='could not write the backup'):
        mosquitto.create_backup(paths, destination)

    assert destination.read_text() == 'someone got here first'


def test_a_backup_destination_in_the_backup_directory_is_allowed(tmp_path: pathlib.Path):
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)

    mosquitto.check_backup_destination(paths, paths.backup_dir / 'nightly' / 'backup.tar.gz')


def test_a_backup_destination_elsewhere_needs_a_directory_that_exists(
    tmp_path: pathlib.Path,
):
    """Otherwise the action builds a tree of its own wherever it is pointed."""
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)
    share = tmp_path / 'mnt' / 'backups'

    with pytest.raises(mosquitto.Error, match='not an existing directory'):
        mosquitto.check_backup_destination(paths, share / 'backup.tar.gz')

    share.mkdir(parents=True)
    mosquitto.check_backup_destination(paths, share / 'backup.tar.gz')


@pytest.mark.parametrize(
    'destination',
    [
        '/etc/cron.d/charm-eval',
        '/etc/mosquitto/backup.tar.gz',
        '/usr/local/bin/backup.tar.gz',
        '/var/lib/juju/backup.tar.gz',
        '/root/backup.tar.gz',
    ],
)
def test_a_backup_refuses_a_destination_the_system_reads(tmp_path: pathlib.Path, destination: str):
    """The backup is written as root, so creating a file is itself the privilege.

    Nothing is overwritten -- the action checks that first, and the open is `O_EXCL` --
    but a new root-owned file in one of these directories is a way to change what the
    machine does, and an operator who can run actions should not have one.
    """
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)

    with pytest.raises(mosquitto.Error, match='where the charm will not create files'):
        mosquitto.check_backup_destination(paths, pathlib.Path(destination))


def test_a_backup_destination_is_checked_after_its_directory_is_resolved(
    tmp_path: pathlib.Path,
):
    """A symlinked directory would otherwise be a way around the check."""
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)
    link = tmp_path / 'looks-harmless'
    link.symlink_to('/etc')

    with pytest.raises(mosquitto.Error, match='where the charm will not create files'):
        mosquitto.check_backup_destination(paths, link / 'cron.d' / 'charm-eval')


def test_a_backup_refuses_a_relative_destination(tmp_path: pathlib.Path):
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)

    with pytest.raises(mosquitto.Error, match='not an absolute path'):
        mosquitto.check_backup_destination(paths, pathlib.Path('backup.tar.gz'))


def test_a_backup_creates_no_directories_outside_its_own(tmp_path: pathlib.Path):
    """`check_backup_destination` has already required the directory to exist."""
    paths = layout(tmp_path)
    mosquitto.ensure_directories(paths)

    with pytest.raises(mosquitto.Error, match='could not write the backup'):
        mosquitto.create_backup(paths, tmp_path / 'not-there' / 'backup.tar.gz')

    assert not (tmp_path / 'not-there').exists()


# --- WebSocket listeners -----------------------------------------------------


@contextlib.contextmanager
def websocket_server(response: bytes) -> collections.abc.Generator[int]:
    """Serve one connection with a canned HTTP response, and yield the port."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)

    def serve() -> None:
        try:
            connection, _ = listener.accept()
        except OSError:
            return
        with connection:
            connection.recv(4096)
            connection.sendall(response)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        listener.close()
        thread.join(timeout=5)


def test_a_websocket_listener_that_upgrades_passes():
    response = (
        b'HTTP/1.1 101 Switching Protocols\r\n'
        b'Upgrade: websocket\r\n'
        b'Connection: Upgrade\r\n'
        b'Sec-WebSocket-Protocol: mqtt\r\n\r\n'
    )
    with websocket_server(response) as port:
        passed, message = mosquitto.websocket_check(host='127.0.0.1', port=port)

    assert passed
    assert 'WebSocket upgrade' in message


def test_a_websocket_listener_that_does_not_upgrade_fails():
    """A broker built without WebSocket support answers the port but not the upgrade."""
    with websocket_server(b'HTTP/1.1 404 Not Found\r\n\r\n') as port:
        passed, message = mosquitto.websocket_check(host='127.0.0.1', port=port)

    assert not passed
    assert '404' in message


def test_a_websocket_listener_that_upgrades_without_mqtt_fails():
    """Upgrading to something that is not MQTT is not a working MQTT listener."""
    response = b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n'
    with websocket_server(response) as port:
        passed, message = mosquitto.websocket_check(host='127.0.0.1', port=port)

    assert not passed
    assert 'subprotocol' in message


def test_a_websocket_listener_that_is_not_there_fails():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    listener.close()

    passed, message = mosquitto.websocket_check(host='127.0.0.1', port=port, timeout=2)

    assert not passed
    assert 'could not connect' in message


def test_a_tls_websocket_listener_that_is_not_serving_tls_fails():
    """A handshake the broker cannot complete is a failure, not an exception.

    `ssl.SSLError` is an `OSError`, so TLS material the broker cannot read comes back
    as a failed check rather than as a traceback in the action.
    """
    with websocket_server(b'HTTP/1.1 101 Switching Protocols\r\n\r\n') as port:
        passed, message = mosquitto.websocket_check(
            host='127.0.0.1', port=port, tls=True, timeout=5
        )

    assert not passed
    assert 'failed' in message
