# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""The schemas for the provider and requirer sides of the `mqtt` interface.

It exposes two `interface_tester.schema_base.DataBagSchema` subclasses called:

- `ProviderSchema`
- `RequirerSchema`

and, because a Juju secret is shared over this relation, the schema of that secret's
content, `UserSecret`.

Every top-level field is optional, collections are arrays of objects in a stable order,
and every enumeration has an `UNKNOWN` member, per
https://documentation.ubuntu.com/charmlibs/latest/how-to/design-relation-interfaces/

Examples:
    RequirerSchema:
        unit: <empty>
        app: {
            "topic-permissions": [
                {"filter": "sensors/+/temperature", "access": "read"},
                {"filter": "commands/#", "access": "write"}
            ],
            "client-id-prefix": "telemetry-",
            "requested-secrets": [{"field": "password"}, {"field": "username"}],
            "mtls-cert": null
        }

    ProviderSchema:
        unit: <empty>
        app: {
            "endpoints": [
                {"host": "10.1.2.3", "port": 1883, "tls": false, "protocol": "mqtt"},
                {"host": "10.1.2.3", "port": 8883, "tls": true, "protocol": "mqtt"}
            ],
            "secret-user": "secret:cvh7kruupa1s46bqvuig",
            "granted-permissions": [
                {"filter": "sensors/+/temperature", "access": "read"}
            ],
            "client-id-prefix": null,
            "tls-ca": "-----BEGIN CERTIFICATE-----...",
            "mqtt-version": "5.0",
            "error": null
        }
"""

from __future__ import annotations

import enum

import pydantic

try:
    from interface_tester.schema_base import DataBagSchema
except ImportError:  # pragma: no cover

    class DataBagSchema(pydantic.BaseModel):  # type: ignore[no-redef]
        """A stand-in, so that this file can be read without the interface tester."""

        unit: pydantic.BaseModel | None = None
        app: pydantic.BaseModel | None = None


class Access(enum.StrEnum):
    """The access a client has to a topic filter.

    The members other than `UNKNOWN` are spelt exactly as Mosquitto's `acl_file` grammar
    spells them, so a permission maps onto an access control entry with no translation.
    """

    UNKNOWN = 'UNKNOWN'
    READ = 'read'
    WRITE = 'write'
    READWRITE = 'readwrite'
    DENY = 'deny'


class Protocol(enum.StrEnum):
    """The transport an endpoint speaks MQTT over.

    Encryption is carried separately, by `Endpoint.tls`, so there is no `mqtts` or `wss`
    member.
    """

    UNKNOWN = 'UNKNOWN'
    MQTT = 'mqtt'
    WEBSOCKETS = 'websockets'


class SecretField(enum.StrEnum):
    """A provider field a requirer would like delivered through a Juju secret."""

    UNKNOWN = 'UNKNOWN'
    USERNAME = 'username'
    PASSWORD = 'password'  # noqa: S105
    TLS_CA = 'tls-ca'


class ErrorCode(enum.StrEnum):
    """Why a provider could not satisfy a request."""

    UNKNOWN = 'UNKNOWN'
    INVALID_REQUEST = 'invalid-request'
    PERMISSION_DENIED = 'permission-denied'
    BROKER_UNAVAILABLE = 'broker-unavailable'


class TopicPermission(pydantic.BaseModel, frozen=True):
    """One MQTT topic filter, and the access granted or requested on it."""

    filter: str | None = pydantic.Field(
        default=None,
        description=(
            'An MQTT topic filter: `+` matches one level and `#` matches the remainder.'
            " Mosquitto's `%u` and `%c` substitutions are permitted."
        ),
        examples=['sensors/+/temperature', 'devices/%u/#'],
        title='Topic filter',
    )
    access: Access = pydantic.Field(
        default=Access.UNKNOWN,
        description='The access to grant on the filter.',
        examples=['read', 'write', 'readwrite', 'deny'],
        title='Access',
    )


class Endpoint(pydantic.BaseModel, frozen=True):
    """One address at which the broker accepts MQTT connections."""

    host: str | None = pydantic.Field(
        default=None,
        description='A hostname or IP address the broker listens on.',
        examples=['10.1.2.3', 'broker.example.com'],
        title='Host',
    )
    port: int | None = pydantic.Field(
        default=None,
        description='The TCP port the broker listens on, from 1 to 65535.',
        examples=[1883, 8883],
        title='Port',
    )
    tls: bool = pydantic.Field(
        default=False,
        description='Whether this listener requires TLS.',
        examples=[True, False],
        title='TLS',
    )
    protocol: Protocol = pydantic.Field(
        default=Protocol.UNKNOWN,
        description='The transport the listener speaks MQTT over.',
        examples=['mqtt', 'websockets'],
        title='Protocol',
    )


class SecretRequest(pydantic.BaseModel, frozen=True):
    """One field a requirer would like delivered through a Juju secret."""

    field: SecretField = pydantic.Field(
        default=SecretField.UNKNOWN,
        description='The name of the provider field to deliver through a Juju secret.',
        examples=['username', 'password', 'tls-ca'],
        title='Field',
    )


class Error(pydantic.BaseModel, frozen=True):
    """Why the provider could not satisfy the requirer's request."""

    message: str | None = pydantic.Field(
        default=None,
        description='A human-readable explanation, suitable for a unit status message.',
        examples=['topic filter "#" is not permitted'],
        title='Message',
    )
    code: ErrorCode = pydantic.Field(
        default=ErrorCode.UNKNOWN,
        description='A machine-readable classification of the failure.',
        examples=['invalid-request', 'permission-denied', 'broker-unavailable'],
        title='Code',
    )


