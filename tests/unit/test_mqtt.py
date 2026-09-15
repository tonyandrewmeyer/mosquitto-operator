"""State-transition tests for the `mqtt` relation interface."""

from __future__ import annotations

import json
from typing import Any

import ops
import ops.testing as testing
import pytest

import mqtt

# --------------------------------------------------------------------------------------
# A throwaway charm that wires up both sides of the interface.
# --------------------------------------------------------------------------------------

CHARM_META = {
    'name': 'mqtt-test',
    'provides': {'mqtt': {'interface': 'mqtt'}},
    'requires': {'upstream': {'interface': 'mqtt', 'limit': 1, 'optional': True}},
}

REQUESTED = (mqtt.TopicPermission(filter='sensors/#', access=mqtt.Access.READ),)

ENDPOINTS = (
    mqtt.Endpoint(host='10.1.2.3', port=1883, tls=False, protocol=mqtt.Protocol.MQTT),
    mqtt.Endpoint(host='10.1.2.3', port=8883, tls=True, protocol=mqtt.Protocol.MQTT),
)

# Knobs the tests turn with monkeypatch.setitem, so that the throwaway charm can
# exercise each provider code path from a real hook.
BEHAVIOUR: dict[str, Any] = {
    'publish': True,
    'error': None,
    'username': 'relation-7',
    'password': 'hunter2',
}


