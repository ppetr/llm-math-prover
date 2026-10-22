# Copyright 2026 github.com/ppetr
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

import yaml

from builder.render import render
from builder.schema import StackConfig


def test_render_claude_only(tmp_path):
    cfg = StackConfig.model_validate({"backends": {"claude": {"enabled": True, "model": "claude-opus-4"}}})
    render(cfg, tmp_path)

    compose = yaml.safe_load((tmp_path / "compose.yaml").read_text())
    assert set(compose["services"]) == {"webui", "llm-gateway", "cli"}
    assert "ollama" not in compose.get("volumes", {})

    # The cli service is opt-in via a compose profile, not started by `up`,
    # and points at the same backend webui uses.
    assert compose["services"]["cli"]["profiles"] == ["cli"]
    assert compose["services"]["cli"]["depends_on"] == ["llm-gateway"]

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

    opencode_config = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode_config["model"] == "local/claude"
    provider = opencode_config["provider"]["local"]
    assert provider["options"]["baseURL"] == "http://llm-gateway:4000/v1"
    assert set(provider["models"]) == {"claude"}


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

    opencode_config = json.loads((tmp_path / "opencode.json").read_text())
    assert set(opencode_config["provider"]["local"]["models"]) == {"claude", "ollama"}


def test_render_with_isabelle_routes_cli_and_webui_through_isabelle_hostname(tmp_path):
    cfg = StackConfig.model_validate(
        {
            "backends": {"claude": {"enabled": True, "model": "claude-opus-4"}},
            "tools": {"isabelle": {"enabled": True}},
        }
    )
    render(cfg, tmp_path)

    compose = yaml.safe_load((tmp_path / "compose.yaml").read_text())
    # agent runs with network_mode: "service:isabelle" (design doc §2), so
    # both webui and cli must address it via the isabelle hostname.
    assert compose["services"]["webui"]["environment"]["OPENAI_API_BASE_URL"] == "http://isabelle:8000/v1"
    assert compose["services"]["cli"]["depends_on"] == ["agent"]

    opencode_config = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode_config["provider"]["local"]["options"]["baseURL"] == "http://isabelle:8000/v1"


def test_render_ollama_only_defaults_opencode_model_to_ollama(tmp_path):
    cfg = StackConfig.model_validate({"backends": {"ollama": {"enabled": True, "model": "llama3"}}})
    render(cfg, tmp_path)

    opencode_config = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode_config["model"] == "local/ollama"
