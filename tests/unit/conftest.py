# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Shared fixtures for the state-transition tests.

The charm module deliberately never imports `subprocess`, `apt` or `systemd`: every
interaction with the machine goes through `src/mosquitto.py`. That makes the charm
testable by replacing that one module, which is what `FakeMosquitto` here is for. It is
a hand-rolled, stateful fake rather than a `MagicMock`, so that a test can ask what the
charm *decided* — which files it wrote, whether it reloaded or restarted, whether it
installed the exporter — instead of only which methods it happened to call.

The pure parts of the real module (rendering, change classification, the dataclasses,
the enumerations) are reused rather than reimplemented, so the fake cannot drift away
from the real thing in the ways that matter. `test_charm.py` also asserts that the fake
carries every name the charm reaches for.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
import sys
from typing import Any

import pytest

# The tests import the charm's modules, which live in src/, and the charm libraries
# fetched from Charmhub, which live in lib/. tox sets PYTHONPATH for both; doing it
# here as well means `pytest tests/unit` works from a bare checkout too.
_ROOT = pathlib.Path(__file__).parents[2]
for _path in (_ROOT / 'src', _ROOT / 'lib'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import ops.testing as testing  # noqa: E402

import mosquitto  # noqa: E402
from charm import MosquittoCharm  # noqa: E402


@dataclasses.dataclass
class ExporterState:
    """What the fake believes about the metrics exporter."""

    installed: bool = False
    running: bool = False
    broker_port: int | None = None
    listen_address: str | None = None
    listen_port: int | None = None
    username: str | None = None
    password: str | None = None


class FakeMosquitto:
    """A stateful stand-in for `src/mosquitto.py`.

    Anything that would touch apt, systemd, a real broker or a real filesystem path is
    replaced; everything else is the real implementation, so a change to the rendering
    or to the reload/restart classifier shows up here rather than being papered over.
    """

    # --- The parts of the real module that are pure, and so are not faked ----------

    Paths = mosquitto.Paths
    Change = mosquitto.Change
    Access = mosquitto.Access
    Listener = mosquitto.Listener
    BrokerSettings = mosquitto.BrokerSettings
    TLSMaterial = mosquitto.TLSMaterial
    Bridge = mosquitto.Bridge
    Error = mosquitto.Error
    InstallError = mosquitto.InstallError
    ServiceError = mosquitto.ServiceError
    ConfigError = mosquitto.ConfigError
    HEALTH_USER = mosquitto.HEALTH_USER
    METRICS_USER = mosquitto.METRICS_USER
    HEALTH_TOPIC_PREFIX = mosquitto.HEALTH_TOPIC_PREFIX
    CHARM_CONFIG_FILENAME = mosquitto.CHARM_CONFIG_FILENAME
    BRIDGE_CONFIG_FILENAME = mosquitto.BRIDGE_CONFIG_FILENAME
    EXTRA_CONFIG_FILENAME = mosquitto.EXTRA_CONFIG_FILENAME
    MINIMUM_BRIDGE_VERSION = mosquitto.MINIMUM_BRIDGE_VERSION
    render_config = staticmethod(mosquitto.render_config)
    render_bridge_config = staticmethod(mosquitto.render_bridge_config)
    render_acl_file = staticmethod(mosquitto.render_acl_file)
    render_password_file = staticmethod(mosquitto.render_password_file)
    listeners_for = staticmethod(mosquitto.listeners_for)
    merge_changes = staticmethod(mosquitto.merge_changes)
    classify_change = staticmethod(mosquitto.classify_change)
    parse_directives = staticmethod(mosquitto.parse_directives)
    supports_bridging = staticmethod(mosquitto.supports_bridging)
    version_tuple = staticmethod(mosquitto.version_tuple)
    generate_password = staticmethod(mosquitto.generate_password)

    def __init__(self, root: pathlib.Path, *, version: str | None = '2.0.18'):
        self.root = root
        self.version = version
        self.running = False
        # Whether systemd would start the broker at boot. `pause` clears it.
        self.enabled = True
        # What `check_config` reports. None means the broker accepts the configuration.
        self.rejection: str | None = None
        self.calls: list[str] = []
        self.installs: list[tuple[str, str]] = []
        self.uninstalled: list[str] = []
        # Which source the fake believes the broker on the machine came from, once
        # something has installed it. None means "whatever the test set up".
        self.installed_source: str | None = None
        self.migrations: list[tuple[str, str]] = []
        self.users: dict[str, str] = {}
        self.rules: dict[str, collections.abc.Sequence[tuple[str, str]]] = {}
        self.tls: mosquitto.TLSMaterial | None = None
        self.bridge_ca: str | None = None
        self.main_config: str = ''
        self.bridge_config: str | None = None
        self.extra_config: str = ''
        self.file_limit: int | None = None
        self.sysctl_enabled: bool | None = None
        self.last_change: mosquitto.Change | None = None
        self.exporter = ExporterState()
        self.backups: list[pathlib.Path] = []
        self.restored: list[pathlib.Path] = []
        # Knobs the tests turn to make the machine misbehave.
        self.installs_succeed = True
        self.install_error: str | None = None
        self.start_works = True
        self.health: tuple[bool, str] = (True, 'ok')
        self.sys_tree: dict[str, str] = {'$SYS/broker/version': 'mosquitto 2.0.18'}
        self.last_health_check: dict[str, Any] = {}
        self.start_error: str | None = None
        self.exporter_start_error: str | None = None
        self.stop_error: str | None = None
        self.apply_error: str | None = None
        self.dies_on_apply = False
        self.journal = ''

    # --- Layout -------------------------------------------------------------------

    def paths(self, install_source: str) -> mosquitto.Paths:
        """The real layout, rebased under a temporary directory."""
        real = mosquitto.paths(install_source)
        base = self.root / install_source
        return dataclasses.replace(
            real,
            config_file=base / 'mosquitto.conf',
            conf_dir=base / 'conf.d',
            password_file=base / 'passwd',
            acl_file=base / 'acl',
            persistence_dir=base / 'data',
            log_file=base / 'log' / 'mosquitto.log',
            certs_dir=base / 'certs',
            backup_dir=base / 'backups',
        )

    # --- Packages -----------------------------------------------------------------

    def install(self, install_source: str, channel: str = 'latest/stable') -> None:
        self.calls.append('install')
        self.installs.append((install_source, channel))
        if self.install_error is not None:
            raise mosquitto.InstallError(self.install_error)
        self.installed_source = install_source
        if self.version is None and self.installs_succeed:
            self.version = '2.0.18'

    def uninstall(self, install_source: str) -> None:
        self.calls.append('uninstall')
        self.uninstalled.append(install_source)
        # Removing the source the broker was *not* installed from -- which is what the
        # charm does after migrating between the deb and the snap -- leaves the running
        # broker alone.
        if self.installed_source in (None, install_source):
            self.version = None
            self.running = False

    def get_version(self, install_source: str = 'archive') -> str | None:
        return self.version

    supports_test_config = staticmethod(mosquitto.supports_test_config)

    def check_config(self, file_paths: mosquitto.Paths, version: str | None) -> str | None:
        """Whatever the test has asked the broker to say about the configuration.

        Defaults to accepting it; set `rejection` to have the broker refuse, which is
        how a test reaches the "do not apply a configuration Mosquitto rejects" path.
        """
        self.calls.append('check_config')
        return self.rejection

    different_packaging = staticmethod(mosquitto.different_packaging)

    def migrate_state(self, old: mosquitto.Paths, new: mosquitto.Paths) -> None:
        self.calls.append('migrate_state')
        self.migrations.append((str(old.persistence_dir), str(new.persistence_dir)))

    # --- Files --------------------------------------------------------------------

    def ensure_directories(self, file_paths: mosquitto.Paths) -> None:
        self.calls.append('ensure_directories')
        for directory in (
            file_paths.conf_dir,
            file_paths.persistence_dir,
            file_paths.certs_dir,
            file_paths.backup_dir,
            file_paths.log_file.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def write_password_file(
        self, file_paths: mosquitto.Paths, users: collections.abc.Mapping[str, str]
    ) -> mosquitto.Change:
        self.calls.append('write_password_file')
        # Compare the whole mapping, not just the usernames: a changed password with an
        # unchanged username set is a real change, and treating it as nothing is the
        # bug this fake previously reproduced rather than caught.
        changed = dict(users) != self.users
        self.users = dict(users)
        return mosquitto.Change.RELOAD if changed else mosquitto.Change.NONE

    def snapshot_fragments(self, file_paths: mosquitto.Paths) -> dict[str, str | None]:
        self.calls.append('snapshot_fragments')
        return {
            mosquitto.CHARM_CONFIG_FILENAME: self.main_config or None,
            mosquitto.BRIDGE_CONFIG_FILENAME: self.bridge_config,
            mosquitto.EXTRA_CONFIG_FILENAME: self.extra_config or None,
        }

    def restore_fragments(
        self, file_paths: mosquitto.Paths, snapshot: collections.abc.Mapping[str, str | None]
    ) -> None:
        self.calls.append('restore_fragments')
        self.main_config = snapshot[mosquitto.CHARM_CONFIG_FILENAME] or ''
        self.bridge_config = snapshot[mosquitto.BRIDGE_CONFIG_FILENAME]
        self.extra_config = snapshot[mosquitto.EXTRA_CONFIG_FILENAME] or ''

    def write_acl_file(
        self,
        file_paths: mosquitto.Paths,
        rules: collections.abc.Mapping[str, collections.abc.Sequence[tuple[str, str]]],
    ) -> mosquitto.Change:
        self.calls.append('write_acl_file')
        rendered = mosquitto.render_acl_file(rules)
        changed = rendered != mosquitto.render_acl_file(self.rules)
        self.rules = {name: list(value) for name, value in rules.items()}
        return mosquitto.Change.RELOAD if changed else mosquitto.Change.NONE

    def write_tls_material(
        self, file_paths: mosquitto.Paths, material: mosquitto.TLSMaterial
    ) -> mosquitto.Change:
        self.calls.append('write_tls_material')
        changed = material != self.tls
        self.tls = material
        return mosquitto.Change.RELOAD if changed else mosquitto.Change.NONE

    def write_bridge_ca(self, file_paths: mosquitto.Paths, ca: str) -> mosquitto.Change:
        self.calls.append('write_bridge_ca')
        changed = ca != self.bridge_ca
        self.bridge_ca = ca
        return mosquitto.Change.RELOAD if changed else mosquitto.Change.NONE

    def write_config(
        self,
        file_paths: mosquitto.Paths,
        *,
        main: str,
        bridge: str | None = None,
        extra: str = '',
    ) -> mosquitto.Change:
        self.calls.append('write_config')
        # The real classifier, so that a test asserting RELOAD rather than RESTART is
        # asserting about the charm's rendering and not about this fake.
        change = max(
            mosquitto.classify_change(self.main_config, main),
            mosquitto.classify_change(self.bridge_config or '', bridge or ''),
            mosquitto.classify_change(self.extra_config, extra),
        )
        self.main_config = main
        self.bridge_config = bridge
        self.extra_config = extra
        return change

    def write_service_overrides(self, file_paths: mosquitto.Paths, *, file_limit: int) -> bool:
        self.calls.append('write_service_overrides')
        changed = file_limit != self.file_limit
        self.file_limit = file_limit
        return changed

    def apply_sysctl(self, *, enabled: bool) -> None:
        self.calls.append('apply_sysctl')
        self.sysctl_enabled = enabled

    # --- The service --------------------------------------------------------------

    def is_running(self, file_paths: mosquitto.Paths) -> bool:
        return self.running

    def start(self, file_paths: mosquitto.Paths) -> None:
        self.calls.append('start')
        self.enabled = True
        if self.start_error is not None:
            raise mosquitto.ServiceError(self.start_error)
        self.running = self.start_works

    def stop(self, file_paths: mosquitto.Paths) -> None:
        self.calls.append('stop')
        if self.stop_error is not None:
            raise mosquitto.ServiceError(self.stop_error)
        self.running = False

    def pause(self, file_paths: mosquitto.Paths) -> None:
        """Stop the broker and disable it, so a reboot does not bring it back."""
        self.calls.append('pause')
        self.stop(file_paths)
        self.enabled = False

    def apply(self, file_paths: mosquitto.Paths, change: mosquitto.Change) -> None:
        self.calls.append('apply')
        self.last_change = change
        if self.apply_error is not None:
            raise mosquitto.ServiceError(self.apply_error)
        if self.dies_on_apply:
            # A reload the broker accepts and then exits on, which is what a bad
            # configuration does on 2.0: `systemctl reload` still reports success.
            self.running = False

    def last_log(self, file_paths: mosquitto.Paths, lines: int = 20) -> str:
        self.calls.append('last_log')
        return self.journal

    # --- The exporter -------------------------------------------------------------

    def install_exporter(
        self,
        source: pathlib.Path,
        file_paths: mosquitto.Paths,
        *,
        broker_host: str,
        broker_port: int,
        username: str,
        password: str,
        listen_address: str,
        listen_port: int,
    ) -> bool:
        self.calls.append('install_exporter')
        previous = dataclasses.replace(self.exporter)
        self.exporter.installed = True
        self.exporter.broker_port = broker_port
        self.exporter.listen_address = listen_address
        self.exporter.listen_port = listen_port
        self.exporter.username = username
        self.exporter.password = password
        return dataclasses.replace(self.exporter, running=previous.running) != previous

    def exporter_running(self) -> bool:
        return self.exporter.running

    def start_exporter(self) -> None:
        self.calls.append('start_exporter')
        if self.exporter_start_error is not None:
            raise mosquitto.ServiceError(self.exporter_start_error)
        self.exporter.running = True

    def remove_exporter(self) -> None:
        self.calls.append('remove_exporter')
        self.exporter = ExporterState()

    # --- Talking to the broker ----------------------------------------------------

    def health_check(
        self,
        file_paths: mosquitto.Paths,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        cafile: pathlib.Path | None = None,
        timeout: int = 10,
    ) -> tuple[bool, str]:
        self.calls.append('health_check')
        self.last_health_check = {
            'host': host,
            'port': port,
            'username': username,
            'cafile': cafile,
        }
        return self.health

    def sys_snapshot(
        self,
        file_paths: mosquitto.Paths,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        timeout: int = 10,
    ) -> dict[str, str]:
        self.calls.append('sys_snapshot')
        return dict(self.sys_tree)

    # --- Backups ------------------------------------------------------------------

    def create_backup(
        self, file_paths: mosquitto.Paths, destination: pathlib.Path | None = None
    ) -> pathlib.Path:
        self.calls.append('create_backup')
        path = destination or (file_paths.backup_dir / 'mosquitto-backup.tar.gz')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'not really a tarball')
        self.backups.append(path)
        return path

    def restore_backup(self, file_paths: mosquitto.Paths, source: pathlib.Path) -> None:
        self.calls.append('restore_backup')
        if not source.is_file():
            raise mosquitto.Error(f'{source} is not a file')
        self.restored.append(source)

    # --- Assertions helpers -------------------------------------------------------

    def touched_workload(self) -> bool:
        """Whether anything that changes the machine was called."""
        return bool(
            set(self.calls)
            & {
                'install',
                'uninstall',
                'ensure_directories',
                'write_password_file',
                'write_acl_file',
                'write_config',
                'write_service_overrides',
                'apply_sysctl',
                'start',
                'apply',
                'install_exporter',
            }
        )


@pytest.fixture
def fake(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> FakeMosquitto:
    """Replace the workload module the charm talks to."""
    stand_in = FakeMosquitto(tmp_path / 'workload')
    monkeypatch.setattr('charm.mosquitto', stand_in)
    return stand_in


@pytest.fixture
def ctx() -> testing.Context[MosquittoCharm]:
    """A context for the real charm class, reading the real charmcraft.yaml."""
    return testing.Context(MosquittoCharm)
