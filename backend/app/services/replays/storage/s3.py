from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from app.services.replays.storage.base import (
    InvalidReplayObjectKey,
    ReplayObjectNotFound,
    ReplayObjectTooLarge,
    StoredObject,
    UploadTarget,
    validate_object_key,
)

_RANGE_CHUNK_SIZE = 1024 * 1024
_PUT_MAX_SECONDS = 1800
_GET_MAX_SECONDS = 300


class S3ReplayStorage:
    """S3-compatible replay object store under a private key prefix."""

    def __init__(self, *, client: Any, bucket: str, prefix: str) -> None:
        cleaned_prefix = prefix.strip("/")
        if not cleaned_prefix:
            raise ValueError("replay S3 prefix must be a non-empty private prefix")
        if not bucket:
            raise ValueError("replay S3 bucket is required")
        self._client = client
        self._bucket = bucket
        self._prefix = cleaned_prefix

    def resolve_key(self, key: str) -> str:
        validated = validate_object_key(key)
        physical = f"{self._prefix}/{validated}"
        if not physical.startswith(f"{self._prefix}/"):
            raise InvalidReplayObjectKey(f"object key escapes private prefix: {key!r}")
        return physical

    async def create_upload_target(
        self,
        key: str,
        *,
        expires_at: datetime,
        upload_url: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UploadTarget:
        del upload_url
        physical = self.resolve_key(key)
        capped_expires_at, expires_in = _cap_expiry(expires_at, _PUT_MAX_SECONDS)
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            ClientMethod="put_object",
            Params={"Bucket": self._bucket, "Key": physical},
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
        return UploadTarget(
            method="PUT",
            url=url,
            headers=dict(headers or {}),
            expires_at=capped_expires_at,
        )

    async def create_download_target(
        self,
        key: str,
        *,
        expires_at: datetime,
        headers: Mapping[str, str] | None = None,
    ) -> UploadTarget:
        physical = self.resolve_key(key)
        capped_expires_at, expires_in = _cap_expiry(expires_at, _GET_MAX_SECONDS)
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            ClientMethod="get_object",
            Params={"Bucket": self._bucket, "Key": physical},
            ExpiresIn=expires_in,
            HttpMethod="GET",
        )
        return UploadTarget(
            method="GET",
            url=url,
            headers=dict(headers or {}),
            expires_at=capped_expires_at,
        )

    async def write_stream(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        max_bytes: int,
    ) -> StoredObject:
        physical = self.resolve_key(key)
        hasher = hashlib.sha256()
        size = 0
        parts: list[bytes] = []
        async for chunk in chunks:
            size += len(chunk)
            if size > max_bytes:
                raise ReplayObjectTooLarge(f"object {key!r} exceeds max_bytes={max_bytes}")
            hasher.update(chunk)
            parts.append(chunk)
        body = b"".join(parts)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=physical,
            Body=body,
        )
        return StoredObject(key=key, size_bytes=size, sha256=hasher.hexdigest())

    async def stat(self, key: str) -> StoredObject:
        physical = self.resolve_key(key)

        def _head() -> int:
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=physical)
            except ClientError as error:
                if _is_not_found(error):
                    raise ReplayObjectNotFound(key) from error
                raise
            return int(response["ContentLength"])

        size = await asyncio.to_thread(_head)
        return StoredObject(key=key, size_bytes=size, sha256=None)

    async def download_to_path(self, key: str, destination: Path) -> StoredObject:
        physical = self.resolve_key(key)

        def _download() -> int:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=physical)
            except ClientError as error:
                if _is_not_found(error):
                    raise ReplayObjectNotFound(key) from error
                raise
            body = response["Body"]
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                payload = body.read()
                if not isinstance(payload, (bytes, bytearray)):
                    raise TypeError("S3 get_object Body.read() must return bytes")
                data = bytes(payload)
                destination.write_bytes(data)
                return len(data)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        size = await asyncio.to_thread(_download)
        return StoredObject(key=key, size_bytes=size, sha256=None)

    async def upload_from_path(self, key: str, source: Path) -> StoredObject:
        physical = self.resolve_key(key)

        def _upload() -> tuple[int, str]:
            resolved = source.resolve()
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            payload = resolved.read_bytes()
            hasher = hashlib.sha256(payload)
            self._client.put_object(Bucket=self._bucket, Key=physical, Body=payload)
            return len(payload), hasher.hexdigest()

        size, digest = await asyncio.to_thread(_upload)
        return StoredObject(key=key, size_bytes=size, sha256=digest)

    async def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        physical = self.resolve_key(key)

        def _head_size() -> int:
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=physical)
            except ClientError as error:
                if _is_not_found(error):
                    raise ReplayObjectNotFound(key) from error
                raise
            return int(response["ContentLength"])

        size = await asyncio.to_thread(_head_size)
        if not (0 <= start <= end < size):
            raise ValueError(
                f"invalid range start={start} end={end} for object size={size}"
            )

        remaining = end - start + 1
        offset = start

        def _read_range(current: int, length: int) -> bytes:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=physical,
                Range=f"bytes={current}-{current + length - 1}",
            )
            body = response["Body"]
            try:
                payload = body.read()
                if not isinstance(payload, (bytes, bytearray)):
                    raise TypeError("S3 get_object Body.read() must return bytes")
                return bytes(payload)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        while remaining > 0:
            chunk_size = min(_RANGE_CHUNK_SIZE, remaining)
            chunk = await asyncio.to_thread(_read_range, offset, chunk_size)
            if not chunk:
                break
            yield chunk
            offset += len(chunk)
            remaining -= len(chunk)

    async def delete(self, key: str) -> None:
        physical = self.resolve_key(key)

        def _delete() -> None:
            try:
                self._client.delete_object(Bucket=self._bucket, Key=physical)
            except ClientError as error:
                if _is_not_found(error):
                    return
                raise

        await asyncio.to_thread(_delete)


def _cap_expiry(expires_at: datetime, max_seconds: int) -> tuple[datetime, int]:
    now = datetime.now(UTC)
    requested = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    seconds = int((requested - now).total_seconds())
    expires_in = max(1, min(seconds, max_seconds))
    return now + timedelta(seconds=expires_in), expires_in


def _is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    return code in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}
