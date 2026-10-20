"""Check restored raw files: decrypt each, decompress, and compare the SHA-256 with the database
row (raw files are stored zstd-compressed; the checksum is of the original bytes).
Usage: python3 verify_raw.py <outbox> <identity-file>   (PG* env points at the restored DB)"""

import hashlib
import subprocess
import sys
from pathlib import Path


def main() -> int:
    outbox, identity = Path(sys.argv[1]), sys.argv[2]
    rows = subprocess.run(
        ["psql", "-At", "-F", "|", "-c", "SELECT storage_path, sha256 FROM history_rawfile"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    bad = 0
    for row in rows:
        path, expected = row.split("|")
        encrypted = outbox / "raw" / f"{path}.age"
        decrypted = subprocess.run(
            f"age -d -i {identity} {encrypted} | zstd -q -d", shell=True,  # noqa: S602 - fixed args
            check=True, capture_output=True,
        ).stdout
        actual = hashlib.sha256(decrypted).hexdigest()
        if actual != expected:
            print(f"MISMATCH {path}: {actual} != {expected}")
            bad += 1
    print(f"raw files verified: {len(rows) - bad}/{len(rows)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
