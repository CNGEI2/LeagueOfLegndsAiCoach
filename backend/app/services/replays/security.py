import hashlib
import hmac
import secrets


def issue_replay_token(secret: bytes) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _digest(secret, token)


def verify_replay_token(secret: bytes, token: str, expected_digest: str) -> bool:
    return hmac.compare_digest(_digest(secret, token), expected_digest)


def _digest(secret: bytes, token: str) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
