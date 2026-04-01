from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def _prepend_local_src() -> None:
    """Prefer the package under this checkout's src tree."""
    src_str = str(SRC_ROOT)
    if sys.path:
        try:
            if Path(sys.path[0] or ".").resolve() == SRC_ROOT:
                return
        except OSError:
            pass
    sys.path.insert(0, src_str)


_prepend_local_src()
