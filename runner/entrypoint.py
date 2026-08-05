#!/usr/local/bin/python
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

SOURCE = Path("/input")
WORKSPACE = Path("/workspace")


def copy_workspace(source: Path, destination: Path) -> None:
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        relative = root_path.relative_to(source)
        target_root = destination / relative
        target_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in directories:
            candidate = root_path / name
            if candidate.is_symlink() or not stat.S_ISDIR(candidate.lstat().st_mode):
                raise RuntimeError("workspace contains an unsafe directory")
        for name in files:
            candidate = root_path / name
            metadata = candidate.lstat()
            if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("workspace contains an unsafe file")
            target = target_root / name
            with candidate.open("rb") as source_file, target.open("xb") as target_file:
                shutil.copyfileobj(source_file, target_file, length=128 * 1024)
            target.chmod(0o700 if metadata.st_mode & 0o111 else 0o600)


def main() -> int:
    if len(sys.argv) < 2:
        print("runner requires a trusted recipe argv", file=sys.stderr)
        return 125
    try:
        copy_workspace(SOURCE, WORKSPACE)
        os.chdir(WORKSPACE)
        os.execvp(sys.argv[1], sys.argv[1:])
    except (OSError, RuntimeError) as error:
        print(f"runner setup failed: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
