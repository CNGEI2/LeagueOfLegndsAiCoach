from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

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
# S3 requires every part except the last to be at least 5 MiB; use a larger
# default so most replay uploads only need a handful of upload_part calls.
_UPLOAD_PART_SIZE = 8 * 1024 * 1024


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
        final_physical = self.resolve_key(key)
        temp_physical = _temp_physical_key(final_physical)

        size, digest = await self._multipart_upload_stream(temp_physical, chunks, max_bytes)

        try:
            await asyncio.to_thread(self._promote_physical, temp_physical, final_physical)
        except Exception:
            await asyncio.to_thread(self._delete_physical_missing_ok, temp_physical)
            raise
        return StoredObject(key=key, size_bytes=size, sha256=digest)

    async def stat(self, key: str) -> StoredObject:
        physical = self.resolve_key(key)
        size = await asyncio.to_thread(self._head_size, physical)
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
            size = 0
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    while True:
                        chunk = body.read(_RANGE_CHUNK_SIZE)
                        if not chunk:
                            break
                        if not isinstance(chunk, (bytes, bytearray)):
                            raise TypeError("S3 get_object Body.read() must return bytes")
                        handle.write(chunk)
                        size += len(chunk)
                return size
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        size = await asyncio.to_thread(_download)
        return StoredObject(key=key, size_bytes=size, sha256=None)

    async def upload_from_path(self, key: str, source: Path) -> StoredObject:
        final_physical = self.resolve_key(key)
        temp_physical = _temp_physical_key(final_physical)

        def _upload() -> tuple[int, str]:
            resolved = source.resolve()
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            hasher = hashlib.sha256()
            size = 0
            upload_id = self._create_multipart_upload(temp_physical)
            parts: list[dict[str, Any]] = []
            part_number = 1
            completed = False
            try:
                with resolved.open("rb") as handle:
                    while True:
                        chunk = handle.read(_UPLOAD_PART_SIZE)
                        if not chunk:
                            break
                        size += len(chunk)
                        hasher.update(chunk)
                        etag = self._upload_part(temp_physical, upload_id, part_number, chunk)
                        parts.append({"ETag": etag, "PartNumber": part_number})
                        part_number += 1
                if not parts:
                    etag = self._upload_part(temp_physical, upload_id, part_number, b"")
                    parts.append({"ETag": etag, "PartNumber": part_number})
                self._complete_multipart_upload(temp_physical, upload_id, parts)
                completed = True
            finally:
                if not completed:
                    self._abort_multipart_upload_safe(temp_physical, upload_id)
            return size, hasher.hexdigest()

        size, digest = await asyncio.to_thread(_upload)
        try:
            await asyncio.to_thread(self._promote_physical, temp_physical, final_physical)
        except Exception:
            await asyncio.to_thread(self._delete_physical_missing_ok, temp_physical)
            raise
        return StoredObject(key=key, size_bytes=size, sha256=digest)

    async def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        physical = self.resolve_key(key)
        size = await asyncio.to_thread(self._head_size, physical)
        if not (0 <= start <= end < size):
            raise ValueError(f"invalid range start={start} end={end} for object size={size}")

        remaining = end - start + 1
        offset = start

        while remaining > 0:
            window = min(_RANGE_CHUNK_SIZE, remaining)
            chunk = await asyncio.to_thread(self._read_range, physical, offset, window)
            if not chunk:
                break
            yield chunk
            offset += len(chunk)
            remaining -= len(chunk)

    async def delete(self, key: str) -> None:
        physical = self.resolve_key(key)
        await asyncio.to_thread(self._delete_physical_missing_ok, physical)

    async def promote(self, temp_key: str, final_key: str) -> StoredObject:
        temp_physical = self.resolve_key(temp_key)
        final_physical = self.resolve_key(final_key)
        try:
            size = await asyncio.to_thread(self._promote_physical, temp_physical, final_physical)
        except ReplayObjectNotFound as error:
            raise ReplayObjectNotFound(temp_key) from error
        return StoredObject(key=final_key, size_bytes=size, sha256=None)

    async def delete_prefix(self, prefix: str) -> None:
        validated = validate_object_key(prefix)
        physical_prefix = f"{self._prefix}/{validated}/"
        if not physical_prefix.startswith(f"{self._prefix}/"):
            raise InvalidReplayObjectKey(f"object key escapes private prefix: {prefix!r}")
        await asyncio.to_thread(self._delete_all_under_prefix, physical_prefix)

    # -- internal helpers (always invoked via asyncio.to_thread) --------------

    async def _multipart_upload_stream(
        self,
        temp_physical: str,
        chunks: AsyncIterable[bytes],
        max_bytes: int,
    ) -> tuple[int, str]:
        hasher = hashlib.sha256()
        size = 0
        upload_id = await asyncio.to_thread(self._create_multipart_upload, temp_physical)
        parts: list[dict[str, Any]] = []
        buffer = bytearray()
        part_number = 1
        completed = False
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise ReplayObjectTooLarge(f"object exceeds max_bytes={max_bytes}")
                hasher.update(chunk)
                buffer.extend(chunk)
                while len(buffer) >= _UPLOAD_PART_SIZE:
                    part_payload = bytes(buffer[:_UPLOAD_PART_SIZE])
                    del buffer[:_UPLOAD_PART_SIZE]
                    etag = await asyncio.to_thread(
                        self._upload_part, temp_physical, upload_id, part_number, part_payload
                    )
                    parts.append({"ETag": etag, "PartNumber": part_number})
                    part_number += 1

            if buffer or not parts:
                part_payload = bytes(buffer)
                etag = await asyncio.to_thread(
                    self._upload_part, temp_physical, upload_id, part_number, part_payload
                )
                parts.append({"ETag": etag, "PartNumber": part_number})

            await asyncio.to_thread(
                self._complete_multipart_upload, temp_physical, upload_id, parts
            )
            completed = True
        finally:
            if not completed:
                await asyncio.to_thread(self._abort_multipart_upload_safe, temp_physical, upload_id)
        return size, hasher.hexdigest()

    def _create_multipart_upload(self, physical_key: str) -> str:
        response = self._client.create_multipart_upload(Bucket=self._bucket, Key=physical_key)
        return str(response["UploadId"])

    def _upload_part(
        self, physical_key: str, upload_id: str, part_number: int, payload: bytes
    ) -> str:
        response = self._client.upload_part(
            Bucket=self._bucket,
            Key=physical_key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=payload,
        )
        return str(response["ETag"])

    def _complete_multipart_upload(
        self, physical_key: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> None:
        self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=physical_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def _abort_multipart_upload_safe(self, physical_key: str, upload_id: str) -> None:
        with contextlib.suppress(ClientError):
            self._client.abort_multipart_upload(
                Bucket=self._bucket, Key=physical_key, UploadId=upload_id
            )

    def _promote_physical(self, temp_physical: str, final_physical: str) -> int:
        size = self._head_size(temp_physical, missing_key=temp_physical)
        self._client.copy_object(
            Bucket=self._bucket,
            Key=final_physical,
            CopySource={"Bucket": self._bucket, "Key": temp_physical},
        )
        self._delete_physical_missing_ok(temp_physical)
        return size

    def _delete_physical_missing_ok(self, physical_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=physical_key)
        except ClientError as error:
            if not _is_not_found(error):
                raise

    def _head_size(self, physical_key: str, *, missing_key: str | None = None) -> int:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=physical_key)
        except ClientError as error:
            if _is_not_found(error):
                raise ReplayObjectNotFound(missing_key or physical_key) from error
            raise
        return int(response["ContentLength"])

    def _read_range(self, physical_key: str, offset: int, length: int) -> bytes:
        response = self._client.get_object(
            Bucket=self._bucket,
            Key=physical_key,
            Range=f"bytes={offset}-{offset + length - 1}",
        )
        body = response["Body"]
        try:
            buffer = bytearray()
            remaining = length
            while remaining > 0:
                chunk = body.read(remaining)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray)):
                    raise TypeError("S3 get_object Body.read() must return bytes")
                buffer.extend(chunk)
                remaining -= len(chunk)
            return bytes(buffer)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def _delete_all_under_prefix(self, physical_prefix: str) -> None:
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": physical_prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            contents = response.get("Contents", [])
            if contents:
                objects = [{"Key": item["Key"]} for item in contents]
                self._client.delete_objects(
                    Bucket=self._bucket, Delete={"Objects": objects, "Quiet": True}
                )
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")


def _temp_physical_key(final_physical: str) -> str:
    return f"{final_physical}.upload-temp-{uuid4().hex}"


def _cap_expiry(expires_at: datetime, max_seconds: int) -> tuple[datetime, int]:
    now = datetime.now(UTC)
    requested = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    seconds = int((requested - now).total_seconds())
    expires_in = max(1, min(seconds, max_seconds))
    return now + timedelta(seconds=expires_in), expires_in


def _is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    return code in {"404", "NoSuchKey", "NotFound", "NoSuchBucket", "NoSuchUpload"}
