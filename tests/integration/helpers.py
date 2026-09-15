# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Shared helpers for the integration tests."""

from __future__ import annotations

import logging
import secrets
import shlex

import jubilant

logger = logging.getLogger(__name__)

CHARM_CONFIG_PATH = '/etc/mosquitto/conf.d/50-charm.conf'


def read_charm_config(juju: jubilant.Juju, unit: str, path: str = CHARM_CONFIG_PATH) -> str:
    """Return the charm's rendered Mosquitto configuration from a unit."""
    return juju.exec(f'/bin/cat {path}', unit=unit, wait=60).stdout


def main_pid(juju: jubilant.Juju, unit: str, service: str = 'mosquitto') -> str:
    """Return the broker's main PID.

    Comparing this across a configuration change is how the tests tell a reload (the
    PID is unchanged, and clients stay connected) from a restart.
    """
    result = juju.exec(
        f'/bin/sh -c "systemctl show {service} -p MainPID --value"', unit=unit, wait=60
    )
    return result.stdout.strip()


def service_is_running(juju: jubilant.Juju, unit: str, service: str = 'mosquitto') -> bool:
    """Whether a systemd service is active on a unit.

    `systemctl is-active` exits non-zero for a stopped service, and `Juju.exec` raises
    on a non-zero exit, so this has to tolerate failure rather than treat it as one.
    """
    result = exec_allowed_to_fail(juju, unit, f'/bin/sh -c "systemctl is-active {service}"')
    return result is not None and result.stdout.strip() == 'active'


def round_trip(
    juju: jubilant.Juju,
    unit: str,
    username: str,
    password: str,
    topic: str,
    *,
    host: str = '127.0.0.1',
    port: int = 1883,
    cafile: str | None = None,
) -> bool:
    """Whether a client can publish to a topic and read its own message back.

    This is the only assertion that really proves the broker works: the configuration
    file changing, or a reload returning zero, proves nothing at all.

    The password is passed through `$XDG_CONFIG_HOME/mosquitto_rr` rather than on the
    command line, matching what the charm itself does.
    """
    directory = f'/tmp/charm-test-{secrets.token_hex(4)}'  # noqa: S108
    command = [
        '/usr/bin/mosquitto_rr',
        '-h', host,
        '-p', str(port),
        '-u', username,
        '-t', topic,
        '-e', topic,
        '-m', 'ping',
        '-q', '1',
        '-W', '5',
        '-i', f'test-{secrets.token_hex(4)}',
    ]  # fmt: skip
    if cafile:
        command.extend(['--cafile', cafile])
    script = (
        f'mkdir -p {directory} && '
        f'printf -- {shlex.quote(f"-P {password}\n")} > {directory}/mosquitto_rr && '
        f'chmod 0600 {directory}/mosquitto_rr && '
        f'XDG_CONFIG_HOME={directory} {shlex.join(command)}; '
        f'status=$?; rm -rf {directory}; exit $status'
    )
    result = exec_allowed_to_fail(juju, unit, f'/bin/sh -c {shlex.quote(script)}', wait=90)
    if result is None:
        logger.info(
            'Round trip on %s as %s was refused, as it may well should be.', username, topic
        )
    return result is not None


def exec_allowed_to_fail(
    juju: jubilant.Juju, unit: str, command: str, *, wait: float = 60
) -> jubilant.Task | None:
    """Run a command on a unit, returning None if it failed.

    `Juju.exec` raises on a non-zero exit, but several of these tests are asserting
    that something is *refused* — an anonymous publish, or a topic outside a user's
    ACL — so they need the failure as a value rather than an exception.
    """
    try:
        return juju.exec(command, unit=unit, wait=wait)
    except jubilant.TaskError:
        return None
