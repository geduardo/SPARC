#!/usr/bin/env python
"""Repeatable benchmark and hotspot profiler for the local simulation code.

This script forces imports from the repository's local ``src`` tree so the
results are not skewed by an unrelated editable install elsewhere on the
machine. It targets a representative active-cutting workload and emits stable
throughput numbers plus hotspot snapshots for optimization work.
"""

from __future__ import annotations

import argparse
import cProfile
import contextlib
import ctypes
from collections import defaultdict
from dataclasses import asdict, dataclass
import io
import json
import platform
import pathlib
import pstats
import re
import socket
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, DefaultDict, Dict, Iterable, List, Optional


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import numpy as np

from wedm import EnvironmentConfig, WireEDMEnv, WireModuleParameters


POWERSCHEME_RE = re.compile(
    r"Power Scheme GUID:\s+([0-9a-fA-F-]+)\s+\(([^)]+)\)", re.MULTILINE
)
POWERCFG_INDEX_RE = re.compile(
    r"Current (AC|DC) Power Setting Index:\s+0x([0-9a-fA-F]+)", re.MULTILINE
)


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_uint32),
        ("BatteryFullLifeTime", ctypes.c_uint32),
    ]


@dataclass
class RunSample:
    wall_seconds: float
    steps_run: int
    steps_per_second: float
    simulated_us: int
    termination_reason: str
    crater_count: int
    crater_volume_mm3: float
    wire_temperature_mean: float
    wire_max_damage: float
    workpiece_position_um: float


@dataclass
class ModuleHotspot:
    name: str
    wall_share_pct: float
    avg_call_us: float
    calls: int
    total_seconds: float


