# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# pytest-jubilant gives each test file its own model through the module-scoped `juju`
# fixture, so this module can run as its own CI job.

"""Bridging two Mosquitto applications, which is how this charm scales.

Mosquitto does not cluster, so more than one broker means a bridge: edge to central,
or hub and spoke. The only assertion that proves a bridge works is a message published
on one broker turning up on the other, so that is what this module does.
"""

from __future__ import annotations

import logging
import pathlib
import shlex

import helpers
import jubilant
import pytest

logger = logging.getLogger(__name__)

EDGE = 'mosquitto-edge'
CENTRAL = 'mosquitto-central'
EDGE_UNIT = f'{EDGE}/0'
CENTRAL_UNIT = f'{CENTRAL}/0'

BRIDGE_CONFIG = '/etc/mosquitto/conf.d/60-charm-bridge.conf'
TOPIC = 'sensors/kitchen/temperature'
PASSWORD = 'bridge-test-password'

# The archive ships 2.0.18, and the charm refuses to configure a bridge below 2.0.19
# because of CVE-2024-3935 (a double free reachable through an outgoing bridge with
# incoming topic remapping). The PPA carries current releases.
PPA = 'ppa'


def subscribe(juju: jubilant.Juju, unit: str, topic: str, username: str, password: str) -> str:
    """Read one retained message from a broker, and return it.

    Retained messages are what make this assertion synchronous: the message is
    published on the edge before the subscriber exists, the bridge carries it across,
    and the central broker hands it to whoever subscribes next.
    """
    directory = '/tmp/charm-bridge-sub'  # noqa: S108
    command = [
        '/usr/bin/mosquitto_sub',
        '-h', '127.0.0.1',
        '-p', '1883',
        '-u', username,
        '-t', topic,
        '-C', '1',
        '-W', '20',
    ]  # fmt: skip
    script = (
        f'mkdir -p {directory} && '
        f'printf -- {shlex.quote(f"-P {password}\n")} > {directory}/mosquitto_sub && '
        f'chmod 0600 {directory}/mosquitto_sub && '
        f'XDG_CONFIG_HOME={directory} {shlex.join(command)}; '
        f'status=$?; rm -rf {directory}; exit $status'
    )
    result = helpers.exec_allowed_to_fail(juju, unit, f'/bin/sh -c {shlex.quote(script)}', wait=90)
    return '' if result is None else result.stdout.strip()


