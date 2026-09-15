# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""The workload module against a real machine.

No Juju and no `ops.testing` here: this installs Mosquitto from the archive, writes the
files the charm writes, starts the real service and talks MQTT to it. It is the layer
that catches the things a fake cannot — a password file the broker will not read, a
reload that silently leaves the broker serving nothing, a key the broker cannot open
after it drops privileges.
"""

from __future__ import annotations

import grp
import io
import os
import pathlib
import pwd
import shutil
import stat
import subprocess
import tarfile
import tempfile

import conftest
import pytest

import mosquitto

_SKIP = conftest.skip_reason()
if _SKIP is not None:
    pytest.skip(_SKIP, allow_module_level=True)


def mode(path: pathlib.Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def owner(path: pathlib.Path) -> tuple[str, str]:
    info = path.stat()
    return pwd.getpwuid(info.st_uid).pw_name, grp.getgrgid(info.st_gid).gr_name


# --- Installation -------------------------------------------------------------------


def test_install_from_the_archive(installed: mosquitto.Paths):
    assert pathlib.Path('/usr/sbin/mosquitto').exists()
    # The client tools are a separate package, and the charm needs them for health
    # checks and for reading the $SYS tree.
    assert installed.passwd_tool.exists()
    assert installed.rr_tool.exists()
    assert installed.sub_tool.exists()


def test_get_version(installed: mosquitto.Paths):
    version = mosquitto.get_version('archive')

    assert version is not None
    assert version.startswith('2.')
    assert mosquitto.version_tuple(version) >= (2, 0, 0)


def test_get_version_is_none_when_not_installed(installed: mosquitto.Paths):
    """The snap is not installed here, so its binary is a convenient absent one."""
    assert mosquitto.get_version('snap') is None


def test_ensure_directories(installed: mosquitto.Paths):
    mosquitto.ensure_directories(installed)

    assert mode(installed.conf_dir) == 0o755
    # Mosquitto refuses to use a persistence directory other people can read.
    assert mode(installed.persistence_dir) == 0o700
    assert mode(installed.certs_dir) == 0o700
    assert owner(installed.persistence_dir) == (installed.user, installed.group)
    assert owner(installed.certs_dir) == (installed.user, installed.group)


# --- The password file ---------------------------------------------------------------


def test_write_password_file(installed: mosquitto.Paths):
    change = mosquitto.write_password_file(
        installed, {'alice': 'alice-password', 'bob': 'bob-password'}
    )

    assert change is mosquitto.Change.RELOAD
    contents = installed.password_file.read_text()
    # Mosquitto 2.x hashes with PBKDF2-SHA512, which it spells `$7$`. A file that is
    # still plaintext is one the broker will reject.
    assert 'alice-password' not in contents
    assert all(line.split(':', 1)[1].startswith('$7$') for line in contents.splitlines())
    # Since 2.0 the broker drops privileges before reading this, and warns (and will
    # one day refuse) if it is group or world readable.
    assert mode(installed.password_file) == 0o600
    assert owner(installed.password_file) == (installed.user, installed.group)


def test_rewriting_the_same_users_is_not_a_change(installed: mosquitto.Paths):
    """The hash is salted, so comparing the files would say "changed" every time."""
    mosquitto.write_password_file(installed, {'alice': 'alice-password'})

    assert mosquitto.write_password_file(installed, {'alice': 'alice-password'}) is (
        mosquitto.Change.NONE
    )


def test_no_temporary_password_files_are_left_behind(installed: mosquitto.Paths):
    mosquitto.write_password_file(installed, {'alice': 'alice-password'})

    assert not list(installed.password_file.parent.glob('.passwd-*'))


# --- A running broker ----------------------------------------------------------------


def test_the_broker_starts_and_answers(broker: mosquitto.Paths):
    assert mosquitto.is_running(broker)

    passed, message = mosquitto.health_check(
        broker,
        host='127.0.0.1',
        port=1883,
        username=mosquitto.HEALTH_USER,
        password=conftest.HEALTH_PASSWORD,
    )

    assert passed, message


def test_the_broker_refuses_an_unknown_user(broker: mosquitto.Paths):
    passed, _ = mosquitto.health_check(
        broker,
        host='127.0.0.1',
        port=1883,
        username='nobody',
        password='nothing',
        timeout=5,
    )

    assert not passed


def publish(topic: str, *, username: str | None = None, password: str | None = None) -> bool:
    """Whether the broker accepted one message, using the real client tool.

    `mosquitto_pub` exits 0 even when the broker refuses the publish, and under MQTT
    3.1.1 there is no reason code at all, so this asks for MQTT 5 and reads what the
    tool said rather than trusting its exit status.
    """
    command = ['/usr/bin/mosquitto_pub', '-V', 'mqttv5', '-h', '127.0.0.1', '-p', '1883']
    if username is not None:
        command += ['-u', username]
    if password is not None:
        command += ['-P', password]
    command += ['-t', topic, '-m', 'x', '-q', '1']
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
    return result.returncode == 0 and 'Not authorized' not in result.stderr


def test_the_acl_is_enforced(broker: mosquitto.Paths):
    """The health user may only touch the health topic."""
    granted = publish(
        f'{mosquitto.HEALTH_TOPIC_PREFIX}/probe',
        username=mosquitto.HEALTH_USER,
        password=conftest.HEALTH_PASSWORD,
    )
    refused = publish(
        'somewhere/else',
        username=mosquitto.HEALTH_USER,
        password=conftest.HEALTH_PASSWORD,
    )

    assert granted
    assert not refused, 'a topic outside the ACL was accepted'


def test_an_anonymous_client_is_refused(broker: mosquitto.Paths):
    assert not publish('anything')


def test_a_reload_safe_change_does_not_restart_the_broker(broker: mosquitto.Paths):
    """A restart drops every client; a reload does not. That is why this is tested.

    The broker still has to be serving afterwards: "the file changed and the reload
    returned zero" proves nothing at all.
    """
    before = conftest.main_pid(broker)
    settings = mosquitto.BrokerSettings(
        listeners=(mosquitto.Listener(port=1883),), sys_interval=17
    )

    change = mosquitto.write_config(broker, main=mosquitto.render_config(settings, broker))
    mosquitto.apply(broker, change)

    assert change is mosquitto.Change.RELOAD
    assert conftest.main_pid(broker) == before, 'a reload-safe change restarted the broker'
    passed, message = mosquitto.health_check(
        broker,
        host='127.0.0.1',
        port=1883,
        username=mosquitto.HEALTH_USER,
        password=conftest.HEALTH_PASSWORD,
    )
    assert passed, message


def test_a_listener_change_restarts_the_broker(broker: mosquitto.Paths):
    before = conftest.main_pid(broker)
    settings = mosquitto.BrokerSettings(
        listeners=(mosquitto.Listener(port=1884),), sys_interval=17
    )

    change = mosquitto.write_config(broker, main=mosquitto.render_config(settings, broker))
    mosquitto.apply(broker, change)

    assert change is mosquitto.Change.RESTART
    assert conftest.main_pid(broker) != before
    passed, message = mosquitto.health_check(
        broker,
        host='127.0.0.1',
        port=1884,
        username=mosquitto.HEALTH_USER,
        password=conftest.HEALTH_PASSWORD,
    )
    assert passed, message

    # Put the default listener back for the tests that follow.
    restore = mosquitto.BrokerSettings(listeners=(mosquitto.Listener(port=1883),), sys_interval=1)
    mosquitto.apply(
        broker, mosquitto.write_config(broker, main=mosquitto.render_config(restore, broker))
    )


def test_the_service_override_lets_the_broker_start(broker: mosquitto.Paths):
    """The packaged unit sets no LimitNOFILE, so the charm has to, without breaking it.

    The sandboxing in the drop-in is easy to get wrong in a way that only shows up
    here: `SystemCallFilter=~@privileged` would stop the broker dropping to its own
    user, and systemd would kill it with SIGSYS before it ever listened.
    """
    dropin = (
        pathlib.Path(mosquitto.DROPIN_DIR_TEMPLATE.format(service=broker.service))
        / mosquitto.DROPIN_FILENAME
    )
    mosquitto.write_service_overrides(broker, file_limit=4096)
    assert 'LimitNOFILE=4096' in dropin.read_text()

    try:
        subprocess.run(['/bin/systemctl', 'daemon-reload'], check=True, capture_output=True)
        mosquitto.stop(broker)
        mosquitto.start(broker)
        limit = subprocess.run(
            ['/bin/systemctl', 'show', broker.service, '-p', 'LimitNOFILE', '--value'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert int(limit) >= 4096
    finally:
        # Whatever happened, leave a running broker for the tests that follow. A start
        # that fails leaves the log file owned by root, and since 2.0 the broker drops
        # privileges before opening it, so nothing would start again after this.
        dropin.unlink(missing_ok=True)
        subprocess.run(['/bin/systemctl', 'daemon-reload'], check=False, capture_output=True)
        subprocess.run(
            ['/bin/systemctl', 'reset-failed', broker.service], check=False, capture_output=True
        )
        mosquitto.ensure_directories(broker)
        if broker.log_file.exists():
            shutil.chown(broker.log_file, broker.user, broker.group)
        mosquitto.start(broker)


def test_sys_snapshot(broker: mosquitto.Paths):
    # $SYS is published every sys_interval seconds, so ask for it often enough that a
    # short collection sees a full tree.
    settings = mosquitto.BrokerSettings(listeners=(mosquitto.Listener(port=1883),), sys_interval=1)
    mosquitto.apply(
        broker, mosquitto.write_config(broker, main=mosquitto.render_config(settings, broker))
    )

    snapshot = mosquitto.sys_snapshot(
        broker,
        host='127.0.0.1',
        port=1883,
        username=mosquitto.METRICS_USER,
        password=conftest.METRICS_PASSWORD,
        timeout=5,
    )

    assert '$SYS/broker/version' in snapshot
    # The one with a space in its topic name, which trips up naive parsing.
    assert '$SYS/broker/retained messages/count' in snapshot


# --- Backup and restore ---------------------------------------------------------------


def test_backup_and_restore_round_trip(broker: mosquitto.Paths):
    mosquitto.write_password_file(broker, {mosquitto.HEALTH_USER: conftest.HEALTH_PASSWORD})
    before = broker.password_file.read_text()

    backup = mosquitto.create_backup(broker)
    assert backup.is_file()
    assert mode(backup) == 0o600

    mosquitto.write_password_file(broker, {'someone-else': 'a-password'})
    assert broker.password_file.read_text() != before

    mosquitto.stop(broker)
    try:
        mosquitto.restore_backup(broker, backup)
    finally:
        mosquitto.start(broker)

    assert broker.password_file.read_text() == before
    passed, message = mosquitto.health_check(
        broker,
        host='127.0.0.1',
        port=1883,
        username=mosquitto.HEALTH_USER,
        password=conftest.HEALTH_PASSWORD,
    )
    assert passed, message


def test_restore_rejects_a_missing_file(broker: mosquitto.Paths):
    with pytest.raises(mosquitto.Error):
        mosquitto.restore_backup(broker, pathlib.Path('/nonexistent.tar.gz'))


def test_restore_rejects_a_path_outside_the_broker_directories(
    broker: mosquitto.Paths, tmp_path: pathlib.Path
):
    """A tarball is attacker-controlled input, so this is a security boundary."""
    payload = tmp_path / 'payload'
    payload.write_text('nothing useful\n')
    archive_path = tmp_path / 'escape.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        archive.add(payload, arcname='etc/cron.d/backdoor')

    with pytest.raises(mosquitto.Error, match='unexpected path'):
        mosquitto.restore_backup(broker, archive_path)

    assert not pathlib.Path('/etc/cron.d/backdoor').exists()


def test_restore_rejects_a_traversing_path(broker: mosquitto.Paths, tmp_path: pathlib.Path):
    """`..` in a member name must not reach outside the broker's directories."""
    escapee = pathlib.Path('/tmp/mosquitto-charm-escaped')  # noqa: S108
    escapee.unlink(missing_ok=True)
    archive_path = tmp_path / 'traverse.tar.gz'
    payload = b'nothing useful\n'
    with tarfile.open(archive_path, 'w:gz') as archive:
        info = tarfile.TarInfo(f'etc/mosquitto/../..{escapee}')
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    try:
        with pytest.raises(mosquitto.Error):
            mosquitto.restore_backup(broker, archive_path)
        assert not escapee.exists(), 'a backup tarball wrote outside the broker directories'
    finally:
        escapee.unlink(missing_ok=True)


