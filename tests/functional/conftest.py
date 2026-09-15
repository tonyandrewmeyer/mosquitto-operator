# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Fixtures for the functional tests.

These exercise `src/mosquitto.py` against real apt, real systemd and a real broker,
with no Juju anywhere. They install packages and write to /etc and /var, so they are
skipped unless they are explicitly asked for and are running as root.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
if str(_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(_ROOT / 'src'))

import mosquitto  # noqa: E402

ENABLE_VARIABLE = 'MOSQUITTO_FUNCTIONAL_TESTS'

HEALTH_TOPIC = f'{mosquitto.HEALTH_TOPIC_PREFIX}/#'
HEALTH_PASSWORD = 'functional-test-password'
METRICS_PASSWORD = 'functional-test-metrics-password'


def skip_reason() -> str | None:
    """Why these tests cannot run here, if they cannot."""
    if os.environ.get(ENABLE_VARIABLE) != '1':
        return (
            f'The functional tests install Mosquitto from the archive and manage it '
            f'with systemd, so they only run when {ENABLE_VARIABLE}=1 is set. Run them '
            f'in a throwaway machine, not on your laptop.'
        )
    if os.geteuid() != 0:
        return 'The functional tests install packages and write to /etc, so they need root.'
    if shutil.which('systemctl') is None:
        return 'The functional tests drive a real systemd service.'
    return None


@pytest.fixture(scope='module')
def paths() -> mosquitto.Paths:
    """The Debian package layout, which is what the archive install uses."""
    return mosquitto.paths('archive')


@pytest.fixture(scope='module')
def installed(paths: mosquitto.Paths):
    """Mosquitto installed from the archive, and taken away again afterwards.

    The teardown matters: the machine these run in is also used for the integration
    tests, which deploy the charm and expect to install Mosquitto themselves.
    """
    mosquitto.install('archive')
    yield paths
    subprocess.run(['/bin/systemctl', 'stop', paths.service], check=False, capture_output=True)
    mosquitto.remove_exporter()
    mosquitto.apply_sysctl(enabled=False)
    mosquitto.uninstall('archive')
    subprocess.run(
        ['/usr/bin/apt-get', 'purge', '--yes', 'mosquitto', 'mosquitto-clients'],
        check=False,
        capture_output=True,
    )
    for directory in (
        paths.conf_dir,
        paths.certs_dir,
        paths.backup_dir,
        paths.persistence_dir,
        paths.log_file.parent,
        pathlib.Path(mosquitto.DROPIN_DIR_TEMPLATE.format(service=paths.service)),
    ):
        shutil.rmtree(directory, ignore_errors=True)
    for path in (paths.password_file, paths.acl_file):
        path.unlink(missing_ok=True)
    subprocess.run(['/bin/systemctl', 'daemon-reload'], check=False, capture_output=True)


@pytest.fixture(scope='module')
def broker(installed: mosquitto.Paths) -> mosquitto.Paths:
    """A configured, running broker with one user that may use the health topic."""
    paths = installed
    mosquitto.ensure_directories(paths)
    mosquitto.write_password_file(
        paths,
        {mosquitto.HEALTH_USER: HEALTH_PASSWORD, mosquitto.METRICS_USER: METRICS_PASSWORD},
    )
    mosquitto.write_acl_file(
        paths,
        {
            mosquitto.HEALTH_USER: [(HEALTH_TOPIC, mosquitto.Access.READWRITE)],
            # `#` does not match `$SYS`, so the monitoring grant has to name it.
            mosquitto.METRICS_USER: [('$SYS/#', mosquitto.Access.READ)],
        },
    )
    mosquitto.write_config(
        paths,
        main=mosquitto.render_config(
            mosquitto.BrokerSettings(listeners=(mosquitto.Listener(port=1883),)), paths
        ),
    )
    # Start from a stopped broker, so that a service left running by something else
    # cannot serve the tests with a configuration they did not write.
    subprocess.run(['/bin/systemctl', 'stop', paths.service], check=False, capture_output=True)
    # `write_service_overrides` is deliberately *not* called here: the drop-in it
    # writes stops the broker starting at all on 24.04 (see the xfail in
    # test_workload.py), which would take every other test with it.
    mosquitto.start(paths)
    return paths


def main_pid(paths: mosquitto.Paths) -> str:
    """The broker's main PID, straight from systemd.

    Comparing this across a change is how a reload (connections survive) is told from a
    restart (they do not).
    """
    result = subprocess.run(
        ['/bin/systemctl', 'show', paths.service, '-p', 'MainPID', '--value'],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
