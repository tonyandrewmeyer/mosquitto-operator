#!/bin/bash
# After `juju remove-unit`, does the surviving unit still see the removed unit in its
# relation, and does relation-departed fire? Covers both a peer relation and an
# ordinary provides/requires relation between two applications, in one model.
#
# Usage: run.sh <model-name> [path-to-charm]
set -u
MODEL="$1"
CHARM="${2:-$HOME/peertest/peertest_amd64.charm}"

units_idle() {  # units_idle <app> <count>
  juju status -m "$MODEL" --format=json 2>/dev/null | python3 -c "
import json,sys
u=json.load(sys.stdin).get('applications',{}).get('$1',{}).get('units',{})
sys.exit(0 if len(u)==$2 and all(x['juju-status']['current']=='idle' for x in u.values()) else 1)"
}

wait_for() {  # wait_for <app> <count> <tries>
  for _ in $(seq 1 "$3"); do units_idle "$1" "$2" && return 0; sleep 10; done
  return 1
}

members() {  # members <unit> <endpoint>
  local rid
  rid=$(juju exec -m "$MODEL" --unit "$1" -- "relation-ids $2" 2>/dev/null | tr -d '\r' | head -1)
  [ -z "$rid" ] && { echo "(no relation)"; return; }
  local out
  out=$(juju exec -m "$MODEL" --unit "$1" -- "relation-list -r $rid" 2>/dev/null | tr -d '\r')
  echo "${out:-(empty)}"
}

departed_count() {  # departed_count <unit> <endpoint>
  juju debug-log -m "$MODEL" --replay --include "unit-${1//\//-}" --no-tail 2>&1 \
    | grep -cE "ran \"$2-relation-departed\" hook" || true
}

echo "### juju version: $(juju version)"
juju add-model "$MODEL" >/dev/null 2>&1

# `a` is the far side of an ordinary relation; `b` has two units, so it has a peer
# relation as well. Removing b/1 therefore tests both kinds at once.
juju deploy "$CHARM" a -m "$MODEL" >/dev/null 2>&1
juju deploy "$CHARM" b -m "$MODEL" -n 2 >/dev/null 2>&1
wait_for a 1 90 && wait_for b 2 90 || { echo "!!! units never settled"; juju status -m "$MODEL"; exit 1; }
juju integrate -m "$MODEL" a:regular b:regular-req >/dev/null 2>&1
sleep 30
wait_for a 1 60 && wait_for b 2 60 || echo "!!! did not settle after integrate"

echo "### status before removal"
juju status -m "$MODEL" 2>&1 | sed -n '/^Unit/,/^$/p'
echo "### BEFORE  a/0 regular  : $(members a/0 regular)"
echo "### BEFORE  b/0 peers    : $(members b/0 peers)"
echo "### BEFORE  b/0 regular-req: $(members b/0 regular-req)"

echo "### removing b/1"
juju remove-unit -m "$MODEL" b/1 --no-prompt 2>&1 | tail -1
for _ in $(seq 1 60); do units_idle b 1 && break; sleep 10; done

echo "### waiting 180s for things to settle"
sleep 180

echo
echo "### AFTER   a/0 regular  : $(members a/0 regular)   <-- ordinary relation, remote side"
echo "### AFTER   b/0 peers    : $(members b/0 peers)   <-- peer relation, same application"
echo "### regular-relation-departed hooks on a/0 : $(departed_count a/0 regular)"
echo "### peers-relation-departed hooks on b/0   : $(departed_count b/0 peers)"
echo
echo "### final status"
juju status -m "$MODEL" 2>&1 | sed -n '/^Unit/,/^$/p'
echo "### DONE $MODEL"
