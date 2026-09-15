# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the standalone Mosquitto Prometheus exporter.

The exporter is deliberately split into pure functions (mapping, parsing, rendering), a
registry that only holds state, and a thin subprocess and HTTP layer. These tests
exercise the pure parts directly, and use fakes for the rest: no test here starts a real
subprocess or binds a real socket.
"""

import http.server
import io
import logging
import pathlib
import subprocess
import threading
import typing

import pytest

import exporter

# --------------------------------------------------------------------------------------
# parse_line
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('line', 'expected'),
    [
        ('$SYS/broker/clients/connected\t3\n', ('$SYS/broker/clients/connected', '3')),
        ('$SYS/broker/clients/connected\t3', ('$SYS/broker/clients/connected', '3')),
        ('$SYS/broker/clients/connected\t3\r\n', ('$SYS/broker/clients/connected', '3')),
        # The topic has an embedded space.
        (
            '$SYS/broker/retained messages/count\t53\n',
            ('$SYS/broker/retained messages/count', '53'),
        ),
        # The payload has an embedded space.
        ('$SYS/broker/uptime\t32 seconds\n', ('$SYS/broker/uptime', '32 seconds')),
        # An empty payload is legitimate: a cleared retained message.
        ('$SYS/broker/version\t\n', ('$SYS/broker/version', '')),
        # Only the first tab separates; any others belong to the payload.
        ('$SYS/broker/x\ta\tb\n', ('$SYS/broker/x', 'a\tb')),
    ],
)
def test_parse_line(line: str, expected: tuple[str, str]):
    assert exporter.parse_line(line) == expected


@pytest.mark.parametrize(
    'line',
    [
        '',
        '\n',
        'no tab at all\n',
        '$SYS/broker/uptime 32 seconds\n',  # space-separated, the old ambiguous format
        '\t3\n',  # empty topic
    ],
)
def test_parse_line_rejects(line: str):
    with pytest.raises(ValueError, match='subscriber output'):
        exporter.parse_line(line)


# --------------------------------------------------------------------------------------
# parse_value
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('payload', 'expected'),
    [
        ('0', 0.0),
        ('53', 53.0),
        ('1.80', 1.8),
        ('-1', -1.0),
        ('-0.5', -0.5),
        # $SYS/broker/uptime appends " seconds" to the number.
        ('32 seconds', 32.0),
        ('1 seconds', 1.0),
        ('   7   ', 7.0),
    ],
)
def test_parse_value(payload: str, expected: float):
    assert exporter.parse_value(payload) == expected


@pytest.mark.parametrize('payload', ['', 'seconds', 'not a number', '   ', 'NaN'])
def test_parse_value_rejects(payload: str):
    with pytest.raises(ValueError, match='no numeric value'):
        exporter.parse_value(payload)


# --------------------------------------------------------------------------------------
# map_topic
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize('topic', sorted(exporter.MAPPINGS))
def test_every_mapping_produces_exactly_one_sample(topic: str):
    """Every entry in the table maps cleanly, and the sapcc naming rule is respected."""
    mapping = exporter.MAPPINGS[topic]
    payload = 'mosquitto version 2.0.18' if mapping.label else '7'
    (sample,) = exporter.map_topic(topic, payload)

    assert sample.name == mapping.name
    assert sample.kind == mapping.kind
    assert sample.help == mapping.help
    assert sample.help.endswith('.')


@pytest.mark.parametrize('topic', sorted(exporter.MAPPINGS))
def test_mapping_names_are_valid_prometheus_identifiers(topic: str):
    name = exporter.MAPPINGS[topic].name
    assert name.isidentifier()
    assert name.islower()


def test_mapping_names_are_unique():
    names = [mapping.name for mapping in exporter.MAPPINGS.values()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    ('topic', 'payload', 'name', 'labels', 'value', 'kind'),
    [
        # Counters.
        ('$SYS/broker/bytes/received', '193', 'broker_bytes_received', (), 193.0, 'counter'),
        ('$SYS/broker/bytes/sent', '16361', 'broker_bytes_sent', (), 16361.0, 'counter'),
        ('$SYS/broker/messages/received', '17', 'broker_messages_received', (), 17.0, 'counter'),
        ('$SYS/broker/messages/sent', '415', 'broker_messages_sent', (), 415.0, 'counter'),
        (
            '$SYS/broker/publish/bytes/received',
            '21',
            'broker_publish_bytes_received',
            (),
            21.0,
            'counter',
        ),
        (
            '$SYS/broker/publish/bytes/sent',
            '1705',
            'broker_publish_bytes_sent',
            (),
            1705.0,
            'counter',
        ),
        (
            '$SYS/broker/publish/messages/received',
            '3',
            'broker_publish_messages_received',
            (),
            3.0,
            'counter',
        ),
        (
            '$SYS/broker/publish/messages/sent',
            '407',
            'broker_publish_messages_sent',
            (),
            407.0,
            'counter',
        ),
        (
            '$SYS/broker/publish/messages/dropped',
            '0',
            'broker_publish_messages_dropped',
            (),
            0.0,
            'counter',
        ),
        ('$SYS/broker/clients/maximum', '1', 'broker_clients_maximum', (), 1.0, 'counter'),
        ('$SYS/broker/clients/total', '1', 'broker_clients_total', (), 1.0, 'counter'),
        # The uptime payload carries a " seconds" suffix.
        ('$SYS/broker/uptime', '32 seconds', 'broker_uptime', (), 32.0, 'counter'),
        # Gauges.
        ('$SYS/broker/clients/connected', '1', 'broker_clients_connected', (), 1.0, 'gauge'),
        (
            '$SYS/broker/clients/disconnected',
            '4',
            'broker_clients_disconnected',
            (),
            4.0,
            'gauge',
        ),
        ('$SYS/broker/clients/expired', '2', 'broker_clients_expired', (), 2.0, 'gauge'),
        ('$SYS/broker/messages/stored', '53', 'broker_messages_stored', (), 53.0, 'gauge'),
        (
            '$SYS/broker/store/messages/count',
            '53',
            'broker_store_messages_count',
            (),
            53.0,
            'gauge',
        ),
        (
            '$SYS/broker/store/messages/bytes',
            '215',
            'broker_store_messages_bytes',
            (),
            215.0,
            'gauge',
        ),
        # The topic itself has an embedded space.
        (
            '$SYS/broker/retained messages/count',
            '53',
            'broker_retained_messages_count',
            (),
            53.0,
            'gauge',
        ),
        ('$SYS/broker/subscriptions/count', '1', 'broker_subscriptions_count', (), 1.0, 'gauge'),
        (
            '$SYS/broker/shared_subscriptions/count',
            '0',
            'broker_shared_subscriptions_count',
            (),
            0.0,
            'gauge',
        ),
        ('$SYS/broker/heap/current', '47192', 'broker_heap_current', (), 47192.0, 'gauge'),
        ('$SYS/broker/heap/maximum', '47760', 'broker_heap_maximum', (), 47760.0, 'gauge'),
        # Load averages: the window is part of the name, as sapcc emits it.
        (
            '$SYS/broker/load/messages/received/1min',
            '14.42',
            'broker_load_messages_received_1min',
            (),
            14.42,
            'gauge',
        ),
        (
            '$SYS/broker/load/messages/sent/5min',
            '42.27',
            'broker_load_messages_sent_5min',
            (),
            42.27,
            'gauge',
        ),
        (
            '$SYS/broker/load/publish/dropped/15min',
            '0.00',
            'broker_load_publish_dropped_15min',
            (),
            0.0,
            'gauge',
        ),
        (
            '$SYS/broker/load/publish/received/1min',
            '2.85',
            'broker_load_publish_received_1min',
            (),
            2.85,
            'gauge',
        ),
        (
            '$SYS/broker/load/publish/sent/5min',
            '38.82',
            'broker_load_publish_sent_5min',
            (),
            38.82,
            'gauge',
        ),
        (
            '$SYS/broker/load/bytes/received/15min',
            '12.72',
            'broker_load_bytes_received_15min',
            (),
            12.72,
            'gauge',
        ),
        (
            '$SYS/broker/load/bytes/sent/1min',
            '5598.91',
            'broker_load_bytes_sent_1min',
            (),
            5598.91,
            'gauge',
        ),
        (
            '$SYS/broker/load/connections/1min',
            '5.07',
            'broker_load_connections_1min',
            (),
            5.07,
            'gauge',
        ),
        (
            '$SYS/broker/load/sockets/15min',
            '0.40',
            'broker_load_sockets_15min',
            (),
            0.4,
            'gauge',
        ),
        # An info-style metric: the payload becomes a label and the value is 1.
        (
            '$SYS/broker/version',
            'mosquitto version 2.0.18',
            'mosquitto_broker_info',
            (('version', 'mosquitto version 2.0.18'),),
            1.0,
            'gauge',
        ),
        # Bridge state is matched by pattern, with the bridge name as a label.
        (
            '$SYS/broker/connection/upstream.bridge/state',
            '1',
            'mosquitto_bridge_state',
            (('bridge', 'upstream.bridge'),),
            1.0,
            'gauge',
        ),
        (
            '$SYS/broker/connection/edge-01/state',
            '0',
            'mosquitto_bridge_state',
            (('bridge', 'edge-01'),),
            0.0,
            'gauge',
        ),
    ],
)
def test_map_topic(
    topic: str,
    payload: str,
    name: str,
    labels: tuple[tuple[str, str], ...],
    value: float,
    kind: exporter.MetricKind,
):
    assert exporter.map_topic(topic, payload) == [
        exporter.Sample(name, labels, value, kind, exporter.map_topic(topic, payload)[0].help)
    ]


@pytest.mark.parametrize(
    'topic',
    [
        # Deliberately ignored.
        '$SYS/broker/timestamp',
        '$SYS/broker/clients/active',
        '$SYS/broker/clients/inactive',
        '$SYS/broker/log/E',
        '$SYS/broker/log/W',
        '$SYS/broker/log/M/subscribe',
        # Genuinely unknown: skipped rather than guessed at.
        '$SYS/broker/something/new',
        '$SYS/broker',
        '$SYS/broker/connection/bridge/notstate',
        '$SYS/broker/load/messages/received/30min',
        'devices/sensor/1/temperature',
    ],
)
def test_map_topic_skips(topic: str):
    assert exporter.map_topic(topic, '1') == []


@pytest.mark.parametrize(
    'payload',
    ['', 'not a number', 'seconds'],
)
def test_map_topic_rejects_unusable_payload(payload: str):
    with pytest.raises(ValueError, match='no numeric value'):
        exporter.map_topic('$SYS/broker/clients/connected', payload)


def test_map_topic_accepts_any_payload_for_info_metrics():
    """An info metric's payload is a label, so it never has to be a number."""
    (sample,) = exporter.map_topic('$SYS/broker/version', 'mosquitto version 2.1.2')
    assert sample.labels == (('version', 'mosquitto version 2.1.2'),)
    assert sample.value == 1.0


