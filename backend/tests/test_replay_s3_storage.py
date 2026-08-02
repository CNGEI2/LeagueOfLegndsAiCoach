from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from app.core.config import Settings
from app.services.replays.storage import s3 as s3_module
from app.services.replays.storage.base import (
    InvalidReplayObjectKey,
    ReplayObjectNotFound,
    ReplayObjectTooLarge,
)
from app.services.replays.storage.factory import build_replay_storage
from app.services.replays.storage.local import LocalReplayStorage
from app.services.replays.storage.s3 import S3ReplayStorage

BUCKET = "replay-private"
PREFIX = "replays"
LOGICAL_KEY = "source/abc/input"
PHYSICAL_KEY = f"{PREFIX}/{LOGICAL_KEY}"


async def aiter(chunks: Iterable[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def _client() -> Any:
    return boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        config=Config(signature_version="s3v4"),
    )


def _storage(client: Any) -> S3ReplayStorage:
    return S3ReplayStorage(client=client, bucket=BUCKET, prefix=PREFIX)


def _expires_seconds(url: str) -> int:
    query = parse_qs(urlparse(url).query)
    if "X-Amz-Expires" in query:
        return int(query["X-Amz-Expires"][0])
    values = query.get("Expires")
    assert values is not None
    # SigV2 encodes an absolute unix timestamp rather than a relative TTL.
    return int(values[0]) - int(datetime.now(UTC).timestamp())


# ---------------------------------------------------------------------------
# Presigned URL tests exercise the real boto3 client + Stubber since they never
# touch the multipart/streaming code paths.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_presigned_put_caps_expiry_at_30_minutes() -> None:
    client = _client()
    storage = _storage(client)
    expires_at = datetime.now(UTC) + timedelta(hours=2)

    target = await storage.create_upload_target(LOGICAL_KEY, expires_at=expires_at)

    assert target.method == "PUT"
    assert not hasattr(target, "key")
    assert _expires_seconds(target.url) == 1800
    assert PHYSICAL_KEY in target.url
    assert "acl=" not in target.url.lower()
    assert target.expires_at <= datetime.now(UTC) + timedelta(minutes=30, seconds=5)


@pytest.mark.asyncio
async def test_presigned_get_caps_expiry_at_5_minutes() -> None:
    client = _client()
    storage = _storage(client)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    target = await storage.create_download_target(LOGICAL_KEY, expires_at=expires_at)

    assert target.method == "GET"
    assert not hasattr(target, "key")
    assert _expires_seconds(target.url) == 300
    assert PHYSICAL_KEY in target.url
    assert target.expires_at <= datetime.now(UTC) + timedelta(minutes=5, seconds=5)


@pytest.mark.asyncio
async def test_stat_uses_head_object_size() -> None:
    client = _client()
    storage = _storage(client)
    with Stubber(client) as stubber:
        stubber.add_response(
            "head_object",
            {"ContentLength": 2048, "ETag": '"abc"'},
            {"Bucket": BUCKET, "Key": PHYSICAL_KEY},
        )
        stated = await storage.stat(LOGICAL_KEY)

    assert stated.key == LOGICAL_KEY
    assert stated.size_bytes == 2048
    assert stated.sha256 is None


@pytest.mark.asyncio
async def test_delete_missing_object_is_idempotent_success() -> None:
    client = _client()
    storage = _storage(client)
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "delete_object",
            service_error_code="NoSuchKey",
            http_status_code=404,
            expected_params={"Bucket": BUCKET, "Key": PHYSICAL_KEY},
        )
        await storage.delete(LOGICAL_KEY)


