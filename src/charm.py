#!/usr/bin/env python3
"""Mosquitto MQTT Broker Charm."""

import logging
from dataclasses import dataclass
from typing import Dict, Any

from ops import CharmBase, main, ConfigChangedEvent, InstallEvent, StartEvent, StopEvent
from ops import ActionEvent, RelationChangedEvent, StorageAttachedEvent
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from mosquitto import MosquittoManager

logger = logging.getLogger(__name__)


@dataclass
class MosquittoConfig:
    """Configuration for Mosquitto MQTT broker."""
    
    port: int = 1883
    websockets_port: int = 9001
    log_level: str = "warning"
    persistence: bool = True
    persistence_location: str = "/var/lib/mosquitto"
    max_connections: int = -1
    allow_anonymous: bool = False
    keepalive: int = 60
    message_size_limit: int = 268435456

    def __post_init__(self):
        """Validate configuration values."""
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port: {self.port}")
        if self.websockets_port < 1 or self.websockets_port > 65535:
            raise ValueError(f"Invalid websockets port: {self.websockets_port}")
        if self.log_level not in ("debug", "info", "warning", "error"):
            raise ValueError(f"Invalid log level: {self.log_level}")
        if self.keepalive < 1:
            raise ValueError(f"Invalid keepalive: {self.keepalive}")

    @classmethod
    def from_charm_config(cls, config: Dict[str, Any]) -> "MosquittoConfig":
        """Create config from charm configuration."""
        return cls(
            port=config["port"],
            websockets_port=config["websockets-port"],
            log_level=config["log-level"],
            persistence=config["persistence"],
            persistence_location=config["persistence-location"],
            max_connections=config["max-connections"],
            allow_anonymous=config["allow-anonymous"],
            keepalive=config["keepalive"],
            message_size_limit=config["message-size-limit"],
        )


@dataclass
class AddUserActionParams:
    """Parameters for add-user action."""
    
    username: str
    password: str


@dataclass
class RemoveUserActionParams:
    """Parameters for remove-user action."""
    
    username: str


@dataclass
class RestoreDataActionParams:
    """Parameters for restore-data action."""
    
    backup_path: str


