"""Unit tests for the Mosquitto charm."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ops import testing
from charm import MosquittoCharm, MosquittoConfig


class TestMosquittoCharm:
    """Test cases for MosquittoCharm."""

    def test_config_validation_valid(self):
        """Test that valid configuration passes validation."""
        config = MosquittoConfig(
            port=1883,
            websockets_port=9001,
            log_level="info",
            persistence=True,
            max_connections=100,
            allow_anonymous=False,
            keepalive=60,
            message_size_limit=1024
        )
        assert config.port == 1883
        assert config.log_level == "info"

    def test_config_validation_invalid_port(self):
        """Test that invalid port raises ValueError."""
        with pytest.raises(ValueError, match="Invalid port"):
            MosquittoConfig(port=0)

    def test_config_validation_invalid_log_level(self):
        """Test that invalid log level raises ValueError."""
        with pytest.raises(ValueError, match="Invalid log level"):
            MosquittoConfig(log_level="invalid")

    def test_config_from_charm_config(self):
        """Test creating config from charm configuration."""
        charm_config = {
            "port": 1884,
            "websockets-port": 9002,
            "log-level": "debug",
            "persistence": False,
            "persistence-location": "/custom/path",
            "max-connections": 500,
            "allow-anonymous": True,
            "keepalive": 30,
            "message-size-limit": 2048,
        }
        
        config = MosquittoConfig.from_charm_config(charm_config)
        
        assert config.port == 1884
        assert config.websockets_port == 9002
        assert config.log_level == "debug"
        assert config.persistence is False
        assert config.max_connections == 500
        assert config.allow_anonymous is True

    @patch('charm.MosquittoManager')
    def test_install_event(self, mock_manager_class):
        """Test install event handling."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.install(), state)
        
        # Assert
        mock_manager.install.assert_called_once()
        assert out.unit_status.name == "maintenance"
        assert "Installing Mosquitto" in out.unit_status.message

    @patch('charm.MosquittoManager')
    def test_install_event_failure(self, mock_manager_class):
        """Test install event failure handling."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager.install.side_effect = Exception("Install failed")
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.install(), state)
        
        # Assert
        assert out.unit_status.name == "blocked"
        assert "Installation failed" in out.unit_status.message

    @patch('charm.MosquittoManager')
    def test_start_event(self, mock_manager_class):
        """Test start event handling."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State(
            config={
                "port": 1883,
                "websockets-port": 9001,
                "log-level": "info",
                "persistence": True,
                "persistence-location": "/var/lib/mosquitto",
                "max-connections": -1,
                "allow-anonymous": False,
                "keepalive": 60,
                "message-size-limit": 268435456,
            }
        )
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.start(), state)
        
        # Assert
        mock_manager.configure.assert_called_once()
        mock_manager.start.assert_called_once()
        assert out.unit_status.name == "active"
        assert "Mosquitto running" in out.unit_status.message

    @patch('charm.MosquittoManager')
    def test_config_changed_event(self, mock_manager_class):
        """Test config changed event handling."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State(
            config={
                "port": 1884,  # Changed port
                "websockets-port": 9001,
                "log-level": "debug",  # Changed log level
                "persistence": False,  # Changed persistence
                "persistence-location": "/var/lib/mosquitto",
                "max-connections": 100,  # Changed max connections
                "allow-anonymous": False,
                "keepalive": 60,
                "message-size-limit": 268435456,
            }
        )
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.config_changed(), state)
        
        # Assert
        mock_manager.configure.assert_called_once()
        mock_manager.restart.assert_called_once()
        assert out.unit_status.name == "active"

    @patch('charm.MosquittoManager')
    def test_stop_event(self, mock_manager_class):
        """Test stop event handling."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.stop(), state)
        
        # Assert
        mock_manager.stop.assert_called_once()
        assert out.unit_status.name == "maintenance"
        assert "Stopping Mosquitto" in out.unit_status.message

    @patch('charm.MosquittoManager')
    def test_get_stats_action(self, mock_manager_class):
        """Test get-stats action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_stats = {"connections": 5, "messages": 100}
        mock_manager.get_stats.return_value = mock_stats
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.action("get-stats"), state)
        
        # Assert
        mock_manager.get_stats.assert_called_once()
        assert out.results == mock_stats

    @patch('charm.MosquittoManager')
    def test_get_stats_action_failure(self, mock_manager_class):
        """Test get-stats action failure."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager.get_stats.side_effect = Exception("Stats failed")
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.action("get-stats"), state)
        
        # Assert
        assert "Failed to get stats" in str(out.failure)

    @patch('charm.MosquittoManager')
    def test_add_user_action(self, mock_manager_class):
        """Test add-user action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(
            ctx.on.action("add-user", params={"username": "testuser", "password": "testpass"}),
            state
        )
        
        # Assert
        mock_manager.add_user.assert_called_once_with("testuser", "testpass")
        assert "testuser" in out.results["message"]
        assert "added successfully" in out.results["message"]

    @patch('charm.MosquittoManager')
    def test_remove_user_action(self, mock_manager_class):
        """Test remove-user action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(
            ctx.on.action("remove-user", params={"username": "testuser"}),
            state
        )
        
        # Assert
        mock_manager.remove_user.assert_called_once_with("testuser")
        assert "testuser" in out.results["message"]
        assert "removed successfully" in out.results["message"]

    @patch('charm.MosquittoManager')
    def test_list_users_action(self, mock_manager_class):
        """Test list-users action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_users = ["user1", "user2", "user3"]
        mock_manager.list_users.return_value = mock_users
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.action("list-users"), state)
        
        # Assert
        mock_manager.list_users.assert_called_once()
        assert out.results["users"] == mock_users

    @patch('charm.MosquittoManager')
    def test_backup_data_action(self, mock_manager_class):
        """Test backup-data action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        backup_path = "/tmp/backup_20231201_120000.tar.gz"
        mock_manager.backup_data.return_value = backup_path
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.action("backup-data"), state)
        
        # Assert
        mock_manager.backup_data.assert_called_once()
        assert out.results["backup-path"] == backup_path

    @patch('charm.MosquittoManager')
    def test_restore_data_action(self, mock_manager_class):
        """Test restore-data action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        backup_path = "/tmp/backup.tar.gz"
        
        # Act
        out = ctx.run(
            ctx.on.action("restore-data", params={"backup-path": backup_path}),
            state
        )
        
        # Assert
        mock_manager.restore_data.assert_called_once_with(backup_path)
        assert "restored successfully" in out.results["message"]

    @patch('charm.MosquittoManager')
    def test_reload_config_action(self, mock_manager_class):
        """Test reload-config action."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State()
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.action("reload-config"), state)
        
        # Assert
        mock_manager.reload_config.assert_called_once()
        assert "reloaded successfully" in out.results["message"]

    @patch('charm.MosquittoManager')
    def test_mqtt_relation_joined(self, mock_manager_class):
        """Test MQTT relation joined event."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State(
            leader=True,
            config={
                "port": 1883,
                "websockets-port": 9001,
                "log-level": "info",
                "persistence": True,
                "persistence-location": "/var/lib/mosquitto",
                "max-connections": -1,
                "allow-anonymous": False,
                "keepalive": 60,
                "message-size-limit": 268435456,
            },
            relations=[
                testing.Relation("mqtt", remote_app_name="client-app")
            ]
        )
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.relation_joined("mqtt", remote_unit_id=0), state)
        
        # Assert
        mqtt_relation = out.get_relation("mqtt")
        assert mqtt_relation.local_app_data["port"] == "1883"
        assert mqtt_relation.local_app_data["websockets-port"] == "9001"

    @patch('charm.MosquittoManager')
    def test_storage_attached_event(self, mock_manager_class):
        """Test storage attached event."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State(
            config={
                "port": 1883,
                "websockets-port": 9001,
                "log-level": "info",
                "persistence": True,
                "persistence-location": "/var/lib/mosquitto",
                "max-connections": -1,
                "allow-anonymous": False,
                "keepalive": 60,
                "message-size-limit": 268435456,
            },
            storages=[
                testing.Storage("data", location="/custom/storage/path")
            ]
        )
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act
        out = ctx.run(ctx.on.storage_attached("data"), state)
        
        # Assert
        # Storage location should be updated in the manager
        mock_manager.configure.assert_called_once()

    @patch('charm.MosquittoManager')  
    def test_certificates_relation_changed(self, mock_manager_class):
        """Test certificates relation changed event."""
        # Setup
        ctx = testing.Context(MosquittoCharm)
        state = testing.State(
            relations=[
                testing.Relation("certificates", remote_app_name="cert-provider")
            ]
        )
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Act - This should not fail, but TLS support is not yet implemented  
        out = ctx.run(ctx.on.relation_changed("certificates", remote_unit_id=0), state)
        
        # Assert - Should complete without error
        assert out.unit_status.name != "error"