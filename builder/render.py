"""Renders compose.yaml and litellm-config.yaml from a StackConfig.

One-shot CLI step (see design doc §4) - not a long-running service.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from builder.schema import StackConfig

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Maps a backend's config key to how LiteLLM names the provider and the
# env var it reads the API key from.
_PROVIDER = {
    "claude": {"litellm_prefix": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"},
    "gpt": {"litellm_prefix": "openai", "api_key_env": "OPENAI_API_KEY"},
    "gemini": {"litellm_prefix": "gemini", "api_key_env": "GEMINI_API_KEY"},
}


def _enabled_cloud_backends(config: StackConfig) -> list[dict]:
    backends = []
    for name, info in _PROVIDER.items():
        backend = getattr(config.backends, name)
        if not backend.enabled:
            continue
        backends.append(
            {
                "name": name,
                "litellm_model": f"{info['litellm_prefix']}/{backend.model}",
                "api_key_env": info["api_key_env"],
            }
        )
    return backends


def render(config: StackConfig, output_dir: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    isabelle_enabled = config.tools.isabelle.enabled
    cloud_backends = _enabled_cloud_backends(config)
    context = {
        "cloud_backends": cloud_backends,
        "ollama_enabled": config.backends.ollama.enabled,
        "ollama_model": config.backends.ollama.model,
        "isabelle_enabled": isabelle_enabled,
        # OpenCode needs an explicit default or it falls back to its own
        # (opencode.ai-login-gated) Zen models instead of our provider.
        "default_model": cloud_backends[0]["name"] if cloud_backends else "ollama",
        "webui_image": config.images.webui,
        "litellm_image": config.images.litellm,
        "ollama_image": config.images.ollama,
        # The agent runs with network_mode: "service:isabelle" (see design
        # doc §2), so it has no network identity of its own - reachable only
        # at the *isabelle* service's hostname, not "agent".
        "api_base": "http://isabelle:8000/v1" if isabelle_enabled else "http://llm-gateway:4000/v1",
    }

    (output_dir / "compose.yaml").write_text(env.get_template("compose.yaml.j2").render(**context))
    (output_dir / "litellm-config.yaml").write_text(
        env.get_template("litellm-config.yaml.j2").render(**context)
    )
    (output_dir / "opencode.json").write_text(
        env.get_template("opencode.json.j2").render(**context)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the container stack from config.yaml")
    parser.add_argument("config", type=Path, help="Path to config.yaml")
    parser.add_argument("--out", type=Path, default=Path("dist"), help="Output directory (default: dist/)")
    args = parser.parse_args()

    config = StackConfig.from_yaml(args.config)
    render(config, args.out)
    print(
        f"Wrote {args.out / 'compose.yaml'}, {args.out / 'litellm-config.yaml'}, "
        f"and {args.out / 'opencode.json'}"
    )


if __name__ == "__main__":
    main()
