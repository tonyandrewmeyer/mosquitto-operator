#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""A charm for the Eclipse Mosquitto MQTT broker."""

from __future__ import annotations

import json
import logging
import pathlib
import socket
from typing import TYPE_CHECKING

import ops
import ops.tracing
import pydantic
from charmlibs.interfaces import tls_certificates

import config
import mosquitto
import mqtt
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)

PEER = 'mosquitto-peers'
USERS_KEY = 'users'
SECRET_LABEL = 'mqtt-user-{username}'
SOURCE_KEY = 'install-source'
EXPORTER_SOURCE = pathlib.Path(__file__).parent / 'exporter.py'


class MosquittoCharm(ops.CharmBase):
    """Operate a Mosquitto MQTT broker on a machine."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self._tracing = ops.tracing.Tracing(
            self, 'charm-tracing', ca_relation_name='receive-ca-cert'
        )
        self.mqtt = mqtt.MQTTProvider(self, 'mqtt')
        self.upstream = mqtt.MQTTRequirer(
            self,
            'upstream',
            topic_permissions=(),
            client_id_prefix=self.unit.name.replace('/', '-'),
        )
        self.certificates = tls_certificates.TLSCertificatesRequiresV4(
            self,
            'certificates',
            certificate_requests=self._certificate_requests(),
            mode=tls_certificates.Mode.UNIT,
        )
        self.cos_agent = COSAgentProvider(
            self,
            metrics_endpoints=[{'path': '/metrics', 'port': self._metrics_port()}],
            metrics_rules_dir='./src/prometheus_alert_rules',
            dashboard_dirs=['./src/grafana_dashboards'],
            refresh_events=[self.on.config_changed],
        )

        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.remove, self._on_remove)
        framework.observe(self.on.config_changed, self._on_reconcile)
        framework.observe(self.on.upgrade_charm, self._on_upgrade)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.secret_changed, self._on_reconcile)
        framework.observe(self.on[PEER].relation_changed, self._on_reconcile)
        framework.observe(self.on[PEER].relation_departed, self._on_reconcile)
        framework.observe(self.on['data'].storage_attached, self._on_reconcile)
        framework.observe(self.certificates.on.certificate_available, self._on_reconcile)
        framework.observe(self.mqtt.on.client_joined, self._on_reconcile)
        framework.observe(self.mqtt.on.client_departed, self._on_client_departed)
        framework.observe(self.upstream.on.broker_available, self._on_reconcile)
        framework.observe(self.upstream.on.broker_gone, self._on_reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

        framework.observe(self.on.set_password_action, self._on_set_password)
        framework.observe(self.on.remove_user_action, self._on_remove_user)
        framework.observe(self.on.list_users_action, self._on_list_users)
        framework.observe(self.on.grant_action, self._on_grant)
        framework.observe(self.on.revoke_action, self._on_revoke)
        framework.observe(self.on.health_check_action, self._on_health_check)
        framework.observe(self.on.broker_stats_action, self._on_broker_stats)
        framework.observe(self.on.create_backup_action, self._on_create_backup)
        framework.observe(self.on.restore_backup_action, self._on_restore_backup)
        framework.observe(self.on.force_reconfigure_action, self._on_force_reconfigure)
        framework.observe(self.on.pause_action, self._on_pause)
        framework.observe(self.on.resume_action, self._on_resume)

    # --- Configuration -------------------------------------------------------

    @property
    def _config(self) -> config.MosquittoConfig | None:
        """The charm's configuration, or None if it is invalid.

        Invalid configuration is reported through `collect_unit_status`, so that the
        message says which option is wrong rather than leaving a traceback in the log.
        """
        try:
            return self.load_config(config.MosquittoConfig)
        except (pydantic.ValidationError, ValueError):
            return None

    @property
    def _config_error(self) -> str | None:
        """The first configuration error, phrased for an operator."""
        try:
            self.load_config(config.MosquittoConfig)
        except pydantic.ValidationError as e:
            first = e.errors()[0]
            location = '.'.join(str(part) for part in first['loc']).replace('_', '-')
            message = first['msg'].removeprefix('Value error, ')
            return f'{location}: {message}' if location else message
        except ValueError as e:
            return str(e)
        return None

    def _metrics_port(self) -> int:
        """The exporter's port, falling back to the default when config is invalid."""
        settings = self._config
        return settings.metrics_port if settings else 9234

    def _paths(self) -> mosquitto.Paths:
        """Where Mosquitto's files live, for the configured install source."""
        settings = self._config
        return mosquitto.paths(settings.install_source if settings else 'archive')

    def _certificate_requests(self) -> list[tls_certificates.CertificateRequestAttributes]:
        """What to ask the certificate authority for.

        Clients connect to the broker directly rather than through an ingress, so the
        certificate has to name every address they might use.
        """
        settings = self._config
        fqdn = socket.getfqdn()
        sans_dns = {fqdn, socket.gethostname()}
        sans_ip: set[str] = set()
        binding = self.model.get_binding('mqtt') or self.model.get_binding(PEER)
        if binding is not None:
            for address in (binding.network.bind_address, binding.network.ingress_address):
                if address is not None:
                    sans_ip.add(str(address))
        if settings is not None:
            sans_dns.update(settings.extra_sans_dns)
        return [
            tls_certificates.CertificateRequestAttributes(
                common_name=(settings.certificate_common_name if settings else '') or fqdn,
                sans_dns=sorted(name for name in sans_dns if name),
                sans_ip=sorted(sans_ip),
                organization=(settings.certificate_organization if settings else '') or None,
            )
        ]

    # --- Stored state --------------------------------------------------------

    @property
    def _peers(self) -> ops.Relation | None:
        """The peer relation, which is where the user list lives."""
        return self.model.get_relation(PEER)

    def _load_users(self) -> dict[str, dict[str, object]]:
        """Read the managed users from the peer application databag."""
        relation = self._peers
        if relation is None:
            return {}
        raw = relation.data[self.app].get(USERS_KEY, '')
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            logger.error('The stored user list is not valid JSON; treating it as empty.')
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _save_users(self, users: Mapping[str, dict[str, object]]) -> None:
        """Write the managed users to the peer application databag."""
        relation = self._peers
        if relation is None:
            logger.warning('No peer relation yet; the user list cannot be saved.')
            return
        relation.data[self.app][USERS_KEY] = json.dumps(users, sort_keys=True)

    def _password_for(self, username: str) -> str:
        """Return a user's password, creating one on first use.

        Passwords live in application-owned Juju secrets rather than in relation data,
        so they are never readable from `juju show-unit`.
        """
        label = SECRET_LABEL.format(username=username)
        try:
            secret = self.model.get_secret(label=label)
        except ops.SecretNotFoundError:
            password = mosquitto.generate_password()
            self.app.add_secret(
                {'username': username, 'password': password},
                label=label,
                description=f'MQTT credentials for {username}',
            )
            return password
        return secret.get_content(refresh=True)['password']

    def _set_password(self, username: str, password: str) -> None:
        """Set a user's password, without creating a pointless secret revision."""
        label = SECRET_LABEL.format(username=username)
        content = {'username': username, 'password': password}
        try:
            secret = self.model.get_secret(label=label)
        except ops.SecretNotFoundError:
            self.app.add_secret(content, label=label)
            return
        # Every `set_content` makes a revision, whether or not anything changed, and
        # every revision is another secret-changed event for every observer.
        if secret.peek_content() != content:
            secret.set_content(content)

    def _forget_password(self, username: str) -> None:
        """Remove a user's secret."""
        try:
            secret = self.model.get_secret(label=SECRET_LABEL.format(username=username))
        except ops.SecretNotFoundError:
            return
        secret.remove_all_revisions()

    # --- Lifecycle -----------------------------------------------------------

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install Mosquitto."""
        settings = self._config
        if settings is None:
            return
        self.unit.status = ops.MaintenanceStatus('installing Mosquitto')
        mosquitto.install(settings.install_source, settings.package_channel)
        paths = mosquitto.paths(settings.install_source)
        mosquitto.ensure_directories(paths)
        self._remember_install_source(settings.install_source)

    def _on_start(self, event: ops.StartEvent) -> None:
        """Configure and start the broker."""
        self._reconcile()

    def _on_stop(self, event: ops.StopEvent) -> None:
        """Stop the broker and the exporter."""
        mosquitto.remove_exporter()
        try:
            mosquitto.stop(self._paths())
        except mosquitto.ServiceError as e:
            logger.warning('Could not stop Mosquitto cleanly: %s', e)

    def _on_remove(self, event: ops.RemoveEvent) -> None:
        """Remove Mosquitto, leaving the data behind for the storage to carry."""
        settings = self._config
        mosquitto.apply_sysctl(enabled=False)
        mosquitto.uninstall(settings.install_source if settings else 'archive')

    def _on_upgrade(self, event: ops.UpgradeCharmEvent) -> None:
        """Reinstall as needed and reconcile after a charm upgrade."""
        settings = self._config
        if settings is not None:
            mosquitto.install(settings.install_source, settings.package_channel)
        self._reconcile()

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Re-check the broker, in case something changed it behind our back."""
        self._reconcile()

    def _on_reconcile(self, event: ops.EventBase) -> None:
        """Bring the broker into line with the charm's desired state."""
        self._reconcile()

    def _on_client_departed(self, event: mqtt.MQTTClientDepartedEvent) -> None:
        """Remove the user that belonged to a departing client."""
        users = self._load_users()
        owner = f'relation:{event.relation.id}'
        for username, record in list(users.items()):
            if record.get('owner') == owner:
                del users[username]
                self._forget_password(username)
        self._save_users(users)
        self._reconcile()

    # --- Reconciliation ------------------------------------------------------

    def _remember_install_source(self, source: str) -> None:
        """Record which layout the broker's state is currently in."""
        relation = self._peers
        if relation is not None and self.unit.is_leader():
            relation.data[self.app][SOURCE_KEY] = source

    def _previous_install_source(self) -> str | None:
        """The install source the broker's state was last written for."""
        relation = self._peers
        if relation is None:
            return None
        return relation.data[self.app].get(SOURCE_KEY) or None

    def _reconcile(self) -> None:
        """Render the configuration and apply whatever it needs.

        Everything funnels through here, so that the broker's state is a function of
        the charm's inputs rather than of the order events happened to arrive in.
        """
        settings = self._config
        if settings is None or self._scale_problem() or self._is_paused():
            return

        paths = mosquitto.paths(settings.install_source)
        previous = self._previous_install_source()
        if previous is not None and previous != settings.install_source:
            logger.info('Install source changed from %s to %s.', previous, settings.install_source)
            self.unit.status = ops.MaintenanceStatus('changing install source')
            mosquitto.install(settings.install_source, settings.package_channel)
            mosquitto.migrate_state(mosquitto.paths(previous), paths)
        self._remember_install_source(settings.install_source)

        version = mosquitto.get_version(settings.install_source)
        if version is None:
            logger.info('Mosquitto is not installed yet; installing.')
            mosquitto.install(settings.install_source, settings.package_channel)
            version = mosquitto.get_version(settings.install_source)
        if version is not None:
            self.unit.set_workload_version(version)

        mosquitto.ensure_directories(paths)

        users, rules = self._desired_users()
        changes = [
            mosquitto.write_password_file(paths, users),
            mosquitto.write_acl_file(paths, rules),
        ]

        material = self._tls_material()
        if material is not None:
            changes.append(mosquitto.write_tls_material(paths, material))

        listeners = mosquitto.listeners_for(
            port=settings.port,
            tls_port=settings.tls_port,
            websockets_port=settings.websockets_port,
            tls_websockets_port=settings.tls_websockets_port,
            have_certificates=material is not None,
        )
        broker = mosquitto.BrokerSettings(
            listeners=listeners,
            allow_anonymous=settings.allow_anonymous,
            tls=material,
            tls_version=settings.tls_version,
            require_client_certificate=settings.require_client_certificate,
            use_identity_as_username=settings.use_identity_as_username,
            persistence=settings.persistence,
            autosave_interval=settings.autosave_interval,
            persistent_client_expiration=settings.persistent_client_expiration,
            max_connections=settings.max_connections,
            max_inflight_messages=settings.max_inflight_messages,
            max_queued_messages=settings.max_queued_messages,
            max_queued_bytes=settings.max_queued_bytes,
            max_packet_size=settings.max_packet_size,
            max_keepalive=settings.max_keepalive,
            memory_limit=settings.memory_limit,
            retain_available=settings.retain_available,
            queue_qos0_messages=settings.queue_qos0_messages,
            log_level=settings.log_level,
            connection_messages=settings.connection_messages,
            sys_interval=settings.sys_interval,
        )
        bridge_config, bridge_change = self._bridge(settings, paths, version)
        changes.append(bridge_change)
        changes.append(
            mosquitto.write_config(
                paths,
                main=mosquitto.render_config(broker, paths),
                bridge=bridge_config,
                extra=settings.extra_config,
            )
        )

        if mosquitto.write_service_overrides(paths, file_limit=settings.file_limit()):
            changes.append(mosquitto.Change.RESTART)
        mosquitto.apply_sysctl(enabled=settings.sysctl_tuning)

        if not mosquitto.is_running(paths):
            mosquitto.start(paths)
        else:
            mosquitto.apply(paths, mosquitto.merge_changes(changes))

        self._reconcile_exporter(settings, paths, users)
        self._publish_mqtt(settings, material is not None)

    def _scale_problem(self) -> str | None:
        """Why this deployment cannot work, if it cannot.

        Mosquitto is a single broker process with no replication: two units would be
        two unrelated brokers, and a client that reconnected to the other one would
        find its session, queued messages and retained messages simply gone. That
        failure only shows up under load, long after deployment, so the charm refuses
        up front instead.
        """
        relation = self._peers
        if relation is not None and relation.units:
            return (
                f'Mosquitto does not cluster, so this charm runs one unit; '
                f'{len(relation.units) + 1} are deployed. Remove the extra units with '
                f'`juju remove-unit`, and integrate separate Mosquitto applications on '
                f'`upstream` if you need more than one broker.'
            )
        return None

    def _desired_users(
        self,
    ) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]]]:
        """Work out every MQTT user that should exist, and what it may do."""
        users: dict[str, str] = {}
        rules: dict[str, list[tuple[str, str]]] = {}

        # The charm's own users. They exist so that the health check and the exporter
        # authenticate as themselves rather than borrowing an operator's credentials,
        # and so that neither can touch anything else.
        users[mosquitto.HEALTH_USER] = self._password_for(mosquitto.HEALTH_USER)
        rules[mosquitto.HEALTH_USER] = [
            (f'{mosquitto.HEALTH_TOPIC_PREFIX}/#', mosquitto.Access.READWRITE)
        ]
        users[mosquitto.METRICS_USER] = self._password_for(mosquitto.METRICS_USER)
        # `#` does not match `$SYS`, so the monitoring grant has to name it.
        rules[mosquitto.METRICS_USER] = [('$SYS/#', mosquitto.Access.READ)]

        for username, record in self._load_users().items():
            users[username] = self._password_for(username)
            acl = record.get('acl')
            rules[username] = [
                (str(topic), str(access))
                for topic, access in (acl if isinstance(acl, list) else [])
            ]
        return users, rules

    def _tls_material(self) -> mosquitto.TLSMaterial | None:
        """The certificate, key and authority chain, once the authority has issued."""
        if not self.model.get_relation('certificates'):
            return None
        requests = self._certificate_requests()
        certificate, private_key = self.certificates.get_assigned_certificate(requests[0])
        if certificate is None or private_key is None:
            return None
        return mosquitto.TLSMaterial(
            certificate=str(certificate.certificate),
            private_key=str(private_key),
            ca=str(certificate.ca),
        )

    def _bridge(
        self, settings: config.MosquittoConfig, paths: mosquitto.Paths, version: str | None
    ) -> tuple[str | None, mosquitto.Change]:
        """Render the bridge to the upstream broker, if there is one."""
        connection = self.upstream.get_connection()
        if connection is None or not connection.endpoints:
            return None, mosquitto.Change.NONE
        if not mosquitto.supports_bridging(version):
            logger.error(
                'Refusing to configure a bridge on Mosquitto %s: versions before 2.0.19 '
                'are vulnerable to CVE-2024-3935 through bridge topic remapping. Set '
                'install-source=ppa for a current release.',
                version,
            )
            return None, mosquitto.Change.NONE

        endpoint = sorted(connection.endpoints, key=lambda e: (not e.tls, e.port))[0]
        change = mosquitto.Change.NONE
        if connection.tls_ca:
            change = mosquitto.write_bridge_ca(paths, connection.tls_ca)
        topics = tuple(
            line.strip()
            for line in settings.bridge_topics.splitlines()
            if line.strip() and not line.strip().startswith('#')
        )
        if not topics:
            logger.warning(
                'An upstream broker is integrated but bridge-topics is empty, so the '
                'bridge would carry no traffic. Set bridge-topics to forward something.'
            )
        bridge = mosquitto.Bridge(
            name=f'{self.app.name}-upstream',
            host=endpoint.host,
            port=endpoint.port,
            topics=topics,
            username=connection.username,
            password=connection.password,
            tls_ca=connection.tls_ca,
            client_id=self.unit.name.replace('/', '-'),
        )
        return mosquitto.render_bridge_config(bridge, paths), change

    def _reconcile_exporter(
        self,
        settings: config.MosquittoConfig,
        paths: mosquitto.Paths,
        users: Mapping[str, str],
    ) -> None:
        """Install or remove the metrics exporter.

        There is no point running it when nothing is collecting, or when `$SYS` is
        switched off and there would be nothing to read.
        """
        if not self.model.relations['cos-agent'] or not settings.sys_interval:
            mosquitto.remove_exporter()
            return
        if not settings.port:
            logger.warning(
                'The metrics exporter needs the plaintext listener, which is disabled; '
                'not starting it.'
            )
            mosquitto.remove_exporter()
            return
        address = self._bind_address() or '127.0.0.1'
        changed = mosquitto.install_exporter(
            EXPORTER_SOURCE,
            paths,
            broker_host='127.0.0.1',
            broker_port=settings.port,
            username=mosquitto.METRICS_USER,
            password=users[mosquitto.METRICS_USER],
            listen_address=address,
            listen_port=settings.metrics_port,
        )
        if changed or not mosquitto.is_running(paths):
            mosquitto.start_exporter()

    def _bind_address(self) -> str | None:
        """The unit's address on the MQTT binding.

        Always from the network binding, never from `private-address` in relation
        data: Juju 4.0 no longer maintains that field.
        """
        binding = self.model.get_binding('mqtt') or self.model.get_binding(PEER)
        if binding is None or binding.network.bind_address is None:
            return None
        return str(binding.network.bind_address)

    def _publish_mqtt(self, settings: config.MosquittoConfig, have_tls: bool) -> None:
        """Give every related client its credentials, endpoints and permissions."""
        if not self.unit.is_leader():
            return
        address = self._bind_address()
        if address is None:
            logger.debug('No bind address yet; not publishing MQTT endpoints.')
            return

        endpoints = []
        if settings.port:
            endpoints.append(mqtt.Endpoint(host=address, port=settings.port, tls=False))
        if have_tls and settings.tls_port:
            endpoints.append(mqtt.Endpoint(host=address, port=settings.tls_port, tls=True))
        if settings.websockets_port:
            endpoints.append(
                mqtt.Endpoint(
                    host=address, port=settings.websockets_port, tls=False, protocol='websockets'
                )
            )
        if have_tls and settings.tls_websockets_port:
            endpoints.append(
                mqtt.Endpoint(
                    host=address,
                    port=settings.tls_websockets_port,
                    tls=True,
                    protocol='websockets',
                )
            )

        ca = None
        material = self._tls_material()
        if material is not None:
            ca = material.ca

        users = self._load_users()
        changed = False
        for relation_id, request in self.mqtt.get_requests().items():
            relation = self.model.get_relation('mqtt', relation_id)
            if relation is None or relation.app is None:
                continue
            username = f'{relation.app.name}-{relation_id}'
            granted = self._grant_for(request.topic_permissions)
            record = users.get(username)
            acl = [[topic, access] for topic, access in granted]
            if record is None or record.get('acl') != acl:
                users[username] = {'owner': f'relation:{relation_id}', 'acl': acl}
                changed = True
            password = self._password_for(username)
            self.mqtt.publish_endpoints(relation, endpoints, tls_ca=ca, mqtt_version='5.0')
            self.mqtt.set_credentials(relation, username, password)
            self.mqtt.set_granted_permissions(
                relation,
                [mqtt.TopicPermission(filter=topic, access=mqtt.Access(access))
                 for topic, access in granted],
            )
        if changed:
            self._save_users(users)

    def _grant_for(
        self, requested: Sequence[mqtt.TopicPermission]
    ) -> list[tuple[str, str]]:
        """Decide what a client actually gets, given what it asked for.

        Requests are granted as made, except that nothing may reach `$SYS`: the
        statistics tree exposes every client id and every topic count on the broker,
        and a client asking for it is almost always asking by accident.
        """
        granted: list[tuple[str, str]] = []
        for permission in requested:
            if not permission.filter:
                continue
            if permission.filter.startswith('$SYS'):
                logger.warning(
                    'Refusing a request for %s: the $SYS tree is not offered over the '
                    'mqtt integration.',
                    permission.filter,
                )
                continue
            access = permission.access
            if access is mqtt.Access.UNKNOWN:
                access = mqtt.Access.READWRITE
            granted.append((permission.filter, str(access)))
        return granted

    # --- Pausing -------------------------------------------------------------

    def _is_paused(self) -> bool:
        """Whether an operator has paused the broker for maintenance."""
        relation = self._peers
        if relation is None:
            return False
        return relation.data[self.unit].get('paused') == 'true'

    def _set_paused(self, *, paused: bool) -> None:
        """Record whether the broker is paused."""
        relation = self._peers
        if relation is None:
            return
        relation.data[self.unit]['paused'] = 'true' if paused else ''

    # --- Status --------------------------------------------------------------

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report what the unit is doing, and what is wrong if anything is."""
        error = self._config_error
        if error is not None:
            event.add_status(ops.BlockedStatus(f'invalid configuration — {error}'))
            return

        scale = self._scale_problem()
        if scale is not None:
            event.add_status(ops.BlockedStatus(scale))
            return

        if self._is_paused():
            event.add_status(ops.MaintenanceStatus('paused; run the resume action to start'))
            return

        settings = self._config
        assert settings is not None  # noqa: S101 — guarded by the config error check above.
        paths = mosquitto.paths(settings.install_source)

        if mosquitto.get_version(settings.install_source) is None:
            event.add_status(ops.MaintenanceStatus('installing Mosquitto'))
            return
        if not mosquitto.is_running(paths):
            event.add_status(ops.BlockedStatus('Mosquitto is not running; check the unit log'))
            return

        if settings.allow_anonymous:
            event.add_status(
                ops.ActiveStatus('ready — anonymous access is enabled, which is not safe')
            )
        elif self.model.relations['upstream'] and not settings.bridge_topics.strip():
            event.add_status(
                ops.ActiveStatus('ready — the bridge forwards nothing until bridge-topics is set')
            )
        elif settings.tls_wanted and not self.model.get_relation('certificates'):
            event.add_status(
                ops.ActiveStatus('ready — integrate a certificate authority to enable TLS')
            )
        else:
            event.add_status(ops.ActiveStatus())

    # --- Actions -------------------------------------------------------------

    def _require_leader(self, event: ops.ActionEvent) -> bool:
        """Fail an action that changes shared state when this unit is not the leader."""
        if not self.unit.is_leader():
            event.fail('This action changes shared state, so it must run on the leader unit.')
            return False
        return True

    def _on_set_password(self, event: ops.ActionEvent) -> None:
        """Create an MQTT user, or change an existing user's password."""
        if not self._require_leader(event):
            return
        params = event.load_params(config.SetPasswordParams, errors='fail')
        users = self._load_users()
        password = params.password or mosquitto.generate_password()
        if params.username not in users:
            users[params.username] = {'owner': 'action', 'acl': []}
            self._save_users(users)
        self._set_password(params.username, password)
        self._reconcile()
        event.set_results({
            'username': params.username,
            'secret-id': self.model.get_secret(
                label=SECRET_LABEL.format(username=params.username)
            ).id,
            'generated': 'true' if params.password is None else 'false',
        })
        event.log(
            'The password is in the Juju secret above; read it with '
            '`juju show-secret --reveal <id>`.'
        )

    def _on_remove_user(self, event: ops.ActionEvent) -> None:
        """Remove an MQTT user."""
        if not self._require_leader(event):
            return
        params = event.load_params(config.RemoveUserParams, errors='fail')
        users = self._load_users()
        if params.username not in users:
            event.fail(f'There is no user called {params.username}.')
            return
        del users[params.username]
        self._save_users(users)
        self._forget_password(params.username)
        self._reconcile()
        event.set_results({'removed': params.username})

    def _on_list_users(self, event: ops.ActionEvent) -> None:
        """List the managed users and their permissions."""
        users = self._load_users()
        event.set_results({
            'users': json.dumps(
                {
                    username: {
                        'owner': record.get('owner', 'action'),
                        'acl': record.get('acl', []),
                    }
                    for username, record in sorted(users.items())
                },
                indent=2,
                sort_keys=True,
            ),
            'count': len(users),
        })

    def _on_grant(self, event: ops.ActionEvent) -> None:
        """Grant a user access to a topic filter."""
        if not self._require_leader(event):
            return
        params = event.load_params(config.GrantParams, errors='fail')
        users = self._load_users()
        record = users.get(params.username)
        if record is None:
            event.fail(
                f'There is no user called {params.username}; create one with the '
                f'set-password action first.'
            )
            return
        acl = [entry for entry in record.get('acl', []) if entry[0] != params.topic]
        acl.append([params.topic, str(params.access)])
        record['acl'] = sorted(acl)
        self._save_users(users)
        self._reconcile()
        event.set_results({'username': params.username, 'acl': json.dumps(record['acl'])})

    def _on_revoke(self, event: ops.ActionEvent) -> None:
        """Remove a topic permission from a user."""
        if not self._require_leader(event):
            return
        params = event.load_params(config.RevokeParams, errors='fail')
        users = self._load_users()
        record = users.get(params.username)
        if record is None:
            event.fail(f'There is no user called {params.username}.')
            return
        acl = [entry for entry in record.get('acl', []) if entry[0] != params.topic]
        if len(acl) == len(record.get('acl', [])):
            event.fail(f'{params.username} has no permission for {params.topic}.')
            return
        record['acl'] = acl
        self._save_users(users)
        self._reconcile()
        event.set_results({'username': params.username, 'acl': json.dumps(acl)})

    def _on_health_check(self, event: ops.ActionEvent) -> None:
        """Check that the broker is really serving MQTT."""
        params = event.load_params(config.HealthCheckParams, errors='fail')
        settings = self._config
        if settings is None:
            event.fail('The charm configuration is invalid; fix that first.')
            return
        paths = mosquitto.paths(settings.install_source)
        password = self._password_for(mosquitto.HEALTH_USER)

        results: dict[str, str] = {}
        checks: list[tuple[str, int, pathlib.Path | None]] = []
        if params.listener in (config.Listener.PLAIN, config.Listener.ALL) and settings.port:
            checks.append(('plain', settings.port, None))
        if params.listener in (config.Listener.TLS, config.Listener.ALL) and settings.tls_port:
            # The TLS listener is checked separately on purpose: a certificate renewal
            # that leaves the key unreadable breaks only this one, and a plaintext
            # check would happily report everything as fine.
            checks.append(('tls', settings.tls_port, paths.certs_dir / 'ca.crt'))
        if not checks:
            event.fail('There is no listener to check.')
            return

        failures = []
        for name, port, cafile in checks:
            host = '127.0.0.1' if cafile is None else (self._bind_address() or '127.0.0.1')
            passed, message = mosquitto.health_check(
                paths,
                host=host,
                port=port,
                username=mosquitto.HEALTH_USER,
                password=password,
                cafile=cafile,
            )
            results[name] = ('ok: ' if passed else 'failed: ') + message
            if not passed:
                failures.append(name)
        event.set_results(results)
        if failures:
            event.fail(f'The {", ".join(failures)} listener(s) failed their health check.')

    def _on_broker_stats(self, event: ops.ActionEvent) -> None:
        """Return a snapshot of the broker's `$SYS` tree."""
        settings = self._config
        if settings is None or not settings.port:
            event.fail('The plaintext listener is needed to read the $SYS tree.')
            return
        snapshot = mosquitto.sys_snapshot(
            mosquitto.paths(settings.install_source),
            host='127.0.0.1',
            port=settings.port,
            username=mosquitto.METRICS_USER,
            password=self._password_for(mosquitto.METRICS_USER),
        )
        if not snapshot:
            event.fail(
                'Nothing was published to $SYS. Check that sys-interval is not 0 and '
                'that the broker is running.'
            )
            return
        event.set_results({'stats': json.dumps(snapshot, indent=2, sort_keys=True)})

    def _on_create_backup(self, event: ops.ActionEvent) -> None:
        """Back up the broker's state."""
        params = event.load_params(config.CreateBackupParams, errors='fail')
        paths = self._paths()
        destination = pathlib.Path(params.path) if params.path else None
        path = mosquitto.create_backup(paths, destination)
        event.set_results({'path': str(path), 'size': path.stat().st_size})
        event.log(
            'The persistence database is written on autosave, so the copy is a point '
            'in time within the last autosave-interval seconds.'
        )

    def _on_restore_backup(self, event: ops.ActionEvent) -> None:
        """Restore the broker's state from a backup."""
        if not self._require_leader(event):
            return
        params = event.load_params(config.RestoreBackupParams, errors='fail')
        paths = self._paths()
        event.log('Stopping the broker; every client will be disconnected.')
        mosquitto.stop(paths)
        try:
            mosquitto.restore_backup(paths, pathlib.Path(params.path))
        finally:
            mosquitto.start(paths)
        event.set_results({'restored': params.path})

    def _on_force_reconfigure(self, event: ops.ActionEvent) -> None:
        """Re-render the configuration and reconcile unconditionally."""
        paths = self._paths()
        for name in (
            mosquitto.CHARM_CONFIG_FILENAME,
            mosquitto.BRIDGE_CONFIG_FILENAME,
            mosquitto.EXTRA_CONFIG_FILENAME,
        ):
            (paths.conf_dir / name).unlink(missing_ok=True)
        self._reconcile()
        event.set_results({'result': 'reconfigured'})

    def _on_pause(self, event: ops.ActionEvent) -> None:
        """Stop the broker for host maintenance."""
        self._set_paused(paused=True)
        mosquitto.remove_exporter()
        mosquitto.stop(self._paths())
        event.set_results({'result': 'paused'})

    def _on_resume(self, event: ops.ActionEvent) -> None:
        """Start the broker again after a pause."""
        self._set_paused(paused=False)
        self._reconcile()
        event.set_results({'result': 'resumed'})


if __name__ == '__main__':  # pragma: nocover
    ops.main(MosquittoCharm)
