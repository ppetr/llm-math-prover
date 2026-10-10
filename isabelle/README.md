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

## Manual smoke test (Fáze 1 goal) - verified

```sh
docker run --rm -d --name isabelle-afp isabelle-afp
docker exec -it isabelle-afp Isabelle/bin/isabelle client -n agent
```

The `-n agent` matters: `isabelle client` defaults to looking for a server
named `isabelle`, but the entrypoint starts the server as `-n agent` (see
`Dockerfile`). Without a matching `-n`, the client fails with
`*** Isabelle server "isabelle" not running`.

Confirmed output: the client connects, prints the server's address/password,
then

```json
session_start {"session": "HOL"}
```

returns `OK` with a task id, streams `NOTE` progress messages while loading
`Pure`/`HOL`, and ends with `FINISHED` and a session id - the server and base
HOL both work.

Still to confirm: that AFP is actually registered. Try a session that
depends on an AFP entry, e.g. `session_start {"session": "Example-Submission"}`
(or any other AFP session name), in the same client prompt.
