"""Config schema for the stack.

A single source of truth: validates config.yaml, and doubles as the
runtime settings object the agent loads at startup (see design doc §4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class BackendConfig(BaseModel):
    enabled: bool = False
    model: str | None = None

    @model_validator(mode="after")
    def model_required_when_enabled(self) -> "BackendConfig":
        if self.enabled and not self.model:
            raise ValueError("model must be set when a backend is enabled")
        return self


class BackendsConfig(BaseModel):
    claude: BackendConfig = Field(default_factory=BackendConfig)
    gpt: BackendConfig = Field(default_factory=BackendConfig)
    gemini: BackendConfig = Field(default_factory=BackendConfig)
    ollama: BackendConfig = Field(default_factory=BackendConfig)


class ToolConfig(BaseModel):
    enabled: bool = False


class ToolsConfig(BaseModel):
    isabelle: ToolConfig = Field(default_factory=ToolConfig)
    afp_search: ToolConfig = Field(default_factory=ToolConfig)
    web_search: ToolConfig = Field(default_factory=ToolConfig)


class AuthConfig(BaseModel):
    mode: Literal["single_user", "oauth_whitelist"] = "single_user"
    whitelist: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def whitelist_required_for_oauth(self) -> "AuthConfig":
        if self.mode == "oauth_whitelist" and not self.whitelist:
            raise ValueError("whitelist must not be empty when mode is oauth_whitelist")
        return self


class ImagesConfig(BaseModel):
    """Pinned upstream image tags, so a fresh `docker compose up` is
    reproducible instead of drifting with whatever the floating tag
    currently resolves to. Bump these deliberately, not by accident.
    """

    webui: str = "ghcr.io/open-webui/open-webui:v0.12.2"
    litellm: str = "ghcr.io/berriai/litellm:v1.105.1"
    ollama: str = "ollama/ollama:0.40.4"


class StackConfig(BaseModel):
    backends: BackendsConfig = Field(default_factory=BackendsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    images: ImagesConfig = Field(default_factory=ImagesConfig)

    @model_validator(mode="after")
    def at_least_one_backend_enabled(self) -> "StackConfig":
        backends = (self.backends.claude, self.backends.gpt, self.backends.gemini, self.backends.ollama)
        if not any(b.enabled for b in backends):
            raise ValueError("at least one backend must be enabled")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StackConfig":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)
