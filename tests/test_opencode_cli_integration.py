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

"""End-to-end test of the OpenCode CLI container against the agent.

Drives the real ghcr.io/anomalyco/opencode image through its non-interactive
`run` subcommand (README.md "Optional: CLI client (OpenCode)"), proving the
opencode.json wiring (provider/baseURL/default model - builder/templates/
opencode.json.j2) actually lets a client reach the agent and get back a
message, the same way `docker compose --profile cli run --no-deps cli` does.

Stands in for the real LiteLLM gateway with a canned HTTP server instead of
hitting a real model - this test is about the CLI <-> agent wire protocol,
not about model quality, and must not need a paid API key to run.

Requires both images:

    docker build -t ai-math-container-agent -f agent/Dockerfile .
    docker pull ghcr.io/anomalyco/opencode:latest
    pytest -m integration -v -s
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

AGENT_IMAGE = "ai-math-container-agent"
OPENCODE_IMAGE = "ghcr.io/anomalyco/opencode:latest"
RUN_TIMEOUT = 60

# Minimal stdlib-only OpenAI-compatible stand-in for LiteLLM: any POST gets a
# fixed assistant reply, any GET a fixed model list - enough for the agent's
# tool-calling loop (agent/main.py) to produce a final, non-tool-call message.
_FAKE_LLM_SCRIPT = textwrap.dedent(
    """
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _json(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self._json({"choices": [{"message": {"role": "assistant", "content": "PONG"}}]})

        def do_GET(self):
            self._json({"data": [{"id": "claude"}]})

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("0.0.0.0", 4000), Handler).serve_forever()
    """
)


# Like _FAKE_LLM_SCRIPT, but scripted for a two-turn tool-call exchange:
# first reply requests isabelle_check_theory, second summarizes its result.
# Reads both replies from JSON files instead of embedding them inline, so
# the test can hand it a real .thy source without fighting Python-in-a-
# shell-arg quoting.
_SCRIPTED_TOOL_CALL_LLM_SCRIPT = textwrap.dedent(
    """
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    FIRST = json.load(open("/responses/first.json"))
    SECOND = json.load(open("/responses/second.json"))

    class Handler(BaseHTTPRequestHandler):
        def _json(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            has_tool_result = any(m.get("role") == "tool" for m in body.get("messages", []))
            self._json({"choices": [{"message": SECOND if has_tool_result else FIRST}]})

        def do_GET(self):
            self._json({"data": [{"id": "claude"}]})

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("0.0.0.0", 4000), Handler).serve_forever()
    """
)

TRUE_LEMMA = """theory Scratch
imports Main
begin
lemma add_comm: "(a::nat) + b = b + a"
  by simp