def test_restore_rejects_a_symlink(broker: mosquitto.Paths, tmp_path: pathlib.Path):
    """A symlink inside the permitted directories still writes outside them."""
    link = tmp_path / 'server.key'
    link.symlink_to('/root/.ssh/id_ed25519')
    archive_path = tmp_path / 'link.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        archive.add(link, arcname='etc/mosquitto/certs/server.key')

    with pytest.raises(mosquitto.Error, match='contains a link'):
        mosquitto.restore_backup(broker, archive_path)

    assert not (broker.certs_dir / 'server.key').is_symlink()


def test_restore_rejects_a_hard_link(broker: mosquitto.Paths, tmp_path: pathlib.Path):
    target = tmp_path / 'target'
    target.write_text('contents\n')
    link = tmp_path / 'hard'
    os.link(target, link)
    archive_path = tmp_path / 'hardlink.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        archive.add(target, arcname='etc/mosquitto/acl')
        archive.add(link, arcname='etc/mosquitto/passwd')

    with pytest.raises(mosquitto.Error, match='contains a link'):
        mosquitto.restore_backup(broker, archive_path)


def test_backup_to_a_chosen_destination(broker: mosquitto.Paths):
    with tempfile.TemporaryDirectory() as directory:
        destination = pathlib.Path(directory) / 'somewhere' / 'backup.tar.gz'

        result = mosquitto.create_backup(broker, destination)

        assert result == destination
        with tarfile.open(destination) as archive:
            names = archive.getnames()
        assert any(name.endswith('passwd') for name in names)


