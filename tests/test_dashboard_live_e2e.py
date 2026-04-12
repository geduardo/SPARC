from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "live_dashboard_e2e.mjs"


def test_dashboard_live_path_end_to_end() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the dashboard live integration harness")

    completed = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        details = [
            f"node harness exited with code {completed.returncode}",
        ]
        if completed.stdout:
            details.append(f"stdout:\n{completed.stdout}")
        if completed.stderr:
            details.append(f"stderr:\n{completed.stderr}")
        raise AssertionError("\n\n".join(details))

