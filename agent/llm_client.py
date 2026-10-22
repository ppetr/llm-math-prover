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

"""Thin client for the LiteLLM gateway's OpenAI-compatible chat API."""

from __future__ import annotations

import httpx


class LLMClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Sends one chat-completions request, returns the reply message dict."""
        body: dict = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        response = self._client.post("/chat/completions", json=body)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]

    def models(self) -> dict:
        """Returns the gateway's /models response as-is, for clients (e.g. Open WebUI) that list models."""
        response = self._client.get("/models")
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()
