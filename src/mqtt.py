# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""The `mqtt` relation interface, version 0.

An `mqtt` relation lets an application ask a broker for the right to publish to, and
subscribe to, a set of MQTT topic filters, and lets the broker hand back the addresses
to connect to and the credentials to connect with.

Both sides write to the **application** databag, so only the leader unit writes. The
broker never puts credentials in the databag: it creates an application-owned Juju
secret holding the username and password, grants that secret to the relation, and
publishes only the secret URI.

Two classes make up the charm-facing API:

- :class:`MQTTProvider`, for the broker charm.
- :class:`MQTTRequirer`, for a charm that wants to talk to a broker. The Mosquitto
  charm itself uses this on its `upstream` endpoint, to configure a bridge.

The wire format is a long-lived contract and is deliberately specified apart from this
API; see `docs/interfaces/mqtt/v0/` for the interface specification, and
https://documentation.ubuntu.com/charmlibs/latest/how-to/design-relation-interfaces/
for the rules it follows.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import enum
import json
import logging
from typing import Annotated, Any

import ops
import pydantic

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_RELATION_NAME = 'mqtt'
"""The endpoint name a broker charm conventionally offers the interface on."""

DEFAULT_REQUIRER_RELATION_NAME = 'upstream'
"""The endpoint name the Mosquitto charm conventionally consumes the interface on."""

INTERFACE_VERSION = 0
"""The version of the `mqtt` interface that this module speaks."""


class MQTTError(Exception):
    """Raised when the interface cannot do what was asked of it."""


# --------------------------------------------------------------------------------------
# Enumerations
#
# Every enumeration carries an `UNKNOWN` member, and every enumerated field is parsed
# through `_coerce`, so that a value written by a newer peer deserialises to `UNKNOWN`
# rather than raising. See the "Fixed field types" rule in the charmlibs how-to.
# --------------------------------------------------------------------------------------


class Access(enum.StrEnum):
    """The access a client has to a topic filter.

    The members other than `UNKNOWN` are spelt exactly as Mosquitto's `acl_file`
    grammar spells them (`topic read|write|readwrite|deny <filter>`), so that a
    permission maps onto an ACL line with no translation.
    """

    UNKNOWN = 'UNKNOWN'
    READ = 'read'
    WRITE = 'write'
    READWRITE = 'readwrite'
    DENY = 'deny'


class Protocol(enum.StrEnum):
    """The transport an endpoint speaks MQTT over.

    Whether the transport is encrypted is carried separately, by `Endpoint.tls`, so
    there is no `mqtts` or `wss` member: an encrypted WebSocket listener is
    `WEBSOCKETS` with `tls` set.
    """

    UNKNOWN = 'UNKNOWN'
    MQTT = 'mqtt'
    WEBSOCKETS = 'websockets'


class SecretField(enum.StrEnum):
    """A field a requirer would like delivered through a Juju secret."""

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


def _coerce[EnumT: enum.StrEnum](
    enum_class: type[EnumT],
) -> collections.abc.Callable[[Any], EnumT]:
    """Build a validator that maps an unrecognised value to the enum's `UNKNOWN`.

    Args:
        enum_class: the enumeration to parse into. It must have an `UNKNOWN` member.

    Returns:
        A callable suitable for use as a pydantic "before" validator.
    """

    def validate(value: Any) -> EnumT:
        if isinstance(value, enum_class):
            return value
        try:
            return enum_class(value)
        except ValueError:
            logger.debug('Unrecognised %s value %r; treating it as UNKNOWN.', enum_class, value)
            return enum_class['UNKNOWN']

    return validate


_Access = Annotated[Access, pydantic.BeforeValidator(_coerce(Access))]
_Protocol = Annotated[Protocol, pydantic.BeforeValidator(_coerce(Protocol))]
_SecretField = Annotated[SecretField, pydantic.BeforeValidator(_coerce(SecretField))]
_ErrorCode = Annotated[ErrorCode, pydantic.BeforeValidator(_coerce(ErrorCode))]


