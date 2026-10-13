from pathlib import Path

import pytest

from agent.isabelle_tool import IsabelleToolError, parse_registration, wait_for_registration


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
