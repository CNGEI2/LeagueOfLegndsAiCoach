from app.services.replays.security import issue_replay_token, verify_replay_token


def test_token_is_returned_once_as_plaintext_and_verified_by_digest() -> None:
    token, digest = issue_replay_token(b"x" * 32)
    assert token != digest
    assert len(bytes.fromhex(digest)) == 32
    assert verify_replay_token(b"x" * 32, token, digest)
    assert not verify_replay_token(b"x" * 32, token + "x", digest)


def test_verify_rejects_wrong_secret() -> None:
    token, digest = issue_replay_token(b"x" * 32)
    assert not verify_replay_token(b"y" * 32, token, digest)