# --------------------------------------------------------------------------------------
# Collection members
#
# Collections on the wire are arrays of objects, never arrays of primitives and never
# comma-separated strings, so that a member can grow a field later. A member that
# carries no usable information is dropped on reception rather than rejected.
# --------------------------------------------------------------------------------------


class _Item(pydantic.BaseModel, frozen=True):
    """Base class for the objects that make up a collection field."""

    model_config = pydantic.ConfigDict(populate_by_name=True, frozen=True)

    def is_usable(self) -> bool:
        """Whether this object carries enough information to act on.

        Returns:
            True if a recipient should keep this object, False if it should be
            discarded as semantically empty.
        """
        raise NotImplementedError


class TopicPermission(_Item, frozen=True):
    """One MQTT topic filter, and the access granted or requested on it."""

    filter: str | None = pydantic.Field(
        default=None,
        description=(
            'An MQTT topic filter, in MQTT syntax: `+` matches one level and `#`'
            ' matches the remainder. Mosquitto`s `%u` and `%c` substitutions are'
            ' permitted.'
        ),
        examples=['sensors/+/temperature', 'devices/%u/#'],
        title='Topic filter',
    )
    access: _Access = pydantic.Field(
        default=Access.UNKNOWN,
        description='The access to grant on the filter.',
        examples=['read', 'write', 'readwrite', 'deny'],
        title='Access',
    )

    def is_usable(self) -> bool:
        """Whether this permission names both a filter and a known access.

        Returns:
            True if the permission can be turned into an ACL line.
        """
        return self.filter is not None and self.access is not Access.UNKNOWN


class Endpoint(_Item, frozen=True):
    """One address at which the broker accepts MQTT connections."""

    host: str | None = pydantic.Field(
        default=None,
        description='A hostname or IP address the broker listens on.',
        examples=['10.1.2.3', 'broker.example.com'],
        title='Host',
    )
    port: int | None = pydantic.Field(
        default=None,
        description='The TCP port the broker listens on.',
        examples=[1883, 8883],
        title='Port',
    )
    tls: bool = pydantic.Field(
        default=False,
        description='Whether this listener requires TLS.',
        examples=[True, False],
        title='TLS',
    )
    protocol: _Protocol = pydantic.Field(
        default=Protocol.UNKNOWN,
        description='The transport the listener speaks MQTT over.',
        examples=['mqtt', 'websockets'],
        title='Protocol',
    )

    def is_usable(self) -> bool:
        """Whether this endpoint names a host and a port in range.

        Returns:
            True if a client could attempt a connection to this endpoint.
        """
        return self.host is not None and self.port is not None and 1 <= self.port <= 65535

    @property
    def uri(self) -> str:
        """The endpoint as a URI, for logging and for display in a status message.

        Returns:
            A URI such as `mqtts://10.1.2.3:8883`.
        """
        if self.protocol is Protocol.WEBSOCKETS:
            scheme = 'wss' if self.tls else 'ws'
        else:
            scheme = 'mqtts' if self.tls else 'mqtt'
        return f'{scheme}://{self.host}:{self.port}'


class SecretRequest(_Item, frozen=True):
    """One field a requirer would like delivered through a Juju secret."""

    field: _SecretField = pydantic.Field(
        default=SecretField.UNKNOWN,
        description='The name of the provider field to deliver through a Juju secret.',
        examples=['username', 'password', 'tls-ca'],
        title='Field',
    )

    def is_usable(self) -> bool:
        """Whether this request names a field this version of the interface knows.

        Returns:
            True if the field is a recognised one.
        """
        return self.field is not SecretField.UNKNOWN


class Error(pydantic.BaseModel, frozen=True):
    """Why the provider could not satisfy the requirer's request."""

    model_config = pydantic.ConfigDict(populate_by_name=True, frozen=True)

    message: str | None = pydantic.Field(
        default=None,
        description='A human-readable explanation, suitable for a unit status message.',
        examples=['topic filter "#" is not permitted'],
        title='Message',
    )
    code: _ErrorCode = pydantic.Field(
        default=ErrorCode.UNKNOWN,
        description='A machine-readable classification of the failure.',
        examples=['invalid-request', 'permission-denied', 'broker-unavailable'],
        title='Code',
    )


