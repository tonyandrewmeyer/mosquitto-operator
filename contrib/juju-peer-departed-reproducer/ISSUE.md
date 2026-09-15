# Draft bug report for juju/juju

Filled against `.github/ISSUE_TEMPLATE/bug-report.yml` as of 2026-09-16. The headings
below are the template's fields; paste each into the matching box on
<https://github.com/juju/juju/issues/new?template=bug-report.yml>.

The form applies `kind/bug` and `needs-triage` automatically.

---

## Description

On Juju 4.x, removing a unit does not remove it from its application's **peer**
relation. After `juju remove-unit b/1` has completed and `b/1` has gone from
`juju status`:

- `relation-list` on the surviving unit `b/0` still returns `b/1`, and
- `b/0` never runs a `peers-relation-departed` hook.

Ordinary provides/requires relations are **not** affected: the far side of a normal
relation drops the removed unit and does run `<endpoint>-relation-departed`. The same
`remove-unit` therefore behaves correctly for one kind of relation and not the other.

Juju 3.6 handles both correctly.

This is not recoverable from inside a charm. A charm's only way to ask how many peers
exist is that relation, and no event is delivered to prompt it to re-check, so any
charm whose behaviour depends on peer count — a quorum calculation, a leader hand-off,
a "this workload does not cluster, refuse to run more than one unit" guard — stays
wrong indefinitely after a scale-down. The usual fix for counting a departing peer,
excluding `event.departing_unit`, has no event to run in.

---

## Juju version

4.0.14 (also reproduced on 4.1-beta3 and 4.2-beta1; 3.6.28 is unaffected)

---

## Cloud

LXD

---

## Expected behaviour

After `juju remove-unit b/1` completes, `b/0` should run `peers-relation-departed` and
`relation-list` on its peer relation should no longer return `b/1` — which is what
Juju 3.6.28 does, and what the documentation describes.