@dataclass
class CProfileHotspot:
    function: str
    file: str
    line: int
    primitive_calls: int
    total_calls: int
    total_seconds: float
    cumulative_seconds: float


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _ensure_list(payload: Any) -> List[Dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def dominant_reason(samples: Iterable[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for sample in samples:
        reason = str(sample.get("termination_reason", "unknown"))
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda item: item[1])[0]


def run_command(command: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def run_powershell_json(command: str) -> Optional[Any]:
    try:
        result = run_command(["powershell", "-NoProfile", "-Command", command])
    except Exception:
        return None
    stdout = result.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def run_powershell_float(command: str) -> Optional[float]:
    try:
        result = run_command(["powershell", "-NoProfile", "-Command", command])
    except Exception:
        return None
    return _coerce_float(result.stdout.strip())


def get_windows_power_status() -> Dict[str, Any]:
    status = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return {"available": False}

    ac_map = {0: "battery", 1: "ac", 255: "unknown"}
    battery_present = not bool(status.BatteryFlag & 128)
    battery_percent = (
        None if int(status.BatteryLifePercent) == 255 else int(status.BatteryLifePercent)
    )
    return {
        "available": True,
        "power_source": ac_map.get(int(status.ACLineStatus), "unknown"),
        "battery_present": battery_present,
        "battery_percent": battery_percent,
        "battery_saver": bool(status.SystemStatusFlag),
    }


def parse_powercfg_setting_indices(output: str) -> Dict[str, int]:
    indices: Dict[str, int] = {}
    for source, value in POWERCFG_INDEX_RE.findall(output):
        indices[source.lower()] = int(value, 16)
    return indices


def collect_windows_processor_info() -> Dict[str, Any]:
    payload = run_powershell_json(
        "Get-CimInstance Win32_Processor | "
        "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,CurrentClockSpeed,MaxClockSpeed | "
        "ConvertTo-Json -Compress"
    )
    processors = _ensure_list(payload)
    if not processors:
        return {"available": False}

    current_clocks = [
        value
        for value in (_coerce_float(item.get("CurrentClockSpeed")) for item in processors)
        if value is not None
    ]
    max_clocks = [
        value
        for value in (_coerce_float(item.get("MaxClockSpeed")) for item in processors)
        if value is not None
    ]
    return {
        "available": True,
        "name": str(processors[0].get("Name", "")).strip(),
        "packages": len(processors),
        "physical_cores": sum(
            value
            for value in (_coerce_int(item.get("NumberOfCores")) for item in processors)
            if value is not None
        ),
        "logical_processors": sum(
            value
            for value in (
                _coerce_int(item.get("NumberOfLogicalProcessors")) for item in processors
            )
            if value is not None
        ),
        "current_clock_mhz": current_clocks[0] if current_clocks else None,
        "max_clock_mhz": max_clocks[0] if max_clocks else None,
    }


def collect_windows_performance_snapshot() -> Dict[str, Any]:
    return {
        "processor_frequency_mhz": run_powershell_float(
            "(Get-Counter '\\Processor Information(_Total)\\Processor Frequency')."
            "CounterSamples | Select-Object -ExpandProperty CookedValue"
        ),
        "percent_of_max_frequency": run_powershell_float(
            "(Get-Counter '\\Processor Information(_Total)\\% of Maximum Frequency')."
            "CounterSamples | Select-Object -ExpandProperty CookedValue"
        ),
        "percent_processor_performance": run_powershell_float(
            "(Get-Counter '\\Processor Information(_Total)\\% Processor Performance')."
            "CounterSamples | Select-Object -ExpandProperty CookedValue"
        ),
    }


def collect_windows_power_scheme() -> Dict[str, Any]:
    scheme: Dict[str, Any] = {"available": False}

    try:
        active_scheme = run_command(["powercfg", "/getactivescheme"]).stdout
    except Exception:
        active_scheme = ""

    active_match = POWERSCHEME_RE.search(active_scheme)
    if active_match:
        scheme.update(
            {
                "available": True,
                "guid": active_match.group(1),
                "name": active_match.group(2),
            }
        )

    try:
        max_state_output = run_command(
            ["powercfg", "/query", "scheme_current", "sub_processor", "PROCTHROTTLEMAX"]
        ).stdout
    except Exception:
        max_state_output = ""
    try:
        min_state_output = run_command(
            ["powercfg", "/query", "scheme_current", "sub_processor", "PROCTHROTTLEMIN"]
        ).stdout
    except Exception:
        min_state_output = ""

    max_indices = parse_powercfg_setting_indices(max_state_output)
    min_indices = parse_powercfg_setting_indices(min_state_output)
    if max_indices:
        scheme["max_processor_state_pct"] = max_indices
    if min_indices:
        scheme["min_processor_state_pct"] = min_indices
    return scheme


def collect_windows_thermal_info() -> Dict[str, Any]:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | "
            "Select-Object CurrentTemperature,InstanceName | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raw_message = (result.stderr or result.stdout).strip()
        message = raw_message.splitlines()[0] if raw_message else ""
        if "Access denied" in message:
            message = (
                "Thermal sensors are not accessible through the OS on this machine."
            )
        return {
            "available": False,
            "reason": message or "Thermal sensor query failed.",
        }

    payload = result.stdout.strip()
    if not payload:
        return {
            "available": False,
            "reason": "No thermal sensors were reported by the OS.",
        }

    try:
        raw_rows = json.loads(payload)
    except json.JSONDecodeError:
        return {
            "available": False,
            "reason": "Thermal sensor query returned unparseable JSON.",
        }

    rows = []
    for item in _ensure_list(raw_rows):
        current_temp = _coerce_float(item.get("CurrentTemperature"))
        if current_temp is None:
            continue
        rows.append(
            {
                "instance_name": str(item.get("InstanceName", "")),
                "temperature_c": float((current_temp / 10.0) - 273.15),
            }
        )

    if not rows:
        return {
            "available": False,
            "reason": "No usable thermal sensor rows were returned.",
        }

    hottest = max(row["temperature_c"] for row in rows)
    return {
        "available": True,
        "zones": rows,
        "hottest_temperature_c": hottest,
    }


def build_comparability_assessment(
    power_status: Dict[str, Any],
    power_scheme: Dict[str, Any],
    performance_snapshot: Dict[str, Any],
    thermal_info: Dict[str, Any],
) -> Dict[str, Any]:
    warnings: List[str] = []
    notes: List[str] = []

    power_source = power_status.get("power_source", "unknown")
    active_source = "ac" if power_source == "ac" else "dc" if power_source == "battery" else None

    max_state_pct = None
    if active_source:
        max_state_pct = (
            power_scheme.get("max_processor_state_pct", {}) or {}
        ).get(active_source)

    underclocked_policy_hint = bool(
        max_state_pct is not None and int(max_state_pct) < 100
    )
    frequency_pct = performance_snapshot.get("percent_of_max_frequency")
    frequency_limited_hint = bool(
        frequency_pct is not None and float(frequency_pct) < 95.0
    )

    thermal_limited_hint: Optional[bool]
    if thermal_info.get("available"):
        hottest = thermal_info.get("hottest_temperature_c")
        thermal_limited_hint = bool(
            hottest is not None and frequency_limited_hint and float(hottest) >= 80.0
        )
    else:
        thermal_limited_hint = None
        reason = thermal_info.get("reason")
        if reason:
            notes.append(reason)

    if power_source == "battery":
        warnings.append("Machine is running on battery power.")
    elif power_source == "unknown":
        warnings.append("Power source could not be determined.")

    if power_status.get("battery_saver"):
        warnings.append("Battery saver is active.")

    if underclocked_policy_hint:
        warnings.append(
            f"Active {active_source.upper()} processor max state is capped at {int(max_state_pct)}%."
        )

    if frequency_limited_hint:
        warnings.append(
            "Instantaneous CPU frequency snapshot is below 95% of maximum."
        )

    if thermal_limited_hint:
        warnings.append("Thermal sensors indicate possible thermal throttling.")

    return {
        "power_source": power_source,
        "active_processor_max_state_pct": max_state_pct,
        "underclocked_policy_hint": underclocked_policy_hint,
        "frequency_limited_hint": frequency_limited_hint,
        "thermal_limited_hint": thermal_limited_hint,
        "warnings": warnings,
        "notes": notes,
    }


def collect_system_context() -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host_name": socket.gethostname(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
    }

    if platform.system() != "Windows":
        context["comparability"] = {
            "power_source": "unknown",
            "warnings": ["Automatic power-context capture is only implemented for Windows."],
            "notes": [],
        }
        return context

    power_status = get_windows_power_status()
    processor_info = collect_windows_processor_info()
    performance_snapshot = collect_windows_performance_snapshot()
    power_scheme = collect_windows_power_scheme()
    thermal_info = collect_windows_thermal_info()

    context["power_status"] = power_status
    context["processor"] = processor_info
    context["performance_snapshot"] = performance_snapshot
    context["power_scheme"] = power_scheme
    context["thermal"] = thermal_info
    context["comparability"] = build_comparability_assessment(
        power_status,
        power_scheme,
        performance_snapshot,
        thermal_info,
    )
    return context


DASHBOARD_REQUIRED_SIGNALS = (
    "wire_temperature",
    "wire_material_positions_mm",
    "wire_head_idx",
    "wire_offset_mm",
)

DEFAULT_FIDELITY_TOLERANCES = {
    "crater_count_abs": 0.0,
    "wire_temperature_mean_abs": 0.5,
    "wire_max_damage_abs": 1e-4,
    "workpiece_position_um_abs": 0.1,
}


def build_dashboard_signal_status(env: WireEDMEnv) -> Dict[str, Any]:
    wire_temperature = env.state.wire_temperature
    wire_positions = env.state.wire_material_positions_mm
    wire_head_idx = env.state.wire_head_idx
    wire_offset_mm = env.state.wire_offset_mm

    status = {
        "wire_temperature": {
            "present": isinstance(wire_temperature, np.ndarray),
            "shape": list(wire_temperature.shape)
            if isinstance(wire_temperature, np.ndarray)
            else None,
        },
        "wire_material_positions_mm": {
            "present": isinstance(wire_positions, np.ndarray),
            "shape": list(wire_positions.shape)
            if isinstance(wire_positions, np.ndarray)
            else None,
        },
        "wire_head_idx": {
            "present": isinstance(wire_head_idx, (int, np.integer)),
            "value": int(wire_head_idx)
            if isinstance(wire_head_idx, (int, np.integer))
            else None,
        },
        "wire_offset_mm": {
            "present": isinstance(wire_offset_mm, (int, float, np.floating)),
            "value": float(wire_offset_mm)
            if isinstance(wire_offset_mm, (int, float, np.floating))
            else None,
        },
    }
    status["thermal_profile_ready"] = bool(
        status["wire_temperature"]["present"]
        and status["wire_material_positions_mm"]["present"]
        and status["wire_head_idx"]["present"]
        and status["wire_offset_mm"]["present"]
        and status["wire_temperature"]["shape"] is not None
        and status["wire_material_positions_mm"]["shape"] is not None
        and status["wire_temperature"]["shape"]
        == status["wire_material_positions_mm"]["shape"]
    )
    status["required_signals"] = list(DASHBOARD_REQUIRED_SIGNALS)
    return status


def build_fidelity_signature(
    samples: List[RunSample], env: WireEDMEnv
) -> Dict[str, Any]:
    return {
        "termination_reason": dominant_reason(asdict(sample) for sample in samples),
        "crater_count": int(
            round(statistics.median(sample.crater_count for sample in samples))
        ),
        "crater_volume_mm3": float(
            statistics.median(sample.crater_volume_mm3 for sample in samples)
        ),
        "wire_temperature_mean": float(
            statistics.median(sample.wire_temperature_mean for sample in samples)
        ),
        "wire_max_damage": float(
            statistics.median(sample.wire_max_damage for sample in samples)
        ),
        "workpiece_position_um": float(
            statistics.median(sample.workpiece_position_um for sample in samples)
        ),
        "dashboard_required_signals": build_dashboard_signal_status(env),
    }


def scenario_key(scenario: Dict[str, Any]) -> str:
    return (
        f"{float(scenario.get('segment_len_mm', 0.0)):.6f}|"
        f"{int(scenario.get('n_segments', 0))}"
    )


def compare_dashboard_signal_status(
    baseline_status: Dict[str, Any], current_status: Dict[str, Any]
) -> Dict[str, Any]:
    checks = []
    overall_passed = True
    for signal_name in DASHBOARD_REQUIRED_SIGNALS:
        baseline_signal = baseline_status.get(signal_name, {})
        current_signal = current_status.get(signal_name, {})
        passed = bool(
            baseline_signal.get("present") == current_signal.get("present")
            and baseline_signal.get("shape") == current_signal.get("shape")
        )
        checks.append(
            {
                "field": signal_name,
                "passed": passed,
                "baseline": baseline_signal,
                "current": current_signal,
            }
        )
        overall_passed = overall_passed and passed

    thermal_ready_passed = bool(
        baseline_status.get("thermal_profile_ready")
        == current_status.get("thermal_profile_ready")
    )
    checks.append(
        {
            "field": "thermal_profile_ready",
            "passed": thermal_ready_passed,
            "baseline": baseline_status.get("thermal_profile_ready"),
            "current": current_status.get("thermal_profile_ready"),
        }
    )
    overall_passed = overall_passed and thermal_ready_passed
    return {"passed": overall_passed, "checks": checks}


def compare_fidelity_signatures(
    baseline_report: Dict[str, Any],
    current_report: Dict[str, Any],
    tolerances: Dict[str, float],
) -> Dict[str, Any]:
    baseline_scenarios = {
        scenario_key(scenario): scenario for scenario in baseline_report.get("scenarios", [])
    }
    current_scenarios = {
        scenario_key(scenario): scenario for scenario in current_report.get("scenarios", [])
    }

    scenario_results = []
    overall_passed = True
    for key, current_scenario in current_scenarios.items():
        baseline_scenario = baseline_scenarios.get(key)
        if baseline_scenario is None:
            scenario_results.append(
                {
                    "scenario": key,
                    "passed": False,
                    "reason": "Scenario missing from baseline report.",
                }
            )
            overall_passed = False
            continue

        baseline_sig = baseline_scenario.get("fidelity_signature")
        current_sig = current_scenario.get("fidelity_signature")
        if baseline_sig is None or current_sig is None:
            scenario_results.append(
                {
                    "scenario": key,
                    "passed": False,
                    "reason": "One of the reports is missing fidelity_signature.",
                }
            )
            overall_passed = False
            continue

        metric_checks = []

        def add_exact_check(field: str) -> None:
            baseline_value = baseline_sig.get(field)
            current_value = current_sig.get(field)
            passed = baseline_value == current_value
            metric_checks.append(
                {
                    "field": field,
                    "passed": passed,
                    "baseline": baseline_value,
                    "current": current_value,
                }
            )

        def add_tolerance_check(field: str, tolerance_key: str) -> None:
            baseline_value = float(baseline_sig.get(field, 0.0))
            current_value = float(current_sig.get(field, 0.0))
            abs_delta = abs(current_value - baseline_value)
            tolerance = float(tolerances[tolerance_key])
            metric_checks.append(
                {
                    "field": field,
                    "passed": abs_delta <= tolerance,
                    "baseline": baseline_value,
                    "current": current_value,
                    "abs_delta": abs_delta,
                    "tolerance": tolerance,
                }
            )

        add_exact_check("termination_reason")
        add_tolerance_check("crater_count", "crater_count_abs")
        add_tolerance_check("wire_temperature_mean", "wire_temperature_mean_abs")
        add_tolerance_check("wire_max_damage", "wire_max_damage_abs")
        add_tolerance_check("workpiece_position_um", "workpiece_position_um_abs")

        dashboard_result = compare_dashboard_signal_status(
            baseline_sig.get("dashboard_required_signals", {}),
            current_sig.get("dashboard_required_signals", {}),
        )

        passed = all(check["passed"] for check in metric_checks) and dashboard_result[
            "passed"
        ]
        scenario_results.append(
            {
                "scenario": key,
                "passed": passed,
                "metrics": metric_checks,
                "dashboard_required_signals": dashboard_result,
            }
        )
        overall_passed = overall_passed and passed

    return {
        "passed": overall_passed,
        "tolerances": tolerances,
        "scenarios": scenario_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark and profile representative active-cutting workloads."
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=100_000,
        help="Timed simulation steps per scenario (default: 100000).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2_000,
        help="Warmup steps to run before each scenario family (default: 2000).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Benchmark repeats per scenario for stable throughput numbers (default: 3).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Seed for the representative workload (default: 123).",
    )
    parser.add_argument(
        "--initial-gap",
        type=float,
        default=12.0,
        help="Initial gap in um for the active workload (default: 12.0).",
    )
    parser.add_argument(
        "--servo-interval",
        type=int,
        default=1,
        help="Servo interval in us so each step applies control (default: 1).",
    )
    parser.add_argument(
        "--workpiece-height",
        type=float,
        default=20.0,
        help="Workpiece height in mm (default: 20.0).",
    )
    parser.add_argument(
        "--segment-len",
        action="append",
        dest="segment_lengths",
        type=float,
        help=(
            "Wire segment length in mm. Repeat the flag to compare multiple meshes. "
            "Defaults to 0.2 and 0.05."
        ),
    )
    parser.add_argument(
        "--servo",
        type=float,
        default=0.25,
        help="Fixed servo command for the benchmark action (default: 0.25).",
    )
    parser.add_argument(
        "--target-voltage",
        type=float,
        default=90.0,
        help="Fixed target voltage for the benchmark action (default: 90.0).",
    )
    parser.add_argument(
        "--current-mode",
        type=int,
        default=5,
        help="Integer current mode for the benchmark action (default: 5).",
    )
    parser.add_argument(
        "--on-time",
        type=float,
        default=3.0,
        help="Pulse ON time in us for the benchmark action (default: 3.0).",
    )
    parser.add_argument(
        "--off-time",
        type=float,
        default=20.0,
        help="Pulse OFF time in us for the benchmark action (default: 20.0).",
    )
    parser.add_argument(
        "--hotspots",
        choices=["none", "module", "cprofile", "both"],
        default="both",
        help="Hotspot report type to emit (default: both).",
    )
    parser.add_argument(
        "--profile-sort",
        choices=["cumulative", "tottime"],
        default="cumulative",
        help="Sort key for cProfile hotspots (default: cumulative).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of hotspot rows to print per table (default: 10).",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        help="Optional path to write the full report as JSON.",
    )
    parser.add_argument(
        "--compare-to",
        type=str,
        help="Optional baseline profiling JSON to compare fidelity against.",
    )
    parser.add_argument(
        "--fidelity-crater-count-tol",
        type=float,
        default=DEFAULT_FIDELITY_TOLERANCES["crater_count_abs"],
        help="Allowed absolute crater-count delta versus the baseline report.",
    )
    parser.add_argument(
        "--fidelity-wire-temp-tol",
        type=float,
        default=DEFAULT_FIDELITY_TOLERANCES["wire_temperature_mean_abs"],
        help="Allowed absolute mean wire-temperature delta in K.",
    )
    parser.add_argument(
        "--fidelity-wire-damage-tol",
        type=float,
        default=DEFAULT_FIDELITY_TOLERANCES["wire_max_damage_abs"],
        help="Allowed absolute max-damage delta versus the baseline report.",
    )
    parser.add_argument(
        "--fidelity-workpiece-pos-tol",
        type=float,
        default=DEFAULT_FIDELITY_TOLERANCES["workpiece_position_um_abs"],
        help="Allowed absolute workpiece-position delta in um.",
    )
    parser.add_argument(
        "--show-init-output",
        action="store_true",
        help="Print environment initialization messages instead of suppressing them.",
    )
    parser.add_argument(
        "--skip-system-context",
        action="store_true",
        help="Skip machine and power context capture in the report metadata.",
    )
    args = parser.parse_args()
    if not args.segment_lengths:
        args.segment_lengths = [0.2, 0.05]
    return args


def build_action(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "servo": np.array([args.servo], dtype=np.float32),
        "generator_control": {
            "target_voltage": np.array([args.target_voltage], dtype=np.float32),
            "current_mode": np.array([args.current_mode], dtype=np.int32),
            "ON_time": np.array([args.on_time], dtype=np.float32),
            "OFF_time": np.array([args.off_time], dtype=np.float32),
        },
    }


def create_env(
    args: argparse.Namespace, segment_len_mm: float, *, suppress_output: bool = True
) -> WireEDMEnv:
    config = EnvironmentConfig(
        initial_gap=args.initial_gap,
        servo_interval=args.servo_interval,
        workpiece_height=args.workpiece_height,
    )
    wire_params = WireModuleParameters(segment_len=segment_len_mm)

    if suppress_output and not args.show_init_output:
        with contextlib.redirect_stdout(io.StringIO()):
            return WireEDMEnv(config=config, wire_params=wire_params)
    return WireEDMEnv(config=config, wire_params=wire_params)


def prime_scenario(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> None:
    if args.warmup <= 0:
        return
    env = create_env(args, segment_len_mm)
    reset_for_run(env, seed=args.seed)
    run_step_loop(env, action, args.warmup)


def reset_for_run(env: WireEDMEnv, *, seed: int) -> None:
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval


def run_step_loop(env: WireEDMEnv, action: Dict[str, Any], steps: int) -> RunSample:

    termination_reason = "completed"
    steps_run = 0
    crater_count = 0
    crater_volume_mm3 = 0.0
    start = time.perf_counter()
    for _ in range(steps):
        _, _, terminated, truncated, info = env.step(action)
        steps_run += 1
        crater_volume = float(env.state.last_crater_volume)
        if crater_volume > 0.0:
            crater_count += 1
            crater_volume_mm3 += crater_volume
        if terminated or truncated:
            if info.get("wire_broken", False):
                termination_reason = "wire_broken"
            elif info.get("target_reached", False):
                termination_reason = "target_reached"
            elif truncated:
                termination_reason = "truncated"
            else:
                termination_reason = "terminated"
            break

    wall_seconds = time.perf_counter() - start
    return RunSample(
        wall_seconds=wall_seconds,
        steps_run=steps_run,
        steps_per_second=(steps_run / wall_seconds) if wall_seconds > 0 else 0.0,
        simulated_us=int(env.state.time),
        termination_reason=termination_reason,
        crater_count=crater_count,
        crater_volume_mm3=float(crater_volume_mm3),
        wire_temperature_mean=float(np.mean(env.state.wire_temperature)),
        wire_max_damage=float(env.state.wire_max_damage),
        workpiece_position_um=float(env.state.workpiece_position),
    )


def benchmark_scenario(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> Dict[str, Any]:
    prime_scenario(args, segment_len_mm, action)

    samples = []
    env = None
    for _ in range(args.repeats):
        env = create_env(args, segment_len_mm)
        reset_for_run(env, seed=args.seed)
        samples.append(run_step_loop(env, action, args.steps))

    if env is None:
        raise RuntimeError("Benchmark scenario did not create an environment.")

    wall_samples = [sample.wall_seconds for sample in samples]
    throughput_samples = [sample.steps_per_second for sample in samples]

    return {
        "segment_len_mm": float(segment_len_mm),
        "n_segments": int(env.wire.n_segments),
        "benchmark": {
            "repeats": int(args.repeats),
            "steps_requested": int(args.steps),
            "median_wall_seconds": float(statistics.median(wall_samples)),
            "median_steps_per_second": float(statistics.median(throughput_samples)),
            "mean_steps_per_second": float(statistics.mean(throughput_samples)),
            "samples": [asdict(sample) for sample in samples],
        },
        "fidelity_signature": build_fidelity_signature(samples, env),
    }


def wrap_timed_call(
    target: Any,
    attribute: str,
    label: str,
    times_ns: DefaultDict[str, int],
    calls: DefaultDict[str, int],
) -> None:
    original = getattr(target, attribute)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_ns = time.perf_counter_ns()
        try:
            return original(*args, **kwargs)
        finally:
            times_ns[label] += time.perf_counter_ns() - start_ns
            calls[label] += 1

    setattr(target, attribute, wrapper)


def module_hotspots(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> tuple[List[ModuleHotspot], List[ModuleHotspot]]:
    prime_scenario(args, segment_len_mm, action)

    env = create_env(args, segment_len_mm)
    times_ns = defaultdict(int)
    calls = defaultdict(int)
    wire_times_ns = defaultdict(int)
    wire_calls = defaultdict(int)

    wrap_timed_call(env, "_apply_action", "env._apply_action", times_ns, calls)
    wrap_timed_call(
        env, "_check_termination", "env._check_termination", times_ns, calls
    )
    wrap_timed_call(env, "_get_obs", "env._get_obs", times_ns, calls)
    wrap_timed_call(env, "_calc_reward", "env._calc_reward", times_ns, calls)

    for module_name in ["ignition", "material", "dielectric", "wire", "mechanics"]:
        module = getattr(env, module_name)
        wrap_timed_call(module, "update", module_name, times_ns, calls)

    env.wire._profile_update_subhotspots = True
    wire_method_labels = [
        ("_advance_transport", "transport"),
        ("_apply_thermal_core", "thermal_core"),
        ("_accumulate_damage", "damage"),
        ("_sync_state_views", "state_sync"),
    ]
    for method_name, label in wire_method_labels:
        wrap_timed_call(env.wire, method_name, label, wire_times_ns, wire_calls)

    reset_for_run(env, seed=args.seed)
    sample = run_step_loop(env, action, args.steps)
    rows = []
    for name, total_ns in sorted(
        times_ns.items(), key=lambda item: item[1], reverse=True
    ):
        rows.append(
            ModuleHotspot(
                name=name,
                wall_share_pct=(
                    (total_ns / 1e9 / sample.wall_seconds * 100.0)
                    if sample.wall_seconds > 0
                    else 0.0
                ),
                avg_call_us=(total_ns / calls[name] / 1000.0) if calls[name] else 0.0,
                calls=int(calls[name]),
                total_seconds=total_ns / 1e9,
            )
        )

    wire_rows = []
    for name, total_ns in sorted(
        wire_times_ns.items(), key=lambda item: item[1], reverse=True
    ):
        wire_rows.append(
            ModuleHotspot(
                name=name,
                wall_share_pct=(
                    (total_ns / 1e9 / sample.wall_seconds * 100.0)
                    if sample.wall_seconds > 0
                    else 0.0
                ),
                avg_call_us=(total_ns / wire_calls[name] / 1000.0)
                if wire_calls[name]
                else 0.0,
                calls=int(wire_calls[name]),
                total_seconds=total_ns / 1e9,
            )
        )

    return rows, wire_rows


def is_project_file(filename: str) -> bool:
    normalized = filename.replace("\\", "/")
    return "/src/wedm/" in normalized


def format_path(path_str: str) -> str:
    path = pathlib.Path(path_str)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except Exception:
        return path.name


def cprofile_hotspots(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> List[CProfileHotspot]:
    prime_scenario(args, segment_len_mm, action)

    env = create_env(args, segment_len_mm)
    reset_for_run(env, seed=args.seed)
    profiler = cProfile.Profile()
    profiler.enable()
    run_step_loop(env, action, args.steps)
    profiler.disable()

    stats = pstats.Stats(profiler)
    stats.sort_stats(args.profile_sort)

    rows = []
    for func in stats.fcn_list or []:
        filename, line_no, func_name = func
        if not is_project_file(filename):
            continue
        primitive_calls, total_calls, total_seconds, cumulative_seconds, _ = (
            stats.stats[func]
        )
        rows.append(
            CProfileHotspot(
                function=func_name,
                file=format_path(filename),
                line=int(line_no),
                primitive_calls=int(primitive_calls),
                total_calls=int(total_calls),
                total_seconds=float(total_seconds),
                cumulative_seconds=float(cumulative_seconds),
            )
        )
        if len(rows) >= args.top:
            break

    return rows


def print_header(args: argparse.Namespace, system_context: Optional[Dict[str, Any]]) -> None:
    print("=== Simulation Profiling Harness ===")
    print(f"repo_root: {REPO_ROOT}")
    print(f"import_root: {SRC_ROOT}")
    print(
        "workload: "
        f"steps={args.steps} warmup={args.warmup} repeats={args.repeats} seed={args.seed} "
        f"initial_gap_um={args.initial_gap} servo_interval_us={args.servo_interval}"
    )
    print(
        "action: "
        f"servo={args.servo} target_voltage={args.target_voltage} "
        f"current_mode=I{args.current_mode} on_time_us={args.on_time} off_time_us={args.off_time}"
    )
    print(
        "meshes: "
        + ", ".join(f"{segment_len:.4f} mm" for segment_len in args.segment_lengths)
    )
    if args.compare_to:
        print(f"compare_to: {args.compare_to}")
    if not system_context:
        return

    def _fmt_metric(value: Any) -> str:
        numeric = _coerce_float(value)
        if numeric is None:
            return "n/a"
        return f"{numeric:.1f}"

    comparability = system_context.get("comparability", {})
    processor = system_context.get("processor", {})
    power_status = system_context.get("power_status", {})
    power_scheme = system_context.get("power_scheme", {})
    performance = system_context.get("performance_snapshot", {})
    print(
        "system: "
        f"{processor.get('name', 'unknown CPU')} "
        f"power={comparability.get('power_source', 'unknown')} "
        f"scheme={power_scheme.get('name', 'unknown')} "
        f"battery={power_status.get('battery_percent', 'n/a')}% "
        f"freq_pct={_fmt_metric(performance.get('percent_of_max_frequency'))} "
        f"perf_pct={_fmt_metric(performance.get('percent_processor_performance'))}"
    )
    for warning in comparability.get("warnings", []):
        print(f"  warning: {warning}")
    for note in comparability.get("notes", []):
        print(f"  note: {note}")


def print_benchmark(report: Dict[str, Any]) -> None:
    benchmark = report["benchmark"]
    print(
        f"Benchmark: median={benchmark['median_steps_per_second']:.2f} steps/s "
        f"mean={benchmark['mean_steps_per_second']:.2f} steps/s "
        f"segments={report['n_segments']}"
    )
    for index, sample in enumerate(benchmark["samples"], start=1):
        print(
            f"  repeat {index}: {sample['steps_per_second']:.2f} steps/s "
            f"wall={sample['wall_seconds']:.6f}s steps={sample['steps_run']} "
            f"termination={sample['termination_reason']} craters={sample['crater_count']}"
        )


def print_fidelity_signature(report: Dict[str, Any]) -> None:
    fidelity = report.get("fidelity_signature")
    if not fidelity:
        return
    print(
        "Fidelity: "
        f"termination={fidelity['termination_reason']} "
        f"craters={fidelity['crater_count']} "
        f"crater_volume_mm3={fidelity['crater_volume_mm3']:.6f} "
        f"mean_wire_temp={fidelity['wire_temperature_mean']:.2f}K "
        f"max_damage={fidelity['wire_max_damage']:.6f} "
        f"workpiece_pos={fidelity['workpiece_position_um']:.4f}um "
        f"dashboard_ready={fidelity['dashboard_required_signals']['thermal_profile_ready']}"
    )


def print_module_hotspots(rows: Iterable[Dict[str, Any]]) -> None:
    print("Module hotspots:")
    for row in rows:
        print(
            f"  {row['name']:<22} share={row['wall_share_pct']:6.2f}% "
            f"avg_call={row['avg_call_us']:8.3f} us calls={row['calls']:6d}"
        )


def print_wire_subhotspots(rows: Iterable[Dict[str, Any]]) -> None:
    print("Wire sub-buckets:")
    for row in rows:
        print(
            f"  {row['name']:<22} share={row['wall_share_pct']:6.2f}% "
            f"avg_call={row['avg_call_us']:8.3f} us calls={row['calls']:6d}"
        )


def print_cprofile_hotspots(rows: Iterable[Dict[str, Any]], sort_key: str) -> None:
    print(f"cProfile hotspots ({sort_key}):")
    for row in rows:
        print(
            f"  {row['function']:<28} {row['file']}:{row['line']} "
            f"cum={row['cumulative_seconds']:.6f}s total={row['total_seconds']:.6f}s "
            f"calls={row['total_calls']}"
        )


def print_fidelity_comparison(result: Dict[str, Any]) -> None:
    print(
        "Fidelity comparison: "
        + ("PASS" if result.get("passed") else "FAIL")
    )
    for scenario in result.get("scenarios", []):
        scenario_name = scenario.get("scenario", "unknown")
        print(
            f"  scenario {scenario_name}: "
            + ("PASS" if scenario.get("passed") else "FAIL")
        )
        if "reason" in scenario:
            print(f"    reason: {scenario['reason']}")
            continue
        for check in scenario.get("metrics", []):
            status = "ok" if check["passed"] else "mismatch"
            if "tolerance" in check:
                print(
                    f"    {check['field']}: {status} "
                    f"baseline={check['baseline']} current={check['current']} "
                    f"abs_delta={check['abs_delta']:.6g} tol={check['tolerance']:.6g}"
                )
            else:
                print(
                    f"    {check['field']}: {status} "
                    f"baseline={check['baseline']} current={check['current']}"
                )
        dashboard = scenario.get("dashboard_required_signals", {})
        for check in dashboard.get("checks", []):
            status = "ok" if check["passed"] else "mismatch"
            print(f"    {check['field']}: {status}")


def write_json_report(report: Dict[str, Any], output_path_str: str) -> None:
    output_path = pathlib.Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"JSON report written to {output_path}")


def load_json_report(path_str: str) -> Dict[str, Any]:
    return json.loads(pathlib.Path(path_str).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    action = build_action(args)
    system_context = None if args.skip_system_context else collect_system_context()

    print_header(args, system_context)

    report = {
        "metadata": {
            "repo_root": str(REPO_ROOT),
            "import_root": str(SRC_ROOT),
            "steps": int(args.steps),
            "warmup": int(args.warmup),
            "repeats": int(args.repeats),
            "seed": int(args.seed),
            "initial_gap_um": float(args.initial_gap),
            "servo_interval_us": int(args.servo_interval),
            "workpiece_height_mm": float(args.workpiece_height),
            "segment_lengths_mm": [float(value) for value in args.segment_lengths],
            "hotspots": args.hotspots,
            "profile_sort": args.profile_sort,
            "system_context": system_context,
        },
        "action": {
            "servo": float(args.servo),
            "target_voltage": float(args.target_voltage),
            "current_mode": f"I{args.current_mode}",
            "on_time_us": float(args.on_time),
            "off_time_us": float(args.off_time),
        },
        "scenarios": [],
    }

    for segment_len_mm in args.segment_lengths:
        print()
        print(f"=== Scenario: segment_len={segment_len_mm:.4f} mm ===")
        scenario_report = benchmark_scenario(args, segment_len_mm, action)
        print_benchmark(scenario_report)
        print_fidelity_signature(scenario_report)

        if args.hotspots in ("module", "both"):
            top_level_rows, wire_sub_rows = module_hotspots(args, segment_len_mm, action)
            module_rows = [asdict(row) for row in top_level_rows]
            scenario_report["module_hotspots"] = module_rows[: args.top]
            scenario_report["module_subhotspots"] = {
                "wire": [asdict(row) for row in wire_sub_rows[: args.top]]
            }
            print_module_hotspots(scenario_report["module_hotspots"])
            print_wire_subhotspots(scenario_report["module_subhotspots"]["wire"])

        if args.hotspots in ("cprofile", "both"):
            cprofile_rows = [
                asdict(row) for row in cprofile_hotspots(args, segment_len_mm, action)
            ]
            scenario_report["cprofile_hotspots"] = cprofile_rows[: args.top]
            print_cprofile_hotspots(
                scenario_report["cprofile_hotspots"], args.profile_sort
            )

        report["scenarios"].append(scenario_report)

    if args.compare_to:
        tolerances = {
            "crater_count_abs": float(args.fidelity_crater_count_tol),
            "wire_temperature_mean_abs": float(args.fidelity_wire_temp_tol),
            "wire_max_damage_abs": float(args.fidelity_wire_damage_tol),
            "workpiece_position_um_abs": float(args.fidelity_workpiece_pos_tol),
        }
        baseline_report = load_json_report(args.compare_to)
        comparison = compare_fidelity_signatures(baseline_report, report, tolerances)
        comparison["baseline_report_path"] = format_path(args.compare_to)
        report["fidelity_comparison"] = comparison
        print()
        print_fidelity_comparison(comparison)

    if args.json_out:
        write_json_report(report, args.json_out)


if __name__ == "__main__":
    main()
