#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""A dependency-free Prometheus exporter for Eclipse Mosquitto.

Mosquitto has no Prometheus endpoint: it republishes its internal counters to the
``$SYS/broker/#`` topic tree every ``sys_interval`` seconds. This program subscribes to
that tree by running ``mosquitto_sub`` as a long-lived child process, keeps the latest
value of every topic in memory, and serves the result in Prometheus text format.

The metric names deliberately match those produced by ``sapcc/mosquitto-exporter``
(the ``$SYS/`` prefix stripped, then ``/``, ``  ``, ``-`` and ``.`` replaced by ``_``)
so that dashboards written against that exporter keep working.

This module is run as its own systemd service by the charm; it is never imported by the
charm itself. It uses nothing outside the standard library, and the mapping, registry
and rendering layers do no I/O so that they can be unit tested directly.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import functools
import http.server
import logging
import os
import pathlib
import re
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import types
import typing

__version__ = '1.0.0'

logger = logging.getLogger('mosquitto-exporter')

DEFAULT_MOSQUITTO_SUB = '/usr/bin/mosquitto_sub'
"""Where the ``mosquitto-clients`` deb installs the subscriber."""

SUB_TOPIC = '$SYS/#'

SUB_FORMAT = '%t\\t%p'
"""Topic and payload separated by a tab.

A space is not usable as the separator: ``$SYS/broker/retained messages/count`` has an
embedded space in the *topic*, and ``$SYS/broker/uptime`` has one in the *payload*, so
neither a first-space nor a last-space split is unambiguous. No ``$SYS`` topic can
contain a tab.
"""

STALE_AFTER = 60.0
"""Seconds without a ``$SYS`` message after which the broker is considered down.

Mosquitto's ``sys_interval`` defaults to 10 seconds, so this tolerates several missed
republish cycles before flipping ``mosquitto_up`` to 0.
"""

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0

COUNTER = 'counter'
GAUGE = 'gauge'

type MetricKind = typing.Literal['counter', 'gauge']

_NUMBER = re.compile(r'-?\d+(?:\.\d+)?')
_BRIDGE_STATE = re.compile(r'^\$SYS/broker/connection/(?P<bridge>.+)/state$')


@dataclasses.dataclass(frozen=True)
class Sample:
    """A single rendered Prometheus sample.

    Attributes:
        name: The metric name, for example ``broker_clients_connected``.
        labels: Label name/value pairs, in the order they should be rendered.
        value: The sample value.
        kind: Either ``counter`` or ``gauge``.
        help: The ``# HELP`` text for the metric family.
    """

    name: str
    labels: tuple[tuple[str, str], ...]
    value: float
    kind: MetricKind
    help: str


@dataclasses.dataclass(frozen=True)
class _Mapping:
    """How one ``$SYS`` topic becomes a metric.

    Attributes:
        name: The metric name to emit.
        kind: Either ``counter`` or ``gauge``.
        help: The ``# HELP`` text.
        label: If set, the payload becomes the value of this label and the sample value
            is a constant 1, giving a Prometheus "info"-style metric.
    """

    name: str
    kind: MetricKind
    help: str
    label: str | None = None


def _load_mappings() -> dict[str, _Mapping]:
    """Build the mapping entries for the ``$SYS/broker/load/**`` subtree.

    Each load topic is a moving average in units per minute, with ``1min``, ``5min`` and
    ``15min`` variants. ``sapcc/mosquitto-exporter`` folds the window into the metric
    name rather than into a label, so that is what we do too: a label would produce
    ``broker_load_connections{interval="1min"}`` where every existing dashboard and the
    published alert rules expect ``broker_load_connections_1min``.

    Returns:
        A mapping from ``$SYS`` topic to the metric it produces.
    """
    families = {
        'messages/received': 'MQTT messages of any type received',
        'messages/sent': 'MQTT messages of any type sent',
        'publish/received': 'PUBLISH messages received',
        'publish/sent': 'PUBLISH messages sent',
        'publish/dropped': 'PUBLISH messages dropped',
        'bytes/received': 'bytes received',
        'bytes/sent': 'bytes sent',
        'connections': 'MQTT CONNECT packets',
        'sockets': 'socket connections opened',
    }
    mappings: dict[str, _Mapping] = {}
    for suffix, description in families.items():
        for window in ('1min', '5min', '15min'):
            topic = f'$SYS/broker/load/{suffix}/{window}'
            name = 'broker_load_' + suffix.replace('/', '_') + '_' + window
            mappings[topic] = _Mapping(
                name,
                GAUGE,
                f'The moving average of the number of {description} per minute, '
                f'over the last {window.removesuffix("min")} minutes.',
            )
    return mappings


