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

import pytest

from builder.schema import StackConfig


def test_minimal_valid_config():
    cfg = StackConfig.model_validate({"backends": {"claude": {"enabled": True, "model": "claude-opus-4"}}})
    assert cfg.backends.claude.model == "claude-opus-4"
    assert cfg.auth.mode == "single_user"


def test_empty_config_rejected():
    with pytest.raises(ValueError):
        StackConfig.model_validate({})


def test_enabled_backend_without_model_rejected():
    with pytest.raises(ValueError):
        StackConfig.model_validate({"backends": {"claude": {"enabled": True}}})


def test_oauth_whitelist_requires_whitelist():
    with pytest.raises(ValueError):
        StackConfig.model_validate(
            {
                "backends": {"claude": {"enabled": True, "model": "claude-opus-4"}},
                "auth": {"mode": "oauth_whitelist", "whitelist": []},
            }
        )


def test_oauth_whitelist_with_entries_accepted():
    cfg = StackConfig.model_validate(
        {
            "backends": {"claude": {"enabled": True, "model": "claude-opus-4"}},
            "auth": {"mode": "oauth_whitelist", "whitelist": ["alice@example.com"]},
        }
    )
    assert cfg.auth.whitelist == ["alice@example.com"]


def test_from_yaml(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("backends:\n  claude: {enabled: true, model: claude-opus-4}\n")
    cfg = StackConfig.from_yaml(config_path)
    assert cfg.backends.claude.enabled is True
