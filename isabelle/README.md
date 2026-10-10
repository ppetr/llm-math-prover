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
while the first time. Verified working with Docker (2026-10-10).

## Running: `--tmpfs` is required on this host

```sh
docker run --rm -d --name isabelle-afp \
  --tmpfs /home/isabelle/.isabelle:uid=1001,gid=1001,mode=1777 \
  --tmpfs /home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log:uid=1001,gid=1001,mode=1777 \
  isabelle-afp
docker exec -it isabelle-afp Isabelle/bin/isabelle client -n agent
```

**Why:** diagnosed 2026-10-11 as the known btrfs-COW / SQLite-WAL
incompatibility. Isabelle keeps small SQLite build-log databases both under
the user dir (`~/.isabelle/host.db`, `servers.db`, per-session `.db` files)
and under the distribution's own baked-in heaps dir
(`Isabelle/heaps/*/log/HOL.db`, from the `isabelle build -b` step in the
Dockerfile). On this host's btrfs-backed Docker data-root, opening those
existing files through overlay2's copy-up hangs indefinitely at ~0% CPU
(`docker stats`) - not a slow build, a genuine stall. It also once
surfaced as a hard `SQLITE_BUSY: database is locked` instead of hanging.
Mounting tmpfs over both log directories sidesteps btrfs for those files
entirely and the stall disappears.

**Tradeoff:** tmpfs starts empty, so Isabelle no longer trusts the
pre-built HOL heap as current and rebuilds it from source on every fresh
container (confirmed: progresses normally through each theory, finishing
in a few minutes, not instant but no longer hanging). The Dockerfile's
`isabelle build -b` step is still worth keeping as a build-time correctness
check, even though it no longer buys a fast container start on this host.

If you move Docker's data-root to a non-btrfs (or no-COW-flagged)
filesystem, these `--tmpfs` flags should become unnecessary and container
starts should go back to being fast - not verified either way yet.

## Manual smoke test (Fáze 1 goal) - verified

```json
session_start {"session": "HOL"}
```

returns `OK` with a task id, streams `NOTE` progress messages, and ends
with `FINISHED` and a session id. The `-n agent` on the client call matters:
`isabelle client` defaults to looking for a server named `isabelle`, but
the entrypoint starts the server as `-n agent` (see `Dockerfile`). Without
a matching `-n`, the client fails with
`*** Isabelle server "isabelle" not running`.

See `tests/test_isabelle_integration.py` for the automated version
(`pytest -m integration`).