end
"""

ISABELLE_IMAGE = "isabelle-afp"
HEAPLOG_VOLUMES = ("isabelle-afp-user-heaplog", "isabelle-afp-dist-heaplog")
# Generous for the same reason as test_agent_isabelle_integration.py's
# CHECK_TIMEOUT - a cold HOL rebuild can take well past a normal timeout,
# even though the heaplog volumes above normally make it a cache hit.
ISABELLE_RUN_TIMEOUT = 1800


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _image_exists(name: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", name], capture_output=True).returncode == 0


@pytest.fixture
def agent_stack():
    """Starts a fake LiteLLM gateway and the real agent on a private network.

    Mirrors dist/compose.yaml's agent/llm-gateway wiring (same default
    LITELLM_BASE_URL), minus Isabelle - nothing here calls the
    isabelle_check_theory tool, and IsabelleTool only connects lazily on
    first use (agent/isabelle_tool.py), so no sidecar is needed.
    """
    if not _docker_available():
        pytest.skip("docker not available")
    if not _image_exists(AGENT_IMAGE):
        pytest.skip(f"image '{AGENT_IMAGE}' not built - run: docker build -t {AGENT_IMAGE} -f agent/Dockerfile .")
    if not _image_exists(OPENCODE_IMAGE):
        pytest.skip(f"image '{OPENCODE_IMAGE}' not pulled - run: docker pull {OPENCODE_IMAGE}")

    suffix = uuid.uuid4().hex[:8]
    network = f"opencode-cli-test-{suffix}"
    llm_name = f"fake-llm-gateway-{suffix}"
    agent_name = f"agent-{suffix}"
    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    try:
        subprocess.run(
            [
                "docker", "run", "--rm", "-d",
                "--network", network, "--network-alias", "llm-gateway",
                "--name", llm_name,
                "--entrypoint", "python3", AGENT_IMAGE, "-c", _FAKE_LLM_SCRIPT,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker", "run", "--rm", "-d",
                "--network", network, "--network-alias", "agent",
                "--name", agent_name,
                "-e", "AGENT_SIGNING_SECRET=test-signing-secret",
                "-e", "LITELLM_MASTER_KEY=test-key",
                AGENT_IMAGE,
            ],
            check=True,
            capture_output=True,
        )
        yield network
    finally:
        subprocess.run(["docker", "rm", "-f", llm_name], capture_output=True)
        subprocess.run(["docker", "rm", "-f", agent_name], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


def test_opencode_run_reaches_agent_and_prints_its_reply(tmp_path: Path, agent_stack: str):
    opencode_config = {
        "autoupdate": False,
        "model": "local/claude",
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "ai-math-container-test",
                "options": {"baseURL": "http://agent:8000/v1", "apiKey": "test-key"},
                "models": {"claude": {"name": "claude"}},
            }
        },
    }
    config_file = tmp_path / "opencode.json"
    config_file.write_text(json.dumps(opencode_config))

    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", agent_stack,
            "-e", "OPENCODE_CONFIG=/opencode.json",
            "-v", f"{config_file}:/opencode.json:ro",
            OPENCODE_IMAGE,
            "run", "ping",
        ],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "PONG" in result.stdout


@pytest.fixture
def isabelle_cli_stack():
    """Starts a real Isabelle sidecar, the real agent, and a scripted fake
    LLM that drives the isabelle_check_theory tool - the full cli -> agent ->
    Isabelle kernel chain, minus a paid LLM call.

    Network topology matches dist/compose.yaml when tools.isabelle.enabled:
    agent shares the isabelle container's network namespace (same as
    `network_mode: "service:isabelle"`), so a client reaches it at the
    isabelle container's own address - see isabelle/README.md "Agent
    discovery" and builder/templates/compose.yaml.j2.
    """
    if not _docker_available():
        pytest.skip("docker not available")
    if not _image_exists(ISABELLE_IMAGE):
        pytest.skip(f"image '{ISABELLE_IMAGE}' not built - run: docker build -t {ISABELLE_IMAGE} isabelle/")
    if not _image_exists(AGENT_IMAGE):
        pytest.skip(f"image '{AGENT_IMAGE}' not built - run: docker build -t {AGENT_IMAGE} -f agent/Dockerfile .")
    if not _image_exists(OPENCODE_IMAGE):
        pytest.skip(f"image '{OPENCODE_IMAGE}' not pulled - run: docker pull {OPENCODE_IMAGE}")

    suffix = uuid.uuid4().hex[:8]
    network = f"opencode-isabelle-test-{suffix}"
    isabelle_name = f"isabelle-{suffix}"
    agent_name = f"agent-{suffix}"
    server_info_vol = f"isabelle-server-info-test-{suffix}"
    workspace_vol = f"isabelle-workspace-test-{suffix}"

    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    subprocess.run(["docker", "volume", "create", server_info_vol], check=True, capture_output=True)
    subprocess.run(["docker", "volume", "create", workspace_vol], check=True, capture_output=True)
    try:
        subprocess.run(
            [
                "docker", "run", "--rm", "-d",
                "--network", network, "--network-alias", "isabelle",
                "--name", isabelle_name,
                "--mount",
                f"type=volume,source={HEAPLOG_VOLUMES[0]},"
                "destination=/home/isabelle/.isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log",
                "--mount",
                f"type=volume,source={HEAPLOG_VOLUMES[1]},"
                "destination=/home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log",
                "--mount", f"type=volume,source={server_info_vol},destination=/home/isabelle/server-info",
                "--mount", f"type=volume,source={workspace_vol},destination=/isabelle-workspace",
                ISABELLE_IMAGE,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker", "run", "--rm", "-d",
                "--network", f"container:{isabelle_name}",
                "--name", agent_name,
                "-e", "AGENT_SIGNING_SECRET=test-signing-secret",
                "-e", "LITELLM_MASTER_KEY=test-key",
                "--mount", f"type=volume,source={server_info_vol},destination=/isabelle-server-info,readonly",
                "--mount", f"type=volume,source={workspace_vol},destination=/isabelle-workspace",
                AGENT_IMAGE,
            ],
            check=True,
            capture_output=True,
        )
        yield network
    finally:
        subprocess.run(["docker", "rm", "-f", agent_name], capture_output=True)
        subprocess.run(["docker", "rm", "-f", isabelle_name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", server_info_vol], capture_output=True)
        subprocess.run(["docker", "volume", "rm", workspace_vol], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


def test_opencode_run_drives_a_real_isabelle_check_theory_call(tmp_path: Path, isabelle_cli_stack: str):
    network = isabelle_cli_stack
    suffix = uuid.uuid4().hex[:8]
    llm_name = f"fake-llm-gateway-{suffix}"

    responses_dir = tmp_path / "responses"
    responses_dir.mkdir()
    tool_call_args = json.dumps({"theory_name": "Scratch", "theory_source": TRUE_LEMMA})
    (responses_dir / "first.json").write_text(
        json.dumps(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "isabelle_check_theory", "arguments": tool_call_args},
                    }
                ],
            }
        )
    )
    (responses_dir / "second.json").write_text(json.dumps({"role": "assistant", "content": "VERIFIED"}))

    subprocess.run(
        [
            "docker", "run", "--rm", "-d",
            "--network", network, "--network-alias", "llm-gateway",
            "--name", llm_name,
            "-v", f"{responses_dir}:/responses:ro",
            "--entrypoint", "python3", AGENT_IMAGE, "-c", _SCRIPTED_TOOL_CALL_LLM_SCRIPT,
        ],
        check=True,
        capture_output=True,
    )
    try:
        opencode_config = {
            "autoupdate": False,
            "model": "local/claude",
            "provider": {
                "local": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "ai-math-container-test",
                    # Matches api_base when tools.isabelle.enabled (builder/render.py):
                    # the agent has no network identity of its own.
                    "options": {"baseURL": "http://isabelle:8000/v1", "apiKey": "test-key"},
                    "models": {"claude": {"name": "claude"}},
                }
            },
        }
        config_file = tmp_path / "opencode.json"
        config_file.write_text(json.dumps(opencode_config))

        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--network", network,
                "-e", "OPENCODE_CONFIG=/opencode.json",
                "-v", f"{config_file}:/opencode.json:ro",
                OPENCODE_IMAGE,
                "run", "Can you check this theorem?",
            ],
            capture_output=True,
            text=True,
            timeout=ISABELLE_RUN_TIMEOUT,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", llm_name], capture_output=True)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "VERIFIED" in result.stdout
