import hmac

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


def _assert_replay_not_found(authorization: str | None, *, required: bool = True) -> None:
    with pytest.raises(ApiError) as raised:
        parse_bearer_token(authorization, required=required)
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert raised.value.status_code == 404
    if authorization is not None:
        assert authorization not in raised.value.message


def test_parse_bearer_token_accepts_valid_bearer_and_rejects_invalid() -> None:
    accepted = parse_bearer_token("Bearer abc.def")
    assert isinstance(accepted, str)
    assert hmac.compare_digest(accepted, "abc.def")

    lowercase = parse_bearer_token("bearer abc.def", required=True)
    assert isinstance(lowercase, str)
    assert hmac.compare_digest(lowercase, "abc.def")

    multi_space = parse_bearer_token("Bearer  abc.def", required=True)
    assert isinstance(multi_space, str)
    assert hmac.compare_digest(multi_space, "abc.def")

    assert parse_bearer_token(None) is None

    _assert_replay_not_found("Basic abc")
    _assert_replay_not_found("Bearer")
    _assert_replay_not_found("Bearer ")
    _assert_replay_not_found("Bearer tok en")
    _assert_replay_not_found("Bearer token ")
    _assert_replay_not_found(" Bearer abc.def")
    _assert_replay_not_found("\tBearer abc.def")
    _assert_replay_not_found("Bearer\tabc.def")
    _assert_replay_not_found("Bearer\u00a0abc.def")
    _assert_replay_not_found("Bearer café")
    _assert_replay_not_found("Bearer " + ("x" * 513))

    multi_byte = "é"
    assert len(multi_byte) == 1
    assert len(multi_byte.encode("utf-8")) == 2
    oversized_multibyte = multi_byte * 257  # 514 bytes, 257 chars
    assert len(oversized_multibyte) < 512
    assert len(oversized_multibyte.encode("utf-8")) > 512
    _assert_replay_not_found("Bearer " + oversized_multibyte)

    exact = "y" * 512
    parsed = parse_bearer_token("Bearer " + exact, required=True)
    assert isinstance(parsed, str)
    assert hmac.compare_digest(parsed, exact)
    assert "Bearer " + exact not in repr(parsed)


def test_parse_bearer_token_rejects_tab_separator_without_leaking_token() -> None:
    token = "secret-token68value"
    authorization = f"Bearer\t{token}"
    with pytest.raises(ApiError) as raised:
        parse_bearer_token(authorization, required=True)
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert token not in raised.value.message
    assert authorization not in raised.value.message


def test_parse_bearer_token_rejects_leading_whitespace_without_leaking_token() -> None:
    token = "secret-token68value"
    authorization = f" Bearer {token}"
    with pytest.raises(ApiError) as raised:
        parse_bearer_token(authorization, required=True)
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert token not in raised.value.message
    assert authorization not in raised.value.message
