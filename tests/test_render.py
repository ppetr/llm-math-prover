import yaml

from builder.render import render
from builder.schema import StackConfig


def test_render_claude_only(tmp_path):
    cfg = StackConfig.model_validate({"backends": {"claude": {"enabled": True, "model": "claude-opus-4"}}})
    render(cfg, tmp_path)

    compose = yaml.safe_load((tmp_path / "compose.yaml").read_text())
    assert set(compose["services"]) == {"webui", "llm-gateway"}
    assert "ollama" not in compose.get("volumes", {})

    litellm_config = yaml.safe_load((tmp_path / "litellm-config.yaml").read_text())
    assert litellm_config["model_list"] == [
        {
            "model_name": "claude",
            "litellm_params": {
                "model": "anthropic/claude-opus-4",
                "api_key": "os.environ/ANTHROPIC_API_KEY",
            },
        }
    ]


def test_render_with_ollama(tmp_path):
    cfg = StackConfig.model_validate(
        {
            "backends": {
                "claude": {"enabled": True, "model": "claude-opus-4"},
                "ollama": {"enabled": True, "model": "llama3"},
            }
        }
    )
    render(cfg, tmp_path)

    compose = yaml.safe_load((tmp_path / "compose.yaml").read_text())
    assert "ollama" in compose["services"]
    assert "ollama-data" in compose["volumes"]

    litellm_config = yaml.safe_load((tmp_path / "litellm-config.yaml").read_text())
    model_names = {m["model_name"] for m in litellm_config["model_list"]}
    assert model_names == {"claude", "ollama"}
