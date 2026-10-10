# ai-math-container

Config-driven container stack for a cloud-LLM agent that proves theorems with
Isabelle/HOL. Design rationale: [docs/design/isabelle-agent-stack.md](docs/design/isabelle-agent-stack.md).

Currently implements Fáze 0 only: Open WebUI talking to Claude/GPT/Gemini
through a LiteLLM gateway, both generated from one `config.yaml`. Isabelle,
the agent service, and file downloads arrive in later phases.

## Fáze 0: generate and run

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

## Development

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
