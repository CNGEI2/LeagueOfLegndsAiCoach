import hashlib
import hmac
import re
import secrets

from app.core.errors import replay_not_found

_DEFAULT_MAX_TOKEN_LENGTH = 512
_TOKEN68_RE = re.compile(r"^[-A-Za-z0-9._~+/]+(=*)$")
_BEARER_SCHEME = "bearer"


def issue_replay_token(secret: bytes) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _digest(secret, token)


def verify_replay_token(secret: bytes, token: str, expected_digest: str) -> bool:
    return hmac.compare_digest(_digest(secret, token), expected_digest)


def parse_bearer_token(
    authorization: str | None,
    *,
    max_length: int = _DEFAULT_MAX_TOKEN_LENGTH,
    required: bool = False,
) -> str | None:
    if authorization is None:
        if required:
            raise replay_not_found()
        return None
    if not authorization or authorization[0].isspace():
        raise replay_not_found()
    if len(authorization) < len(_BEARER_SCHEME) + 2:
        raise replay_not_found()
    scheme = authorization[: len(_BEARER_SCHEME)]
    if scheme.lower() != _BEARER_SCHEME:
        raise replay_not_found()
    remainder = authorization[len(_BEARER_SCHEME) :]
    if not remainder or remainder[0] != " ":
        raise replay_not_found()
    index = 0
    while index < len(remainder) and remainder[index] == " ":
        index += 1
    token = remainder[index:]
    if not _is_valid_bearer_token(token, max_length=max_length):
        raise replay_not_found()
    return token


def _is_valid_bearer_token(token: str, *, max_length: int) -> bool:
    if not token:
        return False
    try:
        encoded = token.encode("ascii")
    except UnicodeEncodeError:
        return False
    if len(encoded) > max_length:
        return False
    if any(ch.isspace() for ch in token):
        return False
    return _TOKEN68_RE.fullmatch(token) is not None


def _digest(secret: bytes, token: str) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
