from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.config import Config
from botocore.stub import Stubber

from app.core.config import Settings
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
async def test_download_and_upload_round_trip(tmp_path: Path) -> None:
    client = _client()
    storage = _storage(client)
    payload = b"fixture-bytes"
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    destination = tmp_path / "downloaded.bin"

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": '"upload"'},
            {"Bucket": BUCKET, "Key": PHYSICAL_KEY, "Body": payload},
        )
        uploaded = await storage.upload_from_path(LOGICAL_KEY, source)
        assert uploaded.key == LOGICAL_KEY
        assert uploaded.size_bytes == len(payload)
        assert uploaded.sha256 is not None

        stubber.add_response(
            "get_object",
            {"Body": _Body(payload), "ContentLength": len(payload)},
            {"Bucket": BUCKET, "Key": PHYSICAL_KEY},
        )
        downloaded = await storage.download_to_path(LOGICAL_KEY, destination)

    assert destination.read_bytes() == payload
    assert downloaded.key == LOGICAL_KEY
    assert downloaded.size_bytes == len(payload)


@pytest.mark.asyncio
async def test_write_stream_and_iter_range() -> None:
    client = _client()
    storage = _storage(client)
    payload = b"abcdefghij"

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": '"stream"'},
            {"Bucket": BUCKET, "Key": PHYSICAL_KEY, "Body": payload},
        )
        written = await storage.write_stream(LOGICAL_KEY, aiter([b"abcde", b"fghij"]), max_bytes=10)
        assert written.key == LOGICAL_KEY
        assert written.size_bytes == 10

        stubber.add_response(
            "head_object",
            {"ContentLength": 10},
            {"Bucket": BUCKET, "Key": PHYSICAL_KEY},
        )
        stubber.add_response(
            "get_object",
            {"Body": _Body(b"cdef"), "ContentLength": 4},
            {"Bucket": BUCKET, "Key": PHYSICAL_KEY, "Range": "bytes=2-5"},
        )
        chunks = [chunk async for chunk in storage.iter_range(LOGICAL_KEY, 2, 5)]

    assert b"".join(chunks) == b"cdef"


@pytest.mark.asyncio
async def test_write_stream_rejects_oversized_payload() -> None:
    client = _client()
    storage = _storage(client)
    with pytest.raises(ReplayObjectTooLarge):
        await storage.write_stream(LOGICAL_KEY, aiter([b"123", b"456"]), max_bytes=5)


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


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amt: int | None = None) -> bytes:
        if amt is None:
            data, self._payload = self._payload, b""
            return data
        data, self._payload = self._payload[:amt], self._payload[amt:]
        return data

    def close(self) -> None:
        return None

    def __iter__(self) -> Iterable[bytes]:
        yield self.read()
