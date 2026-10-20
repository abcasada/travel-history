"""The raw import archive (PLAN.md §8.2): every original upload is kept byte-for-byte, zstd-
compressed, read-only, checksummed, on the HDD. The app never modifies or deletes these files
(CLAUDE.md rule 12)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

import zstandard
from django.conf import settings

from .models import RawFile

READ_BLOCK = 1 << 20
ZSTD_LEVEL = 10


class RawStoreError(Exception):
    pass


def raw_root() -> Path:
    return Path(settings.BULK_DIR) / "raw"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _decompressed_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle, zstandard.ZstdDecompressor().stream_reader(handle) as reader:
        for block in iter(lambda: reader.read(READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def find_existing(owner_id: int, sha256: str) -> RawFile | None:
    return RawFile.objects.filter(owner_id=owner_id, sha256=sha256).first()


def store_file(
    owner_id: int,
    source: Path,
    *,
    original_name: str,
    content_type: str = "",
    uploaded_via: str = RawFile.UploadedVia.WEB,
    sha256: str | None = None,
) -> RawFile:
    """Compress `source` into the archive, verify it, make it read-only and record it. The caller
    must run inside the owner's RLS context and should check `find_existing` first."""
    digest = sha256 or sha256_file(source)
    relative = f"{owner_id}/{digest[:2]}/{digest}.zst"
    target = raw_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)

    if not (target.exists() and _decompressed_sha256(target) == digest):
        # A leftover from an interrupted run is replaced only if it fails verification.
        if target.exists():
            target.chmod(0o640)
            target.unlink()
        temporary = target.with_suffix(".zst.tmp")
        compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=2, write_checksum=True)
        with source.open("rb") as src, temporary.open("wb") as dst:
            compressor.copy_stream(src, dst, read_size=READ_BLOCK, write_size=READ_BLOCK)
            dst.flush()
            os.fsync(dst.fileno())
        temporary.rename(target)
        if _decompressed_sha256(target) != digest:
            target.unlink()
            raise RawStoreError("stored file failed verification")
    target.chmod(0o440)

    return RawFile.objects.create(
        owner_id=owner_id,
        original_name=original_name[:255],
        content_type=content_type[:100],
        size_bytes=source.stat().st_size,
        sha256=digest,
        storage_path=relative,
        compressed_size=target.stat().st_size,
        uploaded_via=uploaded_via,
    )


def open_original(raw: RawFile) -> BinaryIO:
    """A streaming reader of the original bytes (decompressed on the fly)."""
    handle = (raw_root() / raw.storage_path).open("rb")
    return zstandard.ZstdDecompressor().stream_reader(handle, closefd=True)
