# isabelle image (Phase 1)

Builds Isabelle/HOL + the Archive of Formal Proofs into one image and starts
`isabelle server` as its entrypoint.

Not yet wired into `compose.yaml` - the builder only generates `webui` and
`llm-gateway` so far (Phase 0). This image is a standalone build until the
agent (Phase 2) exists to run alongside it as a `network_mode: "service:isabelle"`
sidecar, per the design doc's §2 networking note.

## Build

```sh
docker build -t isabelle-afp isabelle/
# or: podman build -t isabelle-afp isabelle/
```

This downloads ~70 MB (AFP) on top of the base Isabelle image and can take a
while the first time. Verified working with Docker (2026-10-10).

## Running: no-COW volumes over `log/` are required on this host

One-time setup (host-level, survives across container instances but not
`docker volume rm`):

```sh
docker volume create isabelle-afp-user-heaplog
docker volume create isabelle-afp-dist-heaplog
sudo chattr +C "$(docker volume inspect isabelle-afp-user-heaplog --format '{{.Mountpoint}}')"
sudo chattr +C "$(docker volume inspect isabelle-afp-dist-heaplog --format '{{.Mountpoint}}')"
```

`chattr +C` must run while each volume directory is still empty - btrfs
only makes *new* files inherit no-COW from their parent directory, so
setting it after the volume has been populated is too late.

```sh
docker run --rm -d --name isabelle-afp \
  --mount type=volume,source=isabelle-afp-user-heaplog,destination=/home/isabelle/.isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log \
  --mount type=volume,source=isabelle-afp-dist-heaplog,destination=/home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log \
  isabelle-afp
docker exec -it isabelle-afp Isabelle/bin/isabelle client -n agent
```

**Why:** diagnosed 2026-10-11 as the known btrfs-COW / SQLite-WAL
incompatibility. Isabelle keeps small SQLite build-log databases under
both `log/` subdirectories above - one per session that gets built, under
the user heaps tree (`~/.isabelle/heaps/*/log/*.db`, e.g. for AFP entries)
and under the distribution's own baked-in heaps tree
(`Isabelle/heaps/*/log/{Pure,HOL}.db`, from the `isabelle build -b` step in
the Dockerfile). On this host's btrfs-backed Docker data-root, opening
those existing files through overlay2's copy-up hangs indefinitely at
~0% CPU (`docker stats`) - not a slow build, a genuine stall. It also once
surfaced as a hard `SQLITE_BUSY: database is locked` instead of hanging.
No-COW sidesteps btrfs for those files entirely and the stall disappears.

**Mount exactly these two `log/` subdirectories, not their parents.**
`~/.isabelle` also holds `etc/components` (the AFP registration from
`isabelle components -u`) and the actual compiled heap binaries for
anything built at runtime (e.g. `~/.isabelle/heaps/*/Example-Submission`) -
neither is disposable. An earlier version of this fix mounted tmpfs over
the whole `~/.isabelle` directory, which wiped both of those on every
restart; verified fixed by narrowing the mount to just `log/`.

**Why named volumes, not tmpfs (revised 2026-10-12):** tmpfs also sidesteps
btrfs, but starts empty on every container, so Isabelle never trusts the
pre-built heap as current and rebuilds HOL from source on *every* fresh
container - confirmed working (no hang), just always slow. A named volume
with `chattr +C` instead keeps the build-log database on real (no-COW)
storage, so it survives container restarts: on first use Docker seeds it
from the image's own baked-in log (from the Dockerfile's `isabelle build -b`
step), and once a session's been built once, later containers recognize
it as still valid and skip rebuilding it - only a changed image/AFP
version forces a rebuild again. Remove the volumes
(`docker volume rm isabelle-afp-user-heaplog isabelle-afp-dist-heaplog`)
to force a clean rebuild on demand.

If you move Docker's data-root to a non-btrfs (or no-COW-flagged)
filesystem, none of this (nor the `chattr +C` step) should be necessary -
not verified either way yet.

## Agent discovery: shared `server-info` volume

The agent (Phase 2) runs as a separate container sharing only this
container's network namespace (`network_mode: "service:isabelle"`), not
its filesystem, so it cannot read `~/.isabelle/servers.db` the way
`isabelle client` does. The entrypoint instead tees its startup line
(`server "agent" = 127.0.0.1:4443 (password "...")`, the only place that
password is ever printed) onto a small shared volume:

```sh
docker volume create isabelle-server-info
docker run --rm -d --name isabelle \
  --mount type=volume,source=isabelle-server-info,destination=/home/isabelle/server-info \
  ...
  isabelle-afp
```

The agent mounts the same volume read-only, polls
`server-info/registration.log` until the line appears, and parses
host/port/password out of it to connect directly over TCP (no Docker
socket access needed). See `agent/isabelle_tool.py`.

## Memory: heap caps + host swap are required on this host

A from-scratch HOL rebuild (above, now only on the first run or after an
image/AFP change) has an unbounded JVM
(`isabelle server`'s `ISABELLE_TOOL_JAVA_OPTIONS`, 4GB default) and an
unbounded PolyML build process (`ML_OPTIONS`, no default max at all) - on
this host's 15GB RAM, building HOL this way reliably OOM-killed the host
outright (`dmesg`: `Out of memory: Killed process (java)`, confirmed 5+
times, diagnosed 2026-10-12). Both get capped (6GB JVM / 6GB PolyML) in
the Dockerfile by writing `~/.isabelle/etc/settings` (`ISABELLE_HOME_USER`,
read last and wins - both vars are set with a bare `=` in the
distribution/component settings, so a `docker run -e` override alone gets
clobbered). The host also needs a bigger swap cushion than its default
256MB zram; bump it before running a build/test:

```sh
sudo swapoff /dev/zram0
sudo sh -c 'echo 1 > /sys/block/zram0/reset'
sudo sh -c 'echo 4G > /sys/block/zram0/disksize'
sudo mkswap /dev/zram0
sudo swapon -p 100 /dev/zram0
```

This is a manual, non-persistent bump (the 256MB default is set by an
Ansible-managed `/etc/default/zramswap` with `SWAP=false`, intentionally
not touched here) - redo it after a reboot.

**Build time varies a lot with host load.** With the caps above and no
other load, a fresh HOL+AFP rebuild takes ~7-8 minutes. This host is a
shared desktop, not a dedicated CI runner - under concurrent load (seen:
GPU video transcoding, torrenting) the same rebuild can stretch past 20-40
minutes without anything being wrong, hence `tests/test_isabelle_integration.py`'s
generous `SESSION_TIMEOUT`.

## Manual smoke test (Phase 1 goal) - verified

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