def _drop_unusable[ItemT: _Item](items: frozenset[ItemT] | None) -> frozenset[ItemT] | None:
    """Discard collection members that carry no usable information.

    Args:
        items: the parsed collection, or None if the field was absent.

    Returns:
        The collection without its empty or wholly-unknown members.
    """
    if items is None:
        return None
    return frozenset(item for item in items if item.is_usable())


def _stable(items: frozenset[_Item] | None) -> list[dict[str, Any]] | None:
    """Serialise a collection in an order that does not change between hooks.

    A `frozenset` iterates in hash order, which varies from one charm invocation to
    the next; writing that order out would rewrite the databag on every hook and
    trigger a relation-changed event on the far side each time.

    Args:
        items: the collection to serialise, or None.

    Returns:
        The members as dictionaries, sorted by their canonical JSON form.
    """
    if items is None:
        return None
    dumped = [item.model_dump(mode='json', by_alias=True) for item in items]
    return sorted(dumped, key=lambda item: json.dumps(item, sort_keys=True))


# --------------------------------------------------------------------------------------
# Databag models
#
# Every top-level field is `X | None = None`, so that an empty databag parses, and so
# that a field that has not been set is unambiguously absent.
# --------------------------------------------------------------------------------------


class RequirerAppData(pydantic.BaseModel):
    """The requirer's application databag."""

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
            ' rather than in the databag.'
        ),
        title='Requested secrets',
    )
    mtls_cert: str | None = pydantic.Field(
        default=None,
        alias='mtls-cert',
        description=(
            'The requirer`s client certificate, in PEM form, when it authenticates with'
            ' mutual TLS rather than with a password.'
        ),
        examples=['-----BEGIN CERTIFICATE-----\n...'],
        title='Client certificate',
    )

    _filter_permissions = pydantic.field_validator('topic_permissions')(_drop_unusable)
    _filter_secrets = pydantic.field_validator('requested_secrets')(_drop_unusable)

    @pydantic.field_serializer('topic_permissions', 'requested_secrets')
    def _serialise(self, value: frozenset[_Item] | None) -> list[dict[str, Any]] | None:
        return _stable(value)


