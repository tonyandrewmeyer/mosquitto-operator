# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# The integration tests use Jubilant and the pytest-jubilant plugin, which provides a
# module-scoped `juju` fixture (one temporary model per test file). The `charm` fixture
# is in conftest.py.

"""Core integration tests: deploying, configuring, users and actions."""

from __future__ import annotations

import json
import logging
import pathlib

import helpers
import jubilant
import pytest

logger = logging.getLogger(__name__)

APP = 'mosquitto'


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """The charm deploys and comes up active."""
    juju.deploy(charm, app=APP)
    juju.wait(jubilant.all_active, timeout=900)


def test_workload_version_is_reported(juju: jubilant.Juju):
    """Juju shows which Mosquitto is actually running."""
    version = juju.status().apps[APP].version
    assert version.startswith('2.'), f'unexpected Mosquitto version {version!r}'


def test_the_broker_is_listening(juju: jubilant.Juju):
    """The default listener is on 1883 and is not anonymous."""
    unit = f'{APP}/0'
    config = helpers.read_charm_config(juju, unit)
    assert 'listener 1883' in config
    assert 'allow_anonymous false' in config
    # Mosquitto 2.x only defaults `allow_anonymous` to false once a listener exists,
    # so both halves of this matter.
    assert 'per_listener_settings false' in config


def test_anonymous_clients_are_refused(juju: jubilant.Juju):
    """An unauthenticated client cannot publish."""
    result = helpers.exec_allowed_to_fail(
        juju,
        f'{APP}/0',
        '/usr/bin/mosquitto_pub -h 127.0.0.1 -p 1883 -t test/anon -m x -q 1',
    )
    assert result is None, 'an anonymous client was able to publish'


def test_file_descriptor_limit_is_raised(juju: jubilant.Juju):
    """The packaged unit sets no LimitNOFILE, so the charm must.

    Without this the broker inherits 1024 and stops accepting connections at about a
    thousand clients, which is the most common Mosquitto production failure.
    """
    limit = juju.exec(
        '/bin/sh -c "systemctl show mosquitto -p LimitNOFILE --value"',
        unit=f'{APP}/0',
        wait=60,
    )
    assert int(limit.stdout.strip()) >= 4096


def test_health_check_action(juju: jubilant.Juju):
    """The health check does a real MQTT round trip, not a TCP connect."""
    task = juju.run(f'{APP}/0', 'health-check')
    assert task.success
    assert task.results['plain'].startswith('ok:')


def test_broker_stats_action(juju: jubilant.Juju):
    """The $SYS tree is readable, and has the metrics we alert on."""
    task = juju.run(f'{APP}/0', 'broker-stats')
    assert task.success
    stats = json.loads(task.results['stats'])
    assert '$SYS/broker/version' in stats
    # The one that means data loss, and the one with the embedded space in its topic.
    assert '$SYS/broker/publish/messages/dropped' in stats
    assert '$SYS/broker/retained messages/count' in stats


def test_set_password_returns_a_secret_not_a_password(juju: jubilant.Juju):
    """Action results end up in the operation log, so the password must not."""
    task = juju.run(f'{APP}/0', 'set-password', {'username': 'alice'})
    assert task.success
    assert task.results['generated'] == 'true'
    assert task.results['secret-id'].startswith('secret:')
    assert 'password' not in task.results


def test_a_user_can_publish_and_subscribe(juju: jubilant.Juju):
    """End to end: create a user, grant a topic, and actually use it."""
    juju.run(f'{APP}/0', 'set-password', {'username': 'bob', 'password': 'bob-password'})
    juju.run(f'{APP}/0', 'grant', {'username': 'bob', 'topic': 'sensors/#'})
    juju.wait(jubilant.all_active)
    assert helpers.round_trip(juju, f'{APP}/0', 'bob', 'bob-password', 'sensors/kitchen')


def test_the_acl_is_enforced(juju: jubilant.Juju):
    """A user may only touch what it was granted."""
    assert not helpers.round_trip(juju, f'{APP}/0', 'bob', 'bob-password', 'control/valves'), (
        'bob published to a topic that was never granted'
    )


def test_revoke_takes_effect(juju: jubilant.Juju):
    """Revoking a grant stops working immediately, not at the next restart."""
    juju.run(f'{APP}/0', 'revoke', {'username': 'bob', 'topic': 'sensors/#'})
    juju.wait(jubilant.all_active)
    assert not helpers.round_trip(juju, f'{APP}/0', 'bob', 'bob-password', 'sensors/kitchen')


