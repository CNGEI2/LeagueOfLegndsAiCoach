from __future__ import annotations

from pathlib import Path

import boto3

from app.core.config import ROOT_ENV_FILE, Settings
from app.services.replays.storage.base import ReplayStorage
from app.services.replays.storage.local import LocalReplayStorage
from app.services.replays.storage.s3 import S3ReplayStorage

_REPO_ROOT = ROOT_ENV_FILE.parent
_STATIC_ROOT_CANDIDATES: tuple[Path, ...] = (
    _REPO_ROOT / "frontend" / "public",
    _REPO_ROOT / "frontend" / "out",
    _REPO_ROOT / "backend" / "static",
)


def build_replay_storage(settings: Settings) -> ReplayStorage:
    if not settings.replay_enabled:
        raise ValueError("replay storage cannot be initialized while replay is disabled")

    if settings.replay_storage_backend == "local":
        root = _validate_local_root(settings.replay_local_root)
        return LocalReplayStorage(root)

    if settings.replay_storage_backend == "s3":
        return _build_s3_storage(settings)

    raise ValueError(f"unsupported replay storage backend: {settings.replay_storage_backend!r}")


def _validate_local_root(root: Path) -> Path:
    try:
        root.mkdir(parents=True, exist_ok=True)
        resolved = root.resolve()
    except OSError as error:
        raise ValueError(f"replay local root is not creatable: {root}") from error

    for candidate in _STATIC_ROOT_CANDIDATES:
        try:
            static_root = candidate.resolve()
        except OSError:
            continue
        if not static_root.exists():
            continue
        if resolved == static_root or resolved.is_relative_to(static_root):
            raise ValueError(
                "replay local root must not be located under a public static directory"
            )
    return resolved


def _build_s3_storage(settings: Settings) -> S3ReplayStorage:
    endpoint = settings.replay_s3_endpoint_url.strip()
    region = settings.replay_s3_region.strip()
    bucket = settings.replay_s3_bucket.strip()
    access_key = settings.replay_s3_access_key_id.get_secret_value().strip()
    secret_key = settings.replay_s3_secret_access_key.get_secret_value().strip()
    prefix = settings.replay_s3_prefix.strip()

    missing: list[str] = []
    if not endpoint:
        missing.append("REPLAY_S3_ENDPOINT_URL")
    if not region:
        missing.append("REPLAY_S3_REGION")
    if not bucket:
        missing.append("REPLAY_S3_BUCKET")
    if not access_key:
        missing.append("REPLAY_S3_ACCESS_KEY_ID")
    if not secret_key:
        missing.append("REPLAY_S3_SECRET_ACCESS_KEY")
    if not prefix:
        missing.append("REPLAY_S3_PREFIX")
    if missing:
        raise ValueError(
            "replay S3 storage requires non-empty configuration for: " + ", ".join(missing)
        )

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    return S3ReplayStorage(client=client, bucket=bucket, prefix=prefix)