class MosquittoCharm(CharmBase):
    """Charm for Mosquitto MQTT broker."""

    def __init__(self, *args):
        super().__init__(*args)
        
        self.mosquitto = MosquittoManager()
        
        # Hook into charm events
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        
        # Storage events
        self.framework.observe(self.on.data_storage_attached, self._on_storage_attached)
        
        # Action events
        self.framework.observe(self.on.get_stats_action, self._on_get_stats_action)
        self.framework.observe(self.on.reload_config_action, self._on_reload_config_action)
        self.framework.observe(self.on.add_user_action, self._on_add_user_action)
        self.framework.observe(self.on.remove_user_action, self._on_remove_user_action)
        self.framework.observe(self.on.list_users_action, self._on_list_users_action)
        self.framework.observe(self.on.backup_data_action, self._on_backup_data_action)
        self.framework.observe(self.on.restore_data_action, self._on_restore_data_action)
        
        # Relation events
        self.framework.observe(self.on.mqtt_relation_joined, self._on_mqtt_relation_joined)
        self.framework.observe(self.on.certificates_relation_changed, self._on_certificates_relation_changed)

    def _get_mosquitto_config(self) -> MosquittoConfig:
        """Get Mosquitto configuration from charm config."""
        try:
            return MosquittoConfig.from_charm_config(self.config)
        except ValueError as e:
            logger.error(f"Invalid configuration: {e}")
            self.unit.status = BlockedStatus(f"Invalid configuration: {e}")
            raise

    def _on_install(self, event: InstallEvent) -> None:
        """Handle the install event."""
        self.unit.status = MaintenanceStatus("Installing Mosquitto")
        
        try:
            self.mosquitto.install()
            logger.info("Mosquitto installed successfully")
        except Exception as e:
            logger.error(f"Failed to install Mosquitto: {e}")
            self.unit.status = BlockedStatus(f"Installation failed: {e}")
            return

    def _on_start(self, event: StartEvent) -> None:
        """Handle the start event."""
        self.unit.status = MaintenanceStatus("Starting Mosquitto")
        
        try:
            config = self._get_mosquitto_config()
            self.mosquitto.configure(config)
            self.mosquitto.start()
            
            self.unit.status = ActiveStatus("Mosquitto running")
            logger.info("Mosquitto started successfully")
        except Exception as e:
            logger.error(f"Failed to start Mosquitto: {e}")
            self.unit.status = BlockedStatus(f"Failed to start: {e}")

    def _on_stop(self, event: StopEvent) -> None:
        """Handle the stop event."""
        self.unit.status = MaintenanceStatus("Stopping Mosquitto")
        
        try:
            self.mosquitto.stop()
            logger.info("Mosquitto stopped successfully")
        except Exception as e:
            logger.error(f"Failed to stop Mosquitto: {e}")

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handle configuration changes."""
        self.unit.status = MaintenanceStatus("Updating configuration")
        
        try:
            config = self._get_mosquitto_config()
            self.mosquitto.configure(config)
            
            if self.mosquitto.is_running():
                self.mosquitto.restart()
            
            self.unit.status = ActiveStatus("Mosquitto running")
            logger.info("Configuration updated successfully")
        except Exception as e:
            logger.error(f"Failed to update configuration: {e}")
            self.unit.status = BlockedStatus(f"Configuration error: {e}")

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handle storage attachment."""
        logger.info(f"Storage {event.storage.name} attached at {event.storage.location}")
        
        # Update persistence location if needed
        if event.storage.name == "data":
            config = self._get_mosquitto_config()
            config.persistence_location = str(event.storage.location)
            self.mosquitto.configure(config)

    def _on_get_stats_action(self, event: ActionEvent) -> None:
        """Handle get-stats action."""
        try:
            stats = self.mosquitto.get_stats()
            event.set_results(stats)
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            event.fail(f"Failed to get stats: {e}")

    def _on_reload_config_action(self, event: ActionEvent) -> None:
        """Handle reload-config action."""
        try:
            self.mosquitto.reload_config()
            event.set_results({"message": "Configuration reloaded successfully"})
        except Exception as e:
            logger.error(f"Failed to reload config: {e}")
            event.fail(f"Failed to reload config: {e}")

    def _on_add_user_action(self, event: ActionEvent) -> None:
        """Handle add-user action."""
        try:
            params = AddUserActionParams(
                username=event.params["username"],
                password=event.params["password"]
            )
            self.mosquitto.add_user(params.username, params.password)
            event.set_results({"message": f"User {params.username} added successfully"})
        except Exception as e:
            logger.error(f"Failed to add user: {e}")
            event.fail(f"Failed to add user: {e}")

    def _on_remove_user_action(self, event: ActionEvent) -> None:
        """Handle remove-user action."""
        try:
            params = RemoveUserActionParams(username=event.params["username"])
            self.mosquitto.remove_user(params.username)
            event.set_results({"message": f"User {params.username} removed successfully"})
        except Exception as e:
            logger.error(f"Failed to remove user: {e}")
            event.fail(f"Failed to remove user: {e}")

    def _on_list_users_action(self, event: ActionEvent) -> None:
        """Handle list-users action."""
        try:
            users = self.mosquitto.list_users()
            event.set_results({"users": users})
        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            event.fail(f"Failed to list users: {e}")

    def _on_backup_data_action(self, event: ActionEvent) -> None:
        """Handle backup-data action."""
        try:
            backup_path = self.mosquitto.backup_data()
            event.set_results({"backup-path": backup_path})
        except Exception as e:
            logger.error(f"Failed to backup data: {e}")
            event.fail(f"Failed to backup data: {e}")

    def _on_restore_data_action(self, event: ActionEvent) -> None:
        """Handle restore-data action."""
        try:
            params = RestoreDataActionParams(backup_path=event.params["backup-path"])
            self.mosquitto.restore_data(params.backup_path)
            event.set_results({"message": "Data restored successfully"})
        except Exception as e:
            logger.error(f"Failed to restore data: {e}")
            event.fail(f"Failed to restore data: {e}")

    def _on_mqtt_relation_joined(self, event: RelationChangedEvent) -> None:
        """Handle MQTT relation events."""
        if self.unit.is_leader():
            # Provide connection information to related applications
            event.relation.data[self.app]["host"] = str(self.model.get_binding("mqtt").network.bind_address)
            event.relation.data[self.app]["port"] = str(self.config["port"])
            event.relation.data[self.app]["websockets-port"] = str(self.config["websockets-port"])

    def _on_certificates_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle certificate relation changes."""
        # TODO: Implement TLS certificate handling
        logger.info("Certificate relation changed - TLS support to be implemented")


if __name__ == "__main__":
    main(MosquittoCharm)