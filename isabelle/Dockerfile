# Isabelle/HOL + AFP, running `isabelle server` for the agent (Phase 2) to
# connect to as a sidecar over a shared network namespace - the server only
# binds to localhost, so it cannot be reached over the regular compose
# network (see design doc §2/§7).
#
# Check https://hub.docker.com/r/makarius/isabelle/tags before bumping this.
FROM makarius/isabelle:Isabelle2025-2

USER root

# afp-current.tar.gz always tracks the AFP release matching the base image's
# Isabelle release - see https://isa-afp.org/download/
ADD https://www.isa-afp.org/release/afp-current.tar.gz /tmp/afp-current.tar.gz
RUN mkdir -p /home/isabelle/afp \
    && tar -xzf /tmp/afp-current.tar.gz -C /home/isabelle/afp --strip-components=1 \
    && rm /tmp/afp-current.tar.gz \
    && chown -R isabelle:isabelle /home/isabelle/afp

USER isabelle
WORKDIR /home/isabelle
RUN Isabelle/bin/isabelle components -u /home/isabelle/afp/thys

# Cap both heavy-memory processes: the orchestrating JVM
# (ISABELLE_TOOL_JAVA_OPTIONS) and the actual PolyML build process
# (ML_OPTIONS), which otherwise grows unbounded and OOMs the host on a
# 15GB-RAM box. Both are set with a bare `=` in the distribution/component
# settings, so a `docker run -e` override gets clobbered when those files
# are re-sourced - ISABELLE_HOME_USER's settings file is sourced last and
# wins, so set them there instead.
RUN mkdir -p /home/isabelle/.isabelle/etc \
    && cat >> /home/isabelle/.isabelle/etc/settings <<'EOF'
ISABELLE_TOOL_JAVA_OPTIONS="-Djava.awt.headless=true -Xms512m -Xmx6g -Xss16m"
ML_OPTIONS="--minheap 1000 --maxheap 6000"
EOF

# Pre-build HOL + Example-Submission here mainly as a build-time
# correctness check (catches a broken AFP registration at `docker build`
# time, not at first deploy). It does NOT make container starts skip the
# build: the resulting build-log sqlite files (Isabelle/heaps/*/log/*.db)
# get baked into this image layer, and loading them at container runtime
# requires overlay2 to copy them up into the writable layer - on a btrfs
# data-root that copy-up + SQLite's WAL locking hang indefinitely at
# ~0% CPU (known btrfs-COW/SQLite-WAL incompatibility). Fix is at the run
# layer, not here: mount tmpfs over the log directories so the container
# always starts with a fresh, empty log db instead of touching the
# btrfs-backed copy - see isabelle/README.md and the `--tmpfs` flags in
# `docker run`. That means every fresh container still rebuilds HOL once
# (a few minutes), just without hanging.
RUN Isabelle/bin/isabelle build -b HOL Example-Submission

# Documentation only - EXPOSE does not make a localhost-bound service
# reachable from other containers, see the sidecar note above.
EXPOSE 4443

# The server prints its one-line registration (name, port, randomly
# generated password) to its own stdout on startup - that's the only place
# it appears, "-L" only logs later session events, not this line. The
# agent (Phase 2) is a separate container that shares our network
# namespace but not our filesystem, so it can't read it from
# ~/.isabelle/servers.db like `isabelle client` does - tee stdout into a
# file on a shared volume (see isabelle/README.md) instead, which the
# agent polls and parses to get the connection info it needs.
#
# A fresh registration (new port + password) is written every time the
# server (re)starts - see server-entrypoint.sh and
# agent/isabelle_tool.py's reconnect handling.
RUN mkdir -p /home/isabelle/server-info

# Workspace where the agent drops .thy files for `use_theories` to check -
# also a shared volume, so pre-create it here: Docker seeds a fresh named
# volume from whatever already exists at its mount point in the image,
# otherwise it would land root-owned and unwritable. World-writable
# because the agent container (different image, different uid) needs to
# write here too - it's a scratch dir for theory text, not sensitive data.
USER root
RUN mkdir -p /isabelle-workspace && chmod 777 /isabelle-workspace
COPY server-entrypoint.sh /home/isabelle/server-entrypoint.sh
RUN chmod 755 /home/isabelle/server-entrypoint.sh
USER isabelle

ENTRYPOINT ["/home/isabelle/server-entrypoint.sh"]
