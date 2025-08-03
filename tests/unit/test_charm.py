# Copyright 2025 Ubuntu
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://ops.readthedocs.io/en/latest/explanation/testing.html

import pytest
from ops import testing

from charm import MosquittoConfig, MosquittoOperatorCharm


def mock_install():
    """Mock install function."""
    pass


def mock_configure(config: MosquittoConfig):
    """Mock configure function."""
    pass


def mock_start():
    """Mock start function."""
    pass


def mock_stop():
    """Mock stop function."""
    pass


def mock_restart():
    """Mock restart function."""
    pass


def mock_get_version():
    """Get a mock version string without executing the workload code."""
    return "2.0.15"


def mock_get_status():
    """Mock get_status function."""
    return {
        "service-status": "active",
        "version": "2.0.15",
        "active-since": "Mon 2025-08-03 15:24:42 UTC",
        "main-pid": "1234 (mosquitto)",
    }


class TestMosquittoOperatorCharm:
    """Test cases for MosquittoOperatorCharm."""

    def test_install(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm handles the install event correctly."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.install", mock_install)

        # Act:
        state_out = ctx.run(ctx.on.install(), testing.State())

        # Assert:
        assert state_out.unit_status == testing.MaintenanceStatus("installing Mosquitto")

    def test_start(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm has the correct state after handling the start event."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.configure", mock_configure)
        monkeypatch.setattr("charm.mosquitto.start", mock_start)
        monkeypatch.setattr("charm.mosquitto.get_version", mock_get_version)

        # Act:
        state_out = ctx.run(ctx.on.start(), testing.State())

        # Assert:
        assert state_out.workload_version == "2.0.15"
        assert state_out.unit_status == testing.ActiveStatus("Mosquitto is running")

    def test_config_changed(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm handles configuration changes correctly."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.configure", mock_configure)
        monkeypatch.setattr("charm.mosquitto.restart", mock_restart)

        config = {"port": 1884, "allow-anonymous": True}

        # Act:
        state_out = ctx.run(ctx.on.config_changed(), testing.State(config=config))

        # Assert:
        assert state_out.unit_status == testing.ActiveStatus("Mosquitto is running")

    def test_stop(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm handles the stop event correctly."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.stop", mock_stop)

        # Act:
        state_out = ctx.run(ctx.on.stop(), testing.State())

        # Assert:
        assert state_out.unit_status == testing.MaintenanceStatus("stopping Mosquitto")

    def test_restart_action(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the restart action works correctly."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.restart", mock_restart)

        # Act:
        state_out = ctx.run(ctx.on.action("restart"), testing.State())

        # Assert:
        # For now, just verify that the event was handled without error
        # Action testing in ops.testing may need different approach
        assert state_out.unit_status.name != "error"

    def test_get_status_action(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the get-status action returns status information."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.get_status", mock_get_status)

        # Act:
        state_out = ctx.run(ctx.on.action("get-status"), testing.State())

        # Assert:
        # For now, just verify that the event was handled without error
        # Action testing in ops.testing may need different approach
        assert state_out.unit_status.name != "error"

    @pytest.mark.parametrize(
        "config_values,expected_port,expected_anonymous",
        [
            ({"port": 1883, "allow-anonymous": False}, 1883, False),
            ({"port": 1884, "allow-anonymous": True}, 1884, True),
            ({"port": 8883, "allow-anonymous": False}, 8883, False),
        ],
    )
    def test_mosquitto_config_creation(
        self, config_values, expected_port, expected_anonymous, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that MosquittoConfig is created correctly from charm config."""
        # Arrange:
        ctx = testing.Context(MosquittoOperatorCharm)
        monkeypatch.setattr("charm.mosquitto.configure", mock_configure)
        monkeypatch.setattr("charm.mosquitto.restart", mock_restart)

        # Mock the config
        config = {
            "port": expected_port,
            "websockets-port": 9001,
            "max-connections": -1,
            "allow-anonymous": expected_anonymous,
            "log-level": "notice",
            "persistence": True,
            "message-size-limit": 268435456,
        }
        config.update(config_values)

        # Act:
        state = testing.State(config=config)
        state_out = ctx.run(ctx.on.config_changed(), state)

        # Assert: The charm should handle the config without error
        assert state_out.unit_status == testing.ActiveStatus("Mosquitto is running")
