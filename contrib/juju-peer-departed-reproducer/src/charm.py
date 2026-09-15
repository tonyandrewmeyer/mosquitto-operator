#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
"""Report what this unit sees on its peer relation."""

import logging

import ops

logger = logging.getLogger(__name__)

PEER = 'peers'


class PeerTestCharm(ops.CharmBase):
    """Log peer membership on every event, and note relation-departed loudly."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for event in (
            self.on.install,
            self.on.start,
            self.on.config_changed,
            self.on.update_status,
            self.on[PEER].relation_created,
            self.on[PEER].relation_joined,
            self.on[PEER].relation_changed,
        ):
            framework.observe(event, self._report)
        framework.observe(self.on[PEER].relation_departed, self._departed)
        framework.observe(self.on.collect_unit_status, self._status)

    def _peers(self) -> list[str]:
        relation = self.model.get_relation(PEER)
        return sorted(unit.name for unit in relation.units) if relation else []

    def _report(self, event: ops.EventBase) -> None:
        logger.info('PEERTEST %s: peers=%s', event.__class__.__name__, self._peers())

    def _departed(self, event: ops.RelationDepartedEvent) -> None:
        logger.info(
            'PEERTEST RelationDepartedEvent: departing=%s peers=%s',
            event.departing_unit.name if event.departing_unit else None,
            self._peers(),
        )

    def _status(self, event: ops.CollectStatusEvent) -> None:
        peers = self._peers()
        event.add_status(ops.ActiveStatus(f'peers={",".join(peers) or "none"}'))


if __name__ == '__main__':
    ops.main(PeerTestCharm)