class MQTTProviderAppData(pydantic.BaseModel):
    """The databag for the provider side of this interface."""

    model_config = pydantic.ConfigDict(populate_by_name=True)

    endpoints: frozenset[Endpoint] | None = pydantic.Field(
        default=None,
        description=(
            'The listeners the requirer may connect to. Endpoints that name no host, or'
            ' a port outside 1-65535, are discarded on reception.'
        ),
        title='Endpoints',
    )
    secret_user: str | None = pydantic.Field(
        default=None,
        alias='secret-user',
        description=(
            'The URI of a Juju secret, granted to this relation, whose content is the'
            ' username and password to connect with. This is an opaque Juju locator, not'
            ' a network address: the `secret:` scheme is required, and no userinfo, host,'
            ' port, query or fragment is allowed. The path is a Juju secret ID, 20'
            ' lowercase alphanumeric characters. A remote secret may be prefixed with the'
            " source model's UUID, as `secret://<model-uuid>/<id>`."
        ),
        examples=['secret:cvh7kruupa1s46bqvuig'],
        title='User secret URI',
    )
    granted_permissions: frozenset[TopicPermission] | None = pydantic.Field(
        default=None,
        alias='granted-permissions',
        description=(
            'The topic permissions actually installed on the broker, which may be'
            ' narrower than those requested.'
        ),
        title='Granted permissions',
    )
    client_id_prefix: str | None = pydantic.Field(
        default=None,
        alias='client-id-prefix',
        description=(
            'The MQTT client ID prefix actually reserved for the requirer. Optional:'
            ' a broker with no way to reserve one leaves this unset.'
        ),
        examples=['telemetry-'],
        title='Client ID prefix',
    )
    tls_ca: str | None = pydantic.Field(
        default=None,
        alias='tls-ca',
        description=(
            "The certificate authority chain, in PEM form, that signs the broker's"
            ' certificate. Set whenever any published endpoint has `tls` set.'
        ),
        examples=['-----BEGIN CERTIFICATE-----\n...'],
        title='CA chain',
    )
    mqtt_version: str | None = pydantic.Field(
        default=None,
        alias='mqtt-version',
        description='The highest MQTT protocol version the broker supports.',
        examples=['3.1.1', '5.0'],
        title='MQTT version',
    )
    error: Error | None = pydantic.Field(
        default=None,
        description='Why the request could not be satisfied. Absent when it could.',
        title='Error',
    )


class MQTTRequirerAppData(pydantic.BaseModel):
    """The databag for the requirer side of this interface."""

    model_config = pydantic.ConfigDict(populate_by_name=True)

    topic_permissions: frozenset[TopicPermission] | None = pydantic.Field(
        default=None,
        alias='topic-permissions',
        description='The topic filters the requirer wants access to, and the access it wants.',
        title='Topic permissions',
    )
    client_id_prefix: str | None = pydantic.Field(
        default=None,
        alias='client-id-prefix',
        description=(
            'A prefix the requirer would like reserved for its MQTT client IDs, so that'
            ' several of its units can connect at once without evicting each other.'
        ),
        examples=['telemetry-'],
        title='Client ID prefix',
    )
    requested_secrets: frozenset[SecretRequest] | None = pydantic.Field(
        default=None,
        alias='requested-secrets',
        description=(
            'The provider fields the requirer would like delivered through a Juju secret'
            ' rather than in the databag. `username` and `password` are always delivered'
            ' that way, whether or not they are asked for.'
        ),
        title='Requested secrets',
    )
    mtls_cert: str | None = pydantic.Field(
        default=None,
        alias='mtls-cert',
        description=(
            "The requirer's client certificate, in PEM form, when it authenticates with"
            ' mutual TLS rather than with a password.'
        ),
        examples=['-----BEGIN CERTIFICATE-----\n...'],
        title='Client certificate',
    )


class UserSecret(pydantic.BaseModel):
    """The content of the Juju secret named by `secret-user`.

    Juju secret keys may not contain underscores, so a field whose Python name contains
    one is written with hyphens.
    """

    username: str | None = pydantic.Field(
        default=None,
        description='The MQTT username to connect with.',
        examples=['relation-7'],
        title='Username',
    )
    password: str | None = pydantic.Field(
        default=None,
        description='The password for that username.',
        examples=['a-32-character-random-string'],
        title='Password',
    )


class ProviderSchema(DataBagSchema):
    """The schema for the provider side of this interface."""

    app: MQTTProviderAppData


class RequirerSchema(DataBagSchema):
    """The schema for the requirer side of this interface."""

    app: MQTTRequirerAppData
