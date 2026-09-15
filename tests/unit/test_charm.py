# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""State-transition tests for the Mosquitto charm.

Every test drives the real charm class through `ops.testing` with the workload module
replaced by the stateful fake in `conftest.py`, so what is asserted is what the charm
*decided*: which users it wants, whether a change needs a reload or a restart, what it
published to a client, and what it told the operator in its status.
"""

from __future__ import annotations

import ast
import collections.abc
import dataclasses
import inspect
import json
import pathlib
from typing import Any

import conftest
import ops
import ops.testing as testing
import pytest

import charm
import mosquitto
import mqtt

# The `cos_agent` charm library — the one library still fetched from Charmhub rather
# than installed from PyPI — calls pydantic's deprecated `.json()`. `filterwarnings =
# ["error"]` in pyproject.toml would otherwise turn that into an exception inside every
# hook that refreshes the COS relation data, which is every hook this file runs.
pytestmark = pytest.mark.filterwarnings('ignore::DeprecationWarning')

LXD = testing.Model(name='testing', type='lxd')
PEER = 'mosquitto-peers'

CERTIFICATE = '-----BEGIN CERTIFICATE-----\nserver\n-----END CERTIFICATE-----\n'
CA = '-----BEGIN CERTIFICATE-----\nauthority\n-----END CERTIFICATE-----\n'
PRIVATE_KEY = '-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----\n'

SCALE_MESSAGE = (
    'Mosquitto does not cluster, so this charm runs one unit; 2 are deployed. Remove '
    'the extra units with `juju remove-unit`, and integrate separate Mosquitto '
    'applications on `upstream` if you need more than one broker.'
)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def peer_relation(
    users: collections.abc.Mapping[str, dict[str, Any]] | None = None,
    *,
    install_source: str | None = None,
    paused: bool = False,
    other_units: bool = False,
) -> testing.PeerRelation:
    """The peer relation, which is where the charm keeps the user list."""
    local_app_data: dict[str, str] = {}
    if users is not None:
        local_app_data['users'] = json.dumps(users, sort_keys=True)
    if install_source is not None:
        local_app_data['install-source'] = install_source
    return testing.PeerRelation(
        PEER,
        local_app_data=local_app_data,
        local_unit_data={'paused': 'true'} if paused else {},
        peers_data={1: {}} if other_units else {},
    )


def make_state(
    *,
    leader: bool = True,
    peer: testing.PeerRelation | None = None,
    relations: collections.abc.Iterable[testing.RelationBase] = (),
    **kwargs: Any,
) -> testing.State:
    """A single-unit machine deployment, with the peer relation in place."""
    return testing.State(
        leader=leader,
        model=LXD,
        relations=[peer if peer is not None else peer_relation(), *relations],
        **kwargs,
    )


def user_secret(username: str, password: str) -> testing.Secret:
    """A secret of the shape `_password_for` creates."""
    return testing.Secret(
        {'username': username, 'password': password},
        label=charm.SECRET_LABEL.format(username=username),
        owner='app',
    )


def requirer_databag(
    *permissions: tuple[str, str], client_id_prefix: str = 'sensor-'
) -> dict[str, str]:
    """An `mqtt` requirer's application databag."""
    return {
        'topic-permissions': json.dumps(
            [{'filter': topic, 'access': access} for topic, access in permissions]
        ),
        'client-id-prefix': json.dumps(client_id_prefix),
        'requested-secrets': json.dumps([{'field': 'username'}, {'field': 'password'}]),
    }


def upstream_databag(host: str = '10.9.8.7', port: int = 1883) -> dict[str, str]:
    """An upstream broker's provider databag, as the bridge sees it."""
    return {
        'endpoints': json.dumps([{'host': host, 'port': port, 'tls': False, 'protocol': 'mqtt'}]),
        'mqtt-version': json.dumps('5.0'),
    }


@dataclasses.dataclass(frozen=True)
class _AssignedCertificate:
    """Just enough of the TLS library's certificate to satisfy the charm."""

    certificate: str = CERTIFICATE
    ca: str = CA


@pytest.fixture
def certificates(monkeypatch: pytest.MonkeyPatch):
    """Make the certificate authority appear to have issued a certificate."""

    def get_assigned_certificate(
        self: object, request: object
    ) -> tuple[_AssignedCertificate, str]:
        return _AssignedCertificate(), PRIVATE_KEY

    monkeypatch.setattr(
        'charmlibs.interfaces.tls_certificates.TLSCertificatesRequiresV4.get_assigned_certificate',
        get_assigned_certificate,
    )


def directives(text: str) -> set[tuple[str, str]]:
    """The rendered configuration as a set of (directive, value) pairs."""
    return set(mosquitto.parse_directives(text))


def stored_users(state: testing.State) -> dict[str, Any]:
    """The user list from the peer application databag."""
    relation = next(r for r in state.relations if r.endpoint == PEER)
    return json.loads(relation.local_app_data.get('users', '{}'))


# --------------------------------------------------------------------------------------
# The fake itself
# --------------------------------------------------------------------------------------


def _names_the_charm_uses() -> set[str]:
    """Every `mosquitto.<name>` the charm source refers to."""
    tree = ast.parse(pathlib.Path(charm.__file__).read_text())
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == 'mosquitto'
    }


def test_the_fake_carries_every_name_the_charm_uses(fake: conftest.FakeMosquitto):
    """A fake that has drifted from the real module tests nothing useful."""
    used = _names_the_charm_uses()
    assert used, 'the charm no longer talks to the workload module through `mosquitto`'
    assert not {name for name in used if not hasattr(fake, name)}
    assert not {name for name in used if not hasattr(mosquitto, name)}


