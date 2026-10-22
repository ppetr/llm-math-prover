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

"""Runtime settings for the agent service.

Separate from builder.schema.StackConfig, which governs what gets
generated into compose.yaml/litellm-config.yaml at build time - these are
the env vars the generated `agent` container itself reads at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    isabelle_server_info_path: Path
    isabelle_workspace_dir: Path
    isabelle_session: str
    litellm_base_url: str
    litellm_api_key: str
    data_dir: Path
    signing_secret: bytes
    artifact_url_ttl: int
    max_isabelle_sessions: int
    llm_request_timeout: float

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("AGENT_SIGNING_SECRET")
        if not secret:
            raise RuntimeError("AGENT_SIGNING_SECRET env var must be set")
        litellm_api_key = os.environ.get("LITELLM_MASTER_KEY")
        if not litellm_api_key:
            # Must fail here, not later: an empty Bearer token reaches httpx fine
            # but raises an opaque "Illegal header value" on the first actual
            # request, deep inside LLMClient instead of at startup.
            raise RuntimeError("LITELLM_MASTER_KEY env var must be set")
        return cls(
            isabelle_server_info_path=Path(
                os.environ.get(
                    "ISABELLE_SERVER_INFO_PATH", "/isabelle-server-info/registration.log"
                )
            ),
            isabelle_workspace_dir=Path(
                os.environ.get("ISABELLE_WORKSPACE_DIR", "/isabelle-workspace")
            ),
            isabelle_session=os.environ.get("ISABELLE_SESSION", "HOL"),
            litellm_base_url=os.environ.get("LITELLM_BASE_URL", "http://llm-gateway:4000/v1"),
            litellm_api_key=litellm_api_key,
            data_dir=Path(os.environ.get("AGENT_DATA_DIR", "/data")),
            signing_secret=secret.encode(),
            artifact_url_ttl=int(os.environ.get("AGENT_ARTIFACT_URL_TTL", "3600")),
            max_isabelle_sessions=int(os.environ.get("AGENT_MAX_ISABELLE_SESSIONS", "4")),
            # A long-running theory proof plus a growing conversation history
            # can legitimately push Claude's response time well past a minute -
            # this must stay generous, not tight, or the agent aborts calls
            # that were going to succeed anyway (see commit history).
            llm_request_timeout=float(os.environ.get("AGENT_LLM_TIMEOUT_SECONDS", "600")),
        )