def publish(juju: jubilant.Juju, unit: str, topic: str, username: str, password: str) -> bool:
    """Publish one retained message, and say whether the broker accepted it."""
    directory = '/tmp/charm-bridge-pub'  # noqa: S108
    command = [
        '/usr/bin/mosquitto_pub',
        '-V', 'mqttv5',
        '-h', '127.0.0.1',
        '-p', '1883',
        '-u', username,
        '-t', topic,
        '-m', 'bridged',
        '-q', '1',
        '-r',
    ]  # fmt: skip
    script = (
        f'mkdir -p {directory} && '
        f'printf -- {shlex.quote(f"-P {password}\n")} > {directory}/mosquitto_pub && '
        f'chmod 0600 {directory}/mosquitto_pub && '
        f'XDG_CONFIG_HOME={directory} {shlex.join(command)} 2>&1; '
        f'status=$?; rm -rf {directory}; exit $status'
    )
    result = helpers.exec_allowed_to_fail(juju, unit, f'/bin/sh -c {shlex.quote(script)}', wait=90)
    # mosquitto_pub exits 0 even when the broker refuses the publish; MQTT 5 at least
    # makes it say so.
    return result is not None and 'Not authorized' not in result.stdout


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Two Mosquitto applications, deployed from the archive to start with."""
    juju.deploy(charm, app=EDGE, config={'bridge-topics': f'topic {TOPIC} out'})
    juju.deploy(charm, app=CENTRAL)
    juju.wait(jubilant.all_active, timeout=1800)

    juju.integrate(f'{EDGE}:upstream', f'{CENTRAL}:mqtt')
    juju.wait(jubilant.all_active, timeout=900)


def test_the_bridge_is_refused_on_the_archive_version(juju: jubilant.Juju):
    """2.0.18 is vulnerable to CVE-2024-3935 through exactly this feature."""
    version = juju.status().apps[EDGE].version
    assert version.startswith('2.0.18'), f'expected the archive build, got {version!r}'

    exists = helpers.exec_allowed_to_fail(juju, EDGE_UNIT, f'/usr/bin/test -f {BRIDGE_CONFIG}')
    assert exists is None, 'a bridge was configured on a version with a known bridge CVE'


def test_switching_to_the_ppa_configures_the_bridge(juju: jubilant.Juju):
    juju.config(EDGE, {'install-source': PPA})
    juju.config(CENTRAL, {'install-source': PPA})
    juju.wait(jubilant.all_active, timeout=1800)

    assert juju.status().apps[EDGE].version >= '2.0.19'
    bridge = juju.exec(f'/bin/cat {BRIDGE_CONFIG}', unit=EDGE_UNIT, wait=60).stdout
    assert f'connection {EDGE}-upstream' in bridge
    assert f'topic {TOPIC} out' in bridge
    # Without try_private, a message that comes back from the remote is sent straight
    # out again, and the pair echoes for ever.
    assert 'try_private true' in bridge
    assert 'cleansession false' in bridge


def test_a_message_published_on_the_edge_arrives_at_the_central(juju: jubilant.Juju):
    """The only assertion that proves a bridge, rather than proving a config file."""
    juju.run(EDGE_UNIT, 'set-password', {'username': 'sensor', 'password': PASSWORD})
    juju.run(EDGE_UNIT, 'grant', {'username': 'sensor', 'topic': 'sensors/#'})
    juju.run(CENTRAL_UNIT, 'set-password', {'username': 'reader', 'password': PASSWORD})
    juju.run(CENTRAL_UNIT, 'grant', {'username': 'reader', 'topic': 'sensors/#', 'access': 'read'})
    juju.wait(jubilant.all_active, timeout=600)

    assert publish(juju, EDGE_UNIT, TOPIC, 'sensor', PASSWORD)

    received = subscribe(juju, CENTRAL_UNIT, TOPIC, 'reader', PASSWORD)
    assert received == 'bridged', (
        'the message never crossed the bridge. Check the ACL the central broker '
        'granted the edge: the charm constructs its upstream requirer with no topic '
        'permissions, so the user the bridge authenticates as may have been granted '
        'nothing at all.'
    )


def test_the_edge_reports_the_bridge_in_its_status(juju: jubilant.Juju):
    """With bridge-topics set, the charm has nothing to complain about."""
    status = juju.status()
    assert status.apps[EDGE].units[EDGE_UNIT].is_active
    assert 'bridge forwards nothing' not in (
        status.apps[EDGE].units[EDGE_UNIT].workload_status.message
    )


def test_an_empty_bridge_topics_is_reported(juju: jubilant.Juju):
    """A bridge that carries nothing is a configuration mistake, not a failure."""
    juju.config(EDGE, {'bridge-topics': ''})
    juju.wait(jubilant.all_active, timeout=600)

    message = juju.status().apps[EDGE].units[EDGE_UNIT].workload_status.message
    assert 'bridge-topics' in message

    juju.config(EDGE, {'bridge-topics': f'topic {TOPIC} out'})
    juju.wait(jubilant.all_active, timeout=600)


def test_removing_the_integration_removes_the_bridge(juju: jubilant.Juju):
    juju.remove_relation(f'{EDGE}:upstream', f'{CENTRAL}:mqtt')
    juju.wait(jubilant.all_active, timeout=900)

    exists = helpers.exec_allowed_to_fail(juju, EDGE_UNIT, f'/usr/bin/test -f {BRIDGE_CONFIG}')
    assert exists is None, 'the bridge fragment outlived the integration'
    assert helpers.service_is_running(juju, EDGE_UNIT)
