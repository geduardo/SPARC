from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def _prepend_local_src() -> None:
    """Force pytest to import the package under this checkout's src tree."""
    src_str = str(SRC_ROOT)

    for index, entry in enumerate(sys.path):
        try:
            if Path(entry or ".").resolve() == SRC_ROOT:
                if index != 0:
                    sys.path.pop(index)
                    sys.path.insert(0, src_str)
                return
        except OSError:
            continue

    sys.path.insert(0, src_str)


_prepend_local_src()