MAPPINGS: dict[str, _Mapping] = {
    # Counters. These are monotonic totals since the broker started, so they are the
    # ones that belong in rate() and increase(). This list matches sapcc's exactly.
    '$SYS/broker/bytes/received': _Mapping(
        'broker_bytes_received',
        COUNTER,
        'The total number of bytes received since the broker started.',
    ),
    '$SYS/broker/bytes/sent': _Mapping(
        'broker_bytes_sent',
        COUNTER,
        'The total number of bytes sent since the broker started.',
    ),
    '$SYS/broker/messages/received': _Mapping(
        'broker_messages_received',
        COUNTER,
        'The total number of messages of any type received since the broker started.',
    ),
    '$SYS/broker/messages/sent': _Mapping(
        'broker_messages_sent',
        COUNTER,
        'The total number of messages of any type sent since the broker started.',
    ),
    '$SYS/broker/publish/bytes/received': _Mapping(
        'broker_publish_bytes_received',
        COUNTER,
        'The total number of PUBLISH bytes received since the broker started.',
    ),
    '$SYS/broker/publish/bytes/sent': _Mapping(
        'broker_publish_bytes_sent',
        COUNTER,
        'The total number of PUBLISH bytes sent since the broker started.',
    ),
    '$SYS/broker/publish/messages/received': _Mapping(
        'broker_publish_messages_received',
        COUNTER,
        'The total number of PUBLISH messages received since the broker started.',
    ),
    '$SYS/broker/publish/messages/sent': _Mapping(
        'broker_publish_messages_sent',
        COUNTER,
        'The total number of PUBLISH messages sent since the broker started.',
    ),
    '$SYS/broker/publish/messages/dropped': _Mapping(
        'broker_publish_messages_dropped',
        COUNTER,
        'The total number of PUBLISH messages dropped because of inflight or queuing '
        'limits. Any non-zero rate means the broker is losing messages.',
    ),
    '$SYS/broker/uptime': _Mapping(
        'broker_uptime',
        COUNTER,
        'The total number of seconds since the broker started.',
    ),
    '$SYS/broker/clients/maximum': _Mapping(
        'broker_clients_maximum',
        COUNTER,
        'The maximum number of clients connected simultaneously since the broker started.',
    ),
    '$SYS/broker/clients/total': _Mapping(
        'broker_clients_total',
        COUNTER,
        'The total number of connected and disconnected clients currently known to the broker.',
    ),
    # Gauges.
    '$SYS/broker/clients/connected': _Mapping(
        'broker_clients_connected',
        GAUGE,
        'The number of currently connected clients.',
    ),
    '$SYS/broker/clients/disconnected': _Mapping(
        'broker_clients_disconnected',
        GAUGE,
        'The number of disconnected persistent clients whose session the broker is still holding.',
    ),
    '$SYS/broker/clients/expired': _Mapping(
        'broker_clients_expired',
        GAUGE,
        'The number of disconnected persistent clients that have been expired and '
        'removed through persistent_client_expiration.',
    ),
    '$SYS/broker/messages/stored': _Mapping(
        'broker_messages_stored',
        GAUGE,
        'The number of messages currently held in the message store, which includes '
        'retained messages and messages queued for durable clients.',
    ),
    '$SYS/broker/store/messages/count': _Mapping(
        'broker_store_messages_count',
        GAUGE,
        'The number of messages currently held in the message store.',
    ),
    '$SYS/broker/store/messages/bytes': _Mapping(
        'broker_store_messages_bytes',
        GAUGE,
        'The number of bytes currently held by message payloads in the message store.',
    ),
    # The embedded space in this topic is not a typo: Mosquitto really does publish
    # "$SYS/broker/retained messages/count".
    '$SYS/broker/retained messages/count': _Mapping(
        'broker_retained_messages_count',
        GAUGE,
        'The total number of retained messages held by the broker.',
    ),
    '$SYS/broker/subscriptions/count': _Mapping(
        'broker_subscriptions_count',
        GAUGE,
        'The total number of subscriptions active on the broker.',
    ),
    '$SYS/broker/shared_subscriptions/count': _Mapping(
        'broker_shared_subscriptions_count',
        GAUGE,
        'The total number of shared subscription groups active on the broker.',
    ),
    '$SYS/broker/heap/current': _Mapping(
        'broker_heap_current',
        GAUGE,
        'The current size of the heap memory in use by the broker, in bytes.',
    ),
    '$SYS/broker/heap/maximum': _Mapping(
        'broker_heap_maximum',
        GAUGE,
        'The largest heap memory value the broker has used, in bytes.',
    ),
    # An info-style metric: the payload is a version string, so it becomes a label.
    '$SYS/broker/version': _Mapping(
        'mosquitto_broker_info',
        GAUGE,
        'The version of the Mosquitto broker being monitored.',
        label='version',
    ),
    **_load_mappings(),
}

