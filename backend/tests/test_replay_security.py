import pytest

from app.core.errors import ApiError
from app.services.replays.security import (
    issue_replay_token,
    parse_bearer_token,
    verify_replay_token,
)


def test_token_is_returned_once_as_plaintext_and_verified_by_digest() -> None:
    token, digest = issue_replay_token(b"x" * 32)
    assert token != digest
    assert len(bytes.fromhex(digest)) == 32
    assert verify_replay_token(b"x" * 32, token, digest)
    assert not verify_replay_token(b"x" * 32, token + "x", digest)


def test_verify_rejects_wrong_secret() -> None:
    token, digest = issue_replay_token(b"x" * 32)
    assert not verify_replay_token(b"y" * 32, token, digest)


def test_parse_bearer_token_accepts_valid_bearer_and_rejects_invalid() -> None:
    assert parse_bearer_token("Bearer abc.def") == "abc.def"
    assert parse_bearer_token(None) is None
    with pytest.raises(ApiError) as malformed:
        parse_bearer_token("Basic abc", required=True)
    assert malformed.value.code == "REPLAY_NOT_FOUND"
    with pytest.raises(ApiError) as empty:
        parse_bearer_token("Bearer ", required=True)
    assert empty.value.code == "REPLAY_NOT_FOUND"
    with pytest.raises(ApiError) as oversized:
        parse_bearer_token("Bearer " + ("x" * 513), required=True)
    assert oversized.value.code == "REPLAY_NOT_FOUND"
    assert parse_bearer_token("Bearer " + ("y" * 512), required=True) == "y" * 512
