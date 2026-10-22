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

"""Tool registry: OpenAI-style function specs + dispatch for the agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from agent.artifacts import ArtifactStore
from agent.isabelle_tool import IsabelleTool, IsabelleToolError


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    # (user_id, session_id, arguments) -> result text fed back to the LLM as a tool message
    handler: Callable[[str, str | None, dict], str]

    def as_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def build_isabelle_check_theory_tool(isabelle_tool: IsabelleTool, artifacts: ArtifactStore) -> ToolSpec:
    def handler(user_id: str, session_id: str | None, arguments: dict) -> str:
        theory_name = arguments["theory_name"]
        theory_source = arguments["theory_source"]
        try:
            result = isabelle_tool.check_theory(user_id, theory_name, theory_source, session_id=session_id)
        except IsabelleToolError as exc:
            return json.dumps({"ok": False, "errors": [f"tool error: {exc}"]})
        if result.ok:
            artifacts.save(user_id, f"{theory_name}.thy", theory_source.encode())
        return json.dumps({"ok": result.ok, "errors": result.errors})

    return ToolSpec(
        name="isabelle_check_theory",
        description=(
            'Checks an Isabelle/HOL theory against the Isabelle kernel. Returns '
            '{"ok": true} only if the kernel accepted every proof in it - nothing '
            "is proved unless this says ok=true, regardless of how confident the "
            "proof looks. On success the theory is saved as a downloadable artifact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "theory_name": {
                    "type": "string",
                    "description": "Must match the name in the theory's `theory NAME imports ...` header.",
                },
                "theory_source": {
                    "type": "string",
                    "description": "Full .thy file content, including the theory/imports/begin/end wrapper.",
                },
            },
            "required": ["theory_name", "theory_source"],
        },
        handler=handler,
    )


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def openai_tools(self) -> list[dict]:
        return [spec.as_openai_tool() for spec in self._specs.values()]

    def call(self, name: str, user_id: str, session_id: str | None, arguments: dict) -> str:
        spec = self._specs.get(name)
        if spec is None:
            return json.dumps({"error": f"unknown tool: {name}"})
        return spec.handler(user_id, session_id, arguments)
