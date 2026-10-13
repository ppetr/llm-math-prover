"""FastAPI agent: an OpenAI-compatible chat endpoint that runs a tool-calling
loop against the LiteLLM gateway, with Isabelle as the first tool (design
doc §2/§9 Phase 2).

Open WebUI talks to this service exactly like it would talk to LiteLLM
directly (same /v1/chat/completions contract) - tool calls happen inside
the loop below and never reach the user as raw JSON, only the final
assistant message does.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agent.artifacts import ArtifactError, ArtifactStore
from agent.isabelle_tool import IsabelleTool
from agent.llm_client import LLMClient
from agent.settings import Settings
from agent.tools import ToolRegistry, build_isabelle_check_theory_tool

MAX_TOOL_ITERATIONS = 8


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    # Standard OpenAI field - Open WebUI/the API contract carries the end
    # user's id here (design doc §3: user_id is mandatory from day one).
    user: str | None = None
    # Not a standard OpenAI field; Open WebUI doesn't send it today, but the
    # contract reserves it so a future conversation-scoped Isabelle session
    # can key off it instead of collapsing onto user_id.
    session_id: str | None = None


def _wrap_response(model: str, message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def run_chat_completion(
    request: ChatCompletionRequest, llm_client: LLMClient, registry: ToolRegistry
) -> dict[str, Any]:
    user_id = request.user or "anonymous"
    messages: list[dict] = [m.model_dump(exclude_none=True) for m in request.messages]
    tools = registry.openai_tools()

    for _ in range(MAX_TOOL_ITERATIONS):
        message = llm_client.chat(model=request.model, messages=messages, tools=tools)
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return _wrap_response(request.model, message)

        messages.append(message)
        for tool_call in tool_calls:
            function = tool_call["function"]
            try:
                arguments = json.loads(function["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            result = registry.call(function["name"], user_id, arguments)
            messages.append(
                {"role": "tool", "tool_call_id": tool_call["id"], "content": result}
            )

    raise HTTPException(status_code=502, detail="tool-calling loop did not converge")


def create_app(
    llm_client: LLMClient, registry: ToolRegistry, artifacts: ArtifactStore
) -> FastAPI:
    app = FastAPI(title="ai-math-container agent")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        # Open WebUI populates its model dropdown from this endpoint - without
        # it, it silently shows no models even with a valid API key.
        return llm_client.models()

    @app.post("/v1/chat/completions")
    def chat_completions(request: ChatCompletionRequest) -> dict[str, Any]:
        return run_chat_completion(request, llm_client, registry)

    @app.get("/files/{token}")
    def download(token: str) -> Response:
        try:
            download_token = artifacts.verify(token)
            content = artifacts.load(download_token)
        except ArtifactError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{download_token.name}"'
            },
        )

    return app


def build_app() -> FastAPI:
    """Production entrypoint (`uvicorn agent.main:build_app --factory`).

    A factory, not a module-level `app`, so importing this module (e.g. from
    tests) doesn't require AGENT_SIGNING_SECRET/etc. to already be set.
    """
    settings = Settings.from_env()
    isabelle_tool = IsabelleTool(
        server_info_path=settings.isabelle_server_info_path,
        workspace_dir=settings.isabelle_workspace_dir,
        session=settings.isabelle_session,
    )
    artifacts = ArtifactStore(settings.data_dir, settings.signing_secret, settings.artifact_url_ttl)
    registry = ToolRegistry([build_isabelle_check_theory_tool(isabelle_tool, artifacts)])
    llm_client = LLMClient(settings.litellm_base_url, settings.litellm_api_key)
    return create_app(llm_client, registry, artifacts)