def test_load_table_is_complete():
    load = [topic for topic in exporter.MAPPINGS if topic.startswith('$SYS/broker/load/')]
    assert len(load) == 9 * 3
    for topic in load:
        assert topic.endswith(('/1min', '/5min', '/15min'))


# --------------------------------------------------------------------------------------
# Escaping, formatting and rendering
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('plain', 'plain'),
        ('a\\b', 'a\\\\b'),
        ('a\nb', 'a\\nb'),
        # Quotes are not escaped in help text.
        ('say "hi"', 'say "hi"'),
    ],
)
def test_escape_help(text: str, expected: str):
    assert exporter.escape_help(text) == expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('plain', 'plain'),
        ('a\\b', 'a\\\\b'),
        ('say "hi"', 'say \\"hi\\"'),
        ('a\nb', 'a\\nb'),
        # The backslash escape has to happen first, or it doubles the others.
        ('a\\"b', 'a\\\\\\"b'),
    ],
)
def test_escape_label_value(value: str, expected: str):
    assert exporter.escape_label_value(value) == expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [(0.0, '0'), (1.0, '1'), (53.0, '53'), (-1.0, '-1'), (1.5, '1.5'), (0.4, '0.4')],
)
def test_format_value(value: float, expected: str):
    assert exporter.format_value(value) == expected


