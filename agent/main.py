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
from fastapi.responses import Response, StreamingResponse
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
    stream: bool = False


def _wrap_response(model: str, message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def _run_tool_loop(request: ChatCompletionRequest, llm_client: LLMClient, registry: ToolRegistry):
    """Drives the LLM/tool loop, yielding ("tool_call"|"tool_result"|"final", ...) events."""
    user_id = request.user or "anonymous"
    messages: list[dict] = [m.model_dump(exclude_none=True) for m in request.messages]
    tools = registry.openai_tools()

    for _ in range(MAX_TOOL_ITERATIONS):
        message = llm_client.chat(model=request.model, messages=messages, tools=tools)
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            yield ("final", message)
            return

        messages.append(message)
        for tool_call in tool_calls:
            function = tool_call["function"]
            try:
                arguments = json.loads(function["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            yield ("tool_call", function["name"], arguments)
            result = registry.call(function["name"], user_id, request.session_id, arguments)
            yield ("tool_result", function["name"], result)
            messages.append(
                {"role": "tool", "tool_call_id": tool_call["id"], "content": result}
            )

    raise HTTPException(status_code=502, detail="tool-calling loop did not converge")


def run_chat_completion(
    request: ChatCompletionRequest, llm_client: LLMClient, registry: ToolRegistry
) -> dict[str, Any]:
    for kind, *rest in _run_tool_loop(request, llm_client, registry):
        if kind == "final":
            (message,) = rest
            return _wrap_response(request.model, message)
    raise HTTPException(status_code=502, detail="tool-calling loop did not converge")


def _status_line(icon: str, text: str) -> str:
    return f"\n{icon} {text}\n"


def _tool_call_status(name: str, arguments: dict[str, Any]) -> str:
    # Keep only short scalar arguments inline - fields like a full .thy
    # source would otherwise dump the whole file into the chat.
    bits = [
        f"{key}={value}"
        for key, value in arguments.items()
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 60
    ]
    args_text = f" ({', '.join(bits)})" if bits else ""
    return _status_line("🔧", f"calling `{name}`{args_text}…")


def _tool_result_status(name: str, result: str) -> str:
    ok = None
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and "ok" in parsed:
            ok = parsed["ok"]
    except json.JSONDecodeError:
        pass
    icon = "✅" if ok else "❌" if ok is False else "ℹ️"
    return _status_line(icon, f"`{name}` done")


def _sse_chunk(model: str, delta: dict[str, Any], finish_reason: str | None = None) -> str:
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def stream_chat_completion(request: ChatCompletionRequest, llm_client: LLMClient, registry: ToolRegistry):
    """SSE generator so Open WebUI shows tool-call progress instead of a blank wait."""
    model = request.model
    yield _sse_chunk(model, {"role": "assistant", "content": ""})
    try:
        for kind, *rest in _run_tool_loop(request, llm_client, registry):
            if kind == "tool_call":
                name, arguments = rest
                yield _sse_chunk(model, {"content": _tool_call_status(name, arguments)})
            elif kind == "tool_result":
                name, result = rest
                yield _sse_chunk(model, {"content": _tool_result_status(name, result)})
            elif kind == "final":
                (message,) = rest
                content = message.get("content") or ""
                if content:
                    yield _sse_chunk(model, {"content": content})
    except HTTPException as exc:
        yield _sse_chunk(model, {"content": _status_line("⚠️", str(exc.detail))})
    except Exception as exc:
        # Any other failure (gateway error, timeout, ...) must still end the
        # SSE stream cleanly - an uncaught exception here aborts the response
        # mid-chunk and the client sees a transfer-encoding error, not ours.
        yield _sse_chunk(model, {"content": _status_line("⚠️", f"agent error: {exc}")})
    yield _sse_chunk(model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


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
    def chat_completions(request: ChatCompletionRequest):
        if request.stream:
            return StreamingResponse(
                stream_chat_completion(request, llm_client, registry),
                media_type="text/event-stream",
            )
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
        max_sessions=settings.max_isabelle_sessions,
    )
    artifacts = ArtifactStore(settings.data_dir, settings.signing_secret, settings.artifact_url_ttl)
    registry = ToolRegistry([build_isabelle_check_theory_tool(isabelle_tool, artifacts)])
    llm_client = LLMClient(
        settings.litellm_base_url, settings.litellm_api_key, timeout=settings.llm_request_timeout
    )
    return create_app(llm_client, registry, artifacts)
