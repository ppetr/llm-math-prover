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

# Documentation only - EXPOSE does not make a localhost-bound service
# reachable from other containers, see the sidecar note above.
EXPOSE 4443
ENTRYPOINT ["Isabelle/bin/isabelle", "server", "-n", "agent", "-p", "4443", "-L", "/home/isabelle/server.log"]