BRIDGE_STATE = _Mapping(
    'mosquitto_bridge_state',
    GAUGE,
    'Whether the named bridge connection is up (1) or down (0).',
)

IGNORED_TOPICS = frozenset(
    {
        # Static build metadata, with no useful numeric value.
        '$SYS/broker/timestamp',
        # Deprecated aliases of clients/connected and clients/disconnected. Exporting them
        # as well would double-count in any "sum by" dashboard panel.
        '$SYS/broker/clients/active',
        '$SYS/broker/clients/inactive',
    }
)

IGNORED_PREFIXES = (
    # Log republishing ("log_dest topic"). These payloads are free text, not numbers,
    # and belong in Loki rather than in Prometheus.
    '$SYS/broker/log/',
)

UP_HELP = (
    'Whether the exporter is currently receiving $SYS messages from the broker (1) or not (0).'
)
BUILD_INFO_HELP = 'The version of the Mosquitto Prometheus exporter.'


def parse_line(line: str) -> tuple[str, str]:
    r"""Split one line of ``mosquitto_sub -F '%t\t%p'`` output.

    Args:
        line: A single line of subscriber output, with or without its trailing newline.

    Returns:
        A ``(topic, payload)`` pair.

    Raises:
        ValueError: If the line has no tab separator, or an empty topic.
    """
    topic, separator, payload = line.rstrip('\r\n').partition('\t')
    if not separator:
        raise ValueError(f'no tab separator in subscriber output: {line!r}')
    if not topic:
        raise ValueError(f'empty topic in subscriber output: {line!r}')
    return topic, payload


def parse_value(payload: str) -> float:
    """Extract the numeric value from a ``$SYS`` payload.

    Payloads are ASCII strings, and are not always bare numbers: ``$SYS/broker/uptime``
    publishes ``"1234 seconds"``, and the load averages publish values such as
    ``"0.53"``. The first number in the payload is the value, which is also how
    ``sapcc/mosquitto-exporter`` reads them.

    Args:
        payload: The raw topic payload.

    Returns:
        The value as a float.

    Raises:
        ValueError: If the payload contains no number.
    """
    match = _NUMBER.search(payload)
    if match is None:
        raise ValueError(f'no numeric value in payload: {payload!r}')
    return float(match.group())


def map_topic(topic: str, payload: str) -> list[Sample]:
    """Map one ``$SYS`` topic and payload to the samples it produces.

    This is a pure function: it performs no I/O and holds no state.

    Args:
        topic: The full ``$SYS`` topic, for example ``$SYS/broker/clients/connected``.
        payload: The topic payload as published by the broker.

    Returns:
        The samples for this update. This is empty for any topic that is deliberately
        ignored, and for any topic with no mapping.

    Raises:
        ValueError: If the topic is mapped but its payload has no numeric value.
    """
    if topic in IGNORED_TOPICS or topic.startswith(IGNORED_PREFIXES):
        return []

    mapping = MAPPINGS.get(topic)
    labels: tuple[tuple[str, str], ...] = ()
    if mapping is None:
        bridge = _BRIDGE_STATE.match(topic)
        if bridge is None:
            return []
        mapping = BRIDGE_STATE
        labels = (('bridge', bridge.group('bridge')),)

    if mapping.label is not None:
        return [Sample(mapping.name, ((mapping.label, payload),), 1.0, mapping.kind, mapping.help)]

    return [Sample(mapping.name, labels, parse_value(payload), mapping.kind, mapping.help)]


