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


@dataclass
class RestartAction:
    """Action to restart Mosquitto service."""
    pass


@dataclass
class GetStatusAction:
    """Action to get Mosquitto status."""
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

    def _get_mosquitto_config(self) -> MosquittoConfig:
        """Get Mosquitto configuration from charm config."""
        return MosquittoConfig(
            port=self.config["port"],
            websockets_port=self.config["websockets-port"],
            max_connections=self.config["max-connections"],
            allow_anonymous=self.config["allow-anonymous"],
            log_level=self.config["log-level"],
            persistence=self.config["persistence"],
            message_size_limit=self.config["message-size-limit"],
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


if __name__ == "__main__":  # pragma: nocover
    ops.main(MosquittoOperatorCharm)
