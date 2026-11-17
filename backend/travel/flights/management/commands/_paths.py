"""Paths given as `data/private/...` (relative to the repository, as in the docs) point at the
`./data` folder that `./dev` mounts at /data in the tools container."""

from pathlib import Path

from django.core.management.base import CommandError

DATA_MOUNT = Path("/data")


def repo_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() and path.parts[:1] == ("data",) and not path.exists():
        path = DATA_MOUNT.joinpath(*path.parts[1:])
    if not path.is_file():
        raise CommandError(f"no such file: {value}")
    return path
