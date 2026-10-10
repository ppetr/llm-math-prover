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
ENTRYPOINT ["Isabelle/bin/isabelle", "server", "-n", "agent", "-p", "4443", "-L", "/home/isabelle/server.log"]
