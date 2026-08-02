from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import pytest

from app.services.replays.storage.base import ReplayObjectNotFound
from app.services.replays.storage.s3 import S3ReplayStorage

pytestmark = pytest.mark.replay_s3

_ENDPOINT = os.getenv("REPLAY_S3_TEST_ENDPOINT", "")
if not _ENDPOINT:
    pytest.skip(
        "REPLAY_S3_TEST_ENDPOINT is not set; skipping MinIO/S3 streaming integration tests",
        allow_module_level=True,
    )

_BUCKET = os.getenv("REPLAY_S3_TEST_BUCKET", "replay-integration-test")
_REGION = os.getenv("REPLAY_S3_TEST_REGION", "us-east-1")
_ACCESS_KEY = os.getenv("REPLAY_S3_TEST_ACCESS_KEY_ID", "minioadmin")
_SECRET_KEY = os.getenv("REPLAY_S3_TEST_SECRET_ACCESS_KEY", "minioadmin")
_PREFIX = "replay-s3-streaming-it"
_CHUNK_SIZE = 1024 * 1024


async def _aiter(chunks: Iterable[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def _chunked(payload: bytes, size: int = _CHUNK_SIZE) -> list[bytes]:
    return [payload[i : i + size] for i in range(0, len(payload), size)]


@pytest.fixture(scope="module")
def s3_client() -> Any:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        region_name=_REGION,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    with contextlib.suppress(Exception):  # pragma: no cover - bucket already exists
        client.create_bucket(Bucket=_BUCKET)
    return client


@pytest.fixture
def storage(s3_client: Any) -> S3ReplayStorage:
    return S3ReplayStorage(client=s3_client, bucket=_BUCKET, prefix=_PREFIX)


@pytest.mark.asyncio
async def test_real_minio_streams_write_promote_download_and_delete(
    storage: S3ReplayStorage, tmp_path: Path
) -> None:
    unique = os.urandom(4).hex()
    final_key = f"source/{unique}/input"
    temp_key = f"tmp/{final_key}"
    # Larger than the multipart part size so more than one upload_part call happens.
    payload = os.urandom(9 * 1024 * 1024)

    written = await storage.write_stream(
        temp_key, _aiter(_chunked(payload)), max_bytes=len(payload) + 1
    )
    assert written.size_bytes == len(payload)

    promoted = await storage.promote(temp_key, final_key)
    assert promoted.size_bytes == len(payload)
    with pytest.raises(ReplayObjectNotFound):
        await storage.stat(temp_key)

    destination = tmp_path / "downloaded.bin"
    downloaded = await storage.download_to_path(final_key, destination)
    assert downloaded.size_bytes == len(payload)
    assert destination.read_bytes() == payload

    ranged = [chunk async for chunk in storage.iter_range(final_key, 10, 20)]
    assert b"".join(ranged) == payload[10:21]

    await storage.delete_prefix(f"source/{unique}")
    with pytest.raises(ReplayObjectNotFound):
        await storage.stat(final_key)


@pytest.mark.asyncio
async def test_real_minio_upload_from_path_round_trip(
    storage: S3ReplayStorage, tmp_path: Path
) -> None:
    unique = os.urandom(4).hex()
    key = f"normalized/{unique}/video"
    source = tmp_path / "source.bin"
    source.write_bytes(os.urandom(6 * 1024 * 1024))

    uploaded = await storage.upload_from_path(key, source)
    assert uploaded.size_bytes == source.stat().st_size

    destination = tmp_path / "downloaded.bin"
    await storage.download_to_path(key, destination)
    assert destination.read_bytes() == source.read_bytes()

    await storage.delete_prefix(f"normalized/{unique}")
    with pytest.raises(ReplayObjectNotFound):
        await storage.stat(key)