class _Charm(ops.CharmBase):
    """A charm that is both an MQTT provider and an MQTT requirer."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.provider = mqtt.MQTTProvider(self)
        self.requirer = mqtt.MQTTRequirer(
            self, topic_permissions=REQUESTED, client_id_prefix='telemetry-'
        )
        self.seen: list[str] = []
        framework.observe(self.provider.on.client_joined, self._on_client_joined)
        framework.observe(self.provider.on.client_departed, self._on_client_departed)
        framework.observe(self.requirer.on.broker_available, self._on_broker_available)
        framework.observe(self.requirer.on.broker_gone, self._on_broker_gone)

    def _on_client_joined(self, event: mqtt.MQTTClientJoinedEvent):
        self.seen.append(f'joined:{event.app_name}:{event.client_id_prefix}')
        self.joined_permissions = event.topic_permissions
        if not self.unit.is_leader():
            return
        if BEHAVIOUR['error'] is not None:
            self.provider.set_error(
                event.relation, BEHAVIOUR['error'], code=mqtt.ErrorCode.PERMISSION_DENIED
            )
            return
        if not BEHAVIOUR['publish']:
            return
        self.provider.publish_endpoints(
            event.relation, ENDPOINTS, tls_ca='-----BEGIN CERTIFICATE-----', mqtt_version='5.0'
        )
        self.provider.set_credentials(
            event.relation, BEHAVIOUR['username'], BEHAVIOUR['password']
        )
        self.provider.set_granted_permissions(event.relation, event.topic_permissions)

    def _on_client_departed(self, event: mqtt.MQTTClientDepartedEvent):
        self.seen.append('departed')

    def _on_broker_available(self, event: mqtt.MQTTBrokerAvailableEvent):
        self.seen.append('available')
        self.connection = self.requirer.get_connection()

    def _on_broker_gone(self, event: mqtt.MQTTBrokerGoneEvent):
        self.seen.append('gone')


LXD = testing.Model(name='testing', type='lxd')


@pytest.fixture
def ctx():
    with testing.Context(_Charm, meta=CHARM_META) as context:
        yield context


def _requirer_databag(**overrides: str) -> dict[str, str]:
    data = {
        'topic-permissions': json.dumps([{'filter': 'sensors/#', 'access': 'read'}]),
        'client-id-prefix': json.dumps('telemetry-'),
        'requested-secrets': json.dumps([{'field': 'username'}, {'field': 'password'}]),
        'mtls-cert': json.dumps(None),
    }
    data.update(overrides)
    return data


def _loaded(databag: dict[str, str], key: str) -> Any:
    return json.loads(databag[key])


# --------------------------------------------------------------------------------------
# Requirer publishes its request
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize('event_name', ['relation_created', 'relation_joined'])
def test_requirer_publishes_request(ctx: testing.Context, event_name: str):
    relation = testing.Relation('upstream', remote_app_name='broker')
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    state_out = ctx.run(getattr(ctx.on, event_name)(relation), state_in)

    databag = state_out.get_relation(relation.id).local_app_data
    assert _loaded(databag, 'client-id-prefix') == 'telemetry-'
    assert _loaded(databag, 'topic-permissions') == [{'filter': 'sensors/#', 'access': 'read'}]
    # Collections are emitted in a stable order, so that rewriting the same request
    # does not wake the far side up.
    assert _loaded(databag, 'requested-secrets') == [
        {'field': 'password'},
        {'field': 'username'},
    ]
    assert _loaded(databag, 'mtls-cert') is None


def test_requirer_does_not_publish_when_not_leader(ctx: testing.Context):
    relation = testing.Relation('upstream', remote_app_name='broker')
    state_in = testing.State(leader=False, model=LXD, relations={relation})

    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    assert state_out.get_relation(relation.id).local_app_data == {}


# --------------------------------------------------------------------------------------
# Provider sees the request
# --------------------------------------------------------------------------------------


def test_provider_get_requests(ctx: testing.Context):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.update_status(), state_in) as manager:
        requests = manager.charm.provider.get_requests()
        manager.run()

    assert set(requests) == {relation.id}
    request = requests[relation.id]
    assert request.app_name == 'telemetry'
    assert request.client_id_prefix == 'telemetry-'
    assert request.topic_permissions == frozenset({
        mqtt.TopicPermission(filter='sensors/#', access=mqtt.Access.READ)
    })
    assert request.requested_secrets == frozenset({
        mqtt.SecretField.USERNAME,
        mqtt.SecretField.PASSWORD,
    })
    assert request.mtls_cert is None


def test_provider_emits_client_joined(ctx: testing.Context):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.relation_changed(relation), state_in) as manager:
        manager.run()
        assert manager.charm.seen == ['joined:telemetry:telemetry-']
        assert manager.charm.joined_permissions == frozenset({
            mqtt.TopicPermission(filter='sensors/#', access=mqtt.Access.READ)
        })


# --------------------------------------------------------------------------------------
# Provider publishes endpoints and credentials
# --------------------------------------------------------------------------------------


def test_provider_publishes_endpoints_and_credentials(ctx: testing.Context):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    databag = state_out.get_relation(relation.id).local_app_data
    assert _loaded(databag, 'endpoints') == [
        {'host': '10.1.2.3', 'port': 1883, 'tls': False, 'protocol': 'mqtt'},
        {'host': '10.1.2.3', 'port': 8883, 'tls': True, 'protocol': 'mqtt'},
    ]
    assert _loaded(databag, 'tls-ca') == '-----BEGIN CERTIFICATE-----'
    assert _loaded(databag, 'mqtt-version') == '5.0'
    assert _loaded(databag, 'granted-permissions') == [
        {'filter': 'sensors/#', 'access': 'read'}
    ]
    assert _loaded(databag, 'error') is None

    # The credentials are in a secret, granted to this relation, and only the URI is
    # in the databag.
    secret = state_out.get_secret(label=f'mqtt-client-{relation.id}')
    assert secret.owner == 'app'
    assert secret.latest_content == {'username': 'relation-7', 'password': 'hunter2'}
    assert relation.id in secret.remote_grants
    assert _loaded(databag, 'secret-user') == secret.id
    assert 'password' not in json.dumps(databag)


def test_second_reconcile_creates_no_new_revision(
    ctx: testing.Context, monkeypatch: pytest.MonkeyPatch
):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})
    first = ctx.run(ctx.on.relation_changed(relation), state_in)

    set_content_calls: list[dict[str, str]] = []
    original = ops.Secret.set_content

    def _spy(self: ops.Secret, content: dict[str, str]) -> None:
        set_content_calls.append(content)
        original(self, content)

    monkeypatch.setattr(ops.Secret, 'set_content', _spy)

    with testing.Context(_Charm, meta=CHARM_META) as second_ctx:
        second = second_ctx.run(
            second_ctx.on.relation_changed(first.get_relation(relation.id)), first
        )

    assert set_content_calls == []
    assert second.get_secret(label=f'mqtt-client-{relation.id}').latest_content == (
        first.get_secret(label=f'mqtt-client-{relation.id}').latest_content
    )
    assert (
        second.get_relation(relation.id).local_app_data
        == first.get_relation(relation.id).local_app_data
    )


def test_changed_password_creates_a_new_revision(
    ctx: testing.Context, monkeypatch: pytest.MonkeyPatch
):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})
    first = ctx.run(ctx.on.relation_changed(relation), state_in)

    monkeypatch.setitem(BEHAVIOUR, 'password', 'a-new-password')
    with testing.Context(_Charm, meta=CHARM_META) as second_ctx:
        second = second_ctx.run(
            second_ctx.on.relation_changed(first.get_relation(relation.id)), first
        )

    secret = second.get_secret(label=f'mqtt-client-{relation.id}')
    assert secret.latest_content == {'username': 'relation-7', 'password': 'a-new-password'}


def test_setters_require_leadership(ctx: testing.Context):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=False, model=LXD, relations={relation})

    with ctx(ctx.on.update_status(), state_in) as manager:
        provider = manager.charm.provider
        live = manager.charm.model.get_relation('mqtt', relation.id)
        assert live is not None
        with pytest.raises(mqtt.MQTTError):
            provider.publish_endpoints(live, ENDPOINTS)
        with pytest.raises(mqtt.MQTTError):
            provider.set_credentials(live, 'u', 'p')
        with pytest.raises(mqtt.MQTTError):
            provider.set_granted_permissions(live, REQUESTED)
        with pytest.raises(mqtt.MQTTError):
            provider.set_error(live, 'nope')
        manager.run()


def test_relation_broken_removes_the_secret(ctx: testing.Context):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})
    joined = ctx.run(ctx.on.relation_changed(relation), state_in)

    with testing.Context(_Charm, meta=CHARM_META) as broken_ctx:
        state_out = broken_ctx.run(
            broken_ctx.on.relation_broken(joined.get_relation(relation.id)), joined
        )

    assert state_out.secrets == frozenset()


def test_secret_remove_drops_the_revision(ctx: testing.Context):
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    secret = testing.Secret(
        {'username': 'relation-7', 'password': 'rotated'},
        label=f'mqtt-client-{relation.id}',
        owner='app',
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation}, secrets={secret})

    # Juju asks the owner to drop a superseded revision once nothing tracks it. Only a
    # revision that is neither tracked nor latest can be removed.
    ctx.run(ctx.on.secret_remove(secret, revision=2), state_in)

    assert ctx.removed_secret_revisions == [2]


def test_secret_remove_ignores_other_secrets(ctx: testing.Context):
    secret = testing.Secret({'a': 'b'}, label='something-else', owner='app')
    state_in = testing.State(leader=True, model=LXD, secrets={secret})

    ctx.run(ctx.on.secret_remove(secret, revision=2), state_in)

    assert ctx.removed_secret_revisions == []


# --------------------------------------------------------------------------------------
# Requirer reads the connection back
# --------------------------------------------------------------------------------------


def _provider_databag(**overrides: str) -> dict[str, str]:
    data = {
        'endpoints': json.dumps([
            {'host': '10.1.2.3', 'port': 8883, 'tls': True, 'protocol': 'mqtt'}
        ]),
        'granted-permissions': json.dumps([{'filter': 'sensors/#', 'access': 'read'}]),
        'client-id-prefix': json.dumps('telemetry-'),
        'tls-ca': json.dumps('-----BEGIN CERTIFICATE-----'),
        'mqtt-version': json.dumps('5.0'),
        'error': json.dumps(None),
    }
    data.update(overrides)
    return data


def test_requirer_reads_the_connection(ctx: testing.Context):
    secret = testing.Secret({'username': 'relation-7', 'password': 'hunter2'})
    relation = testing.Relation(
        'upstream',
        remote_app_name='broker',
        remote_app_data=_provider_databag(**{'secret-user': json.dumps(secret.id)}),
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation}, secrets={secret})

    with ctx(ctx.on.relation_changed(relation), state_in) as manager:
        manager.run()
        connection = manager.charm.connection

    assert manager.charm.seen == ['available']
    assert connection is not None
    assert connection.username == 'relation-7'
    assert connection.password == 'hunter2'
    assert connection.tls_ca == '-----BEGIN CERTIFICATE-----'
    assert connection.mqtt_version == '5.0'
    assert connection.error is None
    assert connection.endpoints == frozenset({
        mqtt.Endpoint(host='10.1.2.3', port=8883, tls=True, protocol=mqtt.Protocol.MQTT)
    })
    assert connection.granted_permissions == frozenset({
        mqtt.TopicPermission(filter='sensors/#', access=mqtt.Access.READ)
    })
    assert next(iter(connection.endpoints)).uri == 'mqtts://10.1.2.3:8883'


def test_requirer_connection_is_none_when_nothing_published(ctx: testing.Context):
    relation = testing.Relation('upstream', remote_app_name='broker')
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.relation_changed(relation), state_in) as manager:
        manager.run()
        assert manager.charm.connection is None


def test_requirer_tolerates_an_ungranted_secret(ctx: testing.Context):
    relation = testing.Relation(
        'upstream',
        remote_app_name='broker',
        remote_app_data=_provider_databag(**{'secret-user': json.dumps('secret:nosuchsecret')}),
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.relation_changed(relation), state_in) as manager:
        manager.run()
        connection = manager.charm.connection

    assert connection is not None
    assert connection.username is None
    assert connection.password is None


def test_requirer_broker_gone(ctx: testing.Context):
    relation = testing.Relation(
        'upstream', remote_app_name='broker', remote_app_data=_provider_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.relation_broken(relation), state_in) as manager:
        manager.run()
        assert manager.charm.seen == ['gone']


def test_secret_changed_re_emits_broker_available(ctx: testing.Context):
    secret = testing.Secret({'username': 'relation-7', 'password': 'rotated'})
    relation = testing.Relation(
        'upstream',
        remote_app_name='broker',
        remote_app_data=_provider_databag(**{'secret-user': json.dumps(secret.id)}),
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation}, secrets={secret})

    with ctx(ctx.on.secret_changed(secret), state_in) as manager:
        manager.run()
        connection = manager.charm.connection

    assert manager.charm.seen == ['available']
    assert connection is not None
    assert connection.password == 'rotated'


# --------------------------------------------------------------------------------------
# The error path
# --------------------------------------------------------------------------------------


def test_provider_publishes_an_error(ctx: testing.Context, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(BEHAVIOUR, 'error', 'topic filter "#" is not permitted')
    relation = testing.Relation(
        'mqtt', remote_app_name='telemetry', remote_app_data=_requirer_databag()
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    databag = state_out.get_relation(relation.id).local_app_data
    assert _loaded(databag, 'error') == {
        'message': 'topic filter "#" is not permitted',
        'code': 'permission-denied',
    }
    assert _loaded(databag, 'secret-user') is None
    assert state_out.secrets == frozenset()


def test_requirer_surfaces_the_error(ctx: testing.Context):
    relation = testing.Relation(
        'upstream',
        remote_app_name='broker',
        remote_app_data={
            'error': json.dumps({'message': 'broker is full', 'code': 'broker-unavailable'})
        },
    )
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.relation_changed(relation), state_in) as manager:
        manager.run()
        connection = manager.charm.connection

    assert connection is not None
    assert connection.error == 'broker is full'
    assert connection.endpoints == frozenset()


# --------------------------------------------------------------------------------------
# Forward and backward compatibility of the wire format
# --------------------------------------------------------------------------------------


def test_empty_databags_parse():
    assert mqtt.RequirerAppData.model_validate({}) == mqtt.RequirerAppData()
    assert mqtt.ProviderAppData.model_validate({}) == mqtt.ProviderAppData()


@pytest.mark.parametrize(
    'field',
    ['topic-permissions', 'client-id-prefix', 'requested-secrets', 'mtls-cert'],
)
def test_requirer_fields_may_be_absent_or_null(field: str):
    full = {
        'topic-permissions': [{'filter': 'a/#', 'access': 'read'}],
        'client-id-prefix': 'a-',
        'requested-secrets': [{'field': 'username'}],
        'mtls-cert': 'PEM',
    }
    absent = {key: value for key, value in full.items() if key != field}
    assert mqtt.RequirerAppData.model_validate(absent)
    assert mqtt.RequirerAppData.model_validate({**full, field: None})


@pytest.mark.parametrize(
    'field',
    [
        'endpoints',
        'secret-user',
        'granted-permissions',
        'client-id-prefix',
        'tls-ca',
        'mqtt-version',
        'error',
    ],
)
def test_provider_fields_may_be_absent_or_null(field: str):
    full = {
        'endpoints': [{'host': 'a', 'port': 1883}],
        'secret-user': 'secret:abc',
        'granted-permissions': [{'filter': 'a/#', 'access': 'read'}],
        'client-id-prefix': 'a-',
        'tls-ca': 'PEM',
        'mqtt-version': '5.0',
        'error': {'message': 'nope'},
    }
    absent = {key: value for key, value in full.items() if key != field}
    assert mqtt.ProviderAppData.model_validate(absent)
    assert mqtt.ProviderAppData.model_validate({**full, field: None})


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('read', mqtt.Access.READ),
        ('deny', mqtt.Access.DENY),
        ('subscribe-only', mqtt.Access.UNKNOWN),
        (42, mqtt.Access.UNKNOWN),
        (None, mqtt.Access.UNKNOWN),
    ],
)
def test_unknown_enum_values_become_unknown(raw: Any, expected: mqtt.Access):
    assert mqtt.TopicPermission.model_validate({'filter': 'a/#', 'access': raw}).access == expected


def test_unusable_collection_members_are_dropped():
    data = mqtt.RequirerAppData.model_validate({
        'topic-permissions': [
            {'filter': 'a/#', 'access': 'read'},
            {},
            {'strange-data': 'bar'},
            {'filter': 'b/#', 'access': 'read', 'new-field': 'd'},
            {'filter': 'c/#', 'access': 'from-the-future'},
            {'access': 'read'},
        ]
    })
    assert data.topic_permissions == frozenset({
        mqtt.TopicPermission(filter='a/#', access=mqtt.Access.READ),
        mqtt.TopicPermission(filter='b/#', access=mqtt.Access.READ),
    })


def test_out_of_range_endpoints_are_dropped():
    data = mqtt.ProviderAppData.model_validate({
        'endpoints': [
            {'host': 'a', 'port': 1883},
            {'host': 'b'},
            {'port': 1883},
            {'host': 'c', 'port': 0},
            {'host': 'd', 'port': 70000},
        ]
    })
    assert data.endpoints == frozenset({mqtt.Endpoint(host='a', port=1883)})


@pytest.mark.parametrize(
    'databag',
    [
        {'topic-permissions': '"not-a-list"'},
        {'topic-permissions': '{"filter": "a"}'},
        {'client-id-prefix': '[1, 2, 3]'},
        {'topic-permissions': 'this is not json at all'},
        {'requested-secrets': '17'},
    ],
)
def test_malformed_requirer_databag_does_not_raise(
    ctx: testing.Context, databag: dict[str, str]
):
    relation = testing.Relation('mqtt', remote_app_name='telemetry', remote_app_data=databag)
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.update_status(), state_in) as manager:
        assert manager.charm.provider.get_requests() == {}
        manager.run()


@pytest.mark.parametrize(
    'databag',
    [
        {'endpoints': '"10.1.2.3:1883"'},
        {'endpoints': '[["10.1.2.3", 1883]]'},
        {'mqtt-version': '{"major": 5}'},
        {'error': '"a bare string"'},
        {'secret-user': 'not json'},
    ],
)
def test_malformed_provider_databag_does_not_raise(
    ctx: testing.Context, databag: dict[str, str]
):
    relation = testing.Relation('upstream', remote_app_name='broker', remote_app_data=databag)
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.relation_changed(relation), state_in) as manager:
        manager.run()
        assert manager.charm.connection is None


def test_unknown_top_level_fields_are_ignored():
    data = mqtt.ProviderAppData.model_validate({
        'mqtt-version': '5.0',
        'a-field-from-v1': {'anything': True},
    })
    assert data.mqtt_version == '5.0'


# --------------------------------------------------------------------------------------
# Round trip through Relation.save() and Relation.load()
# --------------------------------------------------------------------------------------

FULL_PROVIDER_DATA = mqtt.ProviderAppData(
    endpoints=frozenset({
        mqtt.Endpoint(host='10.1.2.3', port=1883, tls=False, protocol=mqtt.Protocol.MQTT),
        mqtt.Endpoint(host='broker.example.com', port=443, tls=True,
                      protocol=mqtt.Protocol.WEBSOCKETS),
    }),
    secret_user='secret:cvh7kruupa1s46bqvuig',
    granted_permissions=frozenset({
        mqtt.TopicPermission(filter='sensors/#', access=mqtt.Access.READ),
        mqtt.TopicPermission(filter='commands/#', access=mqtt.Access.WRITE),
    }),
    client_id_prefix='telemetry-',
    tls_ca='-----BEGIN CERTIFICATE-----',
    mqtt_version='5.0',
    error=mqtt.Error(message='partially granted', code=mqtt.ErrorCode.PERMISSION_DENIED),
)

FULL_REQUIRER_DATA = mqtt.RequirerAppData(
    topic_permissions=frozenset({
        mqtt.TopicPermission(filter='sensors/#', access=mqtt.Access.READ),
        mqtt.TopicPermission(filter='commands/#', access=mqtt.Access.WRITE),
    }),
    client_id_prefix='telemetry-',
    requested_secrets=frozenset({
        mqtt.SecretRequest(field=mqtt.SecretField.USERNAME),
        mqtt.SecretRequest(field=mqtt.SecretField.PASSWORD),
        mqtt.SecretRequest(field=mqtt.SecretField.TLS_CA),
    }),
    mtls_cert='-----BEGIN CERTIFICATE-----',
)


@pytest.mark.parametrize(
    ('endpoint', 'model'),
    [('mqtt', FULL_PROVIDER_DATA), ('upstream', FULL_REQUIRER_DATA)],
)
def test_every_field_round_trips(
    ctx: testing.Context, endpoint: str, model: Any
):
    relation = testing.Relation(endpoint, remote_app_name='peer')
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.update_status(), state_in) as manager:
        live = manager.charm.model.get_relation(endpoint, relation.id)
        assert live is not None
        live.save(model, manager.charm.app)
        loaded = live.load(type(model), manager.charm.app)
        manager.run()

    assert loaded == model


def test_save_is_stable_across_hooks(ctx: testing.Context):
    relation = testing.Relation('mqtt', remote_app_name='peer')
    state_in = testing.State(leader=True, model=LXD, relations={relation})

    with ctx(ctx.on.update_status(), state_in) as manager:
        live = manager.charm.model.get_relation('mqtt', relation.id)
        assert live is not None
        live.save(FULL_PROVIDER_DATA, manager.charm.app)
        first = dict(live.data[manager.charm.app])
        # A fresh model with the same members, built in a different order.
        reordered = FULL_PROVIDER_DATA.model_copy(
            update={'endpoints': frozenset(reversed(list(FULL_PROVIDER_DATA.endpoints or ())))}
        )
        live.save(reordered, manager.charm.app)
        second = dict(live.data[manager.charm.app])
        manager.run()

    assert first == second


# --------------------------------------------------------------------------------------
# The secret content schema
# --------------------------------------------------------------------------------------


def test_secret_keys_have_no_underscores():
    content = mqtt.secret_content(mqtt.UserSecret(username='u', password='p'))
    assert content == {'username': 'u', 'password': 'p'}
    assert not any('_' in key for key in content)


@pytest.mark.parametrize(
    ('content', 'username', 'password'),
    [
        ({'username': 'u', 'password': 'p'}, 'u', 'p'),
        ({'username': 'u'}, 'u', None),
        ({}, None, None),
        ({'username': 'u', 'password': 'p', 'a-future-field': 'x'}, 'u', 'p'),
    ],
)
def test_secret_content_parses(
    content: dict[str, str], username: str | None, password: str | None
):
    parsed = mqtt.parse_secret_content(content)
    assert parsed.username == username
    assert parsed.password == password


def test_unset_secret_fields_are_omitted():
    assert mqtt.secret_content(mqtt.UserSecret(username='u')) == {'username': 'u'}