class ProviderAppData(pydantic.BaseModel):
    """The provider's application databag."""

    model_config = pydantic.ConfigDict(populate_by_name=True)

    endpoints: frozenset[Endpoint] | None = pydantic.Field(
        default=None,
        description='The listeners the requirer may connect to.',
        title='Endpoints',
    )
    secret_user: str | None = pydantic.Field(
        default=None,
        alias='secret-user',
        description=(
            'The URI of a Juju secret, granted to this relation, whose content is the'
            ' username and password to connect with. This is an opaque Juju locator:'
            ' the `secret:` scheme, no userinfo, no query and no fragment.'
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
        description='The MQTT client ID prefix actually reserved for the requirer.',
        examples=['telemetry-'],
        title='Client ID prefix',
    )
    tls_ca: str | None = pydantic.Field(
        default=None,
        alias='tls-ca',
        description=(
            'The certificate authority chain, in PEM form, that signs the broker`s'
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

    _filter_endpoints = pydantic.field_validator('endpoints')(_drop_unusable)
    _filter_granted = pydantic.field_validator('granted_permissions')(_drop_unusable)

    @pydantic.field_serializer('endpoints', 'granted_permissions')
    def _serialise(self, value: frozenset[_Item] | None) -> list[dict[str, Any]] | None:
        return _stable(value)


class UserSecret(pydantic.BaseModel):
    """The content of the Juju secret named by `secret-user`.

    The rules that apply to the databag apply here too: no mandatory fields, no field
    reuse, and the schema lives alongside the interface it belongs to.
    """

    model_config = pydantic.ConfigDict(populate_by_name=True)

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


def secret_content(secret: UserSecret) -> dict[str, str]:
    """Render a secret model as Juju secret content.

    Juju secret keys may not contain underscores, so field names are written with
    hyphens. Fields that are unset are omitted rather than written as an empty string,
    so that setting the same credentials twice produces identical content.

    Args:
        secret: the model to render.

    Returns:
        A mapping suitable for passing to `Application.add_secret` or
        `Secret.set_content`.
    """
    dumped = secret.model_dump(mode='json', by_alias=True, exclude_none=True)
    return {key.replace('_', '-'): str(value) for key, value in dumped.items()}


def parse_secret_content(content: collections.abc.Mapping[str, str]) -> UserSecret:
    """Parse Juju secret content back into a secret model.

    Args:
        content: the mapping returned by `Secret.get_content`.

    Returns:
        The parsed model. Unrecognised keys are ignored, so that content written by a
        newer peer still parses.
    """
    renamed = {key.replace('-', '_'): value for key, value in content.items()}
    return UserSecret.model_validate(renamed)


# --------------------------------------------------------------------------------------
# The charm-facing data classes
#
# These are deliberately separate from the databag models: the wire format is a
# long-lived contract, while this API is ours to change.
# --------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, eq=False)
class ClientRequest:
    """What one related application has asked the broker for."""

    relation: ops.Relation
    """The relation the request arrived on."""

    app_name: str
    """The name of the requiring application."""

    topic_permissions: frozenset[TopicPermission] = frozenset()
    """The topic filters and access the application asked for."""

    client_id_prefix: str | None = None
    """The MQTT client ID prefix the application asked to reserve."""

    requested_secrets: frozenset[SecretField] = frozenset()
    """The fields the application asked to receive through a Juju secret."""

    mtls_cert: str | None = None
    """The application's client certificate, when it authenticates with mutual TLS."""


@dataclasses.dataclass(frozen=True)
class BrokerConnection:
    """Everything a requirer needs in order to connect to the broker."""

    endpoints: frozenset[Endpoint] = frozenset()
    """The listeners the broker offered."""

    username: str | None = None
    """The username from the granted Juju secret, if it could be read."""

    password: str | None = None
    """The password from the granted Juju secret, if it could be read."""

    tls_ca: str | None = None
    """The CA chain that signs the broker's certificate, in PEM form."""

    granted_permissions: frozenset[TopicPermission] = frozenset()
    """The topic permissions the broker actually installed."""

    mqtt_version: str | None = None
    """The highest MQTT protocol version the broker supports."""

    error: str | None = None
    """The broker's explanation of why the request could not be satisfied."""


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------


class MQTTClientJoinedEvent(ops.RelationEvent):
    """A related application has asked the broker for access."""

    @property
    def app_name(self) -> str:
        """The name of the requiring application."""
        return self.relation.app.name if self.relation.app is not None else ''

    @property
    def topic_permissions(self) -> frozenset[TopicPermission]:
        """The topic filters and access the application asked for."""
        data = _load(RequirerAppData, self.relation, self.relation.app)
        if data is None or data.topic_permissions is None:
            return frozenset()
        return data.topic_permissions

    @property
    def client_id_prefix(self) -> str | None:
        """The MQTT client ID prefix the application asked to reserve."""
        data = _load(RequirerAppData, self.relation, self.relation.app)
        return None if data is None else data.client_id_prefix


class MQTTClientDepartedEvent(ops.RelationEvent):
    """A related application has gone away, and its credentials should be revoked."""


class MQTTProviderEvents(ops.ObjectEvents):
    """Events emitted by :class:`MQTTProvider`."""

    client_joined = ops.EventSource(MQTTClientJoinedEvent)
    client_departed = ops.EventSource(MQTTClientDepartedEvent)


class MQTTBrokerAvailableEvent(ops.RelationEvent):
    """The broker has published connection details, or changed them."""


class MQTTBrokerGoneEvent(ops.RelationEvent):
    """The broker relation has been removed."""


class MQTTRequirerEvents(ops.ObjectEvents):
    """Events emitted by :class:`MQTTRequirer`."""

    broker_available = ops.EventSource(MQTTBrokerAvailableEvent)
    broker_gone = ops.EventSource(MQTTBrokerGoneEvent)


# --------------------------------------------------------------------------------------
# Reading and writing databags
# --------------------------------------------------------------------------------------


def _load[ModelT: pydantic.BaseModel](
    model: type[ModelT], relation: ops.Relation, source: ops.Application | None
) -> ModelT | None:
    """Load one side of a relation's application databag.

    Args:
        model: the databag model to parse into.
        relation: the relation to read from.
        source: the application whose databag to read. None when the remote
            application is not known, which happens on a broken relation.

    Returns:
        The parsed databag, or None if it is absent or could not be parsed. A databag
        that does not parse is logged and ignored, never raised: a peer running a
        newer or a broken charm must not be able to put this unit into error.
    """
    if source is None:
        return None
    try:
        return relation.load(model, source)
    except (ValueError, TypeError):
        logger.warning(
            'Ignoring unparsable %s databag on relation %s:%d.',
            source.name,
            relation.name,
            relation.id,
            exc_info=True,
        )
        return None


# --------------------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------------------


class MQTTProvider(ops.Object):
    """Offers an MQTT broker to related applications."""

    on = MQTTProviderEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: ops.CharmBase, relation_name: str = DEFAULT_PROVIDER_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        # Juju 4.0 creates a secret only when the hook commits, so a secret created
        # earlier in this hook cannot be fetched back by label. Remember the objects
        # we have already handled instead of asking Juju for them again.
        self._secrets: dict[str, ops.Secret] = {}
        events = charm.on[relation_name]
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)
        self.framework.observe(charm.on.secret_remove, self._on_secret_remove)

    def get_requests(self) -> dict[int, ClientRequest]:
        """Return the outstanding request per relation id, for reconciliation.

        Returns:
            A mapping of relation id to the request on that relation. Relations whose
            databag is empty or unparsable are omitted, so the broker simply does not
            reconcile them.
        """
        requests: dict[int, ClientRequest] = {}
        for relation in self._charm.model.relations[self._relation_name]:
            request = self._get_request(relation)
            if request is not None:
                requests[relation.id] = request
        return requests

    def publish_endpoints(
        self,
        relation: ops.Relation,
        endpoints: collections.abc.Iterable[Endpoint],
        *,
        tls_ca: str | None = None,
        mqtt_version: str | None = None,
    ) -> None:
        """Publish the addresses the requirer should connect to.

        The charm computes the hosts itself, from `model.get_binding(...).network`;
        this module never reads `private-address` from relation data, because Juju 4.0
        no longer maintains it.

        Args:
            relation: the relation to publish on.
            endpoints: the listeners the requirer may use. Endpoints that name no host
                or no in-range port are discarded.
            tls_ca: the CA chain that signs the broker's certificate, in PEM form. Set
                this whenever any endpoint has `tls` set.
            mqtt_version: the highest MQTT protocol version the broker supports.

        Raises:
            MQTTError: if this unit is not the leader.
        """
        usable = _drop_unusable(frozenset(endpoints)) or frozenset()
        self._update(
            relation,
            endpoints=usable,
            tls_ca=tls_ca,
            mqtt_version=mqtt_version,
            error=None,
        )

    def set_credentials(self, relation: ops.Relation, username: str, password: str) -> str:
        """Create or update the credentials secret and publish its URI.

        The credentials never reach the databag. They go into an application-owned Juju
        secret, which is granted to this relation; only the secret's URI is published.

        Args:
            relation: the relation the credentials are for.
            username: the MQTT username.
            password: the password for that username.

        Returns:
            The secret's id, which is also what is published as `secret-user`.

        Raises:
            MQTTError: if this unit is not the leader, or if Juju did not give the
                secret an id.
        """
        self._require_leader()
        content = secret_content(UserSecret(username=username, password=password))
        label = self._secret_label(relation)
        secret = self._secrets.get(label)
        if secret is None:
            try:
                secret = self._charm.model.get_secret(label=label)
            except ops.SecretNotFoundError:
                secret = self._charm.app.add_secret(content, label=label)
            else:
                # Comparing before setting matters: `set_content` always creates a new
                # revision, so setting the same credentials on every hook would leave
                # Juju with a revision per hook and send the requirer a
                # `secret-changed` each time.
                if secret.peek_content() != content:
                    secret.set_content(content)
            self._secrets[label] = secret
        elif secret.peek_content() != content:
            secret.set_content(content)
        secret.grant(relation)
        if secret.id is None:  # pragma: no cover
            raise MQTTError('Juju did not give the credentials secret an id.')
        self._update(relation, secret_user=secret.id)
        return secret.id

    def set_granted_permissions(
        self, relation: ops.Relation, permissions: collections.abc.Iterable[TopicPermission]
    ) -> None:
        """Publish the topic permissions actually installed on the broker.

        Args:
            relation: the relation to publish on.
            permissions: the permissions installed, which may be narrower than those
                requested.

        Raises:
            MQTTError: if this unit is not the leader.
        """
        granted = _drop_unusable(frozenset(permissions)) or frozenset()
        self._update(relation, granted_permissions=granted)

    def set_error(
        self,
        relation: ops.Relation,
        message: str,
        *,
        code: ErrorCode = ErrorCode.UNKNOWN,
    ) -> None:
        """Tell the requirer that its request could not be satisfied.

        Credentials already published are left alone, so that an existing client is not
        disconnected by a later request that the broker refuses.

        Args:
            relation: the relation to publish on.
            message: a human-readable explanation, suitable for a status message.
            code: a machine-readable classification of the failure.

        Raises:
            MQTTError: if this unit is not the leader.
        """
        self._update(relation, error=Error(message=message, code=code))

    def _get_request(self, relation: ops.Relation) -> ClientRequest | None:
        """Parse one relation's requirer databag into a request."""
        if relation.app is None:
            return None
        data = _load(RequirerAppData, relation, relation.app)
        if data is None:
            return None
        requested = data.requested_secrets or frozenset()
        return ClientRequest(
            relation=relation,
            app_name=relation.app.name,
            topic_permissions=data.topic_permissions or frozenset(),
            client_id_prefix=data.client_id_prefix,
            requested_secrets=frozenset(request.field for request in requested),
            mtls_cert=data.mtls_cert,
        )

    def _secret_label(self, relation: ops.Relation) -> str:
        """The label of the credentials secret for one relation."""
        return f'{self._relation_name}-client-{relation.id}'

    def _require_leader(self) -> None:
        """Raise unless this unit may write the application databag.

        Raises:
            MQTTError: if this unit is not the leader.
        """
        if not self._charm.unit.is_leader():
            raise MQTTError(
                'Only the leader unit can write MQTT relation data; '
                'guard the call with `self.unit.is_leader()`.'
            )

    def _update(self, relation: ops.Relation, **changes: Any) -> None:
        """Merge changes into our application databag, writing only if it differs."""
        self._require_leader()
        current = _load(ProviderAppData, relation, self._charm.app) or ProviderAppData()
        updated = current.model_copy(update=changes)
        if updated == current:
            return
        relation.save(updated, self._charm.app)

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        self.on.client_joined.emit(event.relation, app=event.relation.app)

    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        if self._charm.unit.is_leader():
            self._remove_secret(event.relation)
        self.on.client_departed.emit(event.relation, app=event.relation.app)

    def _remove_secret(self, relation: ops.Relation) -> None:
        """Remove the credentials secret for a relation that has gone away."""
        label = self._secret_label(relation)
        secret = self._secrets.pop(label, None)
        if secret is None:
            try:
                secret = self._charm.model.get_secret(label=label)
            except ops.SecretNotFoundError:
                return
        secret.remove_all_revisions()

    def _on_secret_remove(self, event: ops.SecretRemoveEvent) -> None:
        """Drop a revision Juju no longer needs, so revisions do not accumulate."""
        label = event.secret.label
        if label is None or not label.startswith(f'{self._relation_name}-client-'):
            return
        try:
            event.secret.remove_revision(event.revision)
        except ops.SecretNotFoundError:
            # Juju can deliver secret-remove for a secret that has already gone.
            # See https://github.com/juju/juju/issues/19036.
            logger.warning('No such secret %s; nothing to remove.', label)


# --------------------------------------------------------------------------------------
# Requirer
# --------------------------------------------------------------------------------------


class MQTTRequirer(ops.Object):
    """Requests access to an MQTT broker."""

    on = MQTTRequirerEvents()  # type: ignore[reportAssignmentType]

    def __init__(
        self,
        charm: ops.CharmBase,
        relation_name: str = DEFAULT_REQUIRER_RELATION_NAME,
        *,
        topic_permissions: collections.abc.Iterable[TopicPermission] = (),
        client_id_prefix: str | None = None,
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._topic_permissions = frozenset(topic_permissions)
        self._client_id_prefix = client_id_prefix
        events = charm.on[relation_name]
        self.framework.observe(events.relation_created, self._on_relation_created)
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)
        self.framework.observe(charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(charm.on.secret_changed, self._on_secret_changed)

    def get_connection(self) -> BrokerConnection | None:
        """Return the broker connection details, or None if not yet available.

        Returns:
            The connection details, including the username and password read from the
            granted Juju secret, or None if the relation is absent, the broker has not
            published anything yet, or the databag could not be parsed.
        """
        relation = self._charm.model.get_relation(self._relation_name)
        if relation is None:
            return None
        data = _load(ProviderAppData, relation, relation.app)
        if data is None:
            return None
        username, password = self._read_credentials(data.secret_user)
        error = None if data.error is None else data.error.message
        if not data.endpoints and username is None and error is None:
            return None
        return BrokerConnection(
            endpoints=data.endpoints or frozenset(),
            username=username,
            password=password,
            tls_ca=data.tls_ca,
            granted_permissions=data.granted_permissions or frozenset(),
            mqtt_version=data.mqtt_version,
            error=error,
        )

    def _read_credentials(self, uri: str | None) -> tuple[str | None, str | None]:
        """Read the username and password out of the granted secret."""
        if not uri:
            return None, None
        try:
            secret = self._charm.model.get_secret(id=uri)
            content = secret.get_content(refresh=True)
        except (ops.SecretNotFoundError, ops.ModelError):
            logger.warning('Cannot read the MQTT credentials secret %s yet.', uri)
            return None, None
        user = parse_secret_content(content)
        return user.username, user.password

    def _publish_request(self, relation: ops.Relation) -> None:
        """Write this requirer's request, if this unit is the leader."""
        if not self._charm.unit.is_leader():
            return
        # Our provider always delivers the credentials through a Juju secret, so these
        # are the fields we always ask for.
        requested = frozenset(
            {
                SecretRequest(field=SecretField.USERNAME),
                SecretRequest(field=SecretField.PASSWORD),
            }
        )
        data = RequirerAppData(
            topic_permissions=self._topic_permissions or None,
            client_id_prefix=self._client_id_prefix,
            requested_secrets=requested,
        )
        current = _load(RequirerAppData, relation, self._charm.app)
        if data == current:
            return
        relation.save(data, self._charm.app)

    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        self._publish_request(event.relation)

    def _on_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        self._publish_request(event.relation)

    def _on_leader_elected(self, event: ops.LeaderElectedEvent) -> None:
        for relation in self._charm.model.relations[self._relation_name]:
            self._publish_request(relation)

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        self._publish_request(event.relation)
        self.on.broker_available.emit(event.relation, app=event.relation.app)

    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        self.on.broker_gone.emit(event.relation, app=event.relation.app)

    def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
        relation = self._charm.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return
        data = _load(ProviderAppData, relation, relation.app)
        if data is None or not data.secret_user:
            return
        if event.secret.id != data.secret_user:
            return
        self.on.broker_available.emit(relation, app=relation.app)