def test_the_charm_owns_the_main_configuration(broker: mosquitto.Paths):
    """The packaged mosquitto.conf sets directives the charm's fragment also sets.

    Mosquitto refuses to start when a directive such as `persistence_location` or
    `log_dest file` appears twice in any file, so the charm replaces the main file with
    nothing but an include, and keeps the original alongside.
    """
    contents = broker.config_file.read_text()
    directives = dict(mosquitto.parse_directives(contents))

    assert directives == {'include_dir': str(broker.conf_dir)}
    original = broker.config_file.with_suffix(broker.config_file.suffix + '.charm-orig')
    assert original.is_file(), 'the packaged configuration was replaced without a copy'
    assert 'persistence_location' in original.read_text()


def test_last_log_reads_the_journal_and_the_log_file(broker: mosquitto.Paths):
    """It is what the charm puts in front of an operator when the broker will not start.

    Both sources: the broker is configured with `log_dest file`, so anything that goes
    wrong after it opens that file is not in the journal at all.
    """
    broker.log_file.parent.mkdir(parents=True, exist_ok=True)
    with broker.log_file.open('a') as log:
        log.write('1970-01-01: a line only the log file has\n')

    logs = mosquitto.last_log(broker, lines=5)

    assert 'mosquitto' in logs.lower()
    assert 'a line only the log file has' in logs