def escape_help(text: str) -> str:
    """Escape text for use in a ``# HELP`` line.

    Args:
        text: The unescaped help text.

    Returns:
        The text with backslashes and newlines escaped, as the Prometheus text exposition
        format requires.
    """
    return text.replace('\\', r'\\').replace('\n', r'\n')


def escape_label_value(value: str) -> str:
    """Escape a label value for the Prometheus text format.

    Args:
        value: The unescaped label value.

    Returns:
        The value with backslashes, double quotes and newlines escaped.
    """
    return value.replace('\\', r'\\').replace('"', r'\"').replace('\n', r'\n')


def format_value(value: float) -> str:
    """Render a sample value.

    Args:
        value: The value to render.

    Returns:
        The value as a string, without a pointless trailing ``.0`` for whole numbers.
    """
    if value == int(value):
        return str(int(value))
    return repr(value)


def render(samples: typing.Iterable[Sample]) -> str:
    """Render samples as a Prometheus text exposition format document.

    This is a pure function: it performs no I/O and holds no state. Samples are grouped
    into metric families by name, and families are emitted in name order so that the
    output is stable.

    Args:
        samples: The samples to render.

    Returns:
        The exposition document, ending in a newline.
    """
    families: dict[str, list[Sample]] = {}
    for sample in samples:
        families.setdefault(sample.name, []).append(sample)

    lines: list[str] = []
    for name in sorted(families):
        members = sorted(families[name], key=lambda sample: sample.labels)
        first = members[0]
        lines.append(f'# HELP {name} {escape_help(first.help)}')
        lines.append(f'# TYPE {name} {first.kind}')
        for sample in members:
            labels = ','.join(
                f'{key}="{escape_label_value(value)}"' for key, value in sample.labels
            )
            suffix = f'{{{labels}}}' if labels else ''
            lines.append(f'{name}{suffix} {format_value(sample.value)}')
    return '\n'.join(lines) + '\n'


class Registry:
    """The latest value of every mapped ``$SYS`` topic.

    The registry is updated from the subscriber thread and read from the HTTP server's
    worker threads, so every access is guarded by a lock.
    """

    def __init__(self, *, stale_after: float = STALE_AFTER) -> None:
        """Initialise an empty registry.

        Args:
            stale_after: How many seconds may pass without a ``$SYS`` message before the
                broker is reported as down.
        """
        self._stale_after = stale_after
        self._lock = threading.Lock()
        self._samples: dict[tuple[str, tuple[tuple[str, str], ...]], Sample] = {}
        self._last_update: float | None = None
        self._unmapped: set[str] = set()

    @property
    def last_update(self) -> float | None:
        """The monotonic time of the most recent accepted update, if there was one."""
        with self._lock:
            return self._last_update

    def update(self, topic: str, payload: str, *, now: float | None = None) -> int:
        """Record an update for one ``$SYS`` topic.

        Unmapped topics are skipped rather than guessed at, and are logged once each at
        debug level so that the mapping table can be extended later.

        Args:
            topic: The full ``$SYS`` topic.
            payload: The topic payload.
            now: The monotonic timestamp to record, for testing. Defaults to now.

        Returns:
            The number of samples recorded.

        Raises:
            ValueError: If the topic is mapped but its payload has no numeric value.
        """
        samples = map_topic(topic, payload)
        if not samples and topic not in IGNORED_TOPICS:
            self._note_unmapped(topic)
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            for sample in samples:
                self._samples[sample.name, sample.labels] = sample
            # Even a topic we do not export is evidence that the broker is alive.
            self._last_update = timestamp
        return len(samples)

    def update_from_line(self, line: str, *, now: float | None = None) -> int:
        """Record an update from a raw line of subscriber output.

        Malformed lines are logged and discarded rather than propagated, so that one bad
        line cannot take the exporter down.

        Args:
            line: A single line of ``mosquitto_sub`` output.
            now: The monotonic timestamp to record, for testing. Defaults to now.

        Returns:
            The number of samples recorded, which is zero for a malformed line.
        """
        try:
            topic, payload = parse_line(line)
        except ValueError as exc:
            logger.warning('Discarding malformed subscriber output: %s', exc)
            return 0
        try:
            return self.update(topic, payload, now=now)
        except ValueError as exc:
            logger.warning('Discarding unusable payload on %s: %s', topic, exc)
            return 0

    def _note_unmapped(self, topic: str) -> None:
        """Log an unmapped topic, once.

        Args:
            topic: The topic that has no mapping.
        """
        with self._lock:
            if topic in self._unmapped:
                return
            self._unmapped.add(topic)
        logger.debug('No metric mapping for $SYS topic %r; skipping it.', topic)

    def is_up(self, *, now: float | None = None) -> bool:
        """Report whether the broker is currently publishing to ``$SYS``.

        Args:
            now: The monotonic timestamp to compare against, for testing.

        Returns:
            True if a ``$SYS`` message arrived within the staleness window.
        """
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            if self._last_update is None:
                return False
            return timestamp - self._last_update <= self._stale_after

    def snapshot(self, *, now: float | None = None) -> list[Sample]:
        """Take a consistent copy of the registry, plus the exporter's own metrics.

        Args:
            now: The monotonic timestamp to use for the staleness check, for testing.

        Returns:
            Every sample that should appear on ``/metrics``.
        """
        up = 1.0 if self.is_up(now=now) else 0.0
        with self._lock:
            samples = list(self._samples.values())
        samples.append(Sample('mosquitto_up', (), up, GAUGE, UP_HELP))
        samples.append(
            Sample(
                'mosquitto_exporter_build_info',
                (('version', __version__),),
                1.0,
                GAUGE,
                BUILD_INFO_HELP,
            )
        )
        return samples

    def render(self, *, now: float | None = None) -> str:
        """Render the registry as a Prometheus exposition document.

        Args:
            now: The monotonic timestamp to use for the staleness check, for testing.

        Returns:
            The exposition document.
        """
        return render(self.snapshot(now=now))


