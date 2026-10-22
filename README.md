# LLM agent that proves theorems with a real Isabelle/HOL kernel

*Personal project, independent of, and not endorsed or sponsored by, any
current or former employer of the author.*

A config-driven Docker/Podman stack that wires a cloud LLM (Claude, GPT, or
Gemini) to Isabelle/HOL through tool-calling: the LLM can propose a theory,
but it only counts as proved once Isabelle's kernel actually accepts it. See
[docs/design/isabelle-agent-stack.md](docs/design/isabelle-agent-stack.md)
for the architecture and rationale; this README only covers installing,
configuring, and running it.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -e .

cp config.example.yaml config.yaml
```

Edit `config.yaml`: enable one LLM backend with a real model id, and set
`tools.isabelle.enabled: true`. Then build the two images the generated
stack will reference by name (see [isabelle/README.md](isabelle/README.md)
for what the first one contains and host requirements):

```sh
docker build -t isabelle-afp isabelle/                           # see isabelle/README.md
docker build -t ai-math-container-agent -f agent/Dockerfile .    # from the repo root
```

The heap-cache volumes (`isabelle-afp-user-heaplog`,
`isabelle-afp-dist-heaplog`) still need the one-time `chattr +C` setup from
isabelle/README.md *before* the first `docker compose up` - otherwise
compose creates them as ordinary (COW) volumes and the btrfs/SQLite-WAL
hang that fix exists for can come back.

```sh
.venv/bin/python -m builder.render config.yaml --out dist
cp .env.example dist/.env
```

Fill in `dist/.env`: the API key for the backend you enabled, a
`LITELLM_MASTER_KEY`, and `AGENT_SIGNING_SECRET` (`openssl rand -hex 32`).
Then:

```sh
cd dist && docker compose up
# or, once Podman is available: podman compose up
```

Open WebUI comes up on `http://localhost:8080`, talking to the agent (not
straight to the LLM). Ask it to check a theory and it calls the
`isabelle_check_theory` tool, which only reports success if the Isabelle
kernel actually accepted the proof; a verified theory is saved and offered
back as a downloadable `.thy` file. Verify LaTeX rendering separately by
sending a message containing `$$\int_0^1 x^2\,dx = \tfrac13$$` in the chat.

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

## Current limitations

- `isabelle_check_theory` only checks a theory it's given directly - there's
  no AFP or web search yet to find an existing proof on its own. The
  `tools.afp_search`/`web_search` config flags exist but have no effect.
- Single-user only. `auth.mode: oauth_whitelist` is accepted by the config
  schema but not yet wired into the generated stack.
- Only `.thy` source is downloadable; typeset PDF proofs aren't generated
  yet.
- The OpenCode CLI (above) is a plain chat client, not a coding agent.

## Development

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## License

Apache License 2.0 - see [LICENSE](LICENSE).
