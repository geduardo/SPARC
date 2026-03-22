from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_report(path: Path, name_suffix: str, steps_per_second: float) -> None:
    report = {
        "metadata": {
            "steps": 50000,
            "warmup": 2000,
            "repeats": 1,
            "initial_gap_um": 12.0,
        },
        "action": {
            "servo": 0.25,
            "target_voltage": 90.0,
            "current_mode": "I5",
        },
        "scenarios": [
            {
                "segment_len_mm": 0.2,
                "n_segments": 400,
                "benchmark": {
                    "steps_requested": 50000,
                    "median_wall_seconds": 50000 / steps_per_second,
                    "median_steps_per_second": steps_per_second,
                    "mean_steps_per_second": steps_per_second,
                    "samples": [
                        {
                            "termination_reason": "completed",
                            "crater_count": 775,
                            "wire_temperature_mean": 336.53,
                            "wire_max_damage": 0.000166,
                        }
                    ],
                },
                "module_hotspots": [
                    {
                        "name": "wire",
                        "wall_share_pct": 50.8,
                    },
                    {
                        "name": "ignition",
                        "wall_share_pct": 22.6,
                    },
                ],
                "module_subhotspots": {
                    "wire": [
                        {
                            "name": "thermal_core",
                            "wall_share_pct": 31.2,
                            "avg_call_us": 8.5,
                            "calls": 50000,
                            "total_seconds": 0.425,
                        }
                    ]
                },
                "cprofile_hotspots": [
                    {
                        "function": "update",
                        "file": f"src/wedm/modules/wire_{name_suffix}.py",
                        "line": 100,
                        "total_seconds": 0.5,
                        "cumulative_seconds": 0.8,
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(report), encoding="utf-8")


def test_build_perf_dashboard_generates_html(tmp_path: Path) -> None:
    make_report(tmp_path / "baseline_a.json", "a", 30000.0)
    make_report(tmp_path / "baseline_b.json", "b", 40000.0)
    (tmp_path / "ignore_me.json").write_text("{\"hello\": \"world\"}", encoding="utf-8")

    output_path = tmp_path / "perf_dashboard.html"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_perf_dashboard.py"),
            "--input-glob",
            str(tmp_path / "*.json"),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    html = output_path.read_text(encoding="utf-8")
    assert "SPARC Realtime Optimization Dashboard" in html
    assert "baseline_a" in html
    assert "baseline_b" in html
    assert "0.20 mm / 400 seg" in html
    assert "40,000.00 steps/s" in html
    assert "wire dominates latest profile" in html
    assert "Performance Plot" in html
    assert "Before / After" in html
    assert "Module Drilldown" in html
    assert "module_subhotspots" in html
    assert "thermal_core" in html
    assert "Y min" in html
    assert "Vs baseline" in html
    assert "2 profiling report(s)" in result.stdout
