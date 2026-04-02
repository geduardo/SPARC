#!/usr/bin/env python3
"""Canonical CLI entry point for running Wire EDM simulations."""

from __future__ import annotations

import pathlib
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.simulation_runner import main


if __name__ == "__main__":
    main()