def test_render_empty():
    assert exporter.render([]) == '\n'


def test_render_single_counter():
    sample = exporter.Sample('broker_uptime', (), 32.0, 'counter', 'Seconds since start.')
    assert exporter.render([sample]) == (
        '# HELP broker_uptime Seconds since start.\n'
        '# TYPE broker_uptime counter\n'
        'broker_uptime 32\n'
    )


def test_render_single_gauge_with_labels():
    sample = exporter.Sample(
        'mosquitto_bridge_state', (('bridge', 'edge-01'),), 0.0, 'gauge', 'Bridge state.'
    )
    assert exporter.render([sample]) == (
        '# HELP mosquitto_bridge_state Bridge state.\n'
        '# TYPE mosquitto_bridge_state gauge\n'
        'mosquitto_bridge_state{bridge="edge-01"} 0\n'
    )


def test_render_groups_a_family_under_one_help_and_type():
    samples = [
        exporter.Sample('m', (('b', 'two'),), 2.0, 'gauge', 'Help.'),
        exporter.Sample('m', (('b', 'one'),), 1.0, 'gauge', 'Help.'),
    ]
    assert exporter.render(samples) == (
        '# HELP m Help.\n# TYPE m gauge\nm{b="one"} 1\nm{b="two"} 2\n'
    )


def test_render_orders_families_by_name():
    samples = [
        exporter.Sample('zebra', (), 1.0, 'gauge', 'Z.'),
        exporter.Sample('alpha', (), 2.0, 'counter', 'A.'),
    ]
    names = [line for line in exporter.render(samples).splitlines() if line.startswith('# TYPE')]
    assert names == ['# TYPE alpha counter', '# TYPE zebra gauge']


def test_render_renders_multiple_labels_in_order():
    sample = exporter.Sample('m', (('a', '1'), ('b', '2')), 1.0, 'gauge', 'Help.')
    assert 'm{a="1",b="2"} 1' in exporter.render([sample])


def test_render_escapes():
    sample = exporter.Sample(
        'm', (('v', 'a "quoted\\value'),), 1.0, 'gauge', 'A\\backslash and a\nnewline.'
    )
    rendered = exporter.render([sample])
    assert '# HELP m A\\\\backslash and a\\nnewline.' in rendered
    assert 'm{v="a \\"quoted\\\\value"} 1' in rendered


def test_render_always_ends_with_a_newline():
    assert exporter.render([exporter.Sample('m', (), 1.0, 'gauge', 'H.')]).endswith('\n')


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------


def test_registry_starts_empty():
    registry = exporter.Registry()
    assert registry.last_update is None
    assert registry.is_up(now=0.0) is False


def test_registry_update_records_the_latest_value():
    registry = exporter.Registry()
    assert registry.update('$SYS/broker/clients/connected', '1', now=1.0) == 1
    assert registry.update('$SYS/broker/clients/connected', '5', now=2.0) == 1
    assert 'broker_clients_connected 5' in registry.render(now=2.0)
    assert 'broker_clients_connected 1' not in registry.render(now=2.0)


