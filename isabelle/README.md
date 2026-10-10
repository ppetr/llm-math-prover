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
```

This downloads ~70 MB (AFP) on top of the base Isabelle image and can take a
while the first time. Not run yet in this environment - no outbound network
access to Docker Hub / isa-afp.org here, so the build itself is unverified
beyond a manual review of the Dockerfile. Run it somewhere with network
access and report back if anything in it is wrong.

## Manual smoke test (Fáze 1 goal)

```sh
docker run --rm -d --name isabelle-afp isabelle-afp
docker exec -it isabelle-afp Isabelle/bin/isabelle client
```

The second command should connect to the server started by the entrypoint
and drop into an interactive prompt. From there:

```json
session_start {"session": "HOL"}
```

should return `OK`/`FINISHED` with a session ID, confirming the server is up
and HOL loaded. To confirm AFP registration, try starting a session that
depends on an AFP entry, e.g. `session_start {"session": "Example-Submission"}`
(or any other AFP session name).

The exact flags `isabelle client` expects given the server was started with
explicit `-n agent -p 4443` are **not verified yet** - check
`Isabelle/bin/isabelle client -?` inside the container first. If it doesn't
connect by default, pass matching `-n`/`-p` to the client call.
