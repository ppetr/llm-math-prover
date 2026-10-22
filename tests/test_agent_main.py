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

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent.main import ChatCompletionRequest, create_app, run_chat_completion
from agent.tools import ToolRegistry, ToolSpec


class FakeLLM:
    """Replies with a tool call on the first turn, a final answer on the second."""

    def __init__(self, turns=None):
        self.calls = 0
        self._turns = turns

    def chat(self, model, messages, tools=None):
        self.calls += 1
        if self._turns is not None:
            return self._turns[min(self.calls, len(self._turns)) - 1]
        if self.calls == 1:
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": json.dumps({"x": 1})},
                    }
                ],
            }
        return {"role": "assistant", "content": "final answer"}

    def models(self):
        return {"object": "list", "data": [{"id": "claude", "object": "model"}]}


def _echo_registry():
    return ToolRegistry(
        [ToolSpec(name="echo", description="d", parameters={"type": "object"}, handler=lambda u, s, a: json.dumps(a))]
    )


def test_run_chat_completion_resolves_tool_call_then_returns_final_message():
    llm = FakeLLM()
    request = ChatCompletionRequest(model="claude-x", messages=[{"role": "user", "content": "hi"}], user="alice")

    response = run_chat_completion(request, llm, _echo_registry())

    assert llm.calls == 2
    assert response["model"] == "claude-x"
    assert response["choices"][0]["message"] == {"role": "assistant", "content": "final answer"}


def test_run_chat_completion_returns_directly_when_no_tool_call():
    llm = FakeLLM(turns=[{"role": "assistant", "content": "no tools needed"}])
    request = ChatCompletionRequest(model="m", messages=[{"role": "user", "content": "hi"}])

    response = run_chat_completion(request, llm, _echo_registry())

    assert llm.calls == 1
    assert response["choices"][0]["message"]["content"] == "no tools needed"


def test_run_chat_completion_raises_when_loop_never_converges():
    looping_call = {
        "role": "assistant",
        "tool_calls": [
            {"id": "call1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
        ],
    }
    llm = FakeLLM(turns=[looping_call] * 20)
    request = ChatCompletionRequest(model="m", messages=[{"role": "user", "content": "hi"}])

    with pytest.raises(HTTPException) as exc_info:
        run_chat_completion(request, llm, _echo_registry())
    assert exc_info.value.status_code == 502


def test_chat_completions_endpoint_defaults_user_to_anonymous():
    llm = FakeLLM(turns=[{"role": "assistant", "content": "hi there"}])

    class NoArtifacts:
        pass

    app = create_app(llm, _echo_registry(), NoArtifacts())
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi there"


def test_models_endpoint_proxies_llm_client():
    class NoArtifacts:
        pass

    app = create_app(FakeLLM(), ToolRegistry([]), NoArtifacts())
    client = TestClient(app)

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json() == {"object": "list", "data": [{"id": "claude", "object": "model"}]}


def test_healthz():
    class NoArtifacts:
        pass

    app = create_app(FakeLLM(), ToolRegistry([]), NoArtifacts())
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}


def _sse_chunks(response):
    for line in response.iter_lines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload == "[DONE]":
            return
        yield json.loads(payload)


def test_streaming_chat_completion_reports_tool_call_progress_then_final_content():
    llm = FakeLLM()

    class NoArtifacts:
        pass

    app = create_app(llm, _echo_registry(), NoArtifacts())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        chunks = list(_sse_chunks(response))

    contents = [c["choices"][0]["delta"].get("content") for c in chunks]
    assert any("echo" in (c or "") for c in contents)
    assert any("final answer" in (c or "") for c in contents)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_streaming_chat_completion_reports_non_convergence_as_content():
    looping_call = {
        "role": "assistant",
        "tool_calls": [
            {"id": "call1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
        ],
    }
    llm = FakeLLM(turns=[looping_call] * 20)

    class NoArtifacts:
        pass

    app = create_app(llm, _echo_registry(), NoArtifacts())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        chunks = list(_sse_chunks(response))

    contents = [c["choices"][0]["delta"].get("content") or "" for c in chunks]
    assert any("did not converge" in c for c in contents)


def test_streaming_chat_completion_terminates_cleanly_on_unexpected_error():
    class BoomLLM:
        def chat(self, model, messages, tools=None):
            raise RuntimeError("gateway exploded")

        def models(self):
            return {}

    class NoArtifacts:
        pass

    app = create_app(BoomLLM(), _echo_registry(), NoArtifacts())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        chunks = list(_sse_chunks(response))

    contents = [c["choices"][0]["delta"].get("content") or "" for c in chunks]
    assert any("gateway exploded" in c for c in contents)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