def test_registry_keeps_label_variants_apart():
    registry = exporter.Registry()
    registry.update('$SYS/broker/connection/a/state', '1', now=1.0)
    registry.update('$SYS/broker/connection/b/state', '0', now=1.0)
    rendered = registry.render(now=1.0)
    assert 'mosquitto_bridge_state{bridge="a"} 1' in rendered
    assert 'mosquitto_bridge_state{bridge="b"} 0' in rendered


def test_registry_update_skips_unmapped_topics():
    registry = exporter.Registry()
    assert registry.update('$SYS/broker/brand/new', '1', now=1.0) == 0
    assert 'brand' not in registry.render(now=1.0)


def test_registry_logs_each_unmapped_topic_once(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger='mosquitto-exporter')
    registry = exporter.Registry()
    for _ in range(3):
        registry.update('$SYS/broker/brand/new', '1', now=1.0)
    registry.update('$SYS/broker/other/new', '1', now=1.0)

    messages = [
        record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG
    ]
    assert sum('$SYS/broker/brand/new' in message for message in messages) == 1
    assert sum('$SYS/broker/other/new' in message for message in messages) == 1


def test_registry_does_not_log_deliberately_ignored_topics(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger='mosquitto-exporter')
    registry = exporter.Registry()
    registry.update('$SYS/broker/clients/active', '1', now=1.0)
    assert not [record for record in caplog.records if 'No metric mapping' in record.getMessage()]


def test_registry_update_propagates_a_bad_payload():
    registry = exporter.Registry()
    with pytest.raises(ValueError, match='no numeric value'):
        registry.update('$SYS/broker/clients/connected', 'oops', now=1.0)


@pytest.mark.parametrize(
    ('line', 'recorded'),
    [
        ('$SYS/broker/clients/connected\t3\n', 1),
        ('$SYS/broker/retained messages/count\t53\n', 1),
        ('$SYS/broker/uptime\t32 seconds\n', 1),
        # Malformed or unusable: discarded, never raised.
        ('no tab here\n', 0),
        ('\n', 0),
        ('$SYS/broker/clients/connected\toops\n', 0),
        ('$SYS/broker/clients/connected\t\n', 0),
        ('$SYS/broker/unknown/thing\t1\n', 0),
    ],
)
def test_registry_update_from_line_never_raises(line: str, recorded: int):
    registry = exporter.Registry()
    assert registry.update_from_line(line, now=1.0) == recorded


def test_registry_update_from_line_warns_about_malformed_input(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger='mosquitto-exporter')
    registry = exporter.Registry()
    registry.update_from_line('no tab here\n', now=1.0)
    registry.update_from_line('$SYS/broker/clients/connected\toops\n', now=1.0)
    assert len(caplog.records) == 2
    assert all(record.levelno == logging.WARNING for record in caplog.records)


def test_registry_records_liveness_even_for_ignored_topics():
    """A topic we do not export is still evidence that the broker is alive."""
    registry = exporter.Registry()
    registry.update('$SYS/broker/clients/active', '1', now=10.0)
    assert registry.last_update == 10.0
    assert registry.is_up(now=10.0) is True


def test_registry_does_not_record_liveness_for_a_malformed_line():
    registry = exporter.Registry()
    registry.update_from_line('no tab here\n', now=10.0)
    assert registry.last_update is None


@pytest.mark.parametrize(
    ('last_update', 'now', 'expected'),
    [
        (None, 100.0, False),
        (100.0, 100.0, True),
        (100.0, 130.0, True),
        (100.0, 160.0, True),  # exactly on the boundary
        (100.0, 160.1, False),
        (100.0, 1000.0, False),
    ],
)
def test_registry_up_transitions(last_update: float | None, now: float, expected: bool):
    registry = exporter.Registry(stale_after=60.0)
    if last_update is not None:
        registry.update('$SYS/broker/clients/connected', '1', now=last_update)
    assert registry.is_up(now=now) is expected


def test_registry_up_recovers_after_going_stale():
    registry = exporter.Registry(stale_after=10.0)
    registry.update('$SYS/broker/clients/connected', '1', now=0.0)
    assert registry.is_up(now=5.0) is True
    assert registry.is_up(now=50.0) is False
    registry.update('$SYS/broker/clients/connected', '1', now=50.0)
    assert registry.is_up(now=50.0) is True


def test_registry_renders_up_zero_when_nothing_was_ever_received():
    registry = exporter.Registry()
    rendered = registry.render(now=0.0)
    assert '# TYPE mosquitto_up gauge' in rendered
    assert 'mosquitto_up 0' in rendered


def test_registry_renders_up_one_when_receiving():
    registry = exporter.Registry()
    registry.update('$SYS/broker/clients/connected', '1', now=0.0)
    assert 'mosquitto_up 1' in registry.render(now=1.0)


def test_registry_always_renders_build_info():
    registry = exporter.Registry()
    rendered = registry.render(now=0.0)
    assert f'mosquitto_exporter_build_info{{version="{exporter.__version__}"}} 1' in rendered


