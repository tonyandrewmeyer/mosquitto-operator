# Juju: a removed unit is never removed from its peer relation

A minimal reproducer for the Juju behaviour that makes
`tests/integration/test_charm.py::test_removing_the_extra_unit_returns_the_application_to_active`
skip on Juju 4.x, and that is described in
[docs/explanation/one-unit-and-bridging.md](../../docs/explanation/one-unit-and-bridging.md).

It is here so the skip reason can be checked rather than taken on trust. It has nothing
to do with Mosquitto, and can be deleted if the bug is fixed or reported elsewhere.

## The behaviour

After `juju remove-unit app/1` completes and the unit has gone from `juju status`, on
Juju 4.x the surviving unit:

- still sees the removed unit in `relation-list` on the peer relation, and
- never receives a peer `relation-departed` event.

Juju 3.6 does both correctly.

This matters for any charm whose behaviour depends on how many peers exist — a
"this workload does not cluster" check, a quorum calculation, a leader hand-off. The
peer relation is the only way a charm can ask, so there is nothing it can do about it:
excluding `event.departing_unit` is the right fix in principle, but the event never
arrives.

The `relation-list` above is run through `juju exec`, which builds a fresh hook context
each time, so this is not a stale cache in the unit agent — the controller still
believes the unit is a member of the relation.

## Results

Measured on 2026-09-15 and 2026-09-16, LXD on Ubuntu 24.04, one machine per unit.

| Juju | `relation-list` after removal | `relation-departed` fired | Charm's reported peers |
| --- | --- | --- | --- |
| 3.6.28 | *(empty)* | yes | `peers=none` |
| 4.0.14 | `peertest/1` | **no** | `peers=peertest/1` |
| 4.1-beta3 (`4.1/edge`) | `peertest/1` | **no** | `peers=peertest/1` |
| 4.2-beta1 (`4.2/edge`) | `peertest/1` | **no** | `peers=peertest/1` |

`4.2/edge` was the newest build available at the time, so this is still present at the
head of the 4.x line rather than being a 4.0-only regression.

The script waits 180 seconds after the unit disappears from `juju status`. It is not a
matter of waiting longer: the same behaviour was observed on 4.0.14 twenty-five minutes
and five `update-status` hooks after removal.

The charm here has **no storage, no workload and no dependencies beyond `ops`**, which
rules out storage detachment as the cause. (Separately, and only relevant to charms that
do declare storage: `juju remove-unit` on a unit with storage attached waits for that
storage indefinitely without saying so, and needs `--destroy-storage --no-prompt`.)

## Running it

```bash
cd contrib/juju-peer-departed-reproducer
charmcraft pack
cp peertest_amd64.charm ~/peertest/       # run.sh looks for ~/peertest/peertest_amd64.charm
./run.sh <model-name>
```

`run.sh` deploys two units, prints what the surviving unit sees before and after
`juju remove-unit`, and lists the hooks that ran. A correct result looks like the 3.6
row above: an empty `relation-list`, a `peers-relation-departed` hook, and
`peers=none`.

## The charm

`src/charm.py` has no workload. It reports its peer relation membership in its status
message on every event, and logs `RelationDepartedEvent` with the departing unit. That
is all.
