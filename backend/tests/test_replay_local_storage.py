from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.replays.storage.base import (
    InvalidReplayObjectKey,
    ReplayObjectNotFound,
    ReplayObjectTooLarge,
)
from app.services.replays.storage.local import LocalReplayStorage

MIB = 1024 * 1024


async def aiter(chunks: Iterable[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_local_storage_never_uses_user_filename(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    result = await storage.write_stream(
        key="source/abc/input", chunks=aiter([b"video"]), max_bytes=10
    )
    assert result.size_bytes == 5
    assert ".." not in result.key
    assert not list(tmp_path.rglob("owned recording.mp4"))  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_oversized_stream_removes_partial_file(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    with pytest.raises(ReplayObjectTooLarge):
        await storage.write_stream("source/abc/input", aiter([b"123", b"456"]), 5)
    assert not list(tmp_path.rglob("*.part"))  # noqa: ASYNC240


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/absolute",
        "../escape",
        "foo/../bar",
        "foo/./bar",
        "foo//bar",
        "foo/.",
        "foo/..",
        ".hidden",
        "Upper/Case",
        "has space",
        "a" * 257,
    ],
)
def test_object_key_validation_rejects_invalid_keys(tmp_path: Path, key: str) -> None:
    storage = LocalReplayStorage(tmp_path)
    with pytest.raises(InvalidReplayObjectKey):
        storage.resolve_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "a",
        "source/abc/input",
        "0/_-z",
        "a" + ("b" * 255),
    ],
)
def test_object_key_validation_accepts_valid_keys(tmp_path: Path, key: str) -> None:
    storage = LocalReplayStorage(tmp_path)
    resolved = storage.resolve_key(key)
    assert resolved.is_relative_to(tmp_path.resolve())
    assert resolved == (tmp_path.resolve() / key)


@pytest.mark.asyncio
async def test_write_stream_atomically_renames_part_file(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    result = await storage.write_stream("source/abc/input", aiter([b"hello"]), max_bytes=10)
    final = tmp_path / "source" / "abc" / "input"
    assert final.is_file()  # noqa: ASYNC240
    assert final.read_bytes() == b"hello"  # noqa: ASYNC240
    assert result.key == "source/abc/input"
    assert result.sha256 is not None
    assert not list(tmp_path.rglob("*.part"))  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_iter_range_yields_one_mib_chunks_and_checks_bounds(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    payload = b"x" * (MIB + 100)
    await storage.write_stream("source/abc/input", aiter([payload]), max_bytes=len(payload))

    chunks = [chunk async for chunk in storage.iter_range("source/abc/input", 0, MIB + 99)]
    assert [len(chunk) for chunk in chunks] == [MIB, 100]
    assert b"".join(chunks) == payload

    with pytest.raises(ValueError):
        async for _ in storage.iter_range("source/abc/input", -1, 0):
            pass
    with pytest.raises(ValueError):
        async for _ in storage.iter_range("source/abc/input", 10, 9):
            pass
    with pytest.raises(ValueError):
        async for _ in storage.iter_range("source/abc/input", 0, len(payload)):
            pass


@pytest.mark.asyncio
async def test_delete_missing_is_success_and_only_under_root(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    await storage.delete("source/missing/object")

    await storage.write_stream("source/abc/input", aiter([b"data"]), max_bytes=10)
    await storage.delete("source/abc/input")
    assert not (tmp_path / "source" / "abc" / "input").exists()  # noqa: ASYNC240

    outside = tmp_path.parent / "outside-secret"
    outside.write_bytes(b"secret")  # noqa: ASYNC240
    with pytest.raises(InvalidReplayObjectKey):
        await storage.delete("../outside-secret")
    assert outside.read_bytes() == b"secret"  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_stat_download_upload_and_create_upload_target(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    uploaded = await storage.upload_from_path(
        "source/abc/input",
        source=_write_temp(tmp_path / "fixture.bin", b"fixture-bytes"),
    )
    assert uploaded.size_bytes == len(b"fixture-bytes")

    stated = await storage.stat("source/abc/input")
    assert stated.key == "source/abc/input"
    assert stated.size_bytes == len(b"fixture-bytes")

    destination = tmp_path / "downloaded.bin"
    downloaded = await storage.download_to_path("source/abc/input", destination)
    assert destination.read_bytes() == b"fixture-bytes"  # noqa: ASYNC240
    assert downloaded.size_bytes == len(b"fixture-bytes")

    expires_at = datetime.now(UTC) + timedelta(minutes=30)
    target = await storage.create_upload_target(
        "source/abc/input",
        expires_at=expires_at,
        upload_url="/api/v1/replays/abc/content",
    )
    assert target.method == "PUT"
    assert target.url == "/api/v1/replays/abc/content"
    assert target.headers == {}
    assert target.expires_at == expires_at

    with pytest.raises(ReplayObjectNotFound):
        await storage.stat("source/does-not-exist")


def _write_temp(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path