def test_registry_snapshot_is_a_copy():
    registry = exporter.Registry()
    registry.update('$SYS/broker/clients/connected', '1', now=0.0)
    snapshot = registry.snapshot(now=0.0)
    registry.update('$SYS/broker/clients/connected', '9', now=0.0)
    assert any(sample.value == 1.0 for sample in snapshot)


def test_registry_uses_the_real_clock_by_default():
    registry = exporter.Registry()
    registry.update('$SYS/broker/clients/connected', '1')
    assert registry.last_update is not None
    assert registry.is_up() is True


def test_registry_render_of_a_full_update_is_valid_exposition():
    registry = exporter.Registry()
    for line in (
        '$SYS/broker/clients/connected\t1\n',
        '$SYS/broker/uptime\t32 seconds\n',
        '$SYS/broker/retained messages/count\t53\n',
        '$SYS/broker/version\tmosquitto version 2.0.18\n',
    ):
        registry.update_from_line(line, now=0.0)

    rendered = registry.render(now=0.0)
    families = [line.split()[2] for line in rendered.splitlines() if line.startswith('# TYPE')]
    assert families == sorted(families)
    # Every HELP is followed by its TYPE, and every family appears exactly once.
    assert len(families) == len(set(families))
    assert rendered.count('# HELP ') == len(families)
    for line in rendered.splitlines():
        if not line.startswith('#'):
            assert len(line.rsplit(' ', 1)) == 2


# --------------------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------------------


class FakeHandler(exporter.MetricsHandler):
    """A handler with the socket plumbing replaced, so no real socket is needed."""

    def __init__(self, registry: exporter.Registry, path: str):
        self._registry = registry
        self.path = path
        self.sent: list[tuple[int, str, str]] = []

    def _respond(self, status: int, content_type: str, body: str) -> None:
        self.sent.append((status, content_type, body))


@pytest.mark.parametrize(
    ('path', 'status', 'content_type', 'needle'),
    [
        ('/metrics', 200, 'text/plain; version=0.0.4; charset=utf-8', 'mosquitto_up'),
        ('/metrics?foo=bar', 200, 'text/plain; version=0.0.4; charset=utf-8', 'mosquitto_up'),
        ('/', 200, 'text/html; charset=utf-8', 'Mosquitto exporter'),
        ('/nope', 404, 'text/plain; charset=utf-8', 'not found'),
        ('/metrics/', 404, 'text/plain; charset=utf-8', 'not found'),
    ],
)
def test_handler_routes(path: str, status: int, content_type: str, needle: str):
    handler = FakeHandler(exporter.Registry(), path)
    handler.do_GET()
    assert len(handler.sent) == 1
    assert handler.sent[0][0] == status
    assert handler.sent[0][1] == content_type
    assert needle in handler.sent[0][2]


def test_handler_serves_200_before_anything_is_received():
    """A broker we cannot reach must still produce a scrapeable mosquitto_up 0."""
    handler = FakeHandler(exporter.Registry(), '/metrics')
    handler.do_GET()
    status, _, body = handler.sent[0]
    assert status == 200
    assert 'mosquitto_up 0' in body


def test_handler_log_message_goes_to_debug(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG, logger='mosquitto-exporter')
    handler = FakeHandler(exporter.Registry(), '/')

    def address_string(self: FakeHandler) -> str:
        return '127.0.0.1'

    monkeypatch.setattr(FakeHandler, 'address_string', address_string, raising=False)
    handler.log_message('%s %s', 'GET', '/')
    assert 'GET /' in caplog.text


# --------------------------------------------------------------------------------------
# Subscriber command, password handling and environment
# --------------------------------------------------------------------------------------


def test_build_subscriber_command_minimal():
    assert exporter.build_subscriber_command(
        mosquitto_sub_path='/usr/bin/mosquitto_sub', broker_host='10.0.0.1', broker_port=1883
    ) == [
        '/usr/bin/mosquitto_sub',
        '-h',
        '10.0.0.1',
        '-p',
        '1883',
        '-t',
        '$SYS/#',
        '-q',
        '0',
        '-F',
        '%t\\t%p',
    ]


@pytest.mark.parametrize(
    ('kwargs', 'expected'),
    [
        ({'username': 'metrics'}, ['-u', 'metrics']),
        ({'cafile': '/etc/ssl/ca.pem'}, ['--cafile', '/etc/ssl/ca.pem']),
        ({'insecure': True}, ['--insecure']),
        (
            {'username': 'm', 'cafile': '/ca.pem', 'insecure': True},
            ['-u', 'm', '--cafile', '/ca.pem', '--insecure'],
        ),
    ],
)
def test_build_subscriber_command_options(kwargs: dict[str, typing.Any], expected: list[str]):
    command = exporter.build_subscriber_command(
        mosquitto_sub_path='/usr/bin/mosquitto_sub',
        broker_host='127.0.0.1',
        broker_port=8883,
        **kwargs,
    )
    for index, argument in enumerate(command):
        if argument == expected[0]:
            assert command[index : index + len(expected)] == expected
            break
    else:
        pytest.fail(f'{expected} not found in {command}')


