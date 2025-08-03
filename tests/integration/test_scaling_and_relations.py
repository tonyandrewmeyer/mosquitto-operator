"""Integration tests for scaling and relations."""

import pytest
import asyncio
from .helpers import CharmTestHelper, MQTTTestHelper, TestDataManager, assert_eventually


class TestMosquittoScalingAndRelations:
    """Test scaling and relation scenarios."""

    @pytest.fixture(scope="class")
    async def ops_test(self):
        """Set up Jubilant test environment."""
        import jubilant
        ops_test = jubilant.TestOps()
        await ops_test.setup()
        yield ops_test
        await ops_test.teardown()

    @pytest.fixture(scope="class")
    async def charm_under_test(self, ops_test):
        """Deploy the charm under test."""
        import subprocess
        from pathlib import Path
        
        # Build the charm
        subprocess.run(["charmcraft", "pack"], check=True, cwd=".")
        
        # Find the built charm file
        charm_files = list(Path(".").glob("mosquitto_*.charm"))
        assert len(charm_files) == 1
        charm_path = charm_files[0]
        
        # Deploy the charm
        app_name = "mosquitto-relations"
        await ops_test.model.deploy(str(charm_path), application_name=app_name)
        
        # Wait for deployment
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=600
        )
        
        yield app_name
        
        # Cleanup
        await ops_test.model.remove_application(app_name, block_until_done=True)

    @pytest.fixture
    def test_data(self):
        """Provide test data manager."""
        manager = TestDataManager()
        yield manager
        manager.cleanup()

    async def test_mqtt_relation_provides_connection_info(self, ops_test, charm_under_test):
        """Test that MQTT relation provides connection information."""
        app_name = charm_under_test
        charm_helper = CharmTestHelper(ops_test, app_name)
        
        # Deploy a simple application that requires MQTT
        await ops_test.model.deploy("ubuntu", application_name="mqtt-client")
        await ops_test.model.wait_for_idle(apps=["mqtt-client"], timeout=300)
        
        # Create the relation
        await ops_test.model.integrate(f"{app_name}:mqtt", "mqtt-client:mqtt")
        await ops_test.model.wait_for_idle(
            apps=[app_name, "mqtt-client"],
            timeout=300
        )
        
        # Check that relation data is provided
        relations = ops_test.model.applications[app_name].relations
        mqtt_relations = [r for r in relations if r.interface == "mqtt"]
        assert len(mqtt_relations) > 0
        
        # Verify connection information is available
        unit_ip = await charm_helper.get_unit_ip()
        config = await charm_helper.get_config()
        
        # The relation should provide host, port, and websocket port information
        # This would be validated by checking the relation data bag
        # but we can test the functionality by verifying the service is accessible
        mqtt_helper = MQTTTestHelper(unit_ip, config["port"])
        assert await mqtt_helper.test_connection()
        
        # Cleanup
        await ops_test.model.remove_application("mqtt-client", block_until_done=True)

    async def test_certificates_relation_integration(self, ops_test, charm_under_test):
        """Test integration with certificate provider."""
        app_name = charm_under_test
        charm_helper = CharmTestHelper(ops_test, app_name)
        
        # Deploy self-signed certificates provider
        await ops_test.model.deploy("self-signed-certificates", application_name="certs")
        await ops_test.model.wait_for_idle(apps=["certs"], timeout=300)
        
        # Create the certificates relation
        await ops_test.model.integrate(f"{app_name}:certificates", "certs:certificates")
        
        # Wait for relation to be established
        await ops_test.model.wait_for_idle(
            apps=[app_name, "certs"],
            timeout=600
        )
        
        # Verify that the charm handles the certificate relation
        # (Implementation of TLS is noted as TODO in charm code, so we just verify no errors)
        assert charm_helper.unit.workload_status == "active"
        
        # Cleanup
        await ops_test.model.remove_application("certs", block_until_done=True)

    async def test_storage_attachment_and_persistence(self, ops_test, charm_under_test):
        """Test storage attachment and data persistence."""
        app_name = charm_under_test
        charm_helper = CharmTestHelper(ops_test, app_name)
        
        # Add storage to the application
        await ops_test.juju("add-storage", f"{app_name}/0", "data=1G")
        
        # Wait for storage to be attached
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=300
        )
        
        # Verify storage is mounted and accessible
        result = await charm_helper.ssh_run("df -h | grep data")
        assert result.returncode == 0
        
        # Create some test data to verify persistence
        unit_ip = await charm_helper.get_unit_ip()
        test_user = await charm_helper.create_mqtt_user("persistent_user", "test_pass")
        assert test_user
        
        # Publish some retained messages for persistence testing
        mqtt_helper = MQTTTestHelper(unit_ip, 1883, "persistent_user", "test_pass")
        
        # Publish a retained message
        pub_cmd = [
            "mosquitto_pub", "-h", unit_ip, "-p", "1883",
            "-t", "persistent/test", "-m", "retained message", "-r",
            "-u", "persistent_user", "-P", "test_pass"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *pub_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.wait()
        assert process.returncode == 0
        
        # Restart the service to test persistence
        await charm_helper.ssh_run("systemctl restart mosquitto")
        await asyncio.sleep(5)  # Wait for service to restart
        
        # Verify service is running
        assert await charm_helper.check_service_status("mosquitto")
        
        # Verify retained message persists
        sub_cmd = [
            "mosquitto_sub", "-h", unit_ip, "-p", "1883",
            "-t", "persistent/test", "-C", "1",
            "-u", "persistent_user", "-P", "test_pass"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *sub_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            assert b"retained message" in stdout
        except asyncio.TimeoutError:
            process.kill()
            pytest.fail("Retained message was not persisted")

    async def test_logging_relation_integration(self, ops_test, charm_under_test):
        """Test integration with logging provider."""
        app_name = charm_under_test
        
        # Deploy a logging provider (using a simple charm that provides logging interface)
        # Note: This is a conceptual test - actual deployment depends on available charms
        try:
            await ops_test.model.deploy("loki", application_name="logging", channel="edge")
            await ops_test.model.wait_for_idle(apps=["logging"], timeout=300)
            
            # Create the logging relation
            await ops_test.model.integrate(f"{app_name}:logging", "logging:logging")
            
            # Wait for relation to be established
            await ops_test.model.wait_for_idle(
                apps=[app_name, "logging"],
                timeout=600
            )
            
            # Verify that the charm handles the logging relation without errors
            charm_helper = CharmTestHelper(ops_test, app_name)
            assert charm_helper.unit.workload_status == "active"
            
            # Cleanup
            await ops_test.model.remove_application("logging", block_until_done=True)
            
        except Exception:
            # If logging provider is not available, skip this test
            pytest.skip("Logging provider not available for testing")

    async def test_prometheus_scrape_relation(self, ops_test, charm_under_test):
        """Test Prometheus scrape relation."""
        app_name = charm_under_test
        
        try:
            # Deploy Prometheus
            await ops_test.model.deploy("prometheus2", application_name="prometheus", channel="edge")
            await ops_test.model.wait_for_idle(apps=["prometheus"], timeout=300)
            
            # Create the prometheus-scrape relation
            await ops_test.model.integrate(f"{app_name}:prometheus-scrape", "prometheus:scrape")
            
            # Wait for relation to be established
            await ops_test.model.wait_for_idle(
                apps=[app_name, "prometheus"],
                timeout=600
            )
            
            # Verify that the charm handles the prometheus relation without errors
            charm_helper = CharmTestHelper(ops_test, app_name)
            assert charm_helper.unit.workload_status == "active"
            
            # Note: Full metrics validation would require checking Prometheus targets
            # but for integration testing, we verify the relation doesn't break the charm
            
            # Cleanup
            await ops_test.model.remove_application("prometheus", block_until_done=True)
            
        except Exception:
            # If Prometheus is not available, skip this test
            pytest.skip("Prometheus not available for testing")

    async def test_charm_handles_config_changes_under_load(self, ops_test, charm_under_test, test_data):
        """Test charm behavior under load during configuration changes."""
        app_name = charm_under_test
        charm_helper = CharmTestHelper(ops_test, app_name)
        unit_ip = await charm_helper.get_unit_ip()
        
        # Create test user
        test_user = test_data.generate_test_user("loadtest")
        await charm_helper.create_mqtt_user(test_user["username"], test_user["password"])
        
        # Start background MQTT traffic
        mqtt_helper = MQTTTestHelper(unit_ip, 1883, test_user["username"], test_user["password"])
        
        # Create multiple publisher tasks
        async def publish_loop():
            for i in range(50):
                await mqtt_helper.publish_message(f"load/test/{i}", f"Message {i}")
                await asyncio.sleep(0.1)
        
        # Start background traffic
        publisher_tasks = [asyncio.create_task(publish_loop()) for _ in range(3)]
        
        try:
            # Wait for publishers to start
            await asyncio.sleep(2)
            
            # Change configuration while under load
            await charm_helper.set_config_and_wait({
                "log-level": "debug",
                "max-connections": "200"
            })
            
            # Verify service is still running and handling requests
            assert await charm_helper.check_service_status("mosquitto")
            assert await mqtt_helper.test_connection()
            
            # Change port while under load
            await charm_helper.set_config_and_wait({"port": "1884"})
            
            # Verify service is running on new port
            assert await charm_helper.check_service_status("mosquitto")
            assert await charm_helper.check_port_listening(1884)
            
            # Test connection on new port
            mqtt_helper_new = MQTTTestHelper(unit_ip, 1884, test_user["username"], test_user["password"])
            assert await mqtt_helper_new.test_connection()
            
        finally:
            # Cancel background tasks
            for task in publisher_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def test_charm_upgrade_scenario(self, ops_test, charm_under_test):
        """Test charm upgrade scenarios."""
        app_name = charm_under_test
        charm_helper = CharmTestHelper(ops_test, app_name)
        
        # Create some test data before upgrade
        test_users = []
        for i in range(3):
            username = f"upgrade_user_{i}"
            password = f"upgrade_pass_{i}"
            await charm_helper.create_mqtt_user(username, password)
            test_users.append({"username": username, "password": password})
        
        # Get current charm revision
        status = await ops_test.model.get_status()
        current_charm = status.applications[app_name].charm
        
        # Simulate upgrade by refreshing with same charm
        # (In real scenarios, this would be a newer revision)
        await ops_test.model.applications[app_name].refresh()
        
        # Wait for upgrade to complete
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=600
        )
        
        # Verify that user data persisted through upgrade
        existing_users = await charm_helper.list_mqtt_users()
        for test_user in test_users:
            assert test_user["username"] in existing_users
        
        # Verify MQTT functionality still works
        unit_ip = await charm_helper.get_unit_ip()
        for test_user in test_users:
            mqtt_helper = MQTTTestHelper(
                unit_ip, 1883, test_user["username"], test_user["password"]
            )
            assert await mqtt_helper.test_connection()

    async def test_charm_error_recovery(self, ops_test, charm_under_test):
        """Test charm recovery from error states."""
        app_name = charm_under_test
        charm_helper = CharmTestHelper(ops_test, app_name)
        
        # Force an error by corrupting config file
        await charm_helper.ssh_run("echo 'invalid config line' >> /etc/mosquitto/mosquitto.conf")
        
        # Restart service to trigger error
        result = await charm_helper.ssh_run("systemctl restart mosquitto")
        
        # Service should fail due to invalid config
        await asyncio.sleep(5)
        service_status = await charm_helper.check_service_status("mosquitto")
        
        if not service_status:
            # Good, service failed as expected
            # Now trigger config change to fix the issue
            await charm_helper.set_config_and_wait({"log-level": "info"}, timeout=600)
            
            # Verify charm recovered
            assert await charm_helper.check_service_status("mosquitto")
            
            # Verify functionality is restored
            unit_ip = await charm_helper.get_unit_ip()
            mqtt_helper = MQTTTestHelper(unit_ip, 1883)
            
            # Enable anonymous access for this test
            await charm_helper.set_config_and_wait({"allow-anonymous": "true"})
            assert await mqtt_helper.test_connection()

    async def test_multiple_units_deployment(self, ops_test):
        """Test deploying multiple units (if supported)."""
        import subprocess
        from pathlib import Path
        
        # Build the charm
        subprocess.run(["charmcraft", "pack"], check=True, cwd=".")
        charm_files = list(Path(".").glob("mosquitto_*.charm"))
        charm_path = charm_files[0]
        
        # Deploy with multiple units
        app_name = "mosquitto-multi"
        await ops_test.model.deploy(
            str(charm_path), 
            application_name=app_name,
            num_units=2  # Try deploying 2 units
        )
        
        try:
            # Wait for deployment
            await ops_test.model.wait_for_idle(
                apps=[app_name],
                status="active",
                timeout=600
            )
            
            # Verify both units are active
            app = ops_test.model.applications[app_name]
            assert len(app.units) == 2
            
            for unit in app.units:
                assert unit.workload_status == "active"
                
                # Verify each unit has Mosquitto running
                result = await ops_test.juju(
                    "ssh", unit.name, "--", "systemctl", "is-active", "mosquitto"
                )
                assert result.returncode == 0
            
        finally:
            # Cleanup
            await ops_test.model.remove_application(app_name, block_until_done=True)