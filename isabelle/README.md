# isabelle image (Fáze 1)

Builds Isabelle/HOL + the Archive of Formal Proofs into one image and starts
`isabelle server` as its entrypoint.

Not yet wired into `compose.yaml` - the builder only generates `webui` and
`llm-gateway` so far (Fáze 0). This image is a standalone build until the
agent (Fáze 2) exists to run alongside it as a `network_mode: "service:isabelle"`
sidecar, per the design doc's §2 networking note.

## Build

```sh
docker build -t isabelle-afp isabelle/
# or: podman build -t isabelle-afp isabelle/
```

This downloads ~70 MB (AFP) on top of the base Isabelle image and can take a
while the first time. Also pre-builds the `HOL` and `Example-Submission` heap
images (`isabelle build -b`) so a fresh container doesn't have to build them
from scratch on first use. Verified working with Docker (2026-10-10).

## Manual smoke test (Fáze 1 goal) - verified, with a caveat

```sh
docker run --rm -d --name isabelle-afp isabelle-afp
docker exec -it isabelle-afp Isabelle/bin/isabelle client -n agent
```

The `-n agent` matters: `isabelle client` defaults to looking for a server
named `isabelle`, but the entrypoint starts the server as `-n agent` (see
`Dockerfile`). Without a matching `-n`, the client fails with
`*** Isabelle server "isabelle" not running`.

```json
session_start {"session": "HOL"}
```

returns `OK` with a task id, streams `NOTE` progress messages, and should
end with `FINISHED` and a session id.

**Known issue (2026-10-11, unresolved):** on this machine, `session_start`
sometimes stalls indefinitely at `"Starting session HOL ..."` with
`docker stats` showing ~1% CPU - not actually computing, just stuck. Once
surfaced as a hard `SQLITE_BUSY: database is locked` error instead of a
stall. `docker top` confirms the process is *loading* the pre-built
Pure/HOL heap, not rebuilding it, so this isn't the heap-build problem the
pre-build step above targets - something about Isabelle's SQLite build
database doesn't get along with this host's Docker data-root
(`/mnt/stash/@docker`, `btrfs` on a `_netdev` i.e. network-backed block
device - confirmed `/srv` is a symlink to the same volume, not a separate
local disk). `/` is local SSD `btrfs` but only has ~12 GB free. Not fixed
yet; moving Docker's data-root to local disk is the next thing to try if
this keeps reproducing. See `tests/test_isabelle_integration.py`.