@pytest.mark.parametrize('name', sorted(_names_the_charm_uses()))
def test_the_fake_matches_the_real_signature(name: str, fake: conftest.FakeMosquitto):
    """The fake's callables take what the real ones take.

    Only the parameter names and kinds are compared: both modules use postponed
    annotations, so the annotations are strings that differ merely by which module
    they were written in.
    """
    real = getattr(mosquitto, name)
    stand_in = getattr(fake, name)
    if not callable(real) or isinstance(real, type):
        assert stand_in is real or stand_in == real
        return

    def shape(function: object) -> list[tuple[str, inspect._ParameterKind, bool]]:
        return [
            (parameter.name, parameter.kind, parameter.default is inspect.Parameter.empty)
            for parameter in inspect.signature(function).parameters.values()  # type: ignore[arg-type]
        ]

    assert shape(stand_in) == shape(real)


# --------------------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------------------


def test_install(ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto):
    state_out = ctx.run(ctx.on.install(), make_state())

    assert fake.installs == [('archive', 'latest/stable')]
    assert 'ensure_directories' in fake.calls
    # Installing does not start the broker: there is no configuration yet.
    assert not fake.running
    assert 'start' not in fake.calls
    relation = next(r for r in state_out.relations if r.endpoint == PEER)
    assert relation.local_app_data['install-source'] == 'archive'


def test_install_from_the_snap_uses_the_channel(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'install-source': 'snap', 'package-channel': '2.0/stable'})

    ctx.run(ctx.on.install(), state_in)

    assert fake.installs == [('snap', '2.0/stable')]


