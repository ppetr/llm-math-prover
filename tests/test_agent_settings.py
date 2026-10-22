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

from agent.settings import Settings

REQUIRED_ENV = {"AGENT_SIGNING_SECRET": "sig-secret", "LITELLM_MASTER_KEY": "llm-key"}


def test_from_env_requires_signing_secret(monkeypatch):
    monkeypatch.delenv("AGENT_SIGNING_SECRET", raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "llm-key")
    with pytest.raises(RuntimeError, match="AGENT_SIGNING_SECRET"):
        Settings.from_env()


def test_from_env_requires_litellm_master_key(monkeypatch):
    # A missing/empty key must fail fast here, not with the opaque httpx
    # "Illegal header value" an empty "Bearer " token causes on first request.
    monkeypatch.setenv("AGENT_SIGNING_SECRET", "sig-secret")
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LITELLM_MASTER_KEY"):
        Settings.from_env()


def test_from_env_succeeds_with_required_vars_set(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env()
    assert settings.signing_secret == b"sig-secret"
    assert settings.litellm_api_key == "llm-key"
