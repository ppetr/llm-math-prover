# ai-math-container

Config-driven container stack for a cloud-LLM agent that proves theorems with
Isabelle/HOL. Design rationale: [docs/design/isabelle-agent-stack.md](docs/design/isabelle-agent-stack.md).

Implements Phase 0 (Open WebUI + LiteLLM) and Phase 2 (agent with an Isabelle
tool); AFP/web search tools arrive in Phase 3. Phase 1 (the `isabelle` image
itself) is documented separately in [isabelle/README.md](isabelle/README.md).

## Phase 0: generate and run

```sh
python3 -m venv .venv && .venv/bin/pip install -e .

cp config.example.yaml config.yaml   # fill in a real model id
.venv/bin/python -m builder.render config.yaml --out dist
cp .env.example dist/.env            # fill in the matching API key(s)

cd dist && docker compose up
# or, once Podman is available: podman compose up
```

Open WebUI comes up on `http://localhost:8080`, the LiteLLM gateway on
`http://localhost:4000`. Verify LaTeX rendering by sending a message
containing `$$\int_0^1 x^2\,dx = \tfrac13$$` in the chat.

## Phase 2: agent (Isabelle tool)

Set `tools.isabelle.enabled: true` in `config.yaml` before rendering, build
both images the compose file references by name, and fill in
`AGENT_SIGNING_SECRET` in `dist/.env` (`openssl rand -hex 32`):

```sh
docker build -t isabelle-afp isabelle/                           # see isabelle/README.md
docker build -t ai-math-container-agent -f agent/Dockerfile .    # from the repo root
```

The heap-cache volumes (`isabelle-afp-user-heaplog`,
`isabelle-afp-dist-heaplog`) still need the one-time `chattr +C` setup from
isabelle/README.md *before* the first `docker compose up` - otherwise
compose creates them as ordinary (COW) volumes and the btrfs/SQLite-WAL
hang that fix exists for can come back.

Once up, webui talks to the agent instead of llm-gateway directly (see
`docs/design/isabelle-agent-stack.md` §2) - ask it to check a theory and it
calls the `isabelle_check_theory` tool, which only reports success if the
Isabelle kernel actually accepted the proof.

## Optional: CLI client (OpenCode)

`dist/compose.yaml` also defines a `cli` service running
[OpenCode](https://opencode.ai), an open-source terminal agent, pointed at
the same OpenAI-compatible endpoint as webui. It's gated behind a compose
profile so `up` never starts it, and it needs a TTY:

```sh
cd dist && docker compose --profile cli run --no-deps --rm cli
```

`--no-deps` matters once the main stack is already running (`docker compose
up -d`): without it, `run` re-resolves the whole `cli` -> `agent` ->
`llm-gateway` dependency chain on every invocation and ends up recreating
`llm-gateway`, which briefly breaks every other connection to it (webui
included) while the old container is torn down and the new one starts.

For scripted/non-interactive use (e.g. debugging), OpenCode's `run`
subcommand sends one message and exits - no TTY needed:

```sh
docker compose --profile cli run --no-deps --rm -T cli run "your prompt here"
```

It has no access to the repo or the Isabelle workspace yet - this is a chat
client for now, not a coding agent. File/shell tool access and sandboxing
are future work.

## Backing up user data

`webui-data`, `agent-data`, and `isabelle-workspace` hold the stack's only
irreplaceable user data (Open WebUI accounts/chats, agent artifacts,
Isabelle theory files). [scripts/backup-volumes.sh](scripts/backup-volumes.sh)
writes each one to its own `.tar.zst` archive and prints the matching
restore command:

```sh
./scripts/backup-volumes.sh backup               # -> ./volume-backups/*.tar.zst
./scripts/backup-volumes.sh restore ARCHIVE VOLUME_NAME
```

Requires the `zstd` CLI on the host; run `./scripts/backup-volumes.sh` with
no arguments for the full usage.

## Development

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
