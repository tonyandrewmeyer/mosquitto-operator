"""Helper utilities for Mosquitto charm integration tests."""

import asyncio
import subprocess
import tempfile
import json
from typing import Dict, Any, Optional, List
from pathlib import Path


class MQTTTestHelper:
    """Helper class for MQTT testing operations."""
    
    def __init__(self, broker_ip: str, port: int = 1883, username: Optional[str] = None, password: Optional[str] = None):
        """Initialize MQTT test helper.
        
        Args:
            broker_ip: IP address of the MQTT broker
            port: MQTT port (default: 1883)
            username: Username for authentication (optional)
            password: Password for authentication (optional)
        """
        self.broker_ip = broker_ip
        self.port = port
        self.username = username
        self.password = password

    async def publish_message(self, topic: str, message: str, qos: int = 0) -> bool:
        """Publish a message to MQTT broker.
        
        Args:
            topic: MQTT topic to publish to
            message: Message content
            qos: Quality of Service level (0, 1, or 2)
            
        Returns:
            bool: True if publish succeeded, False otherwise
        """
        cmd = [
            "mosquitto_pub",
            "-h", self.broker_ip,
            "-p", str(self.port),
            "-t", topic,
            "-m", message,
            "-q", str(qos)
        ]
        
        if self.username and self.password:
            cmd.extend(["-u", self.username, "-P", self.password])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.wait()
            return process.returncode == 0
        except Exception:
            return False

    async def subscribe_and_wait(self, topic: str, expected_message: str, timeout: int = 10) -> bool:
        """Subscribe to a topic and wait for a specific message.
        
        Args:
            topic: MQTT topic to subscribe to
            expected_message: Message to wait for
            timeout: Timeout in seconds
            
        Returns:
            bool: True if expected message was received, False otherwise
        """
        cmd = [
            "mosquitto_sub",
            "-h", self.broker_ip,
            "-p", str(self.port),
            "-t", topic,
            "-C", "1"  # Exit after receiving 1 message
        ]
        
        if self.username and self.password:
            cmd.extend(["-u", self.username, "-P", self.password])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                return expected_message.encode() in stdout
            except asyncio.TimeoutError:
                process.kill()
                return False
        except Exception:
            return False

    async def test_connection(self) -> bool:
        """Test basic connection to MQTT broker.
        
        Returns:
            bool: True if connection succeeds, False otherwise
        """
        return await self.publish_message("test/connection", "ping")

    async def test_pub_sub_flow(self, topic: str = "test/pubsub", message: str = "test message") -> bool:
        """Test complete publish-subscribe flow.
        
        Args:
            topic: Topic to use for testing
            message: Message to send
            
        Returns:
            bool: True if pub-sub flow works, False otherwise
        """
        # Start subscriber first
        subscribe_task = asyncio.create_task(
            self.subscribe_and_wait(topic, message, timeout=15)
        )
        
        # Give subscriber time to connect
        await asyncio.sleep(2)
        
        # Publish message
        publish_success = await self.publish_message(topic, message)
        if not publish_success:
            subscribe_task.cancel()
            return False
        
        # Wait for subscriber result
        try:
            return await subscribe_task
        except asyncio.CancelledError:
            return False


class CharmTestHelper:
    """Helper class for charm testing operations."""
    
    def __init__(self, ops_test, app_name: str):
        """Initialize charm test helper.
        
        Args:
            ops_test: Jubilant test object
            app_name: Name of the charm application
        """
        self.ops_test = ops_test
        self.app_name = app_name
        self.app = ops_test.model.applications[app_name]
        self.unit = self.app.units[0]

    async def get_unit_ip(self) -> str:
        """Get the IP address of the charm unit.
        
        Returns:
            str: IP address of the unit
        """
        status = await self.ops_test.model.get_status()
        return status.applications[self.app_name].units[self.unit.name].address

    async def run_action_and_wait(self, action_name: str, **params) -> Dict[str, Any]:
        """Run an action and wait for completion.
        
        Args:
            action_name: Name of the action to run
            **params: Action parameters
            
        Returns:
            Dict containing action results
            
        Raises:
            AssertionError: If action fails
        """
        action = await self.unit.run_action(action_name, **params)
        await action.wait()
        
        assert action.status == "completed", f"Action {action_name} failed: {action.message}"
        return action.results

    async def get_config(self) -> Dict[str, Any]:
        """Get current charm configuration.
        
        Returns:
            Dict containing configuration values
        """
        config = await self.app.get_config()
        return {key: value["value"] for key, value in config.items()}

    async def set_config_and_wait(self, config_changes: Dict[str, str], timeout: int = 300):
        """Set configuration and wait for charm to be ready.
        
        Args:
            config_changes: Dictionary of config key-value pairs
            timeout: Timeout in seconds
        """
        await self.app.set_config(config_changes)
        await self.ops_test.model.wait_for_idle(
            apps=[self.app_name],
            status="active",
            timeout=timeout
        )

    async def ssh_run(self, command: str) -> subprocess.CompletedProcess:
        """Run a command on the unit via SSH.
        
        Args:
            command: Command to run
            
        Returns:
            CompletedProcess object with results
        """
        return await self.ops_test.juju("ssh", self.unit.name, "--", *command.split())

    async def check_service_status(self, service_name: str = "mosquitto") -> bool:
        """Check if a systemd service is active.
        
        Args:
            service_name: Name of the service to check
            
        Returns:
            bool: True if service is active, False otherwise
        """
        try:
            result = await self.ssh_run(f"systemctl is-active {service_name}")
            return result.returncode == 0 and "active" in result.stdout.strip()
        except Exception:
            return False

    async def check_port_listening(self, port: int) -> bool:
        """Check if a port is listening.
        
        Args:
            port: Port number to check
            
        Returns:
            bool: True if port is listening, False otherwise
        """
        try:
            result = await self.ssh_run(f"netstat -tlnp | grep :{port}")
            return result.returncode == 0 and "LISTEN" in result.stdout
        except Exception:
            return False

    async def get_file_content(self, file_path: str) -> str:
        """Get content of a file on the unit.
        
        Args:
            file_path: Path to the file
            
        Returns:
            str: File content
            
        Raises:
            Exception: If file cannot be read
        """
        result = await self.ssh_run(f"cat {file_path}")
        if result.returncode != 0:
            raise Exception(f"Failed to read file {file_path}: {result.stderr}")
        return result.stdout

    async def check_file_exists(self, file_path: str) -> bool:
        """Check if a file exists on the unit.
        
        Args:
            file_path: Path to check
            
        Returns:
            bool: True if file exists, False otherwise
        """
        try:
            result = await self.ssh_run(f"test -f {file_path}")
            return result.returncode == 0
        except Exception:
            return False

    async def get_log_entries(self, log_file: str = "/var/log/mosquitto/mosquitto.log", lines: int = 50) -> List[str]:
        """Get recent log entries.
        
        Args:
            log_file: Path to log file
            lines: Number of lines to retrieve
            
        Returns:
            List of log lines
        """
        try:
            result = await self.ssh_run(f"tail -n {lines} {log_file}")
            if result.returncode == 0:
                return result.stdout.strip().split('\n')
            return []
        except Exception:
            return []

    async def create_mqtt_user(self, username: str, password: str) -> bool:
        """Create an MQTT user using charm actions.
        
        Args:
            username: Username to create
            password: Password for the user
            
        Returns:
            bool: True if user creation succeeded
        """
        try:
            await self.run_action_and_wait("add-user", username=username, password=password)
            return True
        except Exception:
            return False

    async def remove_mqtt_user(self, username: str) -> bool:
        """Remove an MQTT user using charm actions.
        
        Args:
            username: Username to remove
            
        Returns:
            bool: True if user removal succeeded
        """
        try:
            await self.run_action_and_wait("remove-user", username=username)
            return True
        except Exception:
            return False

    async def list_mqtt_users(self) -> List[str]:
        """List MQTT users using charm actions.
        
        Returns:
            List of usernames
        """
        try:
            results = await self.run_action_and_wait("list-users")
            return results.get("users", [])
        except Exception:
            return []


