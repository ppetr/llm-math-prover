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

from agent.isabelle_tool import CheckTheoryResult, IsabelleToolError
from agent.tools import ToolRegistry, ToolSpec, build_isabelle_check_theory_tool


class FakeIsabelleTool:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str, str, str | None]] = []

    def check_theory(self, user_id, theory_name, theory_source, session_id=None):
        self.calls.append((user_id, theory_name, theory_source, session_id))
        if self._error is not None:
            raise self._error
        return self._result


class FakeArtifacts:
    def __init__(self):
        self.saved: list[tuple[str, str, bytes]] = []

    def save(self, user_id, name, content):
        self.saved.append((user_id, name, content))


def test_check_theory_tool_saves_artifact_on_success():
    isabelle = FakeIsabelleTool(result=CheckTheoryResult(ok=True, errors=[]))
    artifacts = FakeArtifacts()
    spec = build_isabelle_check_theory_tool(isabelle, artifacts)

    output = spec.handler("alice", None, {"theory_name": "Scratch", "theory_source": "theory ..."})

    assert json.loads(output) == {"ok": True, "errors": []}
    assert artifacts.saved == [("alice", "Scratch.thy", b"theory ...")]
    assert isabelle.calls == [("alice", "Scratch", "theory ...", None)]


def test_check_theory_tool_passes_session_id_through():
    isabelle = FakeIsabelleTool(result=CheckTheoryResult(ok=True, errors=[]))
    spec = build_isabelle_check_theory_tool(isabelle, FakeArtifacts())

    spec.handler("alice", "conv-1", {"theory_name": "Scratch", "theory_source": "theory ..."})

    assert isabelle.calls == [("alice", "Scratch", "theory ...", "conv-1")]


def test_check_theory_tool_does_not_save_artifact_on_failure():
    isabelle = FakeIsabelleTool(result=CheckTheoryResult(ok=False, errors=["bad proof"]))
    artifacts = FakeArtifacts()
    spec = build_isabelle_check_theory_tool(isabelle, artifacts)

    output = spec.handler("alice", None, {"theory_name": "Scratch", "theory_source": "theory ..."})

    assert json.loads(output) == {"ok": False, "errors": ["bad proof"]}
    assert artifacts.saved == []


def test_check_theory_tool_reports_tool_errors_without_raising():
    isabelle = FakeIsabelleTool(error=IsabelleToolError("sidecar unreachable"))
    spec = build_isabelle_check_theory_tool(isabelle, FakeArtifacts())

    output = spec.handler("alice", None, {"theory_name": "Scratch", "theory_source": "theory ..."})

    body = json.loads(output)
    assert body["ok"] is False
    assert "sidecar unreachable" in body["errors"][0]


def test_registry_exposes_openai_tool_specs():
    spec = ToolSpec(name="t", description="d", parameters={"type": "object"}, handler=lambda u, s, a: "x")
    registry = ToolRegistry([spec])

    tools = registry.openai_tools()

    assert tools == [{"type": "function", "function": {"name": "t", "description": "d", "parameters": {"type": "object"}}}]


def test_registry_dispatches_to_handler_with_user_id_session_id_and_arguments():
    seen = {}

    def handler(user_id, session_id, arguments):
        seen["user_id"] = user_id
        seen["session_id"] = session_id
        seen["arguments"] = arguments
        return "result"

    registry = ToolRegistry([ToolSpec(name="t", description="d", parameters={}, handler=handler)])

    result = registry.call("t", "alice", "conv-1", {"x": 1})

    assert result == "result"
    assert seen == {"user_id": "alice", "session_id": "conv-1", "arguments": {"x": 1}}


def test_registry_unknown_tool_returns_error_json_instead_of_raising():
    registry = ToolRegistry([])
    result = json.loads(registry.call("missing", "alice", None, {}))
    assert "unknown tool" in result["error"]