def test_list_users_never_returns_passwords(juju: jubilant.Juju):
    task = juju.run(f'{APP}/0', 'list-users')
    assert task.success
    users = json.loads(task.results['users'])
    assert set(users) == {'alice', 'bob'}
    assert 'bob-password' not in task.results['users']
    # The charm's own users are internal, and are not offered as something to manage.
    assert '_charm_health' not in users


def test_remove_user(juju: jubilant.Juju):
    juju.run(f'{APP}/0', 'remove-user', {'username': 'alice'})
    juju.wait(jubilant.all_active)
    users = json.loads(juju.run(f'{APP}/0', 'list-users').results['users'])
    assert 'alice' not in users


def test_reloadable_config_does_not_restart_the_broker(juju: jubilant.Juju):
    """The reload-versus-restart distinction is the point of the config diffing.

    A reload leaves every client connected. If the charm restarted for a change to
    `sys-interval`, every MQTT client in the deployment would see a disconnect.
    """
    unit = f'{APP}/0'
    before = helpers.main_pid(juju, unit)
    juju.config(APP, {'sys-interval': 20})
    juju.wait(jubilant.all_active)
    assert helpers.main_pid(juju, unit) == before, 'a reload-safe change restarted the broker'
    assert 'sys_interval 20' in helpers.read_charm_config(juju, unit)


def test_a_client_still_works_after_a_reload(juju: jubilant.Juju):
    """Reloading must not leave the broker unable to serve anyone.

    This is the check that catches eclipse-mosquitto#588-style problems: the file
    changed, the reload succeeded, and nothing works.
    """
    task = juju.run(f'{APP}/0', 'health-check')
    assert task.success


def test_listener_change_restarts_the_broker(juju: jubilant.Juju):
    """Changing a listener port is not reload-safe, so it must restart."""
    unit = f'{APP}/0'
    before = helpers.main_pid(juju, unit)
    juju.config(APP, {'port': 1884})
    juju.wait(jubilant.all_active)
    assert helpers.main_pid(juju, unit) != before, 'a listener change did not restart the broker'
    assert 'listener 1884' in helpers.read_charm_config(juju, unit)
    juju.config(APP, {'port': 1883})
    juju.wait(jubilant.all_active)


def test_invalid_config_blocks_with_a_useful_message(juju: jubilant.Juju):
    """Bad configuration should say which option is wrong, not stack trace."""
    juju.config(APP, {'persistent-client-expiration': 'forever'})
    status = juju.wait(jubilant.all_blocked, timeout=300)
    message = status.apps[APP].units[f'{APP}/0'].workload_status.message
    assert 'persistent-client-expiration' in message
    juju.config(APP, {'persistent-client-expiration': '14d'})
    juju.wait(jubilant.all_active)


def test_extra_config_cannot_reopen_anonymous_access(juju: jubilant.Juju):
    """Removing the charm's listener would silently re-enable anonymous access."""
    juju.config(APP, {'extra-config': 'listener 1999\nallow_anonymous true'})
    status = juju.wait(jubilant.all_blocked, timeout=300)
    message = status.apps[APP].units[f'{APP}/0'].workload_status.message
    assert 'must not set directives' in message
    juju.config(APP, {'extra-config': ''})
    juju.wait(jubilant.all_active)


def test_extra_config_is_applied(juju: jubilant.Juju):
    juju.config(APP, {'extra-config': 'max_topic_alias 12'})
    juju.wait(jubilant.all_active)
    unit = f'{APP}/0'
    extra = juju.exec('/bin/cat /etc/mosquitto/conf.d/99-charm-extra.conf', unit=unit, wait=60)
    assert 'max_topic_alias 12' in extra.stdout
    juju.config(APP, {'extra-config': ''})
    juju.wait(jubilant.all_active)


