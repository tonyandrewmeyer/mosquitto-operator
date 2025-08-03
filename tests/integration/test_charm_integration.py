"""Integration tests for the Mosquitto charm using Jubilant."""

import pytest
import asyncio
import subprocess
import time
from pathlib import Path

import jubilant


class TestMosquittoCharmIntegration:
    """Integration tests for Mosquitto charm deployment and functionality."""

    @pytest.fixture(scope="class")
    async def ops_test(self):
        """Set up Jubilant test environment."""
        ops_test = jubilant.TestOps()
        await ops_test.setup()
        yield ops_test
        await ops_test.teardown()

    @pytest.fixture(scope="class")
    async def charm_under_test(self, ops_test):
        """Build and deploy the charm under test."""
        # Build the charm
        subprocess.run(["charmcraft", "pack"], check=True, cwd=".")
        
        # Find the built charm file
        charm_files = list(Path(".").glob("mosquitto_*.charm"))
        assert len(charm_files) == 1, "Expected exactly one charm file"
        charm_path = charm_files[0]
        
        # Deploy the charm
        app_name = "mosquitto-test"
        await ops_test.model.deploy(str(charm_path), application_name=app_name)
        
        # Wait for deployment to complete
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=600
        )
        
        yield app_name
        
        # Cleanup
        await ops_test.model.remove_application(app_name, block_until_done=True)

    async def test_deploy_charm_default_config(self, ops_test, charm_under_test):
        """Test charm deployment with default configuration."""
        app_name = charm_under_test
        
        # Check that the application is active
        app = ops_test.model.applications[app_name]
        assert app.status == "active"
        
        # Check that the unit is active
        unit = app.units[0]
        assert unit.workload_status == "active"
        assert "Mosquitto running" in unit.workload_status_message

    async def test_mosquitto_service_running(self, ops_test, charm_under_test):
        """Test that Mosquitto service is actually running."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Check systemctl status
        result = await ops_test.juju(
            "ssh", unit.name, "--", "systemctl", "is-active", "mosquitto"
        )
        assert result.returncode == 0
        assert "active" in result.stdout.strip()

    async def test_default_configuration(self, ops_test, charm_under_test):
        """Test that default configuration is applied correctly."""
        app_name = charm_under_test
        
        # Get current configuration
        config = await ops_test.model.applications[app_name].get_config()
        
        # Verify default values
        assert config["port"]["value"] == 1883
        assert config["websockets-port"]["value"] == 9001
        assert config["log-level"]["value"] == "warning"
        assert config["persistence"]["value"] is True
        assert config["allow-anonymous"]["value"] is False

    async def test_config_change_port(self, ops_test, charm_under_test):
        """Test changing MQTT port configuration."""
        app_name = charm_under_test
        app = ops_test.model.applications[app_name]
        
        # Change port configuration
        await app.set_config({"port": "1884"})
        
        # Wait for charm to handle config change
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=300
        )
        
        # Verify configuration was applied
        config = await app.get_config()
        assert config["port"]["value"] == 1884
        
        # Verify service is still running
        unit = app.units[0]
        result = await ops_test.juju(
            "ssh", unit.name, "--", "systemctl", "is-active", "mosquitto"
        )
        assert result.returncode == 0

    async def test_config_change_log_level(self, ops_test, charm_under_test):
        """Test changing log level configuration."""
        app_name = charm_under_test
        app = ops_test.model.applications[app_name]
        
        # Change log level to debug
        await app.set_config({"log-level": "debug"})
        
        # Wait for charm to handle config change
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=300
        )
        
        # Verify configuration was applied by checking config file
        unit = app.units[0]
        result = await ops_test.juju(
            "ssh", unit.name, "--", "grep", "log_type debug", "/etc/mosquitto/mosquitto.conf"
        )
        assert result.returncode == 0

    async def test_config_change_persistence(self, ops_test, charm_under_test):
        """Test changing persistence configuration."""
        app_name = charm_under_test
        app = ops_test.model.applications[app_name]
        
        # Disable persistence
        await app.set_config({"persistence": "false"})
        
        # Wait for charm to handle config change
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=300
        )
        
        # Verify configuration was applied
        unit = app.units[0]
        result = await ops_test.juju(
            "ssh", unit.name, "--", "grep", "persistence false", "/etc/mosquitto/mosquitto.conf"
        )
        assert result.returncode == 0

    async def test_get_stats_action(self, ops_test, charm_under_test):
        """Test the get-stats action."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Run get-stats action
        action = await unit.run_action("get-stats")
        await action.wait()
        
        # Verify action succeeded
        assert action.status == "completed"
        
        # Verify expected stats are present
        results = action.results
        assert "service_status" in results
        assert results["service_status"] == "active"
        assert "config_file" in results
        assert "log_file" in results

    async def test_add_remove_user_actions(self, ops_test, charm_under_test):
        """Test user management actions."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Add a user
        action = await unit.run_action("add-user", username="testuser", password="testpass")
        await action.wait()
        assert action.status == "completed"
        assert "testuser" in action.results["message"]
        
        # List users to verify user was added
        action = await unit.run_action("list-users")
        await action.wait()
        assert action.status == "completed"
        assert "testuser" in action.results["users"]
        
        # Remove the user
        action = await unit.run_action("remove-user", username="testuser")
        await action.wait()
        assert action.status == "completed"
        
        # Verify user was removed
        action = await unit.run_action("list-users")
        await action.wait()
        assert action.status == "completed"
        assert "testuser" not in action.results["users"]

    async def test_reload_config_action(self, ops_test, charm_under_test):
        """Test the reload-config action."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Run reload-config action
        action = await unit.run_action("reload-config")
        await action.wait()
        
        # Verify action succeeded
        assert action.status == "completed"
        assert "reloaded successfully" in action.results["message"]
        
        # Verify service is still running
        result = await ops_test.juju(
            "ssh", unit.name, "--", "systemctl", "is-active", "mosquitto"
        )
        assert result.returncode == 0

    async def test_backup_restore_actions(self, ops_test, charm_under_test):
        """Test backup and restore actions."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Add a test user first
        action = await unit.run_action("add-user", username="backuptest", password="backuppass")
        await action.wait()
        assert action.status == "completed"
        
        # Create backup
        action = await unit.run_action("backup-data")
        await action.wait()
        assert action.status == "completed"
        backup_path = action.results["backup-path"]
        assert backup_path.endswith(".tar.gz")
        
        # Remove the test user
        action = await unit.run_action("remove-user", username="backuptest")
        await action.wait()
        assert action.status == "completed"
        
        # Restore from backup
        action = await unit.run_action("restore-data", **{"backup-path": backup_path})
        await action.wait()
        assert action.status == "completed"
        
        # Verify user was restored
        action = await unit.run_action("list-users")
        await action.wait()
        assert action.status == "completed"
        assert "backuptest" in action.results["users"]

    async def test_mqtt_connectivity_default_port(self, ops_test, charm_under_test):
        """Test MQTT connectivity on default port."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Get unit IP address
        status = await ops_test.model.get_status()
        unit_ip = status.applications[app_name].units[unit.name].address
        
        # Add a test user for authentication
        action = await unit.run_action("add-user", username="testclient", password="testpass")
        await action.wait()
        assert action.status == "completed"
        
        # Test MQTT connectivity using mosquitto_pub/sub
        # Subscribe to a test topic (run in background)
        sub_cmd = [
            "mosquitto_sub", "-h", unit_ip, "-p", "1883",
            "-t", "integration/test", "-u", "testclient", "-P", "testpass",
            "-C", "1"  # Exit after receiving 1 message
        ]
        
        # Publish a test message
        pub_cmd = [
            "mosquitto_pub", "-h", unit_ip, "-p", "1883",
            "-t", "integration/test", "-m", "Hello Integration Test",
            "-u", "testclient", "-P", "testpass"
        ]
        
        # Run subscriber in background and publisher
        sub_process = await asyncio.create_subprocess_exec(
            *sub_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Give subscriber time to connect
        await asyncio.sleep(2)
        
        # Publish message
        pub_result = await asyncio.create_subprocess_exec(
            *pub_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await pub_result.wait()
        
        # Wait for subscriber to receive message
        stdout, stderr = await sub_process.communicate()
        
        # Verify message was received
        assert sub_process.returncode == 0
        assert b"Hello Integration Test" in stdout

    async def test_websocket_port_listening(self, ops_test, charm_under_test):
        """Test that WebSocket port is listening."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Check that WebSocket port 9001 is listening
        result = await ops_test.juju(
            "ssh", unit.name, "--", "netstat", "-tlnp", "|", "grep", ":9001"
        )
        assert result.returncode == 0
        assert "LISTEN" in result.stdout

    async def test_anonymous_access_disabled(self, ops_test, charm_under_test):
        """Test that anonymous access is properly disabled by default."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Get unit IP address
        status = await ops_test.model.get_status()
        unit_ip = status.applications[app_name].units[unit.name].address
        
        # Try to connect without credentials (should fail)
        pub_cmd = [
            "mosquitto_pub", "-h", unit_ip, "-p", "1883",
            "-t", "test/anonymous", "-m", "Should fail"
        ]
        
        result = await asyncio.create_subprocess_exec(
            *pub_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await result.wait()
        
        # Should fail due to authentication required
        assert result.returncode != 0

    async def test_enable_anonymous_access(self, ops_test, charm_under_test):
        """Test enabling anonymous access."""
        app_name = charm_under_test
        app = ops_test.model.applications[app_name]
        unit = app.units[0]
        
        # Enable anonymous access
        await app.set_config({"allow-anonymous": "true"})
        
        # Wait for config change
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=300
        )
        
        # Get unit IP address
        status = await ops_test.model.get_status()
        unit_ip = status.applications[app_name].units[unit.name].address
        
        # Try to connect without credentials (should succeed now)
        pub_cmd = [
            "mosquitto_pub", "-h", unit_ip, "-p", "1883",
            "-t", "test/anonymous", "-m", "Should work now"
        ]
        
        result = await asyncio.create_subprocess_exec(
            *pub_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await result.wait()
        
        # Should succeed with anonymous access enabled
        assert result.returncode == 0

    async def test_log_file_creation(self, ops_test, charm_under_test):
        """Test that log files are created and accessible."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Check that log file exists
        result = await ops_test.juju(
            "ssh", unit.name, "--", "test", "-f", "/var/log/mosquitto/mosquitto.log"
        )
        assert result.returncode == 0
        
        # Check that log file has content
        result = await ops_test.juju(
            "ssh", unit.name, "--", "wc", "-l", "/var/log/mosquitto/mosquitto.log"
        )
        assert result.returncode == 0
        line_count = int(result.stdout.strip().split()[0])
        assert line_count > 0

    async def test_persistence_data_directory(self, ops_test, charm_under_test):
        """Test that persistence data directory is created."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Check that persistence directory exists
        result = await ops_test.juju(
            "ssh", unit.name, "--", "test", "-d", "/var/lib/mosquitto"
        )
        assert result.returncode == 0
        
        # Check directory permissions (should be owned by mosquitto user)
        result = await ops_test.juju(
            "ssh", unit.name, "--", "stat", "-c", "%U", "/var/lib/mosquitto"
        )
        assert result.returncode == 0
        assert "mosquitto" in result.stdout.strip()

    async def test_config_file_syntax(self, ops_test, charm_under_test):
        """Test that generated config file has valid syntax."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Test config file with mosquitto -t (test mode)
        result = await ops_test.juju(
            "ssh", unit.name, "--", "mosquitto", "-c", "/etc/mosquitto/mosquitto.conf", "-t"
        )
        assert result.returncode == 0

    async def test_service_restart_survives_reboot(self, ops_test, charm_under_test):
        """Test that service survives machine reboot (if possible)."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Check that service is enabled (will start on boot)
        result = await ops_test.juju(
            "ssh", unit.name, "--", "systemctl", "is-enabled", "mosquitto"
        )
        assert result.returncode == 0
        assert "enabled" in result.stdout.strip()

    async def test_multiple_client_connections(self, ops_test, charm_under_test):
        """Test handling multiple concurrent client connections."""
        app_name = charm_under_test
        unit = ops_test.model.applications[app_name].units[0]
        
        # Get unit IP address
        status = await ops_test.model.get_status()
        unit_ip = status.applications[app_name].units[unit.name].address
        
        # Add test user
        action = await unit.run_action("add-user", username="multiclient", password="testpass")
        await action.wait()
        assert action.status == "completed"
        
        # Create multiple subscriber processes
        subscribers = []
        for i in range(5):
            sub_cmd = [
                "mosquitto_sub", "-h", unit_ip, "-p", "1883",
                "-t", f"multi/test/{i}", "-u", "multiclient", "-P", "testpass",
                "-C", "1"
            ]
            
            process = await asyncio.create_subprocess_exec(
                *sub_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            subscribers.append((process, i))
        
        # Give subscribers time to connect
        await asyncio.sleep(2)
        
        # Publish to each topic
        for i in range(5):
            pub_cmd = [
                "mosquitto_pub", "-h", unit_ip, "-p", "1883",
                "-t", f"multi/test/{i}", "-m", f"Message {i}",
                "-u", "multiclient", "-P", "testpass"
            ]
            
            pub_process = await asyncio.create_subprocess_exec(
                *pub_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await pub_process.wait()
            assert pub_process.returncode == 0
        
        # Wait for all subscribers to receive messages
        for process, i in subscribers:
            stdout, stderr = await process.communicate()
            assert process.returncode == 0
            assert f"Message {i}".encode() in stdout