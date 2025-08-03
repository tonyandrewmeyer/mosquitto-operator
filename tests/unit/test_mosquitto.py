"""Unit tests for the Mosquitto workload manager."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, mock_open, MagicMock
from mosquitto import MosquittoManager, MosquittoError
from charm import MosquittoConfig


class TestMosquittoManager:
    """Test cases for MosquittoManager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = MosquittoManager()

    @patch('mosquitto.subprocess.run')
    def test_install_success(self, mock_run):
        """Test successful installation."""
        mock_run.return_value = Mock(returncode=0)
        
        self.manager.install()
        
        # Verify apt commands were called
        assert mock_run.call_count >= 2
        mock_run.assert_any_call(["apt", "update"], check=True, text=True)
        mock_run.assert_any_call([
            "apt", "install", "-y", 
            "mosquitto", "mosquitto-clients"
        ], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_install_failure(self, mock_run):
        """Test installation failure."""
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(1, "apt")
        
        with pytest.raises(MosquittoError, match="Failed to install Mosquitto"):
            self.manager.install()

    def test_generate_config_content_basic(self):
        """Test generating basic configuration content."""
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
        
        content = self.manager._generate_config_content(config)
        
        assert "port 1883" in content
        assert "max_connections 100" in content
        assert "keepalive_interval 60" in content
        assert "message_size_limit 1024" in content
        assert "persistence true" in content
        assert "allow_anonymous false" in content
        assert "listener 9001" in content
        assert "protocol websockets" in content

    def test_generate_config_content_no_persistence(self):
        """Test generating config content with persistence disabled."""
        config = MosquittoConfig(persistence=False)
        
        content = self.manager._generate_config_content(config)
        
        assert "persistence false" in content
        assert "persistence_location" not in content

    def test_generate_config_content_anonymous_allowed(self):
        """Test generating config content with anonymous access."""
        config = MosquittoConfig(allow_anonymous=True)
        
        content = self.manager._generate_config_content(config)
        
        assert "allow_anonymous true" in content
        assert "password_file" not in content

    def test_generate_config_content_debug_logging(self):
        """Test generating config content with debug logging."""
        config = MosquittoConfig(log_level="debug")
        
        content = self.manager._generate_config_content(config)
        
        assert "log_type information" in content
        assert "log_type debug" in content
        assert "log_type subscribe" in content

    @patch('mosquitto.tempfile.NamedTemporaryFile')
    @patch('mosquitto.subprocess.run')
    def test_write_config_file_success(self, mock_run, mock_tempfile):
        """Test successful config file writing."""
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_config"
        mock_tempfile.return_value.__enter__.return_value = mock_file
        mock_run.return_value = Mock(returncode=0)
        
        config = MosquittoConfig()
        self.manager._write_config_file(config)
        
        mock_file.write.assert_called_once()
        mock_run.assert_any_call(["mv", "/tmp/test_config", str(self.manager.config_path)], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_start_success(self, mock_run):
        """Test successful service start."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager, 'is_running', return_value=True):
            self.manager.start()
        
        mock_run.assert_any_call(["systemctl", "enable", "mosquitto"], check=True, text=True)
        mock_run.assert_any_call(["systemctl", "start", "mosquitto"], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_start_service_fails_to_start(self, mock_run):
        """Test service fails to start after systemctl start."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager, 'is_running', return_value=False):
            with pytest.raises(MosquittoError, match="Service failed to start"):
                self.manager.start()

    @patch('mosquitto.subprocess.run')
    def test_stop_success(self, mock_run):
        """Test successful service stop."""
        mock_run.return_value = Mock(returncode=0)
        
        self.manager.stop()
        
        mock_run.assert_called_with(["systemctl", "stop", "mosquitto"], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_restart_success(self, mock_run):
        """Test successful service restart."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager, 'is_running', return_value=True):
            self.manager.restart()
        
        mock_run.assert_called_with(["systemctl", "restart", "mosquitto"], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_is_running_active(self, mock_run):
        """Test is_running when service is active."""
        mock_run.return_value = Mock(stdout="active", returncode=0)
        
        result = self.manager.is_running()
        
        assert result is True
        mock_run.assert_called_with(
            ["systemctl", "is-active", "mosquitto"],
            capture_output=True,
            check=True,
            text=True
        )

    @patch('mosquitto.subprocess.run')
    def test_is_running_inactive(self, mock_run):
        """Test is_running when service is inactive."""
        mock_run.return_value = Mock(stdout="inactive", returncode=0)
        
        result = self.manager.is_running()
        
        assert result is False

    @patch('mosquitto.subprocess.run')
    def test_is_running_command_fails(self, mock_run):
        """Test is_running when systemctl command fails."""
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(3, "systemctl")
        
        result = self.manager.is_running()
        
        assert result is False

    @patch('mosquitto.subprocess.run')
    def test_reload_config_success(self, mock_run):
        """Test successful config reload."""
        mock_run.return_value = Mock(returncode=0)
        
        self.manager.reload_config()
        
        mock_run.assert_called_with(["systemctl", "reload", "mosquitto"], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_reload_config_fallback_to_restart(self, mock_run):
        """Test config reload falls back to restart on failure."""
        from subprocess import CalledProcessError
        
        # First call (reload) fails, second call (restart) succeeds
        def side_effect(cmd, **kwargs):
            if "reload" in cmd:
                raise CalledProcessError(1, "systemctl")
            return Mock(returncode=0)
        
        mock_run.side_effect = side_effect
        
        with patch.object(self.manager, 'is_running', return_value=True):
            self.manager.reload_config()
        
        # Should have called both reload and restart
        assert mock_run.call_count >= 2

    @patch('mosquitto.subprocess.run')
    def test_get_stats(self, mock_run):
        """Test getting broker statistics."""
        mock_run.return_value = Mock(
            stdout="MainPID=1234\nActiveState=active\nLoadState=loaded",
            returncode=0
        )
        
        with patch.object(self.manager, 'is_running', return_value=True):
            with patch.object(self.manager.log_file, 'exists', return_value=True):
                with patch.object(self.manager.log_file, 'stat') as mock_stat:
                    mock_stat.return_value = Mock(st_size=1024)
                    
                    stats = self.manager.get_stats()
        
        assert stats["service_status"] == "active"
        assert stats["mainpid"] == "1234"
        assert stats["log_size_bytes"] == 1024

    @patch('mosquitto.subprocess.run')
    def test_add_user_new_password_file(self, mock_run):
        """Test adding user when password file doesn't exist."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager.password_file, 'exists', return_value=False):
            with patch.object(self.manager.password_file, 'touch') as mock_touch:
                self.manager.add_user("testuser", "testpass")
        
        mock_touch.assert_called_once()
        mock_run.assert_any_call([
            "mosquitto_passwd", "-b", str(self.manager.password_file), 
            "testuser", "testpass"
        ], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_add_user_existing_password_file(self, mock_run):
        """Test adding user when password file exists."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager.password_file, 'exists', return_value=True):
            self.manager.add_user("testuser", "testpass")
        
        mock_run.assert_called_with([
            "mosquitto_passwd", "-b", str(self.manager.password_file), 
            "testuser", "testpass"
        ], check=True, text=True)

    @patch('mosquitto.subprocess.run')
    def test_remove_user_success(self, mock_run):
        """Test successful user removal."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager.password_file, 'exists', return_value=True):
            self.manager.remove_user("testuser")
        
        mock_run.assert_called_with([
            "mosquitto_passwd", "-D", str(self.manager.password_file), "testuser"
        ], check=True, text=True)

    def test_remove_user_no_password_file(self):
        """Test removing user when password file doesn't exist."""
        with patch.object(self.manager.password_file, 'exists', return_value=False):
            with pytest.raises(MosquittoError, match="Password file does not exist"):
                self.manager.remove_user("testuser")

    def test_list_users_success(self):
        """Test successful user listing."""
        password_content = "user1:$6$hash1\nuser2:$6$hash2\nuser3:$6$hash3\n"
        
        with patch.object(self.manager.password_file, 'exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=password_content)):
                users = self.manager.list_users()
        
        assert users == ["user1", "user2", "user3"]

    def test_list_users_no_password_file(self):
        """Test listing users when password file doesn't exist."""
        with patch.object(self.manager.password_file, 'exists', return_value=False):
            users = self.manager.list_users()
        
        assert users == []

    def test_list_users_empty_file(self):
        """Test listing users with empty password file."""
        with patch.object(self.manager.password_file, 'exists', return_value=True):
            with patch('builtins.open', mock_open(read_data="")):
                users = self.manager.list_users()
        
        assert users == []

    @patch('mosquitto.os.makedirs')
    @patch('mosquitto.subprocess.run')
    def test_backup_data_success(self, mock_run, mock_makedirs):
        """Test successful data backup."""
        mock_run.return_value = Mock(returncode=0)
        
        with patch.object(self.manager.config_path, 'exists', return_value=True):
            with patch.object(self.manager.password_file, 'exists', return_value=True):
                with patch('mosquitto.Path') as mock_path:
                    mock_path.return_value.exists.return_value = True
                    
                    backup_path = self.manager.backup_data()
        
        assert backup_path.startswith("/tmp/mosquitto_backup_")
        assert backup_path.endswith(".tar.gz")
        # Should have called tar command
        tar_calls = [call for call in mock_run.call_args_list if "tar" in str(call)]
        assert len(tar_calls) > 0

    @patch('mosquitto.os.makedirs')
    @patch('mosquitto.subprocess.run')
    def test_restore_data_success(self, mock_run, mock_makedirs):
        """Test successful data restore."""
        mock_run.return_value = Mock(returncode=0)
        backup_path = "/tmp/test_backup.tar.gz"
        
        with patch('mosquitto.Path') as mock_path:
            mock_path.return_value.exists.return_value = True
            
            with patch.object(self.manager, 'is_running', side_effect=[True, False]):
                with patch.object(self.manager, 'stop') as mock_stop:
                    with patch.object(self.manager, 'start') as mock_start:
                        self.manager.restore_data(backup_path)
        
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        # Should have called tar extract command
        tar_calls = [call for call in mock_run.call_args_list if "tar" in str(call)]
        assert len(tar_calls) > 0

    def test_restore_data_backup_not_found(self):
        """Test restore with non-existent backup file."""
        backup_path = "/nonexistent/backup.tar.gz"
        
        with patch('mosquitto.Path') as mock_path:
            mock_path.return_value.exists.return_value = False
            
            with pytest.raises(MosquittoError, match="Backup file not found"):
                self.manager.restore_data(backup_path)