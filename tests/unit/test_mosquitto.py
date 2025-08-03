# Copyright 2025 Ubuntu
# See LICENSE file for licensing details.

"""Unit tests for mosquitto module."""

import pathlib
import subprocess
from unittest.mock import Mock, call

import pytest

import mosquitto
from charm import MosquittoConfig


class TestMosquittoInstallation:
    """Test cases for Mosquitto installation."""

    def test_install_calls_apt_commands(self, monkeypatch: pytest.MonkeyPatch):
        """Test that install function calls correct apt commands."""
        mock_run = Mock()
        mock_mkdir = Mock()
        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("pathlib.Path.mkdir", mock_mkdir)
        
        mosquitto.install()
        
        expected_calls = [
            call(["apt", "update"], check=True, capture_output=True),
            call(["apt", "install", "-y", "mosquitto", "mosquitto-clients"], check=True, capture_output=True),
            call(["chown", "-R", "mosquitto:mosquitto", str(mosquitto.MOSQUITTO_DATA_DIR)], check=True, capture_output=True),
            call(["chown", "-R", "mosquitto:mosquitto", str(mosquitto.MOSQUITTO_LOG_DIR)], check=True, capture_output=True),
        ]
        
        assert mock_run.call_args_list == expected_calls


class TestMosquittoConfiguration:
    """Test cases for Mosquitto configuration."""

    def test_configure_writes_config_file(self, monkeypatch: pytest.MonkeyPatch):
        """Test that configure function writes correct configuration."""
        mock_write_text = Mock()
        mock_run = Mock()
        monkeypatch.setattr("pathlib.Path.write_text", mock_write_text)
        monkeypatch.setattr("subprocess.run", mock_run)
        
        config = MosquittoConfig(
            port=1883,
            websockets_port=9001,
            max_connections=100,
            allow_anonymous=False,
            log_level="notice",
            persistence=True,
            message_size_limit=1024,
        )
        
        mosquitto.configure(config)
        
        # Verify config file was written
        mock_write_text.assert_called_once()
        written_config = mock_write_text.call_args[0][0]
        
        assert "port 1883" in written_config
        assert "listener 9001" in written_config
        assert "protocol websockets" in written_config
        assert "max_connections 100" in written_config
        assert "allow_anonymous false" in written_config
        assert "log_type notice" in written_config
        assert "persistence true" in written_config
        assert "message_size_limit 1024" in written_config

    def test_configure_websockets_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test configuration with WebSockets disabled."""
        mock_write_text = Mock()
        mock_run = Mock()
        monkeypatch.setattr("pathlib.Path.write_text", mock_write_text)
        monkeypatch.setattr("subprocess.run", mock_run)
        
        config = MosquittoConfig(
            port=1883,
            websockets_port=0,  # Disabled
            max_connections=-1,
            allow_anonymous=True,
            log_level="debug",
            persistence=False,
            message_size_limit=0,
        )
        
        mosquitto.configure(config)
        
        written_config = mock_write_text.call_args[0][0]
        
        assert "listener 9001" not in written_config
        assert "protocol websockets" not in written_config
        assert "allow_anonymous true" in written_config
        assert "persistence false" in written_config
        assert "max_connections" not in written_config  # Not set when -1
        assert "message_size_limit" not in written_config  # Not set when 0


class TestMosquittoServiceManagement:
    """Test cases for Mosquitto service management."""

    def test_start_enables_and_starts_service(self, monkeypatch: pytest.MonkeyPatch):
        """Test that start function enables and starts the service."""
        mock_run = Mock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "active"
        monkeypatch.setattr("subprocess.run", mock_run)
        
        mosquitto.start()
        
        expected_calls = [
            call(["systemctl", "enable", "mosquitto"], check=True, capture_output=True),
            call(["systemctl", "start", "mosquitto"], check=True, capture_output=True),
        ]
        
        # Check that enable and start were called (ignoring service check calls)
        actual_calls = [call for call in mock_run.call_args_list if "is-active" not in call[0][0]]
        assert actual_calls == expected_calls

    def test_stop_stops_service(self, monkeypatch: pytest.MonkeyPatch):
        """Test that stop function stops the service."""
        mock_run = Mock()
        monkeypatch.setattr("subprocess.run", mock_run)
        
        mosquitto.stop()
        
        mock_run.assert_called_once_with(
            ["systemctl", "stop", "mosquitto"], check=True, capture_output=True
        )

    def test_restart_restarts_service(self, monkeypatch: pytest.MonkeyPatch):
        """Test that restart function restarts the service."""
        mock_run = Mock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "active"
        monkeypatch.setattr("subprocess.run", mock_run)
        
        mosquitto.restart()
        
        # Check that restart was called (ignoring service check calls)
        restart_calls = [call for call in mock_run.call_args_list if "restart" in call[0][0]]
        assert len(restart_calls) == 1
        assert restart_calls[0] == call(["systemctl", "restart", "mosquitto"], check=True, capture_output=True)


class TestMosquittoVersion:
    """Test cases for getting Mosquitto version."""

    def test_get_version_parses_correctly(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_version parses version from help output."""
        mock_run = Mock()
        mock_run.return_value.stderr = "mosquitto version 2.0.15 running on Linux"
        monkeypatch.setattr("subprocess.run", mock_run)
        
        version = mosquitto.get_version()
        
        assert version == "2.0.15"
        mock_run.assert_called_once_with(["mosquitto", "-h"], capture_output=True, text=True)

    def test_get_version_returns_none_on_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_version returns None when command fails."""
        mock_run = Mock(side_effect=subprocess.SubprocessError())
        monkeypatch.setattr("subprocess.run", mock_run)
        
        version = mosquitto.get_version()
        
        assert version is None


class TestMosquittoStatus:
    """Test cases for getting Mosquitto status."""

    def test_get_status_returns_status_info(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_status returns comprehensive status information."""
        mock_run = Mock()
        mock_run.side_effect = [
            Mock(stdout="active", returncode=0),  # systemctl is-active
            Mock(stdout="● mosquitto.service - LSB: mosquitto MQTT v3.1/v3.1.1 Broker\n"
                       "   Loaded: loaded (/etc/init.d/mosquitto; generated)\n"
                       "   Active: active (running) since Mon 2025-08-03 15:24:42 UTC; 5min ago\n"
                       "     Docs: man:systemd-sysv-generator(8)\n"
                       "  Process: 1234 ExecStart=/etc/init.d/mosquitto start (code=exited, status=0/SUCCESS)\n"
                       "    Tasks: 1 (limit: 1234)\n"
                       "   Memory: 1.2M\n"
                       "   CGroup: /system.slice/mosquitto.service\n"
                       "           └─1234 /usr/sbin/mosquitto -c /etc/mosquitto/mosquitto.conf\n"
                       "Main PID: 1234 (mosquitto)")
        ]
        
        mock_get_version = Mock(return_value="2.0.15")
        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("mosquitto.get_version", mock_get_version)
        
        status = mosquitto.get_status()
        
        assert status["service-status"] == "active"
        assert status["version"] == "2.0.15"
        assert "active (running) since Mon 2025-08-03 15:24:42 UTC" in status["active-since"]
        assert "1234 (mosquitto)" in status["main-pid"]

    def test_get_status_handles_errors(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_status handles subprocess errors gracefully."""
        mock_run = Mock(side_effect=subprocess.SubprocessError())
        monkeypatch.setattr("subprocess.run", mock_run)
        
        status = mosquitto.get_status()
        
        assert status["service-status"] == "unknown"
        assert "error" in status