@pytest.mark.parametrize('kwargs', [{}, {'username': 'm'}, {'insecure': True}])
def test_build_subscriber_command_never_contains_a_password(kwargs: dict[str, typing.Any]):
    command = exporter.build_subscriber_command(
        mosquitto_sub_path='/usr/bin/mosquitto_sub',
        broker_host='127.0.0.1',
        broker_port=1883,
        **kwargs,
    )
    assert '-P' not in command
    assert '--pw' not in command


def test_build_subscriber_command_uses_an_absolute_path():
    command = exporter.build_subscriber_command(
        mosquitto_sub_path=exporter.DEFAULT_MOSQUITTO_SUB,
        broker_host='127.0.0.1',
        broker_port=1883,
    )
    assert command[0].startswith('/')


@pytest.mark.parametrize(
    ('contents', 'expected'),
    [('hunter2', 'hunter2'), ('hunter2\n', 'hunter2'), ('  hunter2  \n', 'hunter2')],
)
def test_read_password(tmp_path: pathlib.Path, contents: str, expected: str):
    path = tmp_path / 'pw'
    path.write_text(contents, encoding='utf-8')
    assert exporter.read_password(str(path)) == expected


@pytest.mark.parametrize('contents', ['', '\n', '   '])
def test_read_password_rejects_an_empty_file(tmp_path: pathlib.Path, contents: str):
    path = tmp_path / 'pw'
    path.write_text(contents, encoding='utf-8')
    with pytest.raises(ValueError, match='is empty'):
        exporter.read_password(str(path))


def test_read_password_rejects_a_missing_file(tmp_path: pathlib.Path):
    with pytest.raises(FileNotFoundError):
        exporter.read_password(str(tmp_path / 'nope'))


def test_subscriber_environment_without_a_password():
    with exporter.subscriber_environment(None) as environment:
        assert (
            'XDG_CONFIG_HOME' not in environment
            or 'mosquitto-exporter-' not in (environment['XDG_CONFIG_HOME'])
        )


def test_subscriber_environment_writes_a_private_options_file():
    with exporter.subscriber_environment('hunter2') as environment:
        directory = pathlib.Path(environment['XDG_CONFIG_HOME'])
        options = directory / 'mosquitto_sub'
        assert options.read_text(encoding='utf-8') == '-P hunter2\n'
        # Readable only by the exporter's own user.
        assert options.stat().st_mode & 0o077 == 0
        assert directory.stat().st_mode & 0o077 == 0
    assert not directory.exists()


def test_subscriber_environment_cleans_up_after_an_error():
    directory = None
    with pytest.raises(RuntimeError, match='boom'):  # noqa: PT012
        with exporter.subscriber_environment('hunter2') as environment:
            directory = pathlib.Path(environment['XDG_CONFIG_HOME'])
            raise RuntimeError('boom')
    assert directory is not None
    assert not directory.exists()


# --------------------------------------------------------------------------------------
# Subprocess plumbing, with a fake process
# --------------------------------------------------------------------------------------


class FakeStream:
    """A stdout or stderr replacement that yields prepared lines."""

    def __init__(
        self,
        lines: typing.Iterable[str] = (),
        on_exhausted: typing.Callable[[], object] | None = None,
    ):
        self._lines = list(lines)
        self._on_exhausted = on_exhausted

    def __iter__(self) -> typing.Iterator[str]:
        yield from self._lines
        if self._on_exhausted is not None:
            self._on_exhausted()


class FakeProcess:
    """Stands in for subprocess.Popen, without ever forking anything."""

    def __init__(
        self,
        stdout_lines: typing.Iterable[str] = (),
        stderr_lines: typing.Iterable[str] = (),
        on_exhausted: typing.Callable[[], object] | None = None,
    ):
        self.stdout = FakeStream(stdout_lines, on_exhausted)
        self.stderr = FakeStream(stderr_lines)
        self.terminated = False
        self.killed = False
        self.returncode: int | None = None
        self.wait_raises = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_raises:
            self.wait_raises = False
            raise subprocess.TimeoutExpired('mosquitto_sub', timeout or 0)
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


def test_terminate_stops_a_running_process():
    process = FakeProcess()
    exporter.terminate(typing.cast('typing.Any', process))
    assert process.terminated is True
    assert process.killed is False


def test_terminate_leaves_an_exited_process_alone():
    process = FakeProcess()
    process.returncode = 0
    exporter.terminate(typing.cast('typing.Any', process))
    assert process.terminated is False


def test_terminate_escalates_to_kill(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger='mosquitto-exporter')
    process = FakeProcess()
    process.wait_raises = True
    exporter.terminate(typing.cast('typing.Any', process), timeout=0.0)
    assert process.killed is True
    assert 'killing it' in caplog.text


def test_drain_stderr_logs_warnings(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger='mosquitto-exporter')
    exporter._drain_stderr(
        typing.cast('typing.Any', FakeStream(['Error: Connection refused\n', '\n', ' \n']))
    )
    assert 'Error: Connection refused' in caplog.text
    assert len(caplog.records) == 1


