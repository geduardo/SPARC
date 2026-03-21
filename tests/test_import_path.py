from __future__ import annotations

from pathlib import Path

import wedm


def test_pytest_imports_local_checkout_package():
    """Pytest should resolve wedm from this checkout, not another install."""
    repo_root = Path(__file__).resolve().parents[1]
    expected_package_dir = repo_root / "src" / "wedm"
    actual_package_dir = Path(wedm.__file__).resolve().parent

    assert actual_package_dir == expected_package_dir