@pytest.mark.asyncio
async def test_rejects_keys_outside_private_prefix() -> None:
    client = _client()
    storage = _storage(client)
    with pytest.raises(InvalidReplayObjectKey):
        await storage.stat("../escape")
    with pytest.raises(InvalidReplayObjectKey):
        await storage.delete("/absolute")
    with pytest.raises(ValueError, match="private prefix"):
        S3ReplayStorage(client=client, bucket=BUCKET, prefix="")
    with pytest.raises(ValueError, match="bucket"):
        S3ReplayStorage(client=client, bucket="", prefix=PREFIX)

    target = await storage.create_upload_target(
        LOGICAL_KEY,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    parsed = urlparse(target.url)
    assert BUCKET in parsed.netloc or f"/{BUCKET}/" in parsed.path
    assert PHYSICAL_KEY in target.url
    assert storage.resolve_key(LOGICAL_KEY) == PHYSICAL_KEY


@pytest.mark.asyncio
async def test_stat_missing_object_raises_not_found() -> None:
    client = _client()
    storage = _storage(client)
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "head_object",
            service_error_code="404",
            http_status_code=404,
            expected_params={"Bucket": BUCKET, "Key": PHYSICAL_KEY},
        )
        with pytest.raises(ReplayObjectNotFound):
            await storage.stat(LOGICAL_KEY)


def test_factory_disabled_does_not_init_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("boto3.client must not be called when replay is disabled")

    monkeypatch.setattr("boto3.client", _boom)
    settings = Settings(_env_file=None, replay_enabled=False, replay_storage_backend="s3")
    with pytest.raises(ValueError, match="disabled"):
        build_replay_storage(settings)


def test_factory_local_requires_creatable_non_static_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_storage_backend="local",
        replay_local_root=tmp_path / "safe-replays",
    )
    storage = build_replay_storage(settings)
    assert isinstance(storage, LocalReplayStorage)
    assert (tmp_path / "safe-replays").is_dir()

    public_root = tmp_path / "frontend" / "public" / "replays"
    public_root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.replays.storage.factory._STATIC_ROOT_CANDIDATES",
        (tmp_path / "frontend" / "public",),
    )
    with pytest.raises(ValueError, match="static"):
        build_replay_storage(
            Settings(
                _env_file=None,
                replay_enabled=True,
                replay_token_secret="x" * 32,
                replay_storage_backend="local",
                replay_local_root=public_root,
            )
        )


def test_factory_s3_requires_endpoint_region_bucket_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("boto3.client must not be called with incomplete s3 config")

    monkeypatch.setattr("boto3.client", _boom)
    base = {
        "replay_enabled": True,
        "replay_token_secret": "x" * 32,
        "replay_storage_backend": "s3",
    }
    incomplete = [
        {},
        {"replay_s3_endpoint_url": "http://localhost:9000"},
        {
            "replay_s3_endpoint_url": "http://localhost:9000",
            "replay_s3_region": "us-east-1",
        },
        {
            "replay_s3_endpoint_url": "http://localhost:9000",
            "replay_s3_region": "us-east-1",
            "replay_s3_bucket": BUCKET,
        },
        {
            "replay_s3_endpoint_url": "http://localhost:9000",
            "replay_s3_region": "us-east-1",
            "replay_s3_bucket": BUCKET,
            "replay_s3_access_key_id": "ak",
        },
    ]
    for kwargs in incomplete:
        with pytest.raises(ValueError):
            build_replay_storage(Settings(_env_file=None, **base, **kwargs))


def test_factory_s3_builds_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}
    real_client = _client()

    def _fake_client(service: str, **kwargs: object) -> Any:
        assert service == "s3"
        created.update(kwargs)
        return real_client

    monkeypatch.setattr("app.services.replays.storage.factory.boto3.client", _fake_client)
    storage = build_replay_storage(
        Settings(
            _env_file=None,
            replay_enabled=True,
            replay_token_secret="x" * 32,
            replay_storage_backend="s3",
            replay_s3_endpoint_url="http://localhost:9000",
            replay_s3_region="us-east-1",
            replay_s3_bucket=BUCKET,
            replay_s3_access_key_id="ak",
            replay_s3_secret_access_key="sk",
            replay_s3_prefix=PREFIX,
        )
    )
    assert isinstance(storage, S3ReplayStorage)
    assert created["endpoint_url"] == "http://localhost:9000"
    assert created["region_name"] == "us-east-1"
    assert created["aws_access_key_id"] == "ak"
    assert created["aws_secret_access_key"] == "sk"


# ---------------------------------------------------------------------------
# Streaming / multipart / lifecycle tests use an in-memory fake client so we
# can freely exercise multi-part uploads, promotion, and prefix deletion
# without botocore's Stubber forcing us to predict internal temp-key names.
# ---------------------------------------------------------------------------


