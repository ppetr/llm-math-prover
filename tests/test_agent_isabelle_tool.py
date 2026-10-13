from pathlib import Path

import pytest
from isabelle_client.data_models import SessionStartRegularResult, UseTheoriesResults

from agent.isabelle_tool import IsabelleTool, IsabelleToolError, parse_registration, wait_for_registration


def test_parse_registration_extracts_host_port_password():
    line = 'server "agent" = 127.0.0.1:4443 (password "9feab555-2eec-4a3d-a605-4e8046c75c62")'
    assert parse_registration(line) == ("127.0.0.1", 4443, "9feab555-2eec-4a3d-a605-4e8046c75c62")


def test_parse_registration_ignores_surrounding_noise():
    text = "some startup banner\n" + 'server "agent" = 127.0.0.1:4443 (password "abc")' + "\ntrailing\n"
    assert parse_registration(text) == ("127.0.0.1", 4443, "abc")


def test_parse_registration_raises_when_missing():
    with pytest.raises(IsabelleToolError):
        parse_registration("no registration line here")


def test_wait_for_registration_returns_as_soon_as_file_has_the_line(tmp_path):
    path = tmp_path / "registration.log"
    path.write_text('server "agent" = 127.0.0.1:4443 (password "pw")')
    assert wait_for_registration(path, timeout=5, poll_interval=0.05) == ("127.0.0.1", 4443, "pw")


def test_wait_for_registration_times_out_when_file_never_appears(tmp_path):
    with pytest.raises(IsabelleToolError):
        wait_for_registration(tmp_path / "never.log", timeout=0.2, poll_interval=0.05)


class _Response:
    def __init__(self, response_body):
        self.response_body = response_body


class FakeIsabelleClient:
    """Stands in for IsabelleClient so IsabelleTool's session pooling can be tested
    without a real sidecar - IsabelleTool._connect() is bypassed by setting
    tool._client directly, since it only calls IsabelleClient(...) when unset.
    """

    def __init__(self):
        self.started: list[str] = []
        self.stopped: list[str] = []
        self._counter = 0

    def session_start(self, session="HOL", **kwargs):
        self._counter += 1
        session_id = f"sess-{self._counter}"
        self.started.append(session_id)
        return [_Response(SessionStartRegularResult(task="t", session_id=session_id, tmp_dir="/tmp"))]

    def session_stop(self, session_id):
        self.stopped.append(session_id)
        return []

    def use_theories(self, session_id, theories, master_dir):
        return [_Response(UseTheoriesResults(ok=True, errors=[], nodes=[]))]


def _tool_with_fake_client(tmp_path, max_sessions=4) -> tuple[IsabelleTool, FakeIsabelleClient]:
    tool = IsabelleTool(
        server_info_path=tmp_path / "unused.log", workspace_dir=tmp_path / "workspace", max_sessions=max_sessions
    )
    client = FakeIsabelleClient()
    tool._client = client
    return tool, client


def test_check_theory_reuses_session_for_same_session_id(tmp_path):
    tool, client = _tool_with_fake_client(tmp_path)

    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-1")
    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-1")

    assert len(client.started) == 1


def test_check_theory_starts_separate_sessions_per_session_id(tmp_path):
    tool, client = _tool_with_fake_client(tmp_path)

    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-1")
    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-2")

    assert len(client.started) == 2


def test_check_theory_falls_back_to_user_id_when_session_id_missing(tmp_path):
    tool, client = _tool_with_fake_client(tmp_path)

    tool.check_theory("alice", "T", "theory T imports Main begin end")
    tool.check_theory("alice", "T", "theory T imports Main begin end")
    tool.check_theory("bob", "T", "theory T imports Main begin end")

    assert len(client.started) == 2


def test_check_theory_evicts_least_recently_used_session_past_the_cap(tmp_path):
    tool, client = _tool_with_fake_client(tmp_path, max_sessions=2)

    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-1")
    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-2")
    tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="conv-3")

    assert client.stopped == [client.started[0]]
    assert len(client.started) == 3


def test_check_theory_rejects_path_traversal_in_session_id(tmp_path):
    tool, _client = _tool_with_fake_client(tmp_path)

    with pytest.raises(IsabelleToolError):
        tool.check_theory("alice", "T", "theory T imports Main begin end", session_id="../escape")
