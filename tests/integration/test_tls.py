# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# pytest-jubilant gives each test file its own model through the module-scoped `juju`
# fixture, so this module can run as its own CI job.

"""TLS: certificates from a real authority, and a listener that really serves them."""

from __future__ import annotations

import logging
import pathlib

import helpers
import jubilant
import pytest

logger = logging.getLogger(__name__)

APP = 'mosquitto'
CA = 'self-signed-certificates'
UNIT = f'{APP}/0'

CA_FILE = '/etc/mosquitto/certs/ca.crt'
KEY_FILE = '/etc/mosquitto/certs/server.key'
PASSWORD = 'tls-test-password'


def unit_address(juju: jubilant.Juju) -> str:
    """The address the certificate names, which is not 127.0.0.1.

    The broker's certificate carries the unit's own addresses as subject alternative
    names, so a TLS client has to connect to one of those or the handshake fails on the
    name check.
    """
    return juju.status().apps[APP].units[UNIT].public_address


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Mosquitto and a certificate authority, integrated on `certificates`."""
    juju.deploy(charm, app=APP)
    juju.deploy(CA, channel='1/stable')
    juju.integrate(f'{APP}:certificates', CA)
    juju.wait(jubilant.all_active, timeout=900)

    juju.run(UNIT, 'set-password', {'username': 'tls-user', 'password': PASSWORD})
    juju.run(UNIT, 'grant', {'username': 'tls-user', 'topic': 'sensors/#'})
    juju.wait(jubilant.all_active)


def test_the_tls_material_is_on_disk(juju: jubilant.Juju):
    for path in (CA_FILE, KEY_FILE, '/etc/mosquitto/certs/server.crt'):
        assert 'BEGIN' in juju.exec(f'/bin/cat {path}', unit=UNIT, wait=60).stdout


def test_the_key_is_readable_by_the_mosquitto_user(juju: jubilant.Juju):
    """Since 2.0 the broker drops privileges before opening the key.

    A key that only root can read is the usual reason a broker will not start after a
    certificate renewal, and it fails at a point where the charm looks fine.
    """
    owner = juju.exec(f'/usr/bin/stat -c "%U %a" {KEY_FILE}', unit=UNIT, wait=60).stdout.split()
    assert owner[0] == 'mosquitto'
    # Readable by its owner and nobody else.
    assert owner[1] in {'600', '640'}

    readable = helpers.exec_allowed_to_fail(
        juju, UNIT, f'/bin/su -s /bin/sh -c "/usr/bin/head -c 1 {KEY_FILE}" mosquitto'
    )
    assert readable is not None, 'the broker user cannot read its own private key'


def test_the_tls_listener_really_serves(juju: jubilant.Juju):
    """A round trip over 8883, not merely a line in the configuration file."""
    # Relating the authority is not the same as it having issued: wait for the
    # listener the certificate enables, not merely for the integration to exist.
    helpers.wait_for_config(juju, UNIT, 'listener 8883')
    assert helpers.round_trip(
        juju,
        UNIT,
        'tls-user',
        PASSWORD,
        'sensors/tls',
        host=unit_address(juju),
        port=8883,
        cafile=CA_FILE,
    )


def test_the_health_check_covers_the_tls_listener(juju: jubilant.Juju):
    task = juju.run(UNIT, 'health-check')
    assert task.success
    assert task.results['tls'].startswith('ok:')


def test_the_plaintext_listener_can_be_turned_off(juju: jubilant.Juju):
    """Once TLS is in place, `port=0` is the right thing to do."""
    juju.config(APP, {'port': 0})
    juju.wait(jubilant.all_active, timeout=600)

    assert helpers.service_is_running(juju, UNIT)
    assert 'listener 1883' not in helpers.read_charm_config(juju, UNIT)
    assert helpers.round_trip(
        juju,
        UNIT,
        'tls-user',
        PASSWORD,
        'sensors/tls',
        host=unit_address(juju),
        port=8883,
        cafile=CA_FILE,
    )
    assert not helpers.round_trip(juju, UNIT, 'tls-user', PASSWORD, 'sensors/tls')

    juju.config(APP, {'port': 1883})
    juju.wait(jubilant.all_active, timeout=600)


def test_removing_the_authority_degrades_gracefully(juju: jubilant.Juju):
    """Losing the certificates must not leave the broker refusing to start.

    The TLS listener is only configured while a certificate exists, precisely so that
    this case closes the listener rather than wedging the whole broker.
    """
    juju.remove_relation(f'{APP}:certificates', CA)
    juju.wait(jubilant.all_active, timeout=600)

    assert helpers.service_is_running(juju, UNIT)
    assert 'listener 8883' not in helpers.read_charm_config(juju, UNIT)
    assert helpers.round_trip(juju, UNIT, 'tls-user', PASSWORD, 'sensors/plain')

    status = juju.status()
    message = status.apps[APP].units[UNIT].workload_status.message
    assert 'certificate authority' in message


def test_reintegrating_brings_tls_back(juju: jubilant.Juju):
    juju.integrate(f'{APP}:certificates', CA)
    juju.wait(jubilant.all_active, timeout=900)

    # Relating the authority is not the same as it having issued: wait for the
    # listener the certificate enables, not merely for the integration to exist.
    helpers.wait_for_config(juju, UNIT, 'listener 8883')
    assert helpers.round_trip(
        juju,
        UNIT,
        'tls-user',
        PASSWORD,
        'sensors/tls',
        host=unit_address(juju),
        port=8883,
        cafile=CA_FILE,
    )
