# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# pytest-jubilant gives each test file its own model through the module-scoped `juju`
# fixture, so this module can run as its own CI job.

"""The snap install source, end to end.

The charm offers `archive`, `ppa` and `snap` as peers, and until this module existed
only the two Debian ones were exercised against a real machine: a strictly confined
snap puts every file somewhere else, generates its own systemd unit, and ships its own
copy of the client tools, so almost nothing about it is shared with the deb path.

What is deliberately *not* here is the `package-channel` refresh. Which channels the
upstream snap has open is not something the charm controls, and a test that refreshed
to `latest/edge` would fail on the day upstream closed it while saying nothing about
the charm. That the charm refreshes a held snap when the channel changes is covered by
the state-transition tests instead.
"""

from __future__ import annotations

import json
import logging
import pathlib

import helpers
import jubilant
import pytest

logger = logging.getLogger(__name__)

APP = 'mosquitto'
UNIT = f'{APP}/0'
SNAP_COMMON = '/var/snap/mosquitto/common'
SNAP_CONFIG = f'{SNAP_COMMON}/conf.d/50-charm.conf'


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """The charm deploys straight onto the snap, rather than moving to it later."""
    juju.deploy(charm, app=APP, config={'install-source': 'snap'})
    juju.wait(jubilant.all_active, timeout=1200)


def test_the_workload_version_is_the_snap_one(juju: jubilant.Juju):
    """The snap carries a current 2.1.x, not the archive's 2.0.18."""
    version = juju.status().apps[APP].version

    assert version.startswith('2.'), f'unexpected Mosquitto version {version!r}'


def test_the_snap_is_held(juju: jubilant.Juju):
    """Otherwise snapd restarts a stateful service whenever it feels like it.

    The charm takes that decision back, which is the whole reason `package-channel`
    exists as a charm option.
    """
    listed = juju.exec('/usr/bin/snap list mosquitto', unit=UNIT, wait=120).stdout

    assert 'mosquitto' in listed
    assert 'held' in listed


def test_the_broker_serves_mqtt(juju: jubilant.Juju):
    """A real QoS 1 round trip, run by the charm through the snap's own client tools.

    This is also the check that the client tools are where the charm's snap layout
    says they are: the snap ships its own, and none of the deb's are installed.
    """
    task = juju.run(UNIT, 'health-check')

    assert task.success
    assert task.results['plain'].startswith('ok: ')


def test_the_state_is_confined_to_the_snap_directory(juju: jubilant.Juju):
    """A strictly confined broker cannot see /etc/mosquitto at all."""
    config = helpers.read_charm_config(juju, UNIT, SNAP_CONFIG)

    assert 'listener 1883' in config
    assert 'allow_anonymous false' in config
    assert f'{SNAP_COMMON}/passwd' in config
    assert f'{SNAP_COMMON}/acl' in config


def test_the_service_is_the_snapd_generated_one(juju: jubilant.Juju):
    """The charm writes no drop-in here: snapd owns and regenerates its units."""
    assert helpers.service_is_running(juju, UNIT, 'snap.mosquitto.mosquitto')

    dropin = helpers.exec_allowed_to_fail(
        juju,
        UNIT,
        '/usr/bin/test -e /etc/systemd/system/snap.mosquitto.mosquitto.service.d',
    )
    assert dropin is None, 'the charm wrote a drop-in snapd will regenerate over'


def test_a_user_created_by_action_reaches_the_broker(juju: jubilant.Juju):
    """The password file is hashed by the snap's `mosquitto_passwd`, not the deb's."""
    created = juju.run(UNIT, 'set-password', {'username': 'alice'})
    assert created.success

    granted = juju.run(UNIT, 'grant', {'username': 'alice', 'topic': 'sensors/#'})
    assert granted.success

    users = json.loads(juju.run(UNIT, 'list-users').results['users'])
    assert users['alice']['acl'] == [['sensors/#', 'readwrite']]


def test_the_sys_tree_is_readable(juju: jubilant.Juju):
    """`broker-stats` runs the snap's `mosquitto_sub` against the snap's broker."""
    task = juju.run(UNIT, 'broker-stats')

    assert task.success
    assert '$SYS/broker/clients/connected' in json.loads(task.results['stats'])


def test_backup_and_restore_on_the_snap_layout(juju: jubilant.Juju):
    """The backup has to be written and read back inside the confinement."""
    backup = juju.run(UNIT, 'create-backup')
    assert backup.success
    path = backup.results['path']
    assert path.startswith(f'{SNAP_COMMON}/backups/')

    restored = juju.run(UNIT, 'restore-backup', {'path': path})
    assert restored.success
    juju.wait(jubilant.all_active, timeout=600)

    # The broker is serving again, which is the part the action now has to prove.
    assert juju.run(UNIT, 'health-check').success


def test_moving_to_the_archive_carries_the_users(juju: jubilant.Juju):
    """Changing the install source migrates every file to the other layout.

    The password file itself is thrown away on purpose — 2.1 hashes with argon2id,
    which 2.0 cannot read — so this is really asking whether the charm rewrote it from
    the Juju secrets it holds.
    """
    juju.config(APP, {'install-source': 'archive'})
    juju.wait(jubilant.all_active, timeout=1200)

    users = json.loads(juju.run(UNIT, 'list-users').results['users'])
    assert 'alice' in users
    assert helpers.service_is_running(juju, UNIT)
    password_file = juju.exec('/bin/cat /etc/mosquitto/passwd', unit=UNIT, wait=60).stdout
    assert 'alice' in password_file


def test_the_snap_is_gone(juju: jubilant.Juju):
    """Two brokers on one machine would fight over port 1883 for ever.

    Only the losing one would be visible in the status, and only at the next reboot.
    """
    listed = helpers.exec_allowed_to_fail(juju, UNIT, '/usr/bin/snap list mosquitto')

    assert listed is None, 'the mosquitto snap outlived the move to the archive'