class _FakeStreamingBody:
    """Mimics botocore's StreamingBody: reads require an explicit, positive
    size and never return the whole payload for a bare ``read()`` call."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.read_sizes: list[int | None] = []
        self.closed = False

    def read(self, amt: int | None = None) -> bytes:
        self.read_sizes.append(amt)
        if amt is None:
            raise AssertionError("Body.read() must never be called without a positive size")
        if amt <= 0:
            raise AssertionError("Body.read() must be called with a positive chunk size")
        chunk = self._data[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _not_found(operation: str, code: str = "NoSuchKey") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "missing"}}, operation)


class FakeS3Client:
    """In-memory double for the subset of the boto3 S3 client that
    ``S3ReplayStorage`` calls. Bodies enforce sized reads and multipart
    uploads must be explicitly completed or aborted, mirroring real S3."""

    def __init__(self, *, list_page_size: int = 1000) -> None:
        self.objects: dict[str, bytes] = {}
        self.multipart_uploads: dict[str, dict[int, bytes]] = {}
        self.bodies: list[_FakeStreamingBody] = []
        self.calls: list[str] = []
        self._upload_seq = 0
        self.list_page_size = list_page_size

    def create_multipart_upload(self, *, Bucket: str, Key: str) -> dict[str, str]:
        self.calls.append("create_multipart_upload")
        self._upload_seq += 1
        upload_id = f"upload-{self._upload_seq}"
        self.multipart_uploads[upload_id] = {}
        return {"UploadId": upload_id}

    def upload_part(
        self, *, Bucket: str, Key: str, UploadId: str, PartNumber: int, Body: bytes
    ) -> dict[str, str]:
        self.calls.append("upload_part")
        if UploadId not in self.multipart_uploads:
            raise _not_found("UploadPart", "NoSuchUpload")
        if not isinstance(Body, (bytes, bytearray)):
            raise TypeError("upload_part Body must be bytes")
        self.multipart_uploads[UploadId][PartNumber] = bytes(Body)
        return {"ETag": f'"etag-{PartNumber}"'}

    def complete_multipart_upload(
        self, *, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict[str, Any]
    ) -> dict[str, object]:
        self.calls.append("complete_multipart_upload")
        parts_state = self.multipart_uploads.pop(UploadId, None)
        if parts_state is None:
            raise _not_found("CompleteMultipartUpload", "NoSuchUpload")
        assembled = bytearray()
        for part in MultipartUpload["Parts"]:
            assembled.extend(parts_state[part["PartNumber"]])
        self.objects[Key] = bytes(assembled)
        return {"ETag": '"complete"'}

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> dict[str, object]:
        self.calls.append("abort_multipart_upload")
        self.multipart_uploads.pop(UploadId, None)
        return {}

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, **_ignored: object
    ) -> dict[str, object]:
        self.calls.append("put_object")
        self.objects[Key] = bytes(Body)
        return {"ETag": '"put"'}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.calls.append("head_object")
        if Key not in self.objects:
            raise _not_found("HeadObject", "404")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, *, Bucket: str, Key: str, Range: str | None = None) -> dict[str, object]:
        self.calls.append("get_object")
        if Key not in self.objects:
            raise _not_found("GetObject")
        payload = self.objects[Key]
        if Range is not None:
            start, end = _parse_range(Range, len(payload))
            payload = payload[start : end + 1]
        body = _FakeStreamingBody(payload)
        self.bodies.append(body)
        return {"Body": body, "ContentLength": len(payload)}

    def copy_object(
        self, *, Bucket: str, Key: str, CopySource: dict[str, str]
    ) -> dict[str, object]:
        self.calls.append("copy_object")
        source_key = CopySource["Key"]
        if source_key not in self.objects:
            raise _not_found("CopyObject")
        self.objects[Key] = self.objects[source_key]
        return {"CopyObjectResult": {"ETag": '"copy"'}}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.calls.append("delete_object")
        self.objects.pop(Key, None)
        return {}

    def list_objects_v2(
        self, *, Bucket: str, Prefix: str = "", ContinuationToken: str | None = None
    ) -> dict[str, object]:
        self.calls.append("list_objects_v2")
        # Continue strictly after the last key seen, like real S3, so that a
        # caller deleting objects between pages never skips or repeats keys.
        matching = sorted(
            key
            for key in self.objects
            if key.startswith(Prefix) and (ContinuationToken is None or key > ContinuationToken)
        )
        page = matching[: self.list_page_size]
        truncated = len(matching) > len(page)
        response: dict[str, object] = {
            "Contents": [{"Key": key} for key in page],
            "IsTruncated": truncated,
        }
        if truncated:
            response["NextContinuationToken"] = page[-1]
        return response

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, object]:
        self.calls.append("delete_objects")
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)
        return {"Deleted": [{"Key": item["Key"]} for item in Delete["Objects"]]}


def _parse_range(range_header: str, size: int) -> tuple[int, int]:
    prefix = "bytes="
    assert range_header.startswith(prefix)
    start_str, end_str = range_header[len(prefix) :].split("-")
    start = int(start_str)
    end = int(end_str) if end_str else size - 1
    return start, end


def _fake_storage(client: FakeS3Client | None = None) -> tuple[FakeS3Client, S3ReplayStorage]:
    fake = client or FakeS3Client()
    storage = S3ReplayStorage(client=fake, bucket=BUCKET, prefix=PREFIX)
    return fake, storage


@pytest.mark.asyncio
async def test_write_stream_uses_multipart_upload_and_never_buffers_whole_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3_module, "_UPLOAD_PART_SIZE", 4)
    fake, storage = _fake_storage()

    result = await storage.write_stream(
        LOGICAL_KEY, aiter([b"ab", b"cd", b"ef", b"gh", b"i"]), max_bytes=100
    )

    assert result.size_bytes == 9
    assert result.sha256 == hashlib.sha256(b"abcdefghi").hexdigest()
    assert fake.objects[PHYSICAL_KEY] == b"abcdefghi"
    assert fake.calls.count("upload_part") >= 2
    assert fake.calls.count("create_multipart_upload") == 1
    assert fake.calls.count("complete_multipart_upload") == 1
    # No temp object (or the internal temp object) should remain after promotion.
    assert list(fake.objects) == [PHYSICAL_KEY]


@pytest.mark.asyncio
async def test_write_stream_rejects_oversized_payload_and_removes_temp() -> None:
    fake, storage = _fake_storage()

    with pytest.raises(ReplayObjectTooLarge):
        await storage.write_stream(LOGICAL_KEY, aiter([b"123", b"456"]), max_bytes=5)

    assert fake.objects == {}
    assert fake.multipart_uploads == {}
    assert "complete_multipart_upload" not in fake.calls
    assert "abort_multipart_upload" in fake.calls


@pytest.mark.asyncio
async def test_upload_from_path_streams_in_sized_chunks_and_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(s3_module, "_UPLOAD_PART_SIZE", 4)
    fake, storage = _fake_storage()
    payload = b"fixture-bytes-of-some-length"
    source = tmp_path / "source.bin"
    source.write_bytes(payload)

    uploaded = await storage.upload_from_path(LOGICAL_KEY, source)

    assert uploaded.key == LOGICAL_KEY
    assert uploaded.size_bytes == len(payload)
    assert fake.objects[PHYSICAL_KEY] == payload
    assert fake.calls.count("upload_part") >= 2
    assert list(fake.objects) == [PHYSICAL_KEY]


@pytest.mark.asyncio
async def test_download_to_path_streams_sized_reads_into_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(s3_module, "_RANGE_CHUNK_SIZE", 4)
    fake, storage = _fake_storage()
    payload = b"fixture-bytes-of-some-length"
    fake.objects[PHYSICAL_KEY] = payload
    destination = tmp_path / "downloaded.bin"

    downloaded = await storage.download_to_path(LOGICAL_KEY, destination)

    assert destination.read_bytes() == payload
    assert downloaded.size_bytes == len(payload)
    body = fake.bodies[-1]
    assert body.closed is True
    assert all(size == 4 for size in body.read_sizes[:-1])
    assert None not in body.read_sizes


@pytest.mark.asyncio
async def test_iter_range_streams_sized_reads_within_the_requested_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3_module, "_RANGE_CHUNK_SIZE", 1024 * 1024)
    fake, storage = _fake_storage()
    payload = b"abcdefghij"
    fake.objects[PHYSICAL_KEY] = payload

    chunks = [chunk async for chunk in storage.iter_range(LOGICAL_KEY, 2, 5)]

    assert b"".join(chunks) == b"cdef"
    body = fake.bodies[-1]
    assert None not in body.read_sizes
    assert all(size > 0 for size in body.read_sizes)


@pytest.mark.asyncio
async def test_promote_copies_temp_to_final_and_deletes_temp() -> None:
    fake, storage = _fake_storage()
    temp_key = "tmp/source/abc/input"
    temp_physical = f"{PREFIX}/{temp_key}"
    fake.objects[temp_physical] = b"promoted-bytes"

    result = await storage.promote(temp_key, LOGICAL_KEY)

    assert result.key == LOGICAL_KEY
    assert result.size_bytes == len(b"promoted-bytes")
    assert fake.objects[PHYSICAL_KEY] == b"promoted-bytes"
    assert temp_physical not in fake.objects
    assert fake.calls.index("copy_object") < fake.calls.index("delete_object")


@pytest.mark.asyncio
async def test_promote_missing_temp_raises_not_found_and_touches_nothing() -> None:
    fake, storage = _fake_storage()

    with pytest.raises(ReplayObjectNotFound):
        await storage.promote("tmp/source/abc/input", LOGICAL_KEY)

    assert fake.objects == {}
    assert "copy_object" not in fake.calls
    assert "delete_object" not in fake.calls


@pytest.mark.asyncio
async def test_promote_preserves_temp_when_copy_fails() -> None:
    fake, storage = _fake_storage()
    temp_key = "tmp/source/abc/input"
    temp_physical = f"{PREFIX}/{temp_key}"
    fake.objects[temp_physical] = b"promoted-bytes"

    def _boom(*, Bucket: str, Key: str, CopySource: dict[str, str]) -> dict[str, object]:
        raise RuntimeError("network blip")

    fake.copy_object = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await storage.promote(temp_key, LOGICAL_KEY)

    # Atomicity: a failed copy must not delete the only copy of the data.
    assert fake.objects[temp_physical] == b"promoted-bytes"
    assert PHYSICAL_KEY not in fake.objects


@pytest.mark.asyncio
async def test_write_stream_deletes_temp_when_promotion_fails() -> None:
    fake, storage = _fake_storage()

    def _boom(*, Bucket: str, Key: str, CopySource: dict[str, str]) -> dict[str, object]:
        raise RuntimeError("network blip")

    fake.copy_object = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await storage.write_stream(LOGICAL_KEY, aiter([b"hello"]), max_bytes=100)

    assert fake.objects == {}


@pytest.mark.asyncio
async def test_delete_prefix_removes_only_objects_under_the_prefix() -> None:
    fake, storage = _fake_storage(FakeS3Client(list_page_size=2))
    fake.objects[f"{PREFIX}/source/abc/input"] = b"a"
    fake.objects[f"{PREFIX}/normalized/abc/video"] = b"b"
    fake.objects[f"{PREFIX}/frames/abc/anchor-0"] = b"c"
    fake.objects[f"{PREFIX}/frames/abc/verify-1"] = b"d"
    fake.objects[f"{PREFIX}/frames/abc/verify-2"] = b"f"
    fake.objects[f"{PREFIX}/source/other/input"] = b"e"

    await storage.delete_prefix("frames/abc")

    assert set(fake.objects) == {
        f"{PREFIX}/source/abc/input",
        f"{PREFIX}/normalized/abc/video",
        f"{PREFIX}/source/other/input",
    }
    assert fake.calls.count("list_objects_v2") >= 2  # exercised pagination


@pytest.mark.asyncio
async def test_delete_prefix_on_empty_prefix_is_a_no_op() -> None:
    fake, storage = _fake_storage()
    fake.objects[f"{PREFIX}/source/other/input"] = b"e"

    await storage.delete_prefix("source/abc")

    assert set(fake.objects) == {f"{PREFIX}/source/other/input"}


@pytest.mark.asyncio
async def test_delete_prefix_rejects_keys_outside_private_prefix() -> None:
    _fake, storage = _fake_storage()
    with pytest.raises(InvalidReplayObjectKey):
        await storage.delete_prefix("../escape")
