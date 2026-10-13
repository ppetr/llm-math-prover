import time

import pytest

from agent.artifacts import ArtifactError, ArtifactStore, DownloadToken


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path, signing_secret=b"test-secret", url_ttl=60)


def test_save_and_load_round_trip(store):
    store.save("alice", "proof.thy", b"theory X ...")
    token = store.sign("alice", "proof.thy")
    download = store.verify(token)
    assert download == DownloadToken(user_id="alice", name="proof.thy", expires_at=download.expires_at)
    assert store.load(download) == b"theory X ..."


def test_tampered_token_rejected(store):
    store.save("alice", "proof.thy", b"data")
    token = store.sign("alice", "proof.thy")
    flipped_char = "A" if token[-2] != "A" else "B"
    tampered = token[:-2] + flipped_char + token[-1]
    with pytest.raises(ArtifactError):
        store.verify(tampered)


def test_expired_token_rejected(tmp_path):
    store = ArtifactStore(tmp_path, signing_secret=b"secret", url_ttl=0)
    store.save("alice", "proof.thy", b"data")
    token = store.sign("alice", "proof.thy")
    time.sleep(0.01)
    with pytest.raises(ArtifactError, match="expired"):
        store.verify(token)


@pytest.mark.parametrize("bad_name", ["../escape", "a/b", "..", "", "a:b"])
def test_path_traversal_and_bad_names_rejected(store, bad_name):
    with pytest.raises(ArtifactError):
        store.save("alice", bad_name, b"data")
    with pytest.raises(ArtifactError):
        store.sign("alice", bad_name)


def test_load_missing_artifact_raises(store):
    token = store.sign("alice", "missing.thy")
    download = store.verify(token)
    with pytest.raises(ArtifactError, match="not found"):
        store.load(download)


def test_malformed_token_rejected(store):
    with pytest.raises(ArtifactError, match="malformed"):
        store.verify("not-a-valid-token")