[The hook reference](https://canonical.com/juju/docs/juju-cli/latest/reference/hook/)
defines `<endpoint>-relation-departed` as *"Emitted when a unit departs from an
existing relation"* and lists *"when a related application is scaled down"* among its
triggers, with no version caveat. The
[4.0.0 release notes](https://canonical.com/juju/docs/juju-cli/latest/releasenotes/juju_4.0.x/juju_4.0.0/)
do not mention any change to relation departure, relation membership, or unit removal
semantics, so this appears to be a regression rather than an intended change. Please
say if it is intended, and the documentation can be updated instead.

---

## Reproduce / Test

A charm with a peer endpoint is needed; its body can be empty, because the observation
is made with `relation-list` and `juju debug-log`. `b` is given two units so it has a
peer relation, and is related to `a` so that an ordinary relation is exercised by the
same removal.

```bash
mkdir -p peertest/src && cd peertest

cat > charmcraft.yaml <<'EOF'
type: charm
name: peertest
title: peertest
summary: Minimal charm with a peer relation and an ordinary relation.
description: Minimal charm with a peer relation and an ordinary relation.
base: ubuntu@24.04
platforms:
  amd64:
parts:
  charm:
    plugin: uv
    source: .
    build-snaps: [astral-uv]
peers:
  peers:
    interface: peertest
provides:
  regular:
    interface: peertest-regular
requires:
  regular-req:
    interface: peertest-regular
EOF

cat > pyproject.toml <<'EOF'
[project]
name = "peertest"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = ["ops~=3.8"]
EOF

cat > src/charm.py <<'EOF'
#!/usr/bin/env python3
import ops


class PeerTestCharm(ops.CharmBase):
    """Does nothing. The hooks are observed through juju debug-log."""


if __name__ == '__main__':
    ops.main(PeerTestCharm)
EOF

uv lock && charmcraft pack

juju add-model peertest
juju deploy ./peertest_amd64.charm a
juju deploy ./peertest_amd64.charm b -n 2
juju integrate a:regular b:regular-req
# wait for all three units to go idle

# Membership before removal.
juju exec --unit b/0 -- 'relation-list -r "$(relation-ids peers)"'         # -> b/1
juju exec --unit a/0 -- 'relation-list -r "$(relation-ids regular)"'       # -> b/0, b/1

juju remove-unit b/1 --no-prompt
# wait for b/1 to disappear from juju status, then give it a minute

# Membership after removal.
juju exec --unit b/0 -- 'relation-list -r "$(relation-ids peers)"'
juju exec --unit a/0 -- 'relation-list -r "$(relation-ids regular)"'

# Which departed hooks ran.
juju debug-log --replay --include unit-b-0 --no-tail | grep 'relation-departed'
juju debug-log --replay --include unit-a-0 --no-tail | grep 'relation-departed'
```

The steps above were run verbatim, with that exact no-op charm, on both versions; the
output below is what they printed.

### Actual result on 4.0.14

```
$ juju exec --unit b/0 -- 'relation-list -r "$(relation-ids peers)"'
b/1                                     # <-- still listed; b/1 no longer exists

$ juju exec --unit a/0 -- 'relation-list -r "$(relation-ids regular)"'
b/0                                     # <-- correct

$ juju debug-log --replay --include unit-b-0 --no-tail | grep relation-departed
                                        # <-- no output at all

$ juju debug-log --replay --include unit-a-0 --no-tail | grep relation-departed
unit-a-0: 01:06:21 INFO juju.worker.uniter.operation ran "regular-relation-departed" hook (via hook dispatching script: dispatch)
```

### Expected result, as seen on 3.6.28

```
$ juju exec --unit b/0 -- 'relation-list -r "$(relation-ids peers)"'
                                        # <-- empty

$ juju exec --unit a/0 -- 'relation-list -r "$(relation-ids regular)"'
b/0

$ juju debug-log --replay --include unit-b-0 --no-tail | grep relation-departed
unit-b-0: 01:01:29 INFO juju.worker.uniter.operation ran "peers-relation-departed" hook (via hook dispatching script: dispatch)

$ juju debug-log --replay --include unit-a-0 --no-tail | grep relation-departed
unit-a-0: 01:01:29 INFO juju.worker.uniter.operation ran "regular-relation-departed" hook (via hook dispatching script: dispatch)
```

---

## Notes & References

### Version matrix

Measured 2026-09-15 and 2026-09-16, LXD on Ubuntu 24.04, one machine per unit, with
the charm above.

| Juju | Ordinary relation: `relation-list` / departed | Peer relation: `relation-list` / departed |
| --- | --- | --- |
| 3.6.28 | drops the unit / fires | empty / fires |
| 4.0.14 | drops the unit / fires | **still lists it / never fires** |
| 4.1-beta3 (`4.1/edge`) | not measured | **still lists it / never fires** |
| 4.2-beta1 (`4.2/edge`) | drops the unit / fires | **still lists it / never fires** |

`4.2/edge` was the newest build available, so this is present at the head of the 4.x
line and not only in 4.0.

### What it is not

- **Not a timing issue.** The measurements above are taken 180 seconds after the unit
  leaves `juju status`. On 4.0.14 the same state was also observed twenty-five minutes
  and five `update-status` hooks after removal.
- **Not a stale cache in the unit agent.** `relation-list` is run through `juju exec`,
  which builds a fresh hook context, so the controller itself still reports the unit as
  a member.
- **Not related to storage.** This charm declares none. (Noted separately in case it is
  the same area of code: `juju remove-unit` on a unit that *does* have storage attached
  waits on that storage indefinitely with no message, and needs `--destroy-storage`.)
- **Not unit removal in general**, and not relation teardown in general — an ordinary
  relation on the same model, torn down by the same `remove-unit`, behaves correctly.

### Possibly related

- #21678 — `destroy-model` hangs "waiting for units to leave scope". Different: that is
  a unit *in error* that cannot run its departing hook, and it was fixed in February
  2026. Here the units are healthy and idle and the removal completes.
- #20214 — `relation-broken` appears before all units got `relation-departed`
  (ordering, not absence).
- #20041 — missing / inconsistent `peers-relation-created`.
- #20713 — `relation-broken` fired for a peer relation during a refresh on Kubernetes.
- PR #20835, *"leave relation scopes upon forced unit removal"*, may be the relevant
  area: it leaves relation scopes explicitly on the **forced** path *"without waiting
  for the uniter to do so"*, which suggests the happy path still relies on the uniter
  to leave scope. That is where this looks like it is going wrong, for peer relations
  only.

I could not find an existing issue for this, but the search was not exhaustive and I
cannot see internal Jira.

### Reproducer

A packaged version of the above, including a `run.sh` that deploys, removes and prints
the before/after membership and hook list for both relation kinds:
<https://github.com/tonyandrewmeyer/mosquitto-operator/tree/main/contrib/juju-peer-departed-reproducer>
