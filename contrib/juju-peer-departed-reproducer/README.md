# Juju 4.x: a removed unit never leaves its *peer* relation

A minimal reproducer for the Juju behaviour that makes
`tests/integration/test_charm.py::test_removing_the_extra_unit_returns_the_application_to_active`
skip on Juju 4.x, and that is described in
[docs/explanation/one-unit-and-bridging.md](../../docs/explanation/one-unit-and-bridging.md).

It is here so the skip reason can be checked rather than taken on trust. It has nothing
to do with Mosquitto, and can be deleted once the bug is fixed or filed elsewhere.

## The behaviour

After `juju remove-unit b/1` completes and the unit has gone from `juju status`, on
Juju 4.x the surviving unit of the same application:

- still sees the removed unit in `relation-list` on its **peer** relation, and
- never receives a peer `relation-departed` event.

**Ordinary provides/requires relations are unaffected** — the far side of a normal
relation correctly drops the removed unit and does get `relation-departed`. So this is
specific to peer relations, not to unit removal in general.

Juju 3.6 gets both right.

## Results

Measured 2026-09-15 and 2026-09-16, LXD on Ubuntu 24.04, one machine per unit. Both
kinds of relation are exercised in a single model by the same run: `a` is related to `b`
on an ordinary endpoint, `b` has two units and therefore also a peer relation, and `b/1`
is removed.

| Juju | Ordinary relation (`a/0`) | | Peer relation (`b/0`) | |
| --- | --- | --- | --- | --- |
| | `relation-list` | `relation-departed` | `relation-list` | `relation-departed` |
| **3.6.28** | drops `b/1` ✅ | fires ✅ | empty ✅ | fires ✅ |
| **4.0.14** | drops `b/1` ✅ | fires ✅ | **still lists `b/1`** ❌ | **never** ❌ |
| **4.1-beta3** (`4.1/edge`) | — | — | **still lists `b/1`** ❌ | **never** ❌ |
| **4.2-beta1** (`4.2/edge`) | drops `b/1` ✅ | fires ✅ | **still lists `b/1`** ❌ | **never** ❌ |

`4.2/edge` was the newest build available, so this is present at the head of the 4.x
line rather than being a 4.0-only regression. (The 4.1 row covers the peer case only;
it was measured before the reproducer grew the ordinary-relation half.)

## What it is not

- **Not a timing issue.** The script waits 180 seconds after the unit leaves
  `juju status`. The same behaviour was also observed on 4.0.14 twenty-five minutes and
  five `update-status` hooks after removal.
- **Not a stale cache in the unit agent.** `relation-list` is run through `juju exec`,
  which builds a fresh hook context each time, so the controller itself still believes
  the unit is in the relation.
- **Not about storage.** This charm declares none. (Separately, and only for charms
  that do: `juju remove-unit` on a unit with storage attached waits for that storage
  indefinitely without saying so, and needs `--destroy-storage --no-prompt`.)
- **Not a documented 4.x change.** The [hook reference][hooks] defines
  `relation-departed` as *"Emitted when a unit departs from an existing relation"* and
  lists scale-down as a trigger, with no version caveat, and the
  [4.0.0 release notes][rn400] do not mention relation departure, relation membership
  or unit removal semantics among the breaking changes.

[hooks]: https://canonical.com/juju/docs/juju-cli/latest/reference/hook/
[rn400]: https://canonical.com/juju/docs/juju-cli/latest/releasenotes/juju_4.0.x/juju_4.0.0/

## Why it matters

Any charm whose behaviour depends on how many peers exist — a "this workload does not
cluster" guard, a quorum calculation, a leader hand-off — cannot recover from a
scale-down on 4.x. The peer relation is the only way a charm can ask, and there is no
event to act on. Excluding `event.departing_unit` from the count, which is the usual
fix for counting a departing peer, has no event to run in.

## Running it

```bash
charmcraft pack
./run.sh <model-name> ./peertest_amd64.charm
```

It deploys `a` (one unit) and `b` (two units), integrates them, removes `b/1`, and
prints what each survivor can see plus the hooks that ran. A correct result looks like
the 3.6 row: `a/0` and `b/0` both drop `b/1`, and both `relation-departed` counts are 1.

## The charm

`src/charm.py` has no workload, no storage and no dependencies beyond `ops`. It reports
its relation membership in its status message on every event, and logs
`relation-departed` with the departing unit. That is all.

## Prior art searched

No matching issue found in `juju/juju` (searched 2026-09-16). The closest, all
different: [#21678][] (`destroy-model` hangs waiting for units to leave scope — a unit
in *error* that cannot run its departing hook; fixed February 2026), [#20214][]
(`relation-broken` ordering relative to `relation-departed`), [#20041][] (missing
`peers-relation-created`), [#20713][] (`relation-broken` fired for a peer relation
during a K8s refresh).

Possibly relevant background: [PR #20835][pr20835], *"leave relation scopes upon forced
unit removal"*, which handles scope-leaving explicitly on the **forced** path and notes
that it does so *"without waiting for the uniter to do so"* — the happy path still
relies on the uniter, which is where this gap appears to be.

[#21678]: https://github.com/juju/juju/issues/21678
[#20214]: https://github.com/juju/juju/issues/20214
[#20041]: https://github.com/juju/juju/issues/20041
[#20713]: https://github.com/juju/juju/issues/20713
[pr20835]: https://github.com/juju/juju/pull/20835
