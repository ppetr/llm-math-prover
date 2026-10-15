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

    context = {
        "cloud_backends": _enabled_cloud_backends(config),
        "ollama_enabled": config.backends.ollama.enabled,
        "ollama_model": config.backends.ollama.model,
        "isabelle_enabled": config.tools.isabelle.enabled,
        "webui_image": config.images.webui,
        "litellm_image": config.images.litellm,
        "ollama_image": config.images.ollama,
    }

    (output_dir / "compose.yaml").write_text(env.get_template("compose.yaml.j2").render(**context))
    (output_dir / "litellm-config.yaml").write_text(
        env.get_template("litellm-config.yaml.j2").render(**context)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the container stack from config.yaml")
    parser.add_argument("config", type=Path, help="Path to config.yaml")
    parser.add_argument("--out", type=Path, default=Path("dist"), help="Output directory (default: dist/)")
    args = parser.parse_args()

    config = StackConfig.from_yaml(args.config)
    render(config, args.out)
    print(f"Wrote {args.out / 'compose.yaml'} and {args.out / 'litellm-config.yaml'}")


if __name__ == "__main__":
    main()
