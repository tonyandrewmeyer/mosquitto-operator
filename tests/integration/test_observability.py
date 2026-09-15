# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# pytest-jubilant gives each test file its own model through the module-scoped `juju`
# fixture, so this module can run as its own CI job.

"""Metrics, alert rules and dashboards, over the `cos-agent` integration.

The subordinate is `opentelemetry-collector` rather than `grafana-agent`: the machine
grafana-agent charm is end of life, and opentelemetry-collector is the charm Canonical
now ships for this job. It is a machine subordinate, it requires `cos-agent` with the
`cos_agent` interface, and its current track on Charmhub is 0.130 with a 24.04 base.
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
COLLECTOR = 'opentelemetry-collector'
COLLECTOR_CHANNEL = '0.130/stable'
UNIT = f'{APP}/0'
EXPORTER_SERVICE = 'mosquitto-charm-exporter'
METRICS_PORT = 9234

# The two the alert rules are written against: one means data loss, the other is how
# anybody notices a broker nothing is talking to.
REQUIRED_METRICS = ('broker_publish_messages_dropped', 'broker_clients_connected')


def mosquitto_is_ready(status: jubilant.Status) -> bool:
    """Whether the broker is up.

    The collector itself stays blocked until it has somewhere to send telemetry, and
    this module deliberately does not deploy the whole of COS, so `all_active` is not
    the right predicate here.
    """
    return jubilant.all_agents_idle(status, APP) and status.apps[APP].is_active


def metrics(juju: jubilant.Juju) -> str:
    """Scrape the exporter the way the collector does."""
    address = juju.status().apps[APP].units[UNIT].public_address
    result = juju.exec(
        f'/usr/bin/curl -sS --max-time 20 http://{address}:{METRICS_PORT}/metrics',
        unit=UNIT,
        wait=90,
    )
    return result.stdout


def cos_agent_data(juju: jubilant.Juju) -> dict[str, object]:
    """What the charm published on the `cos-agent` relation.

    The cos_agent library puts everything — scrape jobs, alert rules and dashboards —
    into one JSON blob in the unit databag.
    """
    info = juju.show_unit(UNIT)
    for relation in info.relation_info:
        if relation.endpoint != 'cos-agent':
            continue
        assert relation.local_unit is not None
        return json.loads(relation.local_unit.data['config'])
    raise AssertionError('no cos-agent relation data on the unit')


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Mosquitto with the collector subordinate alongside it."""
    juju.deploy(charm, app=APP)
    juju.deploy(COLLECTOR, channel=COLLECTOR_CHANNEL)
    juju.integrate(f'{APP}:cos-agent', f'{COLLECTOR}:cos-agent')
    juju.wait(mosquitto_is_ready, timeout=1200)


def test_the_exporter_is_running(juju: jubilant.Juju):
    """It only runs when something is collecting, which is now the case."""
    assert helpers.service_is_running(juju, UNIT, EXPORTER_SERVICE)


def test_the_metrics_endpoint_serves_the_metrics_the_alerts_use(juju: jubilant.Juju):
    scraped = metrics(juju)

    for metric in REQUIRED_METRICS:
        assert metric in scraped, f'{metric} is missing, so the alert rule on it can never fire'
    # `$SYS/broker/retained messages/count` has a space in its topic, which is the one
    # that naive parsing drops.
    assert 'broker_retained_messages_count' in scraped


def test_the_exporter_binds_to_the_unit_address_not_loopback(juju: jubilant.Juju):
    """The collector scrapes over the network, so loopback would serve nothing."""
    address = juju.status().apps[APP].units[UNIT].public_address
    listening = juju.exec(f'/bin/sh -c "ss -ltn | grep {METRICS_PORT}"', unit=UNIT, wait=60).stdout
    # Either the unit's own address, or every interface.
    assert address in listening or '0.0.0.0' in listening  # noqa: S104


def test_the_scrape_job_reaches_the_collector(juju: jubilant.Juju):
    config = cos_agent_data(juju)

    jobs = config['metrics_scrape_jobs']
    assert jobs, 'the collector was told about no scrape jobs'
    assert json.dumps(jobs).find(str(METRICS_PORT)) != -1


def test_the_alert_rules_reach_the_collector(juju: jubilant.Juju):
    """Rules that stay in the charm's source directory alert on nothing."""
    config = cos_agent_data(juju)

    rules = config['metrics_alert_rules']
    assert rules, 'no alert rules were published on the cos-agent relation'
    serialised = json.dumps(rules)
    for metric in REQUIRED_METRICS:
        assert metric in serialised, f'nothing alerts on {metric}'


def test_the_dashboards_reach_the_collector(juju: jubilant.Juju):
    config = cos_agent_data(juju)

    assert config['dashboards'], 'no dashboards were published on the cos-agent relation'


def test_the_broker_stats_action_agrees_with_the_exporter(juju: jubilant.Juju):
    """Both read the same `$SYS` tree, so they should not disagree about it."""
    task = juju.run(UNIT, 'broker-stats')
    assert task.success
    stats = json.loads(task.results['stats'])

    assert '$SYS/broker/clients/connected' in stats
    assert 'broker_clients_connected' in metrics(juju)


def test_turning_off_sys_stops_the_exporter(juju: jubilant.Juju):
    """With `$SYS` disabled there is nothing for the exporter to read."""
    juju.config(APP, {'sys-interval': 0})
    juju.wait(mosquitto_is_ready, timeout=600)

    assert not helpers.service_is_running(juju, UNIT, EXPORTER_SERVICE)

    juju.config(APP, {'sys-interval': 10})
    juju.wait(mosquitto_is_ready, timeout=600)
    assert helpers.service_is_running(juju, UNIT, EXPORTER_SERVICE)


def test_removing_the_integration_removes_the_exporter(juju: jubilant.Juju):
    juju.remove_relation(f'{APP}:cos-agent', f'{COLLECTOR}:cos-agent')
    juju.wait(mosquitto_is_ready, timeout=900)

    assert not helpers.service_is_running(juju, UNIT, EXPORTER_SERVICE)
    unit_file = helpers.exec_allowed_to_fail(
        juju, UNIT, f'/usr/bin/test -f /etc/systemd/system/{EXPORTER_SERVICE}.service'
    )
    assert unit_file is None, 'the exporter unit file outlived the integration'
    # The broker itself is untouched by any of this.
    assert helpers.service_is_running(juju, UNIT)
