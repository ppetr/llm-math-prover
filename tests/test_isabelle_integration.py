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
layer. Worked around below by mounting named volumes with chattr +C
(no-COW) over both log directories (see isabelle/README.md for the full
explanation and one-time setup). Being no-COW rather than tmpfs, these
also persist across container instances, so a session whose build-log
state is still valid gets recognized as such and isn't rebuilt from
source on every single test run - only the first time, or after the
image/AFP version changes.

Known host issue (diagnosed 2026-10-12): the unbounded JVM/ML heap used
by a from-scratch rebuild (4GB+ JVM, unbounded PolyML) OOM-killed the host
(15GB RAM) outright. Worked around in isabelle/Dockerfile by capping both
ISABELLE_TOOL_JAVA_OPTIONS and ML_OPTIONS, plus a larger zram swap on the
host as a cushion - see isabelle/README.md. A capped, from-scratch
HOL+AFP rebuild takes ~7-8 minutes under no other load, but this host is
a shared desktop (not a dedicated CI runner) and real build time varies a
lot with whatever else is running (seen stretching past 20-40 minutes
under heavy concurrent load) - hence the generous SESSION_TIMEOUT below.
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
SESSION_TIMEOUT = 1800
HEAPLOG_MOUNTS = (
    # Mount exactly these two log/ subdirectories, not their parents - see
    # isabelle/README.md. Their parents also hold the AFP component
    # registration and compiled heap binaries, neither of which is
    # disposable; only the SQLite build-log dbs under log/ are affected by
    # the btrfs-COW/SQLite-WAL hang these volumes work around.
    #
    # Named (not tmpfs) so the build-log state survives across container
    # instances - that's what lets `isabelle build` recognize an
    # already-built heap as still valid and skip rebuilding it on the next
    # test run. Requires chattr +C on each volume's host directory (done
    # once, out of band - see isabelle/README.md) for the same btrfs
    # reason tmpfs used to work around.
    "--mount",
    "type=volume,source=isabelle-afp-user-heaplog,"
    "destination=/home/isabelle/.isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log",
    "--mount",
    "type=volume,source=isabelle-afp-dist-heaplog,"
    "destination=/home/isabelle/Isabelle/heaps/polyml-5.9.2_x86_64_32-linux/log",
)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _image_exists() -> bool:
    result = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return result.returncode == 0


@pytest.fixture(scope="function")
def isabelle_container():
    # function-scoped, not module-scoped: a session_start that times out
    # leaves its poly build process running server-side (disconnecting the
    # client does not kill it - see module docstring), and if the next
    # test reused the same container, it would contend with that orphaned
    # process for the same heap-log database. A fresh container per test
    # guarantees that orphan gets killed before the next test starts; the
    # named HEAPLOG_MOUNTS volumes still make the heap cache itself
    # persist across these fresh containers.
    if not _docker_available():
        pytest.skip("docker not available")
    if not _image_exists():
        pytest.skip(f"image '{IMAGE}' not built - run: docker build -t {IMAGE} isabelle/")

    name = f"isabelle-afp-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "--rm", "-d", "--name", name, *HEAPLOG_MOUNTS, IMAGE], check=True
    )
    try:
        _wait_until_execable(name)
        _wait_until_server_ready(name)
        yield name
    finally:
        subprocess.run(["docker", "kill", name], capture_output=True)


def _wait_until_execable(container: str, timeout: float = 15) -> None:
    """Waits until `docker exec` actually works, not just until `docker run -d` returns.

    `docker run -d` can return before the container is ready to accept an
    exec session - every manual reproduction of this test used a sleep
    before the first exec; this fixture originally had none, which is the
    likely cause of the "connection closed"/"not running" failures seen in
    practice (nothing to do with the btrfs/tmpfs issue above).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(["docker", "exec", container, "true"], capture_output=True)
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"container {container!r} never became ready for exec within {timeout}s")


def _wait_until_server_ready(container: str, timeout: float = 30) -> None:
    """Waits until `isabelle server` itself has registered, not just the shell.

    A separate, later readiness point than `_wait_until_execable`: the
    container's shell comes up long before the server's own JVM finishes
    starting and writes its entry to servers.db. Connecting too early gets
    `*** Isabelle server "agent" not running` even though the container and
    its exec subsystem are both already fine.

    Uses `isabelle server -l` (list registered servers) rather than
    `isabelle client -n agent`: a real client connection opens a session
    with the server, and an earlier version of this check did that
    repeatedly - the container was then observed dying moments after a
    *successful* check, immediately before the very next real connection.
    `-l` only reads the server registry, no session involved. (A log-file
    based check was tried in between and dropped: `-L FILE` only writes
    when there is something to log, so the file may never be created at
    all even once the server is fully up.)
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container, "Isabelle/bin/isabelle", "server", "-l"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "agent" in result.stdout:
            return
        time.sleep(1)
    raise TimeoutError(f"isabelle server in {container!r} never became ready within {timeout}s")


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
                f"timed out waiting for {needles!r} after {overall_timeout}s; "
                f"got so far: {lines}"
            )
        try:
            line = q.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError(
                f"timed out waiting for {needles!r} after {overall_timeout}s; "
                f"got so far: {lines}"
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
