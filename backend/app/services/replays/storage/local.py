from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from datetime import datetime
from pathlib import Path

from app.services.replays.storage.base import (
    InvalidReplayObjectKey,
    ReplayObjectNotFound,
    ReplayObjectTooLarge,
    StoredObject,
    UploadTarget,
    validate_object_key,
)

_RANGE_CHUNK_SIZE = 1024 * 1024


class LocalReplayStorage:
    """Filesystem-backed replay object store under a non-public root directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def resolve_key(self, key: str) -> Path:
        validate_object_key(key)
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise InvalidReplayObjectKey(f"object key escapes storage root: {key!r}")
        return path

    def _part_path(self, path: Path) -> Path:
        return path.with_name(f"{path.name}.part")

    async def create_upload_target(
        self,
        key: str,
        *,
        expires_at: datetime,
        upload_url: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UploadTarget:
        self.resolve_key(key)
        if upload_url is None:
            raise ValueError("local storage requires upload_url for create_upload_target")
        return UploadTarget(
            method="PUT",
            url=upload_url,
            headers=dict(headers or {}),
            expires_at=expires_at,
        )

    async def write_stream(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        max_bytes: int,
    ) -> StoredObject:
        path = self.resolve_key(key)
        part = self._part_path(path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        size = 0
        promoted = False
        try:
            handle = await asyncio.to_thread(part.open, "wb")
            try:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise ReplayObjectTooLarge(f"object {key!r} exceeds max_bytes={max_bytes}")
                    hasher.update(chunk)
                    await asyncio.to_thread(handle.write, chunk)
            finally:
                await asyncio.to_thread(handle.close)

            await asyncio.to_thread(os.replace, part, path)
            promoted = True
        finally:
            if not promoted:
                await asyncio.to_thread(self._unlink_if_exists, part)

        return StoredObject(key=key, size_bytes=size, sha256=hasher.hexdigest())

    async def stat(self, key: str) -> StoredObject:
        path = self.resolve_key(key)
        if not await asyncio.to_thread(path.is_file):
            raise ReplayObjectNotFound(key)
        size = await asyncio.to_thread(path.stat)
        return StoredObject(key=key, size_bytes=size.st_size, sha256=None)

    async def download_to_path(self, key: str, destination: Path) -> StoredObject:
        path = self.resolve_key(key)
        if not await asyncio.to_thread(path.is_file):
            raise ReplayObjectNotFound(key)

        def _copy() -> int:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            return destination.stat().st_size

        size = await asyncio.to_thread(_copy)
        return StoredObject(key=key, size_bytes=size, sha256=None)

    async def upload_from_path(self, key: str, source: Path) -> StoredObject:
        path = self.resolve_key(key)
        part = self._part_path(path)
        promoted = False

        def _copy() -> tuple[int, str]:
            resolved_source = source.resolve()
            if not resolved_source.is_file():
                raise FileNotFoundError(resolved_source)
            path.parent.mkdir(parents=True, exist_ok=True)
            hasher = hashlib.sha256()
            size = 0
            with resolved_source.open("rb") as src, part.open("wb") as dst:
                while True:
                    chunk = src.read(_RANGE_CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    hasher.update(chunk)
                    dst.write(chunk)
            os.replace(part, path)
            return size, hasher.hexdigest()

        try:
            size, digest = await asyncio.to_thread(_copy)
            promoted = True
        finally:
            if not promoted:
                await asyncio.to_thread(self._unlink_if_exists, part)

        return StoredObject(key=key, size_bytes=size, sha256=digest)

    async def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        path = self.resolve_key(key)
        if not await asyncio.to_thread(path.is_file):
            raise ReplayObjectNotFound(key)
        size = (await asyncio.to_thread(path.stat)).st_size
        if not (0 <= start <= end < size):
            raise ValueError(f"invalid range start={start} end={end} for object size={size}")

        remaining = end - start + 1
        offset = start

        def _read_chunk(current: int, length: int) -> bytes:
            with path.open("rb") as handle:
                handle.seek(current)
                return handle.read(length)

        while remaining > 0:
            chunk_size = min(_RANGE_CHUNK_SIZE, remaining)
            chunk = await asyncio.to_thread(_read_chunk, offset, chunk_size)
            if not chunk:
                break
            yield chunk
            offset += len(chunk)
            remaining -= len(chunk)

    async def delete(self, key: str) -> None:
        path = self.resolve_key(key)
        await asyncio.to_thread(self._unlink_if_exists, path)
        await asyncio.to_thread(self._unlink_if_exists, self._part_path(path))

    @staticmethod
    def _unlink_if_exists(path: Path) -> None:
        if path.is_file() or path.is_symlink():
            path.unlink()