def test_a_configuration_the_broker_dies_on_is_rolled_back(juju: jubilant.Juju):
    """The charm's own validation cannot catch everything, and 2.0 has no dry run.

    `mosquitto --test-config` arrived in 2.1, so on the archive build a directive the
    broker only rejects at startup is found out the hard way: `systemctl reload`
    reports success and the broker exits. Leaving that configuration on disk is not
    neutral either — the packaged logrotate fragment SIGHUPs the broker every night,
    so a unit that was merely blocked at teatime is down by morning.
    """
    unit = f'{APP}/0'
    juju.run(unit, 'set-password', {'username': 'dave', 'password': 'dave-password'})
    juju.run(unit, 'grant', {'username': 'dave', 'topic': 'sensors/#'})
    juju.wait(jubilant.all_active)

    # Syntactically fine, and refused at startup: `persistence_location` is already
    # set by the charm, and Mosquitto refuses a directive that appears twice.
    juju.config(APP, {'extra-config': 'persistence_location /var/lib/mosquitto/'})
    status = juju.wait(jubilant.all_blocked, timeout=600)

    message = status.apps[APP].units[unit].workload_status.message
    assert 'not applied' in message or 'not running' in message
    # The broker is back on the configuration it was serving, not down with the one
    # that killed it, and a client that was working still works.
    assert helpers.service_is_running(juju, unit)
    assert helpers.round_trip(juju, unit, 'dave', 'dave-password', 'sensors/x')
    extra = helpers.exec_allowed_to_fail(
        juju, unit, '/bin/cat /etc/mosquitto/conf.d/99-charm-extra.conf'
    )
    assert extra is None or 'persistence_location' not in extra.stdout

    juju.config(APP, {'extra-config': ''})
    juju.wait(jubilant.all_active, timeout=600)
    juju.run(unit, 'remove-user', {'username': 'dave'})
    juju.wait(jubilant.all_active)


def test_backup_and_restore(juju: jubilant.Juju):
    unit = f'{APP}/0'
    backup = juju.run(unit, 'create-backup')
    assert backup.success
    path = backup.results['path']
    assert int(backup.results['size']) > 0

    juju.run(unit, 'set-password', {'username': 'carol', 'password': 'carol-password'})
    juju.wait(jubilant.all_active)

    restore = juju.run(unit, 'restore-backup', {'path': path})
    assert restore.success
    juju.wait(jubilant.all_active)
    # The restored password file predates carol, so the broker should not know her.
    assert not helpers.round_trip(juju, unit, 'carol', 'carol-password', 'sensors/x')


def test_pause_and_resume(juju: jubilant.Juju):
    unit = f'{APP}/0'
    juju.run(unit, 'pause')
    juju.wait(jubilant.all_maintenance, timeout=300)
    assert not helpers.service_is_running(juju, unit)

    juju.run(unit, 'resume')
    juju.wait(jubilant.all_active, timeout=300)
    assert helpers.service_is_running(juju, unit)


def test_force_reconfigure(juju: jubilant.Juju):
    """The escape hatch for a unit somebody edited by hand."""
    unit = f'{APP}/0'
    juju.exec('/bin/rm -f /etc/mosquitto/conf.d/50-charm.conf', unit=unit, wait=60)
    task = juju.run(unit, 'force-reconfigure')
    assert task.success
    assert 'listener 1883' in helpers.read_charm_config(juju, unit)


def test_a_second_unit_is_refused(juju: jubilant.Juju):
    """Mosquitto does not cluster, so two units would be two unrelated brokers.

    A client that reconnected to the other one would find its session, queued messages
    and retained messages gone — a failure that only shows up under load, long after
    deployment. The charm refuses up front instead.
    """
    juju.add_unit(APP)
    # Generous, because this waits on a second machine being provisioned and the charm
    # installed on it, not on the charm deciding anything.
    status = juju.wait(jubilant.any_blocked, timeout=1800)
    messages = [unit.workload_status.message for unit in status.apps[APP].units.values()]
    assert any('does not cluster' in message for message in messages)


def test_removing_the_extra_unit_returns_the_application_to_active(juju: jubilant.Juju):
    """The charm has to come back once the operator does what the status told them.

    `destroy_storage` is required: each unit has the `data` filesystem attached, and
    `juju remove-unit` on its own waits for that storage indefinitely rather than
    saying so.
    """
    juju.remove_unit(f'{APP}/1', destroy_storage=True)

    # No version skip. Juju 4.x does not clean up *peer* relation membership when a
    # unit is removed -- `relation-list` on the surviving unit still returns the
    # removed one twenty-five minutes later, and `mosquitto-peers-relation-departed`
    # never fires, which left the charm blocked for ever when it counted peers (see
    # contrib/juju-peer-departed-reproducer/). The charm takes the unit count from
    # goal state instead, which is correct on both, and reconciles it on
    # `update-status` as well as on the departed hook that 3.6 does send.
    juju.wait(jubilant.all_active, timeout=900)
