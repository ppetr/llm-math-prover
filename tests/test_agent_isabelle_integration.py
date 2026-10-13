"""End-to-end test of agent/isabelle_tool.py against a real Isabelle sidecar.

Mirrors tests/test_isabelle_integration.py's style (skips without Docker or
a pre-built image), but drives the check through the *agent's own* Docker
image rather than `isabelle client` directly - this is what actually proves
the sidecar-discovery mechanism (isabelle/README.md "Agent discovery")
works for a separate container, not just from the host.

Requires both images built first:

    docker build -t isabelle-afp isabelle/
    docker build -t ai-math-container-agent -f agent/Dockerfile .
    pytest -m integration -v -s
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ISABELLE_IMAGE = "isabelle-afp"
AGENT_IMAGE = "ai-math-container-agent"
HEAPLOG_VOLUMES = ("isabelle-afp-user-heaplog", "isabelle-afp-dist-heaplog")
# Generous for the same reason as SESSION_TIMEOUT in test_isabelle_integration.py -
# a cold HOL rebuild on this shared host can take well past the Isabelle-side
# default, even though the heaplog volumes above normally make it a cache hit.
CHECK_TIMEOUT = 1800

_SCRIPT = textwrap.dedent(
    """
    import json
    from pathlib import Path
    from agent.isabelle_tool import IsabelleTool

    tool = IsabelleTool(
        server_info_path=Path("/isabelle-server-info/registration.log"),
        workspace_dir=Path("/isabelle-workspace"),
        session="HOL",
    )
    theory_source = Path("/tmp/theory.thy").read_text()
    result = tool.check_theory("test-user", "Scratch", theory_source)
    print(json.dumps({"ok": result.ok, "errors": result.errors}))
    """
)

TRUE_LEMMA = """theory Scratch
imports Main
begin
lemma add_comm: "(a::nat) + b = b + a"
  by simp
end
"""

FALSE_LEMMA = """theory Scratch
imports Main
begin
lemma bogus: "(1::nat) = 2"
  by simp
end
"""


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _image_exists(name: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", name], capture_output=True).returncode == 0


@pytest.fixture
def isabelle_sidecar():
    if not _docker_available():
        pytest.skip("docker not available")
    if not _image_exists(ISABELLE_IMAGE):
        pytest.skip(f"image '{ISABELLE_IMAGE}' not built - run: docker build -t {ISABELLE_IMAGE} isabelle/")
    if not _image_exists(AGENT_IMAGE):
        pytest.skip(
            f"image '{AGENT_IMAGE}' not built - run: "
            f"docker build -t {AGENT_IMAGE} -f agent/Dockerfile ."
        )

    suffix = uuid.uuid4().hex[:8]
    name = f"isabelle-afp-agent-test-{suffix}"
    server_info_vol = f"isabelle-server-info-test-{suffix}"
    workspace_vol = f"isabelle-workspace-test-{suffix}"
    subprocess.run(["docker", "volume", "create", server_info_vol], check=True)
    subprocess.run(["docker", "volume", "create", workspace_vol], check=True)

    mounts = [
        "--mount",
        f"type=volume,source={HEAPLOG_VOLUMES[0]},"
        "destination=/home/isabelle/.isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log",
        "--mount",
        f"type=volume,source={HEAPLOG_VOLUMES[1]},"
        "destination=/home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log",
        "--mount",
        f"type=volume,source={server_info_vol},destination=/home/isabelle/server-info",
        "--mount",
        f"type=volume,source={workspace_vol},destination=/isabelle-workspace",
    ]
    subprocess.run(["docker", "run", "--rm", "-d", "--name", name, *mounts, ISABELLE_IMAGE], check=True)
    try:
        yield name, server_info_vol, workspace_vol
    finally:
        subprocess.run(["docker", "kill", name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", server_info_vol], capture_output=True)
        subprocess.run(["docker", "volume", "rm", workspace_vol], capture_output=True)


def _check_theory(
    tmp_path: Path, container: str, server_info_vol: str, workspace_vol: str, theory_source: str
) -> dict:
    theory_file = tmp_path / "theory.thy"
    theory_file.write_text(theory_source)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            f"container:{container}",
            "--mount",
            f"type=volume,source={server_info_vol},destination=/isabelle-server-info,readonly",
            "--mount",
            f"type=volume,source={workspace_vol},destination=/isabelle-workspace",
            "-v",
            f"{theory_file}:/tmp/theory.thy:ro",
            "--entrypoint",
            "python3",
            AGENT_IMAGE,
            "-c",
            _SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=CHECK_TIMEOUT,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    import json

    return json.loads(result.stdout.strip().splitlines()[-1])


def test_check_theory_accepts_true_lemma(tmp_path, isabelle_sidecar):
    container, server_info_vol, workspace_vol = isabelle_sidecar
    result = _check_theory(tmp_path, container, server_info_vol, workspace_vol, TRUE_LEMMA)
    assert result == {"ok": True, "errors": []}


def test_check_theory_rejects_false_lemma(tmp_path, isabelle_sidecar):
    container, server_info_vol, workspace_vol = isabelle_sidecar
    result = _check_theory(tmp_path, container, server_info_vol, workspace_vol, FALSE_LEMMA)
    assert result["ok"] is False
    assert result["errors"]
