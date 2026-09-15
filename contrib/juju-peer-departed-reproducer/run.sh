#!/bin/bash
# Reproduce: after `juju remove-unit`, does the surviving unit still see the removed
# unit in its peer relation, and does peer relation-departed fire?
#
# Usage: peertest-run.sh <model-name>
set -u
MODEL="$1"
CHARM=$HOME/peertest/peertest_amd64.charm

echo "### juju version: $(juju version)"
juju add-model "$MODEL" >/dev/null 2>&1
juju deploy "$CHARM" peertest -m "$MODEL" -n 2 >/dev/null 2>&1

echo "### waiting for two idle units"
for _ in $(seq 1 90); do
  n=$(juju status -m "$MODEL" --format=json 2>/dev/null | python3 -c '
import json,sys
u=json.load(sys.stdin).get("applications",{}).get("peertest",{}).get("units",{})
print(sum(1 for x in u.values() if x["juju-status"]["current"]=="idle"))' 2>/dev/null || echo 0)
  [ "$n" = "2" ] && break
  sleep 10
done
echo "### status before removal"
juju status -m "$MODEL" 2>&1 | sed -n '/^Unit/,/^$/p'
echo "### relation-list on peertest/0 before removal"
juju exec -m "$MODEL" --unit peertest/0 -- 'relation-list -r peers:0' 2>&1 | tr -d '\r'

echo "### removing peertest/1"
juju remove-unit -m "$MODEL" peertest/1 --no-prompt 2>&1 | tail -1
for _ in $(seq 1 60); do
  n=$(juju status -m "$MODEL" --format=json 2>/dev/null | python3 -c '
import json,sys
print(len(json.load(sys.stdin).get("applications",{}).get("peertest",{}).get("units",{})))' 2>/dev/null || echo 2)
  [ "$n" = "1" ] && break
  sleep 10
done
echo "### units left in juju status: $n"

echo "### waiting 180s for things to settle"
sleep 180

echo "### relation-list on peertest/0 AFTER removal"
juju exec -m "$MODEL" --unit peertest/0 -- 'relation-list -r peers:0' 2>&1 | tr -d '\r'
echo "### did peer relation-departed fire on peertest/0?"
juju debug-log -m "$MODEL" --replay --include unit-peertest-0 --no-tail 2>&1 \
  | grep -cE 'peers-relation-departed|RelationDepartedEvent' || true
echo "### hooks that ran on peertest/0"
juju debug-log -m "$MODEL" --replay --include unit-peertest-0 --no-tail 2>&1 \
  | grep -oE 'ran "[a-z0-9-]+" hook' | sort | uniq -c
echo "### final status"
juju status -m "$MODEL" 2>&1 | sed -n '/^Unit/,/^$/p'
echo "### DONE $MODEL"