def test_run_subscriber_feeds_the_registry(monkeypatch: pytest.MonkeyPatch):
    registry = exporter.Registry()
    stop = threading.Event()
    # The loop ends once the subscriber's output is exhausted.
    process = FakeProcess(
        ['$SYS/broker/clients/connected\t7\n', '$SYS/broker/uptime\t9 seconds\n'],
        ['Error: something\n'],
        on_exhausted=stop.set,
    )

    def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        return process

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    exporter.run_subscriber(['/usr/bin/mosquitto_sub'], {}, registry, stop)

    rendered = registry.render(now=registry.last_update or 0.0)
    assert 'broker_clients_connected 7' in rendered
    assert 'broker_uptime 9' in rendered
    assert process.terminated is True


def test_run_subscriber_survives_a_malformed_line(monkeypatch: pytest.MonkeyPatch):
    registry = exporter.Registry()
    stop = threading.Event()
    process = FakeProcess(
        ['rubbish\n', '$SYS/broker/clients/connected\t7\n'], on_exhausted=stop.set
    )

    def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        return process

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    exporter.run_subscriber(['/usr/bin/mosquitto_sub'], {}, registry, stop)
    assert 'broker_clients_connected 7' in registry.render(now=registry.last_update or 0.0)


def test_run_subscriber_backs_off_when_the_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.WARNING, logger='mosquitto-exporter')
    stop = threading.Event()
    attempts: list[float] = []

    def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        attempts.append(0.0)
        if len(attempts) >= 3:
            stop.set()
        raise OSError('no such file')

    waits: list[float] = []

    def fake_wait(timeout: float | None = None) -> bool:
        waits.append(timeout or 0.0)
        return stop.is_set()

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(stop, 'wait', fake_wait)
    exporter.run_subscriber(['/usr/bin/nope'], {}, exporter.Registry(), stop, max_backoff=8.0)

    assert len(attempts) == 3
    # Capped exponential backoff, doubling each time.
    assert waits == [1.0, 2.0]
    assert 'retrying in' in caplog.text


def test_run_subscriber_caps_the_backoff(monkeypatch: pytest.MonkeyPatch):
    stop = threading.Event()
    waits: list[float] = []

    def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        if len(waits) >= 6:
            stop.set()
        raise OSError('no such file')

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)

    def fake_wait(timeout: float | None = None) -> bool:
        assert timeout is not None
        waits.append(timeout)
        return stop.is_set()

    monkeypatch.setattr(stop, 'wait', fake_wait)
    exporter.run_subscriber(['/usr/bin/nope'], {}, exporter.Registry(), stop, max_backoff=4.0)

    assert max(waits) == 4.0


def test_run_subscriber_returns_immediately_when_already_stopped(monkeypatch: pytest.MonkeyPatch):
    stop = threading.Event()
    stop.set()

    def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        pytest.fail('the subscriber should not be started when stop is already set')

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    exporter.run_subscriber(['/usr/bin/mosquitto_sub'], {}, exporter.Registry(), stop)


# --------------------------------------------------------------------------------------
# Command-line surface
# --------------------------------------------------------------------------------------


def test_parser_defaults():
    args = exporter.build_parser().parse_args([])
    assert args.broker_host == '127.0.0.1'
    assert args.broker_port == 1883
    assert args.username is None
    assert args.password_file is None
    assert args.listen_address == '127.0.0.1'
    assert args.listen_port == 9234
    assert args.cafile is None
    assert args.insecure is False
    assert args.mosquitto_sub_path == '/usr/bin/mosquitto_sub'
    assert args.log_level == 'INFO'


@pytest.mark.parametrize(
    ('argv', 'attribute', 'expected'),
    [
        (['--broker-host', 'broker.example.com'], 'broker_host', 'broker.example.com'),
        (['--broker-port', '8883'], 'broker_port', 8883),
        (['--username', 'metrics'], 'username', 'metrics'),
        (['--password-file', '/var/lib/x/pw'], 'password_file', '/var/lib/x/pw'),
        (['--listen-address', '0.0.0.0'], 'listen_address', '0.0.0.0'),  # noqa: S104
        (['--listen-port', '9999'], 'listen_port', 9999),
        (['--cafile', '/etc/ssl/ca.pem'], 'cafile', '/etc/ssl/ca.pem'),
        (['--insecure'], 'insecure', True),
        (['--mosquitto-sub-path', '/snap/bin/x'], 'mosquitto_sub_path', '/snap/bin/x'),
        (['--log-level', 'DEBUG'], 'log_level', 'DEBUG'),
        # The level is case-insensitive, which is friendlier in a systemd unit.
        (['--log-level', 'debug'], 'log_level', 'DEBUG'),
    ],
)
def test_parser_options(argv: list[str], attribute: str, expected: object):
    assert getattr(exporter.build_parser().parse_args(argv), attribute) == expected


@pytest.mark.parametrize(
    'argv',
    [
        ['--broker-port', 'not-a-number'],
        ['--listen-port', 'not-a-number'],
        ['--log-level', 'CHATTY'],
        ['--unknown-option'],
        # A password must never be accepted on the command line.
        ['--password', 'hunter2'],
    ],
)
def test_parser_rejects(argv: list[str]):
    with pytest.raises(SystemExit):
        exporter.build_parser().parse_args(argv)


def test_parser_has_no_password_option():
    actions = {
        option for action in exporter.build_parser()._actions for option in action.option_strings
    }
    assert '--password' not in actions
    assert '--pass' not in actions
    assert '-P' not in actions
    assert '--password-file' in actions


