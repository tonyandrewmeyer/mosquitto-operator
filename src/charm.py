#!/usr/bin/env python3
# Copyright 2025 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from dataclasses import dataclass

import ops

# A standalone module for workload-specific logic (no charming concerns):
import mosquitto

logger = logging.getLogger(__name__)


@dataclass
class MosquittoConfig:
    """Configuration for Mosquitto MQTT broker."""

    port: int
    websockets_port: int
    max_connections: int
    allow_anonymous: bool
    log_level: str
    persistence: bool
    message_size_limit: int
    tls_port: int
    tls_websockets_port: int
    # TLS configuration
    ca_cert_path: str | None = None
    server_cert_path: str | None = None
    server_key_path: str | None = None
    # Authentication configuration
    password_file_path: str | None = None
    acl_file_path: str | None = None


@dataclass
class RestartAction:
    """Action to restart Mosquitto service."""

    pass


@dataclass
class GetStatusAction:
    """Action to get Mosquitto status."""

    pass


@dataclass
class BackupAction:
    """Action to backup Mosquitto data."""

    backup_name: str | None = None


@dataclass
class RestoreAction:
    """Action to restore Mosquitto data."""

    backup_name: str


@dataclass
class GenerateClientCertAction:
    """Action to generate client certificates."""

    client_name: str
    output_path: str = "/tmp"


@dataclass
class GetMetricsStatusAction:
    """Action to get metrics status."""

    pass


class MosquittoOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.restart_action, self._on_restart_action)
        framework.observe(self.on.get_status_action, self._on_get_status_action)
        framework.observe(self.on.backup_action, self._on_backup_action)
        framework.observe(self.on.restore_action, self._on_restore_action)
        framework.observe(
            self.on.generate_client_cert_action, self._on_generate_client_cert_action
        )
        framework.observe(self.on.get_metrics_status_action, self._on_get_metrics_status_action)

        # Relation events
        framework.observe(
            self.on.certificates_relation_joined, self._on_certificates_relation_joined
        )
        framework.observe(
            self.on.certificates_relation_changed, self._on_certificates_relation_changed
        )
        framework.observe(
            self.on.certificates_relation_departed, self._on_certificates_relation_departed
        )
        framework.observe(self.on.sasl_relation_joined, self._on_sasl_relation_joined)
        framework.observe(self.on.sasl_relation_changed, self._on_sasl_relation_changed)
        framework.observe(self.on.metrics_relation_joined, self._on_metrics_relation_joined)
        framework.observe(self.on.metrics_relation_departed, self._on_metrics_relation_departed)

    def _get_mosquitto_config(self) -> MosquittoConfig:
        """Get Mosquitto configuration from charm config."""
        # Check for TLS certificates
        ca_cert_path = None
        server_cert_path = None
        server_key_path = None

        if self.model.relations.get("certificates"):
            # TLS certificates are available
            ca_cert_path = "/etc/mosquitto/certs/ca.crt"
            server_cert_path = "/etc/mosquitto/certs/server.crt"
            server_key_path = "/etc/mosquitto/certs/server.key"

        # Check for authentication configuration
        password_file_path = None
        acl_file_path = None

        if self.model.relations.get("sasl") or not self.config["allow-anonymous"]:
            password_file_path = "/etc/mosquitto/auth/passwd"
            acl_file_path = "/etc/mosquitto/auth/acl"

        return MosquittoConfig(
            port=self.config["port"],
            websockets_port=self.config["websockets-port"],
            max_connections=self.config["max-connections"],
            allow_anonymous=self.config["allow-anonymous"],
            log_level=self.config["log-level"],
            persistence=self.config["persistence"],
            message_size_limit=self.config["message-size-limit"],
            tls_port=self.config["tls-port"],
            tls_websockets_port=self.config["tls-websockets-port"],
            ca_cert_path=ca_cert_path,
            server_cert_path=server_cert_path,
            server_key_path=server_key_path,
            password_file_path=password_file_path,
            acl_file_path=acl_file_path,
        )

    def _on_install(self, event: ops.InstallEvent):
        """Install the workload on the machine."""
        self.unit.status = ops.MaintenanceStatus("installing Mosquitto")
        mosquitto.install()

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("starting Mosquitto")
        config = self._get_mosquitto_config()
        mosquitto.configure(config)
        mosquitto.start()
        version = mosquitto.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus("Mosquitto is running")

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle configuration changes."""
        self.unit.status = ops.MaintenanceStatus("updating configuration")
        config = self._get_mosquitto_config()
        mosquitto.configure(config)
        mosquitto.restart()
        self.unit.status = ops.ActiveStatus("Mosquitto is running")

    def _on_stop(self, event: ops.StopEvent):
        """Handle stop event."""
        self.unit.status = ops.MaintenanceStatus("stopping Mosquitto")
        mosquitto.stop()

    def _on_restart_action(self, event: ops.ActionEvent):
        """Handle restart action."""
        mosquitto.restart()
        event.set_results({"result": "Mosquitto restarted successfully"})

    def _on_get_status_action(self, event: ops.ActionEvent):
        """Handle get-status action."""
        status = mosquitto.get_status()
        event.set_results(status)

    def _on_backup_action(self, event: ops.ActionEvent):
        """Handle backup action."""
        backup_name = event.params.get("backup-name")
        try:
            result = mosquitto.backup(backup_name)
            event.set_results({"backup-path": result, "status": "success"})
        except Exception as e:
            event.fail(f"Backup failed: {e}")

    def _on_restore_action(self, event: ops.ActionEvent):
        """Handle restore action."""
        backup_name = event.params["backup-name"]
        try:
            mosquitto.restore(backup_name)
            event.set_results({"status": "success", "message": f"Restored from {backup_name}"})
        except Exception as e:
            event.fail(f"Restore failed: {e}")

    def _on_generate_client_cert_action(self, event: ops.ActionEvent):
        """Handle generate-client-cert action."""
        client_name = event.params["client-name"]
        output_path = event.params.get("output-path", "/tmp")
        try:
            cert_files = mosquitto.generate_client_cert(client_name, output_path)
            event.set_results(
                {
                    "status": "success",
                    "client-cert": cert_files["cert"],
                    "client-key": cert_files["key"],
                    "ca-cert": cert_files["ca"],
                }
            )
        except Exception as e:
            event.fail(f"Certificate generation failed: {e}")

    def _on_get_metrics_status_action(self, event: ops.ActionEvent):
        """Handle get-metrics-status action."""
        try:
            status = mosquitto.get_metrics_status()
            event.set_results(status)
        except Exception as e:
            event.fail(f"Failed to get metrics status: {e}")

    # Relation event handlers
    def _on_certificates_relation_joined(self, event: ops.RelationJoinedEvent):
        """Handle certificates relation joined."""
        logger.info("TLS certificates relation joined")
        # Request certificates from the CA
        self._request_certificates()

    def _on_certificates_relation_changed(self, event: ops.RelationChangedEvent):
        """Handle certificates relation changed."""
        logger.info("TLS certificates relation changed")
        # Process received certificates
        if self._process_certificates():
            # Reconfigure with TLS enabled
            self._reconfigure_with_tls()

    def _on_certificates_relation_departed(self, event: ops.RelationDepartedEvent):
        """Handle certificates relation departed."""
        logger.info("TLS certificates relation departed")
        # Remove TLS configuration and restart
        mosquitto.remove_tls_config()
        self._on_config_changed(event)

    def _on_sasl_relation_joined(self, event: ops.RelationJoinedEvent):
        """Handle SASL relation joined."""
        logger.info("SASL authentication relation joined")
        # Configure SASL authentication
        self._configure_sasl_auth()

    def _on_sasl_relation_changed(self, event: ops.RelationChangedEvent):
        """Handle SASL relation changed."""
        logger.info("SASL authentication relation changed")
        # Update SASL configuration
        self._configure_sasl_auth()

    def _on_metrics_relation_joined(self, event: ops.RelationJoinedEvent):
        """Handle metrics relation joined."""
        logger.info("Metrics relation joined")
        # Configure Prometheus metrics endpoint
        self._configure_metrics_endpoint()

    def _on_metrics_relation_departed(self, event: ops.RelationDepartedEvent):
        """Handle metrics relation departed."""
        logger.info("Metrics relation departed")
        # Remove metrics configuration if no more metrics relations
        if not self.model.relations.get("metrics"):
            mosquitto.remove_prometheus_metrics()

    # Helper methods for relation handling
    def _request_certificates(self):
        """Request TLS certificates from certificate authority."""
        # Implementation will be added with TLS support
        pass

    def _process_certificates(self) -> bool:
        """Process received TLS certificates."""
        # Implementation will be added with TLS support
        return False

    def _reconfigure_with_tls(self):
        """Reconfigure Mosquitto with TLS enabled."""
        config = self._get_mosquitto_config()
        mosquitto.configure(config)
        mosquitto.restart()
        self.unit.status = ops.ActiveStatus("Mosquitto is running with TLS")

    def _configure_sasl_auth(self):
        """Configure SASL authentication."""
        # Implementation will be added with SASL support
        pass

    def _configure_metrics_endpoint(self):
        """Configure Prometheus metrics endpoint."""
        logger.info("Configuring Prometheus metrics endpoint")

        # Set up metrics exporter
        mosquitto.setup_prometheus_metrics()

        # Update relation data for Prometheus
        if self.model.relations.get("metrics"):
            for relation in self.model.relations["metrics"]:
                relation.data[self.unit]["port"] = "9090"
                relation.data[self.unit]["path"] = "/metrics"
                relation.data[self.unit]["job"] = f"{self.model.app.name}-mosquitto"


if __name__ == "__main__":  # pragma: nocover
    ops.main(MosquittoOperatorCharm)
