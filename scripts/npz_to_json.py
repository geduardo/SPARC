#!/usr/bin/env python3
"""
Convert NPZ simulation data to JSON format for the visualization dashboard.

Usage:
    python scripts/npz_to_json.py simulation_data.npz -o visualization/data/simulation_data.json
"""

import argparse
import json
import numpy as np
from pathlib import Path


def npz_to_json(npz_path: str, output_path: str = None):
    """Convert NPZ file to JSON format compatible with the dashboard."""

    npz_path = Path(npz_path)
    if output_path is None:
        output_path = npz_path.with_suffix('.json')
    else:
        output_path = Path(output_path)

    print(f"Loading: {npz_path}")
    data = np.load(npz_path, allow_pickle=True)

    json_data = {}
    for key in data.files:
        arr = data[key]
        print(f"  Converting: {key} (shape: {arr.shape}, dtype: {arr.dtype})")

        if arr.dtype == np.object_:
            # Handle object arrays (e.g., arrays of arrays)
            json_data[key] = [
                x.tolist() if hasattr(x, 'tolist') else x
                for x in arr
            ]
        else:
            json_data[key] = arr.tolist()

    print(f"Saving: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(json_data, f)

    # Report file sizes
    npz_size = npz_path.stat().st_size / 1024 / 1024
    json_size = output_path.stat().st_size / 1024 / 1024
    print(f"\nDone! NPZ: {npz_size:.1f} MB -> JSON: {json_size:.1f} MB")


def main():
    parser = argparse.ArgumentParser(
        description="Convert NPZ simulation data to JSON for visualization dashboard"
    )
    parser.add_argument("input", help="Input NPZ file path")
    parser.add_argument(
        "-o", "--output",
        help="Output JSON file path (default: same name with .json extension)"
    )

    args = parser.parse_args()
    npz_to_json(args.input, args.output)


if __name__ == "__main__":
    main()
