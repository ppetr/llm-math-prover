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
  --tmpfs /home/isabelle/.isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log:uid=1001,gid=1001,mode=1777 \
  --tmpfs /home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log:uid=1001,gid=1001,mode=1777 \
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
Mounting tmpfs over just these two `log/` directories sidesteps btrfs for
those files entirely and the stall disappears.

**Mount exactly these two `log/` subdirectories, not their parents.**
`~/.isabelle` also holds `etc/components` (the AFP registration from
`isabelle components -u`) and the actual compiled heap binaries for
anything built at runtime (e.g. `~/.isabelle/heaps/*/Example-Submission`) -
neither is disposable. An earlier version of this fix mounted tmpfs over
the whole `~/.isabelle` directory, which wiped both of those on every
restart; verified fixed by narrowing the mount to just `log/`.

**Tradeoff:** tmpfs starts empty, so Isabelle no longer trusts the
pre-built HOL heap as current and rebuilds it from source on every fresh
container (confirmed: progresses normally through each theory, finishing
in a few minutes, not instant but no longer hanging). The Dockerfile's
`isabelle build -b` step is still worth keeping as a build-time correctness
check, even though it no longer buys a fast container start on this host.

If you move Docker's data-root to a non-btrfs (or no-COW-flagged)
filesystem, these `--tmpfs` flags should become unnecessary and container
starts should go back to being fast - not verified either way yet.

## Memory: heap caps + host swap are required on this host

That same fresh-rebuild-on-every-start (above) has an unbounded JVM
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