class TestDataManager:
    """Helper for managing test data and fixtures."""
    
    def __init__(self):
        """Initialize test data manager."""
        self.temp_files = []
        self.test_users = []

    def create_temp_file(self, content: str, suffix: str = ".tmp") -> Path:
        """Create a temporary file with content.
        
        Args:
            content: Content to write to file
            suffix: File suffix
            
        Returns:
            Path to the temporary file
        """
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False)
        temp_file.write(content)
        temp_file.close()
        
        temp_path = Path(temp_file.name)
        self.temp_files.append(temp_path)
        return temp_path

    def create_mqtt_config(self, **config_overrides) -> Dict[str, Any]:
        """Create MQTT configuration for testing.
        
        Args:
            **config_overrides: Configuration values to override
            
        Returns:
            Dict containing MQTT configuration
        """
        default_config = {
            "port": 1883,
            "websockets-port": 9001,
            "log-level": "info",
            "persistence": True,
            "max-connections": 100,
            "allow-anonymous": False,
            "keepalive": 60,
            "message-size-limit": 1048576
        }
        
        default_config.update(config_overrides)
        return default_config

    def generate_test_user(self, prefix: str = "testuser") -> Dict[str, str]:
        """Generate a test user with unique credentials.
        
        Args:
            prefix: Prefix for username
            
        Returns:
            Dict with username and password
        """
        import uuid
        user_id = str(uuid.uuid4())[:8]
        username = f"{prefix}_{user_id}"
        password = f"pass_{user_id}"
        
        user_data = {"username": username, "password": password}
        self.test_users.append(user_data)
        return user_data

    def cleanup(self):
        """Clean up temporary files and test data."""
        # Remove temporary files
        for temp_file in self.temp_files:
            try:
                temp_file.unlink()
            except FileNotFoundError:
                pass
        
        self.temp_files.clear()
        self.test_users.clear()


def wait_for_condition(condition_func, timeout: int = 30, interval: int = 1):
    """Decorator to wait for a condition to be true.
    
    Args:
        condition_func: Async function that returns bool
        timeout: Maximum time to wait in seconds
        interval: Check interval in seconds
        
    Returns:
        Decorator function
    """
    def decorator(test_func):
        async def wrapper(*args, **kwargs):
            start_time = asyncio.get_event_loop().time()
            
            while True:
                try:
                    if await condition_func():
                        break
                except Exception:
                    pass
                
                current_time = asyncio.get_event_loop().time()
                if current_time - start_time > timeout:
                    raise TimeoutError(f"Condition not met within {timeout} seconds")
                
                await asyncio.sleep(interval)
            
            return await test_func(*args, **kwargs)
        return wrapper
    return decorator


async def assert_eventually(condition_func, timeout: int = 30, message: str = "Condition not met"):
    """Assert that a condition becomes true within a timeout period.
    
    Args:
        condition_func: Async function that returns bool
        timeout: Maximum time to wait in seconds
        message: Error message if condition is not met
        
    Raises:
        AssertionError: If condition is not met within timeout
    """
    start_time = asyncio.get_event_loop().time()
    
    while True:
        try:
            if await condition_func():
                return
        except Exception:
            pass
        
        current_time = asyncio.get_event_loop().time()
        if current_time - start_time > timeout:
            raise AssertionError(f"{message} (timeout after {timeout}s)")
        
        await asyncio.sleep(1)