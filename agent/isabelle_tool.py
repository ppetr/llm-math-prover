"""Wraps the Isabelle server sidecar for the agent's tool-calling loop.

The agent and `isabelle` run as separate containers sharing only a network
namespace (see design doc §2 and isabelle/README.md "Agent discovery"), so
connection info (port, password) is discovered by polling a small file on
a shared volume instead of reading ~/.isabelle/servers.db like
`isabelle client` does.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from isabelle_client import IsabelleClient
from isabelle_client.data_models import (
    SessionStartErrorResult,
    SessionStartRegularResult,
    UseTheoriesErrorResult,
    UseTheoriesResults,
)

_REGISTRATION_RE = re.compile(
    r'server "(?P<name>[^"]*)" = (?P<host>[^:\s]+):(?P<port>\d+) \(password "(?P<password>[^"]*)"\)'
)


class IsabelleToolError(RuntimeError):
    """Raised when the sidecar can't be reached or replies unexpectedly."""


def parse_registration(text: str) -> tuple[str, int, str]:
    """Extracts (host, port, password) from the server's stdout registration line."""
    match = _REGISTRATION_RE.search(text)
    if match is None:
        raise IsabelleToolError(f"no server registration line found in: {text!r}")
    return match["host"], int(match["port"]), match["password"]


def wait_for_registration(path: Path, timeout: float = 60, poll_interval: float = 0.5) -> tuple[str, int, str]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return parse_registration(path.read_text())
            except IsabelleToolError as exc:
                last_error = exc
        time.sleep(poll_interval)
    raise IsabelleToolError(
        f"{path} had no server registration line within {timeout}s"
    ) from last_error


@dataclass(frozen=True)
class CheckTheoryResult:
    ok: bool
    errors: list[str]


class IsabelleTool:
    """Checks theory source against a shared, lazily-started Isabelle session."""

    def __init__(self, server_info_path: Path, workspace_dir: Path, session: str = "HOL") -> None:
        self._server_info_path = server_info_path
        self._workspace_dir = workspace_dir
        self._session = session
        self._client: IsabelleClient | None = None
        self._session_id: str | None = None

    def _connect(self) -> IsabelleClient:
        if self._client is None:
            host, port, password = wait_for_registration(self._server_info_path)
            self._client = IsabelleClient(host, port, password)
        return self._client

    def _ensure_session(self) -> str:
        if self._session_id is None:
            client = self._connect()
            responses = client.session_start(session=self._session)
            last = responses[-1]
            if isinstance(last.response_body, SessionStartErrorResult):
                raise IsabelleToolError(f"session_start failed: {last.response_body.message}")
            if not isinstance(last.response_body, SessionStartRegularResult):
                raise IsabelleToolError(f"unexpected session_start reply: {last!r}")
            self._session_id = last.response_body.session_id
        return self._session_id

    def check_theory(self, user_id: str, theory_name: str, theory_source: str) -> CheckTheoryResult:
        """Writes `theory_source` into the user's workspace dir and checks it.

        `theory_name` must match the `theory ... begin ... end` header inside
        `theory_source` - Isabelle derives the theory's name from the file.
        """
        client = self._connect()
        session_id = self._ensure_session()

        work_dir = self._workspace_dir / user_id
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / f"{theory_name}.thy").write_text(theory_source)

        responses = client.use_theories(
            session_id=session_id, theories=[theory_name], master_dir=str(work_dir)
        )
        last = responses[-1]
        body = last.response_body
        if isinstance(body, UseTheoriesErrorResult):
            return CheckTheoryResult(ok=False, errors=[body.message])
        if isinstance(body, UseTheoriesResults):
            return CheckTheoryResult(ok=body.ok, errors=[m.message for m in body.errors])
        raise IsabelleToolError(f"unexpected use_theories reply: {last!r}")
