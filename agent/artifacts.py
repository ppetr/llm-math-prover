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

"""Output artifacts and signed, time-limited download links (design doc §5).

Mechanism is deliberately plain: an artifact is a file under
data/<user_id>/artifacts/<name>, and a download link is that same
(user_id, name) plus an expiry, HMAC-signed so the token carries its own
authorization - no dependency on a shared session/cookie with Open WebUI,
same idea as a presigned S3 URL.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from pathlib import Path


class ArtifactError(ValueError):
    """Bad artifact name, expired/invalid token, or missing file."""


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return urlsafe_b64decode(data + padding)


def _check_name(name: str) -> None:
    # No "/" (path traversal) and no ":" (the token payload's own field separator).
    if not name or name in (".", "..") or any(c in name for c in "/\\:"):
        raise ArtifactError(f"invalid artifact name: {name!r}")


@dataclass(frozen=True)
class DownloadToken:
    user_id: str
    name: str
    expires_at: int


class ArtifactStore:
    def __init__(self, data_dir: Path, signing_secret: bytes, url_ttl: int) -> None:
        self._data_dir = data_dir
        self._signing_secret = signing_secret
        self._url_ttl = url_ttl

    def _artifact_path(self, user_id: str, name: str) -> Path:
        _check_name(user_id)
        _check_name(name)
        return self._data_dir / user_id / "artifacts" / name

    def save(self, user_id: str, name: str, content: bytes) -> Path:
        path = self._artifact_path(user_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def sign(self, user_id: str, name: str) -> str:
        """Builds a token proving (user_id, name) was issued by us before `expires_at`."""
        _check_name(user_id)
        _check_name(name)
        expires_at = int(time.time()) + self._url_ttl
        payload = f"{user_id}:{name}:{expires_at}".encode()
        signature = hmac.new(self._signing_secret, payload, hashlib.sha256).digest()
        return f"{_b64encode(payload)}.{_b64encode(signature)}"

    def verify(self, token: str) -> DownloadToken:
        try:
            payload_b64, signature_b64 = token.split(".", 1)
            payload = _b64decode(payload_b64)
            signature = _b64decode(signature_b64)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ArtifactError("malformed token") from exc

        expected = hmac.new(self._signing_secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ArtifactError("invalid signature")

        try:
            user_id, name, expires_at_str = payload.decode().split(":", 2)
            expires_at = int(expires_at_str)
        except ValueError as exc:
            raise ArtifactError("malformed token payload") from exc

        if time.time() > expires_at:
            raise ArtifactError("token expired")
        return DownloadToken(user_id=user_id, name=name, expires_at=expires_at)

    def load(self, token: DownloadToken) -> bytes:
        path = self._artifact_path(token.user_id, token.name)
        if not path.is_file():
            raise ArtifactError(f"artifact not found: {token.name!r}")
        return path.read_bytes()