INDEX_PAGE = f"""<!DOCTYPE html>
<html lang="en">
<head><title>Mosquitto exporter</title></head>
<body>
<h1>Mosquitto exporter</h1>
<p>Version {__version__}.</p>
<p><a href="/metrics">Metrics</a></p>
</body>
</html>
"""


class MetricsHandler(http.server.BaseHTTPRequestHandler):
    """Serve ``/metrics`` and a plain index page from a registry."""

    server_version = f'mosquitto-exporter/{__version__}'
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args: typing.Any, registry: Registry, **kwargs: typing.Any) -> None:
        """Initialise the handler.

        Args:
            args: Positional arguments for the base handler.
            registry: The registry to serve.
            kwargs: Keyword arguments for the base handler.
        """
        # The base class handles the whole request from __init__, so the registry has to
        # be in place before we chain up.
        self._registry = registry
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Handle a GET request."""
        path = self.path.partition('?')[0]
        if path == '/metrics':
            self._respond(200, 'text/plain; version=0.0.4; charset=utf-8', self._registry.render())
        elif path == '/':
            self._respond(200, 'text/html; charset=utf-8', INDEX_PAGE)
        else:
            self._respond(404, 'text/plain; charset=utf-8', 'not found\n')

    def _respond(self, status: int, content_type: str, body: str) -> None:
        """Send a complete response.

        Args:
            status: The HTTP status code.
            content_type: The value for the ``Content-Type`` header.
            body: The response body.
        """
        encoded = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: typing.Any) -> None:
        """Route the base class's request logging to our logger.

        Args:
            format: A printf-style format string.
            args: Arguments for the format string.
        """
        logger.debug('%s %s', self.address_string(), format % args)


class _MetricsServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """A threading HTTP server that does not linger on shutdown."""

    daemon_threads = True
    allow_reuse_address = True


def build_server(address: str, port: int, registry: Registry) -> _MetricsServer:
    """Create the metrics HTTP server.

    Args:
        address: The address to bind to.
        port: The port to bind to.
        registry: The registry to serve.

    Returns:
        A server that has bound its socket but is not yet serving.
    """
    handler = functools.partial(MetricsHandler, registry=registry)
    return _MetricsServer((address, port), handler)


def build_subscriber_command(
    *,
    mosquitto_sub_path: str,
    broker_host: str,
    broker_port: int,
    username: str | None = None,
    cafile: str | None = None,
    insecure: bool = False,
) -> list[str]:
    """Build the ``mosquitto_sub`` argument vector.

    The password is deliberately absent: it is passed to the child through a private
    ``mosquitto_sub`` options file instead, so that it never appears in ``ps`` output.

    Args:
        mosquitto_sub_path: The absolute path to the ``mosquitto_sub`` binary.
        broker_host: The broker host to connect to.
        broker_port: The broker port to connect to.
        username: The MQTT username, if the broker requires authentication.
        cafile: A CA bundle, for connecting over a TLS listener.
        insecure: Whether to skip TLS hostname verification.

    Returns:
        The argument vector, suitable for ``subprocess.Popen`` without a shell.
    """
    command = [
        mosquitto_sub_path,
        '-h',
        broker_host,
        '-p',
        str(broker_port),
        '-t',
        SUB_TOPIC,
        '-q',
        '0',
        '-F',
        SUB_FORMAT,
    ]
    if username:
        command += ['-u', username]
    if cafile:
        command += ['--cafile', cafile]
    if insecure:
        command.append('--insecure')
    return command


def read_password(path: str) -> str:
    """Read a password from a file.

    Args:
        path: The path to the file holding the password.

    Returns:
        The password, with surrounding whitespace stripped.

    Raises:
        ValueError: If the file is empty.
    """
    password = pathlib.Path(path).read_text(encoding='utf-8').strip()
    if not password:
        raise ValueError(f'password file {path} is empty')
    return password


@contextlib.contextmanager
def subscriber_environment(password: str | None) -> typing.Generator[dict[str, str]]:
    """Provide an environment that hands the password to ``mosquitto_sub`` safely.

    ``mosquitto_sub`` has no way to read a password from a file or from stdin, and
    passing it with ``-P`` would expose it in the process list. It does, however, read
    default options from ``$XDG_CONFIG_HOME/mosquitto_sub``, so we write the password
    into a private throwaway config directory and point the child at it.

    Args:
        password: The password, or None if the broker needs no authentication.

    Yields:
        The environment to pass to the child process.
    """
    environment = dict(os.environ)
    if password is None:
        yield environment
        return
    directory = tempfile.mkdtemp(prefix='mosquitto-exporter-')
    try:
        options = pathlib.Path(directory, 'mosquitto_sub')
        options.touch(mode=0o600)
        options.write_text(f'-P {password}\n', encoding='utf-8')
        environment['XDG_CONFIG_HOME'] = directory
        yield environment
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _drain_stderr(stream: typing.IO[str]) -> None:
    """Log everything ``mosquitto_sub`` writes to stderr.

    Args:
        stream: The child's stderr.
    """
    for line in stream:
        message = line.strip()
        if message:
            logger.warning('mosquitto_sub: %s', message)


def run_subscriber(
    command: typing.Sequence[str],
    environment: typing.Mapping[str, str],
    registry: Registry,
    stop: threading.Event,
    *,
    max_backoff: float = MAX_BACKOFF,
) -> None:
    """Run ``mosquitto_sub`` and feed its output into the registry, restarting as needed.

    ``mosquitto_sub`` reconnects on its own when the broker goes away and comes back, so
    in practice this loop only runs a second time when the subscriber dies outright: a
    missing binary, a rejected password, or a signal. Either way the registry simply
    stops being updated, which drives ``mosquitto_up`` to 0 once the staleness window
    passes, and the subscriber is restarted after a capped exponential backoff.

    Args:
        command: The argument vector for the subscriber.
        environment: The environment for the subscriber.
        registry: The registry to feed.
        stop: Set this to ask the loop to shut down.
        max_backoff: The longest gap between restart attempts, in seconds.
    """
    backoff = INITIAL_BACKOFF
    while not stop.is_set():
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(environment),
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except OSError as exc:
            logger.error('Could not start %s: %s', command[0], exc)
        else:
            _pump(process, registry, stop)
        if stop.is_set():
            return
        # A subscriber that stayed up for a good while is a transient failure, not a
        # misconfiguration, so do not punish it with the accumulated backoff.
        if time.monotonic() - started > max_backoff:
            backoff = INITIAL_BACKOFF
        logger.warning('Subscriber is not running; retrying in %.0fs.', backoff)
        stop.wait(backoff)
        backoff = min(backoff * 2, max_backoff)


def _pump(process: subprocess.Popen[str], registry: Registry, stop: threading.Event) -> None:
    """Read a running subscriber's output until it ends.

    Args:
        process: The running subscriber.
        registry: The registry to feed.
        stop: Set this to ask the pump to stop.
    """
    assert process.stdout is not None
    assert process.stderr is not None
    errors = threading.Thread(
        target=_drain_stderr, args=(process.stderr,), name='stderr', daemon=True
    )
    errors.start()
    try:
        for line in process.stdout:
            registry.update_from_line(line)
            if stop.is_set():
                break
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning('Error reading from subscriber: %s', exc)
    finally:
        terminate(process)


def terminate(process: subprocess.Popen[str], *, timeout: float = 5.0) -> None:
    """Stop a child process, escalating to SIGKILL if it will not go.

    Args:
        process: The process to stop.
        timeout: How long to wait for a clean exit before killing it.
    """
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning('Subscriber did not exit; killing it.')
        process.kill()
        process.wait()


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        The parser for this program's arguments.
    """
    parser = argparse.ArgumentParser(
        prog='mosquitto-exporter',
        description='Export Eclipse Mosquitto $SYS metrics in Prometheus text format.',
        # Without this, --password is accepted as an abbreviation of --password-file,
        # which is exactly the mistake this program refuses to allow.
        allow_abbrev=False,
    )
    parser.add_argument('--broker-host', default='127.0.0.1', help='broker host to connect to')
    parser.add_argument('--broker-port', type=int, default=1883, help='broker port to connect to')
    parser.add_argument('--username', default=None, help='MQTT username')
    parser.add_argument(
        '--password-file',
        default=None,
        help='file holding the MQTT password (a password is never accepted on the '
        'command line, where it would be visible in the process list)',
    )
    parser.add_argument(
        '--listen-address', default='127.0.0.1', help='address to serve /metrics on'
    )
    parser.add_argument('--listen-port', type=int, default=9234, help='port to serve /metrics on')
    parser.add_argument('--cafile', default=None, help='CA bundle for the broker TLS listener')
    parser.add_argument('--insecure', action='store_true', help='skip TLS hostname verification')
    parser.add_argument(
        '--mosquitto-sub-path',
        default=DEFAULT_MOSQUITTO_SUB,
        help='absolute path to the mosquitto_sub binary',
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
        type=str.upper,
        help='logging verbosity',
    )
    parser.add_argument('--version', action='version', version=__version__)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    """Run the exporter.

    Args:
        argv: The command-line arguments, or None to use ``sys.argv``.

    Returns:
        The process exit status.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level, format='%(asctime)s %(levelname)s %(name)s %(message)s'
    )

    password: str | None = None
    if args.password_file is not None:
        try:
            password = read_password(args.password_file)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            logger.error('Could not read the password file: %s', exc)
            return 1

    registry = Registry()
    try:
        server = build_server(args.listen_address, args.listen_port, registry)
    except OSError as exc:
        logger.error('Could not bind %s:%s: %s', args.listen_address, args.listen_port, exc)
        return 1

    command = build_subscriber_command(
        mosquitto_sub_path=args.mosquitto_sub_path,
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        username=args.username,
        cafile=args.cafile,
        insecure=args.insecure,
    )
    stop = threading.Event()

    def shutdown(signum: int, frame: types.FrameType | None) -> None:
        """Ask the exporter to shut down.

        Args:
            signum: The signal received.
            frame: The interrupted stack frame.
        """
        logger.info('Received signal %s; shutting down.', signal.Signals(signum).name)
        stop.set()
        threading.Thread(target=server.shutdown, name='shutdown', daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    with subscriber_environment(password) as environment:
        subscriber = threading.Thread(
            target=run_subscriber,
            args=(command, environment, registry, stop),
            name='subscriber',
            daemon=True,
        )
        subscriber.start()
        logger.info(
            'Serving Mosquitto metrics on http://%s:%s/metrics',
            args.listen_address,
            args.listen_port,
        )
        server.serve_forever()
        server.server_close()
        stop.set()
        subscriber.join(timeout=10.0)
    return 0


if __name__ == '__main__':
    sys.exit(main())
