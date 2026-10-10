"""Integration test for the Isabelle/HOL + AFP image (Phase 1, isabelle/Dockerfile).

Requires Docker (or Podman aliased as `docker`) and a pre-built image:

    docker build -t isabelle-afp isabelle/
    pytest -m integration -v -s

Skips automatically when Docker or the image isn't available, so a plain
`pytest` run stays fast and offline.

Known host issue (diagnosed 2026-10-11): on a btrfs Docker data-root,
`session_start` can hang indefinitely at "Starting session HOL ..." with
~0% CPU - a btrfs-COW / SQLite-WAL incompatibility hitting Isabelle's
build-log sqlite files once overlay2 copies them up into the writable
layer. Worked around below with `--tmpfs` over both log directories (see
isabelle/README.md for the full explanation). That makes every fresh
container rebuild HOL from source once (a few minutes, not instant, but
finite) instead of hanging - hence the generous SESSION_TIMEOUT.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.integration

IMAGE = "isabelle-afp"
SESSION_TIMEOUT = 400
TMPFS_MOUNTS = (
    "--tmpfs",
    "/home/isabelle/.isabelle:uid=1001,gid=1001,mode=1777",
    "--tmpfs",
    "/home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log:uid=1001,gid=1001,mode=1777",
)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _image_exists() -> bool:
    result = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return result.returncode == 0


@pytest.fixture(scope="module")
def isabelle_container():
    if not _docker_available():
        pytest.skip("docker not available")
    if not _image_exists():
        pytest.skip(f"image '{IMAGE}' not built - run: docker build -t {IMAGE} isabelle/")

    name = f"isabelle-afp-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "--rm", "-d", "--name", name, *TMPFS_MOUNTS, IMAGE], check=True
    )
    try:
        yield name
    finally:
        subprocess.run(["docker", "kill", name], capture_output=True)


def _read_until(stream, overall_timeout: float, needles: tuple[str, ...]) -> str:
    """Reads lines until one contains any of `needles`, or raises on timeout/EOF.

    The Isabelle server protocol is async (an immediate OK/task id, then
    NOTE progress lines, then FINISHED/ERROR whenever the task completes) -
    a plain blocking readline() would hang forever if a reply never comes,
    and a fixed line count breaks the moment progress output changes.

    Reads happen on a separate thread, fed through a queue, rather than a
    select()-then-readline() loop: select() reports on the raw OS pipe, but
    a buffered TextIOWrapper's readline() can pull more than one line off
    that pipe per call - once that happens, select() has nothing new to
    report even though an already-buffered line (e.g. FINISHED) is sitting
    there unread.
    """
    q: "queue.Queue[str | None]" = queue.Queue()

    def pump() -> None:
        try:
            for line in stream:
                q.put(line)
                if any(needle in line for needle in needles):
                    return
        finally:
            q.put(None)

    threading.Thread(target=pump, daemon=True).start()

    deadline = time.monotonic() + overall_timeout
    lines: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"timed out waiting for {needles!r} after {overall_timeout}s; got so far: {lines}"
            )
        try:
            line = q.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError(
                f"timed out waiting for {needles!r} after {overall_timeout}s; got so far: {lines}"
            ) from None
        if line is None:
            raise TimeoutError(f"connection closed before {needles!r}; got so far: {lines}")
        lines.append(line)
        if any(needle in line for needle in needles):
            return "".join(lines)


def _run(container: str, command: str | None, timeout: float, needles: tuple[str, ...]) -> str:
    proc = subprocess.Popen(
        ["docker", "exec", "-i", container, "Isabelle/bin/isabelle", "client", "-n", "agent"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        if command is not None:
            proc.stdin.write(command + "\n")
            proc.stdin.flush()
        return _read_until(proc.stdout, timeout, needles)
    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_server_handshake(isabelle_container):
    """The hello line arrives on connect, before any command is sent."""
    output = _run(isabelle_container, None, timeout=30, needles=("isabelle_id",))
    assert "ERROR" not in output


def test_hol_session_starts(isabelle_container):
    output = _run(
        isabelle_container,
        'session_start {"session": "HOL"}',
        timeout=SESSION_TIMEOUT,
        needles=("FINISHED", "ERROR"),
    )
    assert "FINISHED" in output
    assert "ERROR" not in output


def test_afp_entry_registered(isabelle_container):
    output = _run(
        isabelle_container,
        'session_start {"session": "Example-Submission"}',
        timeout=SESSION_TIMEOUT,
        needles=("FINISHED", "ERROR"),
    )
    assert "FINISHED" in output
    assert "ERROR" not in output