def test_install_does_nothing_when_the_configuration_is_invalid(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """A traceback in the unit log is no use; the status says what to change."""
    state_in = make_state(config={'persistent-client-expiration': 'forever'})

    state_out = ctx.run(ctx.on.install(), state_in)

    assert fake.calls == []
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert 'persistent-client-expiration' in state_out.unit_status.message


def test_start_configures_and_starts_the_broker(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_out = ctx.run(ctx.on.start(), make_state())

    assert fake.running
    assert ('listener', '1883') in directives(fake.main_config)
    assert ('allow_anonymous', 'false') in directives(fake.main_config)
    assert state_out.workload_version == '2.0.18'
    assert fake.sysctl_enabled is True
    # The charm's own users exist so that the health check and the exporter are not
    # borrowing an operator's credentials.
    assert set(fake.users) >= {mosquitto.HEALTH_USER, mosquitto.METRICS_USER}
    assert fake.rules[mosquitto.METRICS_USER] == [('$SYS/#', 'read')]


def test_start_installs_when_mosquitto_is_missing(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.version = None

    ctx.run(ctx.on.start(), make_state())

    assert fake.installs == [('archive', 'latest/stable')]


def test_stop_stops_the_broker_and_the_exporter(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.running = True
    fake.exporter.installed = True

    ctx.run(ctx.on.stop(), make_state())

    assert not fake.running
    assert not fake.exporter.installed
    assert fake.calls == ['remove_exporter', 'stop']


def test_stop_tolerates_a_broker_that_will_not_stop(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """A unit that cannot be removed because the workload is wedged helps nobody."""
    fake.running = True
    fake.stop_error = 'systemd said no'

    ctx.run(ctx.on.stop(), make_state())

    assert any('Could not stop Mosquitto' in line.message for line in ctx.juju_log)


def test_remove_uninstalls_and_drops_the_tuning(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(ctx.on.remove(), make_state())

    assert fake.uninstalled == ['archive']
    assert fake.sysctl_enabled is False


def test_remove_with_invalid_config_falls_back_to_the_archive_layout(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'persistent-client-expiration': 'forever'})

    ctx.run(ctx.on.remove(), state_in)

    assert fake.uninstalled == ['archive']


def test_upgrade_reinstalls_and_reconciles(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(ctx.on.upgrade_charm(), make_state())

    assert fake.installs == [('archive', 'latest/stable')]
    assert fake.running


def test_update_status_reconciles(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    first = ctx.run(ctx.on.start(), make_state())

    ctx.run(ctx.on.update_status(), dataclasses.replace(first))

    # Nothing changed, so the broker is left strictly alone.
    assert fake.last_change is mosquitto.Change.NONE


def test_config_changed_rerenders(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(ctx.on.config_changed(), make_state(config={'log-level': 'debug'}))

    assert ('log_type', 'debug') in directives(fake.main_config)


def test_changing_the_install_source_migrates_the_state(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """The snap cannot see /etc/mosquitto, so the broker's state has to move."""
    state_in = make_state(
        peer=peer_relation(install_source='archive'), config={'install-source': 'snap'}
    )

    ctx.run(ctx.on.config_changed(), state_in)

    assert fake.migrations, 'the broker state was left in the old layout'
    old, new = fake.migrations[0]
    assert 'archive' in old
    assert 'snap' in new


# --------------------------------------------------------------------------------------
# The scale guard
# --------------------------------------------------------------------------------------


def test_a_second_unit_blocks_and_the_workload_is_not_touched(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """Two units would be two unrelated brokers sharing one application name.

    A client that reconnected to the other one would find its session, queued messages
    and retained messages gone, so the charm refuses before it configures anything.
    """
    state_in = make_state(peer=peer_relation(other_units=True))

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert state_out.unit_status == testing.BlockedStatus(SCALE_MESSAGE)
    assert not fake.touched_workload()


@pytest.mark.parametrize('event', ['start', 'upgrade_charm', 'update_status'])
def test_the_scale_guard_holds_for_every_reconciling_event(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, event: str
):
    state_in = make_state(peer=peer_relation(other_units=True))

    ctx.run(getattr(ctx.on, event)(), state_in)

    assert 'start' not in fake.calls
    assert 'write_config' not in fake.calls


# --------------------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------------------


def test_status_when_the_configuration_is_invalid(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'port': 1883, 'tls-port': 1883})

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.BlockedStatus(
        'invalid configuration — tls-port and port are both set to 1883; each listener '
        'needs its own port'
    )


def test_status_names_the_offending_option(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'persistent-client-expiration': 'forever'})

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.BlockedStatus(
        'invalid configuration — persistent-client-expiration: '
        'persistent-client-expiration must be a number followed by h, d, w or m (for '
        "example 14d), or empty to never expire; got 'forever'"
    )


def test_status_when_the_deployment_is_scaled(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(peer=peer_relation(other_units=True))

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.BlockedStatus(SCALE_MESSAGE)


def test_status_when_paused(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(peer=peer_relation(paused=True))

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.MaintenanceStatus(
        'paused; run the resume action to start'
    )
    assert not fake.touched_workload()


def test_status_when_mosquitto_is_not_installed(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.version = None
    fake.installs_succeed = False

    state_out = ctx.run(ctx.on.update_status(), make_state())

    assert state_out.unit_status == testing.MaintenanceStatus('installing Mosquitto')


def test_status_when_the_broker_will_not_run(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.start_works = False

    state_out = ctx.run(ctx.on.update_status(), make_state())

    assert state_out.unit_status == testing.BlockedStatus(
        'Mosquitto is not running — check `juju debug-log` and the unit journal'
    )


def test_a_broker_that_refuses_to_start_says_why(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """The operator should not have to go and find the journal themselves."""
    fake.start_error = 'could not start Mosquitto: Job for mosquitto.service failed'
    fake.journal = 'Error: Unable to open log file'

    state_out = ctx.run(ctx.on.config_changed(), make_state())

    assert state_out.unit_status == testing.BlockedStatus(
        'Mosquitto is not running — could not start Mosquitto: Job for mosquitto.service failed'
    )
    # The reconciliation stops there rather than carrying on as if all were well.
    assert not fake.exporter.installed
    assert any('Recent Mosquitto log' in line.message for line in ctx.juju_log)


def test_a_failed_reload_does_not_error_the_hook(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """A reload is asynchronous, so a rejected configuration surfaces here.

    The broker is still up on its old configuration, so the unit stays active; what
    matters is that the hook does not end in a traceback, and that the failure is in
    the log with the broker's own words.
    """
    first = ctx.run(ctx.on.start(), make_state())
    fake.apply_error = 'could not reload Mosquitto: exit 1'
    fake.journal = 'Error: Unable to open log file'

    state_out = ctx.run(
        ctx.on.config_changed(), dataclasses.replace(first, config={'sys-interval': 20})
    )

    assert state_out.unit_status == testing.ActiveStatus(
        'ready — integrate a certificate authority to enable TLS'
    )
    assert any('would not come up' in line.message for line in ctx.juju_log)
    assert any('Recent Mosquitto log' in line.message for line in ctx.juju_log)


def test_status_warns_about_anonymous_access(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'allow-anonymous': True})

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.ActiveStatus(
        'ready — anonymous access is enabled, which is not safe'
    )


def test_status_warns_about_a_bridge_that_carries_nothing(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    upstream = testing.Relation('upstream', remote_app_name='central')
    state_in = make_state(relations=[upstream])

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.ActiveStatus(
        'ready — the bridge forwards nothing until bridge-topics is set'
    )


def test_status_asks_for_a_certificate_authority(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """tls-port defaults to 8883, but the listener cannot open without a certificate."""
    state_out = ctx.run(ctx.on.update_status(), make_state())

    assert state_out.unit_status == testing.ActiveStatus(
        'ready — integrate a certificate authority to enable TLS'
    )


def test_status_is_plain_active_when_there_is_nothing_to_say(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'tls-port': 0, 'tls-websockets-port': 0})

    state_out = ctx.run(ctx.on.update_status(), state_in)

    assert state_out.unit_status == testing.ActiveStatus()


# --------------------------------------------------------------------------------------
# Reload versus restart
#
# A reload leaves every client connected; a restart disconnects all of them. The
# distinction is the point of the configuration diffing, so it is asserted directly.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('config', 'expected'),
    [
        pytest.param({'sys-interval': 20}, mosquitto.Change.RELOAD, id='reload-safe'),
        pytest.param({'max-queued-messages': 5}, mosquitto.Change.RELOAD, id='queue-limit'),
        pytest.param({'port': 1884}, mosquitto.Change.RESTART, id='listener'),
        pytest.param({'max-connections': 2048}, mosquitto.Change.RESTART, id='max-connections'),
        pytest.param({}, mosquitto.Change.NONE, id='no-change'),
    ],
)
def test_the_change_a_reconfiguration_needs(
    ctx: testing.Context[charm.MosquittoCharm],
    fake: conftest.FakeMosquitto,
    config: dict[str, Any],
    expected: mosquitto.Change,
):
    first = ctx.run(ctx.on.start(), make_state())
    assert fake.running

    ctx.run(ctx.on.config_changed(), dataclasses.replace(first, config=config))

    assert fake.last_change is expected


def test_a_service_override_change_forces_a_restart(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """The file descriptor limit lives in a systemd drop-in, which a reload will not read."""
    first = ctx.run(ctx.on.start(), make_state())

    ctx.run(
        ctx.on.config_changed(),
        dataclasses.replace(first, config={'open-file-limit': 40000}),
    )

    assert fake.file_limit == 40000
    assert fake.last_change is mosquitto.Change.RESTART


# --------------------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------------------


def test_passwords_are_created_once_and_then_reused(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    first = ctx.run(ctx.on.start(), make_state())
    created = dict(fake.users)
    labels = {secret.label for secret in first.secrets}
    assert charm.SECRET_LABEL.format(username=mosquitto.HEALTH_USER) in labels

    ctx.run(ctx.on.config_changed(), dataclasses.replace(first))

    assert fake.users == created, 'the charm rolled its own passwords on every hook'


def test_setting_an_unchanged_password_makes_no_new_revision(
    ctx: testing.Context[charm.MosquittoCharm],
    fake: conftest.FakeMosquitto,
    monkeypatch: pytest.MonkeyPatch,
):
    """Every revision wakes every observer of the secret, so they are not free."""
    calls: list[dict[str, str]] = []
    original = ops.Secret.set_content

    def set_content(self: ops.Secret, content: dict[str, str]) -> None:
        calls.append(content)
        original(self, content)

    monkeypatch.setattr(ops.Secret, 'set_content', set_content)
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    ctx.run(
        ctx.on.action('set-password', params={'username': 'alice', 'password': 'hunter2'}),
        state_in,
    )

    assert calls == []


def test_setting_a_changed_password_does_make_a_revision(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    state_out = ctx.run(
        ctx.on.action('set-password', params={'username': 'alice', 'password': 'hunter3'}),
        state_in,
    )

    secret = state_out.get_secret(label=charm.SECRET_LABEL.format(username='alice'))
    assert secret.latest_content == {'username': 'alice', 'password': 'hunter3'}
    assert fake.users['alice'] == 'hunter3'


def test_removing_a_user_forgets_the_password(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    state_out = ctx.run(ctx.on.action('remove-user', params={'username': 'alice'}), state_in)

    assert ctx.action_results == {'removed': 'alice'}
    assert stored_users(state_out) == {}
    assert not [
        secret
        for secret in state_out.secrets
        if secret.label == charm.SECRET_LABEL.format(username='alice')
    ]
    assert 'alice' not in fake.users


# --------------------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------------------


def test_set_password_generates_one(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_out = ctx.run(ctx.on.action('set-password', params={'username': 'alice'}), make_state())

    assert ctx.action_results is not None
    assert ctx.action_results['username'] == 'alice'
    assert ctx.action_results['generated'] == 'true'
    # Action results go into the operation log, where anyone with model read access can
    # see them, so the password itself must never be among them.
    assert 'password' not in ctx.action_results
    secret = state_out.get_secret(label=charm.SECRET_LABEL.format(username='alice'))
    assert secret.latest_content['password'] not in json.dumps(ctx.action_results)
    assert fake.users['alice'] == secret.latest_content['password']


@pytest.mark.parametrize('existing', [False, True])
def test_set_password_returns_the_secret_id(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, existing: bool
):
    """The id is the only thing that tells an operator where the password went.

    `model.get_secret(label=...)` returns a Secret whose `id` is None, because ops
    only fills that in when the secret was fetched by id, so the charm has to take the
    id from the object `add_secret` returned or from `get_info()`.
    """
    state_in = (
        make_state(
            peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}),
            secrets=[user_secret('alice', 'hunter2')],
        )
        if existing
        else make_state()
    )

    ctx.run(ctx.on.action('set-password', params={'username': 'alice'}), state_in)

    assert ctx.action_results is not None
    secret_id = ctx.action_results['secret-id']
    assert secret_id is not None
    assert secret_id.startswith('secret:')


def test_set_password_accepts_one(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(
        ctx.on.action('set-password', params={'username': 'alice', 'password': 's3cret'}),
        make_state(),
    )

    assert ctx.action_results is not None
    assert ctx.action_results['generated'] == 'false'
    assert fake.users['alice'] == 's3cret'


def test_set_password_refuses_a_reserved_username(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """The charm's own users carry a broker-wide `$SYS` grant nobody else may inherit."""
    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('set-password', params={'username': '_charm_metrics'}), make_state())

    assert 'reserved for the charm' in excinfo.value.message


def test_set_password_refuses_a_username_with_a_colon(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('set-password', params={'username': 'a:b'}), make_state())

    assert 'colon' in excinfo.value.message


def test_remove_user_needs_a_user(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('remove-user', params={'username': 'nobody'}), make_state())

    assert excinfo.value.message == 'There is no user called nobody.'


def test_list_users_never_leaks_passwords(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation(
            {
                'alice': {'owner': 'action', 'acl': [['sensors/#', 'read']]},
                'bob': {'owner': 'relation:7', 'acl': []},
            }
        ),
        secrets=[user_secret('alice', 'hunter2'), user_secret('bob', 'hunter3')],
    )

    ctx.run(ctx.on.action('list-users'), state_in)

    assert ctx.action_results is not None
    assert ctx.action_results['count'] == 2
    listed = json.loads(ctx.action_results['users'])
    assert listed == {
        'alice': {'owner': 'action', 'acl': [['sensors/#', 'read']]},
        'bob': {'owner': 'relation:7', 'acl': []},
    }
    assert 'hunter2' not in json.dumps(ctx.action_results)
    # The charm's own users are not something an operator manages.
    assert mosquitto.HEALTH_USER not in listed


def test_grant_adds_a_permission(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    state_out = ctx.run(
        ctx.on.action('grant', params={'username': 'alice', 'topic': 'sensors/#'}), state_in
    )

    assert stored_users(state_out)['alice']['acl'] == [['sensors/#', 'readwrite']]
    assert fake.rules['alice'] == [('sensors/#', 'readwrite')]


def test_grant_replaces_the_previous_access_to_the_same_topic(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': [['sensors/#', 'readwrite']]}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    state_out = ctx.run(
        ctx.on.action(
            'grant', params={'username': 'alice', 'topic': 'sensors/#', 'access': 'read'}
        ),
        state_in,
    )

    assert stored_users(state_out)['alice']['acl'] == [['sensors/#', 'read']]


def test_grant_needs_a_user(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(
            ctx.on.action('grant', params={'username': 'nobody', 'topic': 'a/#'}), make_state()
        )

    assert 'set-password action first' in excinfo.value.message


def test_grant_rejects_an_unknown_access_level(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    with pytest.raises(testing.ActionFailed):
        ctx.run(
            ctx.on.action(
                'grant', params={'username': 'alice', 'topic': 'a/#', 'access': 'sideways'}
            ),
            make_state(),
        )


def test_revoke_removes_a_permission(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': [['sensors/#', 'read']]}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    state_out = ctx.run(
        ctx.on.action('revoke', params={'username': 'alice', 'topic': 'sensors/#'}), state_in
    )

    assert stored_users(state_out)['alice']['acl'] == []
    assert fake.rules['alice'] == []


def test_revoke_needs_a_user(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(
            ctx.on.action('revoke', params={'username': 'nobody', 'topic': 'a/#'}), make_state()
        )

    assert excinfo.value.message == 'There is no user called nobody.'


def test_revoke_needs_the_permission(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}),
        secrets=[user_secret('alice', 'hunter2')],
    )

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('revoke', params={'username': 'alice', 'topic': 'a/#'}), state_in)

    assert excinfo.value.message == 'alice has no permission for a/#.'


@pytest.mark.parametrize(
    'action',
    ['set-password', 'remove-user', 'grant', 'revoke', 'restore-backup'],
)
def test_the_leader_only_actions_fail_cleanly_on_a_follower(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, action: str
):
    params = {
        'set-password': {'username': 'alice'},
        'remove-user': {'username': 'alice'},
        'grant': {'username': 'alice', 'topic': 'a/#'},
        'revoke': {'username': 'alice', 'topic': 'a/#'},
        'restore-backup': {'path': '/tmp/backup.tar.gz'},  # noqa: S108
    }[action]

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action(action, params=params), make_state(leader=False))

    assert excinfo.value.message == (
        'This action changes shared state, so it must run on the leader unit.'
    )


def test_health_check_checks_both_listeners(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, certificates: None
):
    state_in = make_state(relations=[testing.Relation('certificates', remote_app_name='ca')])

    ctx.run(ctx.on.action('health-check'), state_in)

    assert ctx.action_results is not None
    assert set(ctx.action_results) == {'plain', 'tls'}
    assert ctx.action_results['plain'].startswith('ok: ')
    # The TLS listener is checked with the authority certificate, on the real address:
    # a renewal that leaves the key unreadable breaks only this one.
    assert fake.last_health_check['cafile'] is not None


def test_health_check_can_check_one_listener(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(ctx.on.action('health-check', params={'listener': 'plain'}), make_state())

    assert ctx.action_results is not None
    assert set(ctx.action_results) == {'plain'}


def test_health_check_fails_when_the_broker_does_not_answer(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.health = (False, 'no response from 127.0.0.1:1883 within 10s')

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('health-check', params={'listener': 'plain'}), make_state())

    assert 'plain' in excinfo.value.message
    assert excinfo.value.state is not None


def test_health_check_needs_a_listener(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'port': 0, 'websockets-port': 9001})

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('health-check', params={'listener': 'plain'}), state_in)

    assert excinfo.value.message == 'There is no listener to check.'


def test_health_check_says_when_there_is_no_tls_listener(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """tls-port is set by default, but the listener only exists with a certificate."""
    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('health-check', params={'listener': 'tls'}), make_state())

    assert 'certificate authority' in excinfo.value.message


def test_health_check_needs_valid_configuration(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'persistent-client-expiration': 'forever'})

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('health-check'), state_in)

    assert excinfo.value.message == 'The charm configuration is invalid; fix that first.'


def test_broker_stats_returns_the_sys_tree(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.sys_tree = {'$SYS/broker/clients/connected': '3'}

    ctx.run(ctx.on.action('broker-stats'), make_state())

    assert ctx.action_results is not None
    assert json.loads(ctx.action_results['stats']) == {'$SYS/broker/clients/connected': '3'}


def test_broker_stats_fails_when_sys_is_empty(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.sys_tree = {}

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('broker-stats'), make_state())

    assert 'sys-interval' in excinfo.value.message


def test_broker_stats_needs_the_plaintext_listener(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(config={'port': 0, 'websockets-port': 9001})

    with pytest.raises(testing.ActionFailed) as excinfo:
        ctx.run(ctx.on.action('broker-stats'), state_in)

    assert excinfo.value.message == 'The plaintext listener is needed to read the $SYS tree.'


def test_create_backup(ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto):
    ctx.run(ctx.on.action('create-backup'), make_state())

    assert ctx.action_results is not None
    assert ctx.action_results['size'] > 0
    assert fake.backups
    assert str(fake.backups[0]) == ctx.action_results['path']


def test_create_backup_at_a_chosen_path(
    ctx: testing.Context[charm.MosquittoCharm],
    fake: conftest.FakeMosquitto,
    tmp_path: pathlib.Path,
):
    destination = tmp_path / 'somewhere' / 'backup.tar.gz'

    ctx.run(ctx.on.action('create-backup', params={'path': str(destination)}), make_state())

    assert ctx.action_results is not None
    assert ctx.action_results['path'] == str(destination)
    assert destination.is_file()


def test_restore_backup_stops_and_restarts_the_broker(
    ctx: testing.Context[charm.MosquittoCharm],
    fake: conftest.FakeMosquitto,
    tmp_path: pathlib.Path,
):
    backup = tmp_path / 'backup.tar.gz'
    backup.write_bytes(b'tarball')
    fake.running = True

    ctx.run(ctx.on.action('restore-backup', params={'path': str(backup)}), make_state())

    assert ctx.action_results == {'restored': str(backup)}
    assert fake.restored == [backup]
    assert (
        fake.calls.index('stop') < fake.calls.index('restore_backup') < fake.calls.index('start')
    )
    assert fake.running


def test_restore_backup_fails_cleanly_on_a_bad_tarball(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.running = True

    with pytest.raises(testing.ActionFailed):
        ctx.run(
            ctx.on.action('restore-backup', params={'path': '/nonexistent.tar.gz'}), make_state()
        )

    # Whatever happens, the broker must not be left stopped.
    assert fake.running


def test_force_reconfigure_removes_the_fragments_and_reconciles(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    first = ctx.run(ctx.on.start(), make_state())
    paths = fake.paths('archive')
    fragment = paths.conf_dir / mosquitto.CHARM_CONFIG_FILENAME
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text('stale\n')

    ctx.run(ctx.on.action('force-reconfigure'), dataclasses.replace(first))

    assert ctx.action_results == {'result': 'reconfigured'}
    assert not fragment.exists()
    assert ('listener', '1883') in directives(fake.main_config)


def test_pause_stops_everything(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.running = True
    fake.exporter.installed = True

    state_out = ctx.run(ctx.on.action('pause'), make_state())

    assert ctx.action_results == {'result': 'paused'}
    assert not fake.running
    assert not fake.exporter.installed
    relation = next(r for r in state_out.relations if r.endpoint == PEER)
    assert relation.local_unit_data['paused'] == 'true'


def test_resume_starts_again(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(peer=peer_relation(paused=True))

    state_out = ctx.run(ctx.on.action('resume'), state_in)

    assert ctx.action_results == {'result': 'resumed'}
    assert fake.running
    relation = next(r for r in state_out.relations if r.endpoint == PEER)
    assert relation.local_unit_data.get('paused', '') == ''
    assert state_out.unit_status == testing.ActiveStatus(
        'ready — integrate a certificate authority to enable TLS'
    )


# --------------------------------------------------------------------------------------
# The mqtt provider
# --------------------------------------------------------------------------------------


def test_a_client_gets_a_user_permissions_and_endpoints(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('sensors/#', 'read')),
    )
    state_in = make_state(relations=[relation])

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    username = f'telemetry-{relation.id}'
    assert stored_users(state_out)[username] == {
        'owner': f'relation:{relation.id}',
        'acl': [['sensors/#', 'read']],
    }

    databag = state_out.get_relation(relation.id).local_app_data
    endpoints = json.loads(databag['endpoints'])
    assert {endpoint['port'] for endpoint in endpoints} == {1883}
    assert json.loads(databag['granted-permissions']) == [
        {'filter': 'sensors/#', 'access': 'read'}
    ]
    # The credentials go into a secret granted to the relation, never into the databag.
    secret = state_out.get_secret(label=f'mqtt-client-{relation.id}')
    assert json.loads(databag['secret-user']) == secret.id
    assert secret.latest_content['password'] not in json.dumps(databag)
    assert relation.id in secret.remote_grants


def test_a_client_can_use_its_credentials_immediately(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('sensors/#', 'read')),
    )
    state_in = make_state(relations=[relation])

    ctx.run(ctx.on.relation_changed(relation), state_in)

    username = f'telemetry-{relation.id}'
    assert username in fake.users, 'the password file does not know the user yet'
    assert fake.rules[username] == [('sensors/#', 'read')]


def test_a_second_reconcile_installs_the_client(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """What the charm does today: the client works from the next event onwards."""
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('sensors/#', 'read')),
    )
    first = ctx.run(ctx.on.relation_changed(relation), make_state(relations=[relation]))

    ctx.run(ctx.on.update_status(), dataclasses.replace(first))

    username = f'telemetry-{relation.id}'
    assert username in fake.users
    assert fake.rules[username] == [('sensors/#', 'read')]


def test_a_request_for_the_sys_tree_is_refused(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """`$SYS` exposes every client id and topic count on the broker."""
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('$SYS/#', 'read'), ('sensors/#', 'read')),
    )
    state_in = make_state(relations=[relation])

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    username = f'telemetry-{relation.id}'
    assert stored_users(state_out)[username]['acl'] == [['sensors/#', 'read']]
    databag = state_out.get_relation(relation.id).local_app_data
    assert json.loads(databag['granted-permissions']) == [
        {'filter': 'sensors/#', 'access': 'read'}
    ]
    assert any('$SYS' in line.message for line in ctx.juju_log if line.level == 'WARNING')


def test_a_permission_with_no_access_level_never_reaches_the_charm(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """The interface drops permissions it cannot turn into an ACL line.

    So the charm's own `UNKNOWN` handling only matters to a caller that builds a
    `TopicPermission` itself; over the wire, such a permission is already gone.
    """
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data={'topic-permissions': json.dumps([{'filter': 'sensors/#'}])},
    )
    state_in = make_state(relations=[relation])

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    username = f'telemetry-{relation.id}'
    assert stored_users(state_out)[username]['acl'] == []


def test_an_unknown_access_level_is_granted_as_readwrite(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    with ctx(ctx.on.update_status(), make_state()) as manager:
        granted = manager.charm._grant_for(
            [
                mqtt.TopicPermission(filter='sensors/#'),
                mqtt.TopicPermission(filter='', access=mqtt.Access.READ),
                mqtt.TopicPermission(filter='$SYS/#', access=mqtt.Access.READ),
            ]
        )
        manager.run()

    assert granted == [('sensors/#', 'readwrite')]


def test_a_departing_client_loses_its_user(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('sensors/#', 'read')),
    )
    username = f'telemetry-{relation.id}'
    state_in = make_state(
        peer=peer_relation({username: {'owner': f'relation:{relation.id}', 'acl': []}}),
        relations=[relation],
        secrets=[user_secret(username, 'hunter2')],
    )

    state_out = ctx.run(ctx.on.relation_broken(relation), state_in)

    assert stored_users(state_out) == {}
    assert username not in fake.users
    assert not [
        secret
        for secret in state_out.secrets
        if secret.label == charm.SECRET_LABEL.format(username=username)
    ]


def test_a_follower_publishes_nothing(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('sensors/#', 'read')),
    )
    state_in = make_state(leader=False, relations=[relation])

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    assert state_out.get_relation(relation.id).local_app_data == {}


# --------------------------------------------------------------------------------------
# TLS
# --------------------------------------------------------------------------------------


def test_tls_listeners_appear_once_a_certificate_arrives(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, certificates: None
):
    state_in = make_state(
        relations=[testing.Relation('certificates', remote_app_name='ca')],
        config={'tls-websockets-port': 8884},
    )

    ctx.run(ctx.on.config_changed(), state_in)

    assert fake.tls == mosquitto.TLSMaterial(
        certificate=CERTIFICATE, private_key=PRIVATE_KEY, ca=CA
    )
    rendered = directives(fake.main_config)
    assert ('listener', '8883') in rendered
    assert ('listener', '8884') in rendered
    paths = fake.paths('archive')
    assert ('keyfile', str(paths.certs_dir / 'server.key')) in rendered
    assert ('tls_version', 'tlsv1.2') in rendered


def test_no_tls_listener_without_a_certificate(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """Opening a TLS listener with no certificate leaves the broker refusing to start."""
    ctx.run(ctx.on.config_changed(), make_state())

    assert fake.tls is None
    assert 'write_tls_material' not in fake.calls
    assert ('listener', '8883') not in directives(fake.main_config)


def test_no_tls_material_while_the_authority_has_not_issued(
    ctx: testing.Context[charm.MosquittoCharm],
    fake: conftest.FakeMosquitto,
    monkeypatch: pytest.MonkeyPatch,
):

    def get_assigned_certificate(self: object, request: object) -> tuple[None, None]:
        return None, None

    monkeypatch.setattr(
        'charmlibs.interfaces.tls_certificates.TLSCertificatesRequiresV4.get_assigned_certificate',
        get_assigned_certificate,
    )
    state_in = make_state(relations=[testing.Relation('certificates', remote_app_name='ca')])

    ctx.run(ctx.on.config_changed(), state_in)

    assert fake.tls is None


def test_the_ca_reaches_related_clients(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, certificates: None
):
    relation = testing.Relation(
        'mqtt',
        remote_app_name='telemetry',
        remote_app_data=requirer_databag(('sensors/#', 'read')),
    )
    state_in = make_state(
        relations=[relation, testing.Relation('certificates', remote_app_name='ca')]
    )

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    databag = state_out.get_relation(relation.id).local_app_data
    assert json.loads(databag['tls-ca']) == CA
    endpoints = json.loads(databag['endpoints'])
    assert {endpoint['port'] for endpoint in endpoints} == {1883, 8883}
    assert [endpoint for endpoint in endpoints if endpoint['tls']]


# --------------------------------------------------------------------------------------
# The bridge
# --------------------------------------------------------------------------------------


def test_the_bridge_is_refused_on_a_vulnerable_mosquitto(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """Mosquitto before 2.0.19 is vulnerable to CVE-2024-3935 through a bridge.

    24.04 ships 2.0.18, so this is the default case rather than an unusual one.
    """
    fake.version = '2.0.18'
    upstream = testing.Relation(
        'upstream', remote_app_name='central', remote_app_data=upstream_databag()
    )
    state_in = make_state(relations=[upstream], config={'bridge-topics': 'topic sensors/# out'})

    ctx.run(ctx.on.relation_changed(upstream), state_in)

    assert fake.bridge_config is None
    assert any('CVE-2024-3935' in line.message for line in ctx.juju_log)


def test_the_bridge_is_rendered_on_a_patched_mosquitto(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.version = '2.0.19'
    upstream = testing.Relation(
        'upstream', remote_app_name='central', remote_app_data=upstream_databag()
    )
    state_in = make_state(relations=[upstream], config={'bridge-topics': 'topic sensors/# out'})

    ctx.run(ctx.on.relation_changed(upstream), state_in)

    assert fake.bridge_config is not None
    rendered = directives(fake.bridge_config)
    assert ('connection', 'mosquitto-upstream') in rendered
    assert ('address', '10.9.8.7:1883') in rendered
    assert ('topic', 'sensors/# out') in rendered
    # Without try_private a pair of brokers echoes a message back and forth for ever.
    assert ('try_private', 'true') in rendered


def test_the_bridge_prefers_a_tls_endpoint(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.version = '2.0.19'
    upstream = testing.Relation(
        'upstream',
        remote_app_name='central',
        remote_app_data={
            'endpoints': json.dumps(
                [
                    {'host': '10.9.8.7', 'port': 1883, 'tls': False, 'protocol': 'mqtt'},
                    {'host': '10.9.8.7', 'port': 8883, 'tls': True, 'protocol': 'mqtt'},
                ]
            ),
            'tls-ca': json.dumps(CA),
        },
    )
    state_in = make_state(relations=[upstream], config={'bridge-topics': 'topic sensors/# out'})

    ctx.run(ctx.on.relation_changed(upstream), state_in)

    assert fake.bridge_config is not None
    assert ('address', '10.9.8.7:8883') in directives(fake.bridge_config)
    assert fake.bridge_ca == CA


def test_a_bridge_with_no_topics_says_so(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.version = '2.0.19'
    upstream = testing.Relation(
        'upstream', remote_app_name='central', remote_app_data=upstream_databag()
    )
    state_in = make_state(relations=[upstream])

    ctx.run(ctx.on.relation_changed(upstream), state_in)

    assert any('bridge-topics is empty' in line.message for line in ctx.juju_log)


def test_the_upstream_request_asks_for_no_topic_permissions(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """What the edge asks the central broker for, which is currently nothing.

    `src/charm.py` builds its `MQTTRequirer` with `topic_permissions=()`, so the
    central broker grants the bridge user an empty ACL — and an empty ACL denies every
    publish. A bridge configured this way connects and then carries nothing.
    """
    upstream = testing.Relation('upstream', remote_app_name='central')

    state_out = ctx.run(ctx.on.relation_created(upstream), make_state(relations=[upstream]))

    databag = state_out.get_relation(upstream.id).local_app_data
    assert json.loads(databag['topic-permissions']) is None


def test_no_bridge_without_an_upstream(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(ctx.on.config_changed(), make_state(config={'bridge-topics': 'topic sensors/# out'}))

    assert fake.bridge_config is None


# --------------------------------------------------------------------------------------
# The metrics exporter
# --------------------------------------------------------------------------------------


def test_the_exporter_is_installed_when_something_is_collecting(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(relations=[testing.Relation('cos-agent', remote_app_name='agent')])

    ctx.run(ctx.on.config_changed(), state_in)

    assert fake.exporter.installed
    assert fake.exporter.running
    assert fake.exporter.listen_port == 9234
    assert fake.exporter.username == mosquitto.METRICS_USER
    assert fake.exporter.password == fake.users[mosquitto.METRICS_USER]


def test_the_exporter_is_not_installed_without_a_collector(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    ctx.run(ctx.on.config_changed(), make_state())

    assert not fake.exporter.installed
    assert 'remove_exporter' in fake.calls


def test_the_exporter_goes_away_when_sys_is_switched_off(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """With `$SYS` disabled there is nothing for the exporter to read."""
    state_in = make_state(
        relations=[testing.Relation('cos-agent', remote_app_name='agent')],
        config={'sys-interval': 0},
    )

    ctx.run(ctx.on.config_changed(), state_in)

    assert not fake.exporter.installed


def test_the_exporter_needs_the_plaintext_listener(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(
        relations=[testing.Relation('cos-agent', remote_app_name='agent')],
        config={'port': 0, 'websockets-port': 9001},
    )

    ctx.run(ctx.on.config_changed(), state_in)

    assert not fake.exporter.installed
    assert any('plaintext listener' in line.message for line in ctx.juju_log)


# --------------------------------------------------------------------------------------
# Everything at once
# --------------------------------------------------------------------------------------


def test_a_fully_integrated_deployment(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto, certificates: None
):
    """Every endpoint related at once, which is what `from_context` gives us."""
    fake.version = '2.0.19'
    state_in = testing.State.from_context(
        ctx, leader=True, model=LXD, config={'bridge-topics': 'topic sensors/# out'}
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert fake.running
    assert fake.exporter.running
    assert fake.tls is not None
    assert state_out.unit_status == testing.ActiveStatus()


# --------------------------------------------------------------------------------------
# Degenerate states
#
# The peer relation carries the user list, and it is not there for the first few
# moments of a unit's life. Nothing may fall over in the meantime.
# --------------------------------------------------------------------------------------


def test_without_a_peer_relation_there_are_no_users(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = testing.State(leader=True, model=LXD)

    ctx.run(ctx.on.action('list-users'), state_in)

    assert ctx.action_results == {'users': '{}', 'count': 0}


def test_without_a_peer_relation_a_new_user_cannot_be_saved(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = testing.State(leader=True, model=LXD)

    ctx.run(ctx.on.action('set-password', params={'username': 'alice'}), state_in)

    assert any('user list cannot be saved' in line.message for line in ctx.juju_log)


def test_without_a_peer_relation_pausing_still_stops_the_broker(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    fake.running = True

    ctx.run(ctx.on.action('pause'), testing.State(leader=True, model=LXD))

    assert not fake.running


def test_a_corrupt_user_list_is_ignored(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    """Somebody editing relation data by hand must not put the unit into error."""
    peer = testing.PeerRelation(PEER, local_app_data={'users': 'not json at all'})
    state_in = make_state(peer=peer)

    ctx.run(ctx.on.action('list-users'), state_in)

    assert ctx.action_results == {'users': '{}', 'count': 0}
    assert any('not valid JSON' in line.message for line in ctx.juju_log)


def test_a_user_list_that_is_not_a_mapping_is_ignored(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    peer = testing.PeerRelation(PEER, local_app_data={'users': '["alice"]'})
    state_in = make_state(peer=peer)

    ctx.run(ctx.on.action('list-users'), state_in)

    assert ctx.action_results == {'users': '{}', 'count': 0}


def test_removing_a_user_that_has_no_secret(
    ctx: testing.Context[charm.MosquittoCharm], fake: conftest.FakeMosquitto
):
    state_in = make_state(peer=peer_relation({'alice': {'owner': 'action', 'acl': []}}))

    state_out = ctx.run(ctx.on.action('remove-user', params={'username': 'alice'}), state_in)

    assert stored_users(state_out) == {}
