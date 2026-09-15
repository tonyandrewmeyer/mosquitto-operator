#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Report what this unit sees on each of its relations.

Deployed twice and integrated with itself, this covers both cases in one model: a peer
relation, and an ordinary provides/requires relation between two applications.
"""

import logging

import ops

logger = logging.getLogger(__name__)

PEER = 'peers'
PROVIDES = 'regular'
REQUIRES = 'regular-req'
ENDPOINTS = (PEER, PROVIDES, REQUIRES)


class PeerTestCharm(ops.CharmBase):
    """Log relation membership on every event, and note relation-departed loudly."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for event in (self.on.install, self.on.start, self.on.config_changed,
                      self.on.update_status):  # fmt: skip
            framework.observe(event, self._report)
        for endpoint in ENDPOINTS:
            framework.observe(self.on[endpoint].relation_created, self._report)
            framework.observe(self.on[endpoint].relation_joined, self._report)
            framework.observe(self.on[endpoint].relation_changed, self._report)
            framework.observe(self.on[endpoint].relation_departed, self._departed)
            framework.observe(self.on[endpoint].relation_broken, self._broken)
        framework.observe(self.on.collect_unit_status, self._status)

    def _members(self, endpoint: str) -> list[str]:
        """The units this unit can see on an endpoint, across every relation on it."""
        return sorted(
            unit.name for relation in self.model.relations[endpoint] for unit in relation.units
        )

    def _summary(self) -> str:
        parts = [
            f'{endpoint}={",".join(self._members(endpoint)) or "none"}'
            for endpoint in ENDPOINTS
            if self.model.relations[endpoint]
        ]
        return ' '.join(parts) or 'no relations'

    def _report(self, event: ops.EventBase) -> None:
        logger.info('PEERTEST %s: %s', event.__class__.__name__, self._summary())

    def _departed(self, event: ops.RelationDepartedEvent) -> None:
        logger.info(
            'PEERTEST DEPARTED on %s: departing=%s now %s',
            event.relation.name,
            event.departing_unit.name if event.departing_unit else None,
            self._summary(),
        )

    def _broken(self, event: ops.RelationBrokenEvent) -> None:
        logger.info('PEERTEST BROKEN on %s: now %s', event.relation.name, self._summary())

    def _status(self, event: ops.CollectStatusEvent) -> None:
        event.add_status(ops.ActiveStatus(self._summary()))


if __name__ == '__main__':
    ops.main(PeerTestCharm)