def test_main_reports_an_unreadable_password_file(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.ERROR, logger='mosquitto-exporter')
    assert exporter.main(['--password-file', str(tmp_path / 'missing')]) == 1
    assert 'password file' in caplog.text.lower()


def test_main_reports_a_failure_to_bind(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.ERROR, logger='mosquitto-exporter')

    def fake_build_server(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        raise OSError('address already in use')

    monkeypatch.setattr(exporter, 'build_server', fake_build_server)
    assert exporter.main([]) == 1
    assert 'could not bind' in caplog.text.lower()


def test_handler_respond_writes_a_complete_response(monkeypatch: pytest.MonkeyPatch):
    handler = FakeHandler(exporter.Registry(), '/metrics')
    sent: list[tuple[str, object]] = []
    written = io.BytesIO()

    def send_response(self: FakeHandler, code: int) -> None:
        sent.append(('status', code))

    def send_header(self: FakeHandler, key: str, value: str) -> None:
        sent.append((key, value))

    def end_headers(self: FakeHandler) -> None:
        sent.append(('end', None))

    monkeypatch.setattr(FakeHandler, 'send_response', send_response)
    monkeypatch.setattr(FakeHandler, 'send_header', send_header)
    monkeypatch.setattr(FakeHandler, 'end_headers', end_headers)
    handler.wfile = written

    exporter.MetricsHandler._respond(handler, 200, 'text/plain', 'hello\n')

    assert sent == [
        ('status', 200),
        ('Content-Type', 'text/plain'),
        ('Content-Length', '6'),
        ('end', None),
    ]
    assert written.getvalue() == b'hello\n'


def test_handler_init_sets_the_registry_before_handling(monkeypatch: pytest.MonkeyPatch):
    """The base class serves the whole request from __init__, so ordering matters."""
    registry = exporter.Registry()
    seen: list[object] = []

    def fake_init(self: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
        seen.append(self._registry)

    monkeypatch.setattr(http.server.BaseHTTPRequestHandler, '__init__', fake_init)
    exporter.MetricsHandler(registry=registry)
    assert seen == [registry]


def test_pump_survives_a_read_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.WARNING, logger='mosquitto-exporter')

    class ExplodingStream:
        def __iter__(self) -> typing.Iterator[str]:
            raise OSError('broken pipe')
            yield  # pragma: no cover

    process = FakeProcess()
    process.stdout = typing.cast('typing.Any', ExplodingStream())

    exporter._pump(typing.cast('typing.Any', process), exporter.Registry(), threading.Event())

    assert 'broken pipe' in caplog.text
    assert process.terminated is True


def test_run_subscriber_resets_the_backoff_after_a_long_run(monkeypatch: pytest.MonkeyPatch):
    """A subscriber that ran for ages failed transiently; do not punish it."""
    stop = threading.Event()
    waits: list[float] = []
    clock = iter([0.0, 1000.0, 1000.0, 2000.0, 2000.0, 3000.0])

    def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        if len(waits) >= 2:
            stop.set()
        return FakeProcess()

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(exporter.time, 'monotonic', lambda: next(clock))

    def fake_wait(timeout: float | None = None) -> bool:
        assert timeout is not None
        waits.append(timeout)
        return stop.is_set()

    monkeypatch.setattr(stop, 'wait', fake_wait)
    exporter.run_subscriber(
        ['/usr/bin/mosquitto_sub'], {}, exporter.Registry(), stop, max_backoff=8.0
    )

    assert waits == [1.0, 1.0]


def test_the_staleness_window_is_configurable():
    """A fixed window pages on a healthy broker whose `sys_interval` is longer.

    `mosquitto_up` drops to zero between publishes, and the critical alert fires on a
    broker that is working perfectly well.
    """
    registry = exporter.Registry(stale_after=900.0)
    registry.update('$SYS/broker/uptime', '5 seconds', now=0.0)

    assert registry.is_up(now=300.0)
    assert not registry.is_up(now=1000.0)


def test_the_connection_ceiling_is_exported():
    """So that the alert threshold follows the configured limit, not a default."""
    registry = exporter.Registry(max_connections=5000)

    samples = {sample.name: sample.value for sample in registry.snapshot()}

    assert samples['mosquitto_max_connections'] == 5000.0


def test_an_unlimited_broker_exports_no_ceiling():
    """A ratio alert against a limit that does not exist should never fire."""
    registry = exporter.Registry()

    assert 'mosquitto_max_connections' not in {sample.name for sample in registry.snapshot()}


def test_the_parser_accepts_the_staleness_and_ceiling_options():
    """These are how the charm passes the broker's configuration to the exporter."""
    args = exporter.build_parser().parse_args(
        ['--stale-after', '900', '--max-connections', '5000']
    )

    assert args.stale_after == 900.0
    assert args.max_connections == 5000


def test_the_options_have_conservative_defaults():
    """Run by hand, with no charm to pass anything, nothing should page or lie."""
    args = exporter.build_parser().parse_args([])

    assert args.stale_after == exporter.STALE_AFTER
    assert args.max_connections == -1
