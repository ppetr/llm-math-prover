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

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("AGENT_SIGNING_SECRET")
        if not secret:
            raise RuntimeError("AGENT_SIGNING_SECRET env var must be set")
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
            litellm_api_key=os.environ.get("LITELLM_MASTER_KEY", ""),
            data_dir=Path(os.environ.get("AGENT_DATA_DIR", "/data")),
            signing_secret=secret.encode(),
            artifact_url_ttl=int(os.environ.get("AGENT_ARTIFACT_URL_TTL", "3600")),
        )
