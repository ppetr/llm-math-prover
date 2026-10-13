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

    def close(self) -> None:
        self._client.close()
