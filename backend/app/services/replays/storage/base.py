from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

_OBJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,255}$")


class ReplayObjectTooLarge(Exception):
    """Raised when a streamed or uploaded object exceeds the allowed size."""


class ReplayObjectNotFound(Exception):
    """Raised when a requested object key does not exist."""


class InvalidReplayObjectKey(ValueError):
    """Raised when an object key fails strict validation."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str | None


@dataclass(frozen=True)
class UploadTarget:
    method: str
    url: str
    headers: Mapping[str, str]
    expires_at: datetime


def validate_object_key(key: str) -> str:
    if not _OBJECT_KEY_RE.fullmatch(key):
        raise InvalidReplayObjectKey(f"invalid object key: {key!r}")
    segments = key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise InvalidReplayObjectKey(f"invalid object key segments: {key!r}")
    return key


def temp_upload_key(key: str) -> str:
    """Derive the logical temporary key used for a client-driven direct upload.

    The final key is only exposed to readers once ``promote`` copies the temp
    object over it, so partially uploaded or abandoned uploads never appear at
    the real location.
    """
    return f"tmp/{key}"


class ReplayStorage(Protocol):
    async def create_upload_target(
        self,
        key: str,
        *,
        expires_at: datetime,
        upload_url: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UploadTarget: ...

    async def write_stream(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        max_bytes: int,
    ) -> StoredObject: ...

    async def stat(self, key: str) -> StoredObject: ...

    async def download_to_path(self, key: str, destination: Path) -> StoredObject: ...

    async def upload_from_path(self, key: str, source: Path) -> StoredObject: ...

    def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def promote(self, temp_key: str, final_key: str) -> StoredObject: ...

    async def delete_prefix(self, prefix: str) -> None: ...
