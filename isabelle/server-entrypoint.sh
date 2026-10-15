#!/bin/bash
# Supervises `isabelle server`, restarting it in place if it crashes.
#
# Deliberately does NOT let the container exit on a server crash: `agent`
# shares this container's network namespace (network_mode: "service:isabelle",
# design doc §2), and restarting the *container* would hand `agent` a stale,
# orphaned namespace instead of the new one - it would keep "running" but
# become unreachable until someone restarts it too. Restarting only the
# process in place keeps the namespace (and thus agent's connectivity)
# intact.
set -euo pipefail

child=""

terminate() {
    if [[ -n "$child" ]]; then
        kill -TERM "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    exit 0
}
trap terminate TERM INT

while true; do
    Isabelle/bin/isabelle server -n agent -p 4443 -L /home/isabelle/server.log \
        > >(tee /home/isabelle/server-info/registration.log) 2>&1 &
    child=$!
    status=0
    # `wait` on its own would trip `set -e` on a non-zero exit (e.g. an
    # OOM kill) and exit this script before the loop can restart the
    # server - exactly the case this supervisor exists to handle.
    wait "$child" || status=$?
    echo "isabelle server exited (status $status); restarting in 1s..." >&2
    sleep 1
done
