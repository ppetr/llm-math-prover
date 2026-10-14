"""Wraps the Isabelle server sidecar for the agent's tool-calling loop.

The agent and `isabelle` run as separate containers sharing only a network
namespace (see design doc §2 and isabelle/README.md "Agent discovery"), so
connection info (port, password) is discovered by polling a small file on
a shared volume instead of reading ~/.isabelle/servers.db like
`isabelle client` does.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from isabelle_client import IsabelleClient
from isabelle_client.data_models import (
    SessionStartErrorResult,
    SessionStartRegularResult,
    UseTheoriesErrorResult,
    UseTheoriesResults,
)

logger = logging.getLogger(__name__)

_REGISTRATION_RE = re.compile(
    r'server "(?P<name>[^"]*)" = (?P<host>[^:\s]+):(?P<port>\d+) \(password "(?P<password>[^"]*)"\)'
)

T = TypeVar("T")


class IsabelleToolError(RuntimeError):
    """Raised when the sidecar can't be reached or replies unexpectedly."""


def _call_client(description: str, fn: Callable[[], T]) -> T:
    """Runs an isabelle_client call, turning transport/protocol failures
    (dropped socket, malformed reply, ...) into an IsabelleToolError the
    agent can report back as a normal tool result instead of crashing the
    whole request. The original exception is logged with its traceback and
    chained via `from` so `docker compose logs agent` still shows the real
    cause, not just "unexpected response".
    """
    try:
        return fn()
    except IsabelleToolError:
        raise
    except Exception as exc:
        logger.exception("isabelle_client call failed: %s", description)
        raise IsabelleToolError(f"{description}: {type(exc).__name__}: {exc}") from exc


def _check_session_id(session_id: str) -> None:
    # It becomes a workspace directory component, so no path traversal.
    if not session_id or session_id in (".", "..") or any(c in session_id for c in "/\\"):
        raise IsabelleToolError(f"invalid session_id: {session_id!r}")


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
    """Checks theory source against lazily-started Isabelle sessions, one per
    session_id (falling back to user_id) so concurrent conversations don't
    share Isabelle-level state.

    Sessions are capped at `max_sessions`: once the cap is hit, the least
    recently used one is stopped to free its resources before a new one is
    started (each Isabelle session is a real process on top of the loaded
    heap, not free).
    """

    def __init__(
        self, server_info_path: Path, workspace_dir: Path, session: str = "HOL", max_sessions: int = 4
    ) -> None:
        self._server_info_path = server_info_path
        self._workspace_dir = workspace_dir
        self._session = session
        self._max_sessions = max_sessions
        self._client: IsabelleClient | None = None
        # session_key -> Isabelle session_id, ordered least- to most-recently-used.
        self._sessions: OrderedDict[str, str] = OrderedDict()

    def _connect(self) -> IsabelleClient:
        if self._client is None:
            host, port, password = wait_for_registration(self._server_info_path)
            self._client = IsabelleClient(host, port, password)
        return self._client

    def _invalidate_connection(self) -> None:
        """Drops the cached client/sessions after a transport-level failure.

        server-entrypoint.sh restarts a crashed `isabelle server` in place
        (same container, so `agent`'s shared network namespace survives -
        see isabelle/README.md), handing out a fresh port/password and
        discarding every session. The next call re-reads registration.log
        and starts fresh sessions instead of reusing now-dead ones.
        """
        self._client = None
        self._sessions.clear()

    def _start_session(self, client: IsabelleClient) -> str:
        responses = _call_client("session_start", lambda: client.session_start(session=self._session))
        last = responses[-1]
        if isinstance(last.response_body, SessionStartErrorResult):
            raise IsabelleToolError(f"session_start failed: {last.response_body.message}")
        if not isinstance(last.response_body, SessionStartRegularResult):
            raise IsabelleToolError(f"unexpected session_start reply: {last!r}")
        return last.response_body.session_id

    def _ensure_session(self, client: IsabelleClient, session_key: str) -> str:
        if session_key in self._sessions:
            self._sessions.move_to_end(session_key)
            return self._sessions[session_key]

        if len(self._sessions) >= self._max_sessions:
            _evicted_key, evicted_session_id = self._sessions.popitem(last=False)
            try:
                client.session_stop(session_id=evicted_session_id)
            except Exception:
                pass  # best-effort - a stuck sidecar shouldn't block starting a new session

        session_id = self._start_session(client)
        self._sessions[session_key] = session_id
        return session_id

    def check_theory(
        self, user_id: str, theory_name: str, theory_source: str, session_id: str | None = None
    ) -> CheckTheoryResult:
        """Writes `theory_source` into the conversation's workspace dir and checks it.

        `theory_name` must match the `theory ... begin ... end` header inside
        `theory_source` - Isabelle derives the theory's name from the file.
        `session_id`, when given, scopes both the Isabelle session and the
        workspace dir to the conversation rather than just the user.
        """
        if session_id is not None:
            _check_session_id(session_id)
        session_key = session_id if session_id is not None else user_id

        try:
            client = self._connect()
            isabelle_session_id = self._ensure_session(client, session_key)

            work_dir = (
                self._workspace_dir / user_id if session_id is None else self._workspace_dir / user_id / session_id
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / f"{theory_name}.thy").write_text(theory_source)

            responses = _call_client(
                f"use_theories({theory_name!r}, session={isabelle_session_id!r})",
                lambda: client.use_theories(
                    session_id=isabelle_session_id, theories=[theory_name], master_dir=str(work_dir)
                ),
            )
            last = responses[-1]
            body = last.response_body
            if isinstance(body, UseTheoriesErrorResult):
                return CheckTheoryResult(ok=False, errors=[body.message])
            if isinstance(body, UseTheoriesResults):
                return CheckTheoryResult(ok=body.ok, errors=[m.message for m in body.errors])
            raise IsabelleToolError(f"unexpected use_theories reply: {last!r}")
        except IsabelleToolError:
            self._invalidate_connection()
            raise
