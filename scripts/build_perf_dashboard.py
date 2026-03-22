#!/usr/bin/env python
"""Build a standalone HTML dashboard from simulation profiling reports."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
from html import escape
import json
import math
import pathlib
import statistics
from typing import Any, Dict, Iterable, List, Optional


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INPUT_GLOBS = ["outputs/profiling/*.json"]
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "profiling" / "performance_dashboard.html"
DEFAULT_TARGET_STEPS_PER_SECOND = 1_000_000.0
DEFAULT_METRIC = "slower_than_realtime"
PLOT_METRICS = [
    {
        "key": "slower_than_realtime",
        "label": "Wall s / sim s",
        "digits": 2,
        "suffix": "x",
        "guidance": "Lower is better. Realtime is 1.00x.",
    },
    {
        "key": "steps_per_second",
        "label": "Median steps/s",
        "digits": 2,
        "suffix": " steps/s",
        "guidance": "Higher is better. Target is 1,000,000 steps/s.",
    },
    {
        "key": "target_pct",
        "label": "Target coverage",
        "digits": 2,
        "suffix": "%",
        "guidance": "Higher is better.",
    },
    {
        "key": "crater_count",
        "label": "Crater count",
        "digits": 0,
        "suffix": "",
        "guidance": "Should stay consistent across optimization work.",
    },
    {
        "key": "wire_temperature_mean",
        "label": "Mean wire temperature",
        "digits": 2,
        "suffix": " K",
        "guidance": "Should stay consistent across optimization work.",
    },
    {
        "key": "wire_max_damage",
        "label": "Wire max damage",
        "digits": 6,
        "suffix": "",
        "guidance": "Should stay consistent across optimization work.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a standalone HTML dashboard from profiling JSON reports."
    )
    parser.add_argument(
        "--input-glob",
        action="append",
        default=[],
        help=(
            "Glob pattern for profile JSON files. Repeat to scan multiple patterns. "
            "Defaults to outputs/profiling/*.json."
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Path to the generated HTML file.",
    )
    parser.add_argument(
        "--target-steps-per-second",
        type=float,
        default=DEFAULT_TARGET_STEPS_PER_SECOND,
        help=(
            "Realtime target in steps/s. Default 1000000, which matches 1 s wall / "
            "1 s simulated at dt = 1 us."
        ),
    )
    return parser.parse_args()


def fmt_float(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def fmt_int(value: int) -> str:
    return f"{value:,}"


def human_time(timestamp: dt.datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def display_path(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def scenario_label(segment_len_mm: float, n_segments: int) -> str:
    return f"{segment_len_mm:.2f} mm / {n_segments} seg"


def median_metric(samples: Iterable[Dict[str, Any]], key: str) -> Optional[float]:
    values = [float(sample[key]) for sample in samples if key in sample]
    if not values:
        return None
    return float(statistics.median(values))


def dominant_reason(samples: Iterable[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for sample in samples:
        reason = str(sample.get("termination_reason", "unknown"))
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda item: item[1])[0]


def is_profile_report(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if "metadata" not in data or "scenarios" not in data:
        return False
    if not isinstance(data["metadata"], dict) or not isinstance(data["scenarios"], list):
        return False
    if not data["scenarios"]:
        return False
    return isinstance(data["scenarios"][0], dict) and "benchmark" in data["scenarios"][0]


def collect_input_paths(patterns: List[str]) -> List[pathlib.Path]:
    resolved_patterns = patterns or DEFAULT_INPUT_GLOBS
    paths: List[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    for pattern in resolved_patterns:
        full_pattern = REPO_ROOT / pattern
        for raw_path in glob.glob(str(full_pattern)):
            path = pathlib.Path(raw_path).resolve()
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return sorted(paths, key=lambda path: path.stat().st_mtime)


def normalize_module_key(raw_name: str) -> str:
    name = str(raw_name or "unknown").strip()
    if not name:
        return "unknown"
    if name.startswith("env."):
        return "env"
    if "." in name:
        return name.split(".", 1)[0]
    return name


def canonicalize_module_stem(stem: str) -> str:
    raw = stem.strip().lower()
    if not raw:
        return "other"
    if raw == "wire_edm":
        return "env"
    for prefix in ("wire", "ignition", "dielectric", "mechanics", "material", "env"):
        if raw == prefix or raw.startswith(f"{prefix}_"):
            return "env" if prefix == "env" else prefix
    return raw


def infer_cprofile_module_key(row: Dict[str, Any]) -> str:
    file_ref = str(row.get("file", "")).replace("\\", "/").lower()
    if "/modules/" in file_ref:
        return canonicalize_module_stem(pathlib.PurePosixPath(file_ref).stem)
    if "/envs/" in file_ref:
        return "env"
    return "other"


def build_module_breakdown(
    module_hotspots: List[Dict[str, Any]],
    cprofile_hotspots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}

    for row in module_hotspots:
        key = normalize_module_key(str(row.get("name", "unknown")))
        entry = grouped.setdefault(
            key,
            {
                "key": key,
                "label": key,
                "wall_share_pct": 0.0,
                "components": [],
                "details": [],
            },
        )
        entry["wall_share_pct"] += float(row.get("wall_share_pct", 0.0))
        raw_name = str(row.get("name", key))
        if raw_name not in entry["components"]:
            entry["components"].append(raw_name)

    for row in cprofile_hotspots:
        key = infer_cprofile_module_key(row)
        entry = grouped.setdefault(
            key,
            {
                "key": key,
                "label": key,
                "wall_share_pct": 0.0,
                "components": [],
                "details": [],
            },
        )
        entry["details"].append(
            {
                "function": str(row.get("function", "unknown")),
                "location": f"{row.get('file', '?')}:{row.get('line', '?')}",
                "cumulative_seconds": float(row.get("cumulative_seconds", 0.0)),
                "total_seconds": float(row.get("total_seconds", 0.0)),
                "total_calls": int(row.get("total_calls", 0) or 0),
            }
        )

    modules = list(grouped.values())
    for entry in modules:
        entry["details"].sort(
            key=lambda detail: (
                float(detail.get("cumulative_seconds", 0.0)),
                float(detail.get("total_seconds", 0.0)),
            ),
            reverse=True,
        )
    modules.sort(key=lambda entry: float(entry.get("wall_share_pct", 0.0)), reverse=True)
    return modules


def load_report(path: pathlib.Path, target_steps_per_second: float) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    if not is_profile_report(data):
        return None

    stat = path.stat()
    collected_at = dt.datetime.fromtimestamp(stat.st_mtime)
    scenarios: List[Dict[str, Any]] = []
    for scenario in data["scenarios"]:
        benchmark = scenario.get("benchmark", {})
        samples = benchmark.get("samples", [])
        steps_per_second = float(benchmark.get("median_steps_per_second", 0.0))
        slower_than_realtime = (
            target_steps_per_second / steps_per_second if steps_per_second > 0 else math.inf
        )
        module_hotspots = scenario.get("module_hotspots") or []
        cprofile_hotspots = scenario.get("cprofile_hotspots") or []
        module_breakdown = build_module_breakdown(module_hotspots, cprofile_hotspots)
        top_module = module_breakdown[0] if module_breakdown else None

        scenarios.append(
            {
                "label": scenario_label(
                    float(scenario.get("segment_len_mm", 0.0)),
                    int(scenario.get("n_segments", 0)),
                ),
                "segment_len_mm": float(scenario.get("segment_len_mm", 0.0)),
                "n_segments": int(scenario.get("n_segments", 0)),
                "steps_requested": int(benchmark.get("steps_requested", 0)),
                "steps_per_second": steps_per_second,
                "mean_steps_per_second": float(benchmark.get("mean_steps_per_second", 0.0)),
                "wall_seconds": float(benchmark.get("median_wall_seconds", 0.0)),
                "slower_than_realtime": slower_than_realtime,
                "target_pct": (
                    (steps_per_second / target_steps_per_second) * 100.0
                    if target_steps_per_second > 0
                    else 0.0
                ),
                "termination_reason": dominant_reason(samples),
                "crater_count": median_metric(samples, "crater_count"),
                "wire_temperature_mean": median_metric(samples, "wire_temperature_mean"),
                "wire_max_damage": median_metric(samples, "wire_max_damage"),
                "module_hotspots": module_hotspots,
                "module_subhotspots": scenario.get("module_subhotspots") or {},
                "cprofile_hotspots": cprofile_hotspots,
                "module_breakdown": module_breakdown,
                "top_module_name": top_module.get("label") if top_module else None,
                "top_module_pct": float(top_module.get("wall_share_pct", 0.0))
                if top_module
                else None,
            }
        )

    if not scenarios:
        return None

    return {
        "name": path.stem,
        "path": display_path(path),
        "collected_at": collected_at,
        "collected_at_label": human_time(collected_at),
        "metadata": data["metadata"],
        "action": data.get("action", {}),
        "verification_summary": data.get("verification_summary"),
        "scenarios": scenarios,
    }


def render_metric_card(title: str, value: str, subtitle: str, accent: str) -> str:
    return (
        f'<div class="metric-card {accent}">'
        f"<div class=\"metric-label\">{escape(title)}</div>"
        f"<div class=\"metric-value\">{escape(value)}</div>"
        f"<div class=\"metric-subtitle\">{escape(subtitle)}</div>"
        "</div>"
    )


def render_plot_panel() -> str:
    metric_options = []
    for metric in PLOT_METRICS:
        selected = ' selected="selected"' if metric["key"] == DEFAULT_METRIC else ""
        metric_options.append(
            f'<option value="{escape(metric["key"])}"{selected}>{escape(metric["label"])}</option>'
        )
    return f"""
    <section class="panel trend-panel">
        <div class="section-head">
            <div>
                <h2>Performance Plot</h2>
                <p class="section-note">
                    Change the plotted metric and set manual y-axis bounds when you want to inspect
                    smaller deltas without flattening the chart.
                </p>
            </div>
            <div class="chart-controls">
                <label class="control-field">
                    <span>Metric</span>
                    <select id="metric-select">
                        {''.join(metric_options)}
                    </select>
                </label>
                <label class="control-field">
                    <span>Y min</span>
                    <input id="y-min-input" type="number" step="any" placeholder="auto">
                </label>
                <label class="control-field">
                    <span>Y max</span>
                    <input id="y-max-input" type="number" step="any" placeholder="auto">
                </label>
                <button type="button" class="secondary-button" id="apply-axis-button">Apply axis</button>
                <button type="button" class="secondary-button" id="reset-axis-button">Reset axis</button>
            </div>
        </div>
        <p class="section-note subtle" id="chart-description"></p>
        <svg id="performance-plot" viewBox="0 0 1040 380" class="trend-svg" role="img" aria-label="Performance trend chart"></svg>
        <div class="trend-legend" id="plot-legend"></div>
    </section>
    """


def render_module_panel(report: Dict[str, Any]) -> str:
    return f"""
    <section class="panel">
        <div class="section-head">
            <div>
                <h2>Module Drilldown</h2>
                <p class="section-note">
                    Click a module from the latest snapshot to open the functions and lines that consume its time.
                </p>
            </div>
            <div class="snapshot-badge">Snapshot: {escape(report['name'])}</div>
        </div>
        <div class="module-layout">
            <div class="module-rail" id="module-chip-row"></div>
            <div class="module-detail" id="module-detail"></div>
        </div>
    </section>
    """


def build_delta(current_value: Optional[float], reference_value: Optional[float]) -> Optional[Dict[str, float]]:
    if current_value is None or reference_value is None:
        return None
    current = float(current_value)
    reference = float(reference_value)
    delta_steps = current - reference
    delta_pct = (delta_steps / reference * 100.0) if reference != 0.0 else math.inf
    return {
        "reference": reference,
        "current": current,
        "delta_steps_per_second": delta_steps,
        "delta_pct": delta_pct,
    }


def fmt_delta(delta: Optional[Dict[str, float]]) -> str:
    if not delta:
        return "n/a"
    pct = delta.get("delta_pct")
    if pct is None or not math.isfinite(pct):
        return "n/a"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def annotate_progress(reports: List[Dict[str, Any]]) -> None:
    previous_by_label: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        verification = report.get("verification_summary") or {}
        baseline_entries = {
            str(entry.get("scenario")): entry for entry in verification.get("scenarios", [])
        }
        for scenario in report["scenarios"]:
            previous_scenario = previous_by_label.get(scenario["label"])
            scenario["delta_vs_previous"] = (
                build_delta(scenario["steps_per_second"], previous_scenario["steps_per_second"])
                if previous_scenario is not None
                else None
            )
            baseline_entry = baseline_entries.get(scenario["label"])
            scenario["delta_vs_baseline"] = (
                build_delta(
                    scenario["steps_per_second"],
                    baseline_entry.get("baseline_steps_per_second"),
                )
                if baseline_entry is not None
                else None
            )
            previous_by_label[scenario["label"]] = scenario


def render_verification_panel(report: Dict[str, Any]) -> str:
    verification = report.get("verification_summary") or {}
    scenarios = verification.get("scenarios") or []
    if not scenarios:
        return """
    <section class="panel">
        <h2>Before / After</h2>
        <p class="section-note">
            This snapshot is not tagged as a candidate verification run yet, so no explicit
            baseline comparison was archived with it.
        </p>
    </section>
    """

    rows = []
    for scenario in scenarios:
        delta_pct = scenario.get("delta_pct")
        delta_text = "n/a" if delta_pct is None else f"{delta_pct:+.2f}%"
        rows.append(
            "<tr>"
            f"<td>{escape(str(scenario.get('scenario', 'unknown')))}</td>"
            f"<td>{fmt_float(float(scenario.get('baseline_steps_per_second', 0.0)))}</td>"
            f"<td>{fmt_float(float(scenario.get('candidate_steps_per_second', 0.0)))}</td>"
            f"<td>{escape(delta_text)}</td>"
            f"<td>{'PASS' if scenario.get('fidelity_passed') else 'FAIL'}</td>"
            "</tr>"
        )

    return f"""
    <section class="panel">
        <h2>Before / After</h2>
        <p class="section-note">
            Latest candidate run was checked against <strong>{escape(str(verification.get('baseline_report_name', 'baseline')))}</strong>.
            Each row shows throughput movement for the same scenario plus the archived fidelity verdict.
        </p>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Scenario</th>
                        <th>Baseline steps/s</th>
                        <th>Candidate steps/s</th>
                        <th>Delta</th>
                        <th>Fidelity</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
    </section>
    """


def render_latest_table(report: Dict[str, Any]) -> str:
    rows = []
    for scenario in sorted(report["scenarios"], key=lambda item: item["segment_len_mm"]):
        crater = "n/a" if scenario["crater_count"] is None else fmt_int(int(scenario["crater_count"]))
        temp = (
            "n/a"
            if scenario["wire_temperature_mean"] is None
            else f"{fmt_float(scenario['wire_temperature_mean'], 2)} K"
        )
        damage = (
            "n/a"
            if scenario["wire_max_damage"] is None
            else fmt_float(scenario["wire_max_damage"], 6)
        )
        top_module = (
            "n/a"
            if scenario["top_module_name"] is None
            else f"{scenario['top_module_name']} ({fmt_float(scenario['top_module_pct'], 1)}%)"
        )
        rows.append(
            "<tr>"
            f"<td>{escape(scenario['label'])}</td>"
            f"<td>{fmt_float(scenario['steps_per_second'])}</td>"
            f"<td>{fmt_float(scenario['slower_than_realtime'])}x</td>"
            f"<td>{escape(fmt_delta(scenario.get('delta_vs_previous')))}</td>"
            f"<td>{escape(fmt_delta(scenario.get('delta_vs_baseline')))}</td>"
            f"<td>{fmt_float(scenario['target_pct'])}%</td>"
            f"<td>{escape(scenario['termination_reason'])}</td>"
            f"<td>{crater}</td>"
            f"<td>{temp}</td>"
            f"<td>{damage}</td>"
            f"<td>{escape(top_module)}</td>"
            "</tr>"
        )

    metadata = report["metadata"]
    return f"""
    <section class="panel">
        <h2>{escape(report['name'])}</h2>
        <p class="section-note">
            Collected {escape(report['collected_at_label'])}. Steps={fmt_int(int(metadata.get('steps', 0)))},
            warmup={fmt_int(int(metadata.get('warmup', 0)))}, repeats={fmt_int(int(metadata.get('repeats', 0)))},
            gap={escape(str(metadata.get('initial_gap_um', 'n/a')))} um.
        </p>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Scenario</th>
                        <th>Median steps/s</th>
                        <th>Wall s / sim s</th>
                        <th>Vs previous</th>
                        <th>Vs baseline</th>
                        <th>% of target</th>
                        <th>Termination</th>
                        <th>Crater count</th>
                        <th>Mean wire temp</th>
                        <th>Max damage</th>
                        <th>Top module</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
    </section>
    """


def render_hotspot_bars(report: Dict[str, Any]) -> str:
    cards = []
    for scenario in sorted(report["scenarios"], key=lambda item: item["segment_len_mm"]):
        rows = scenario["module_hotspots"]
        if not rows:
            cards.append(
                f"""
                <div class="subpanel">
                    <h3>{escape(scenario['label'])}</h3>
                    <p class="empty-state">No module hotspot data in this snapshot.</p>
                </div>
                """
            )
            continue

        bars = []
        for row in rows[:8]:
            width = min(max(float(row.get("wall_share_pct", 0.0)), 0.0), 100.0)
            bars.append(
                f"""
                <div class="hotspot-row">
                    <div class="hotspot-name">{escape(str(row.get('name', 'unknown')))}</div>
                    <div class="hotspot-track">
                        <div class="hotspot-fill" style="width: {width:.2f}%"></div>
                    </div>
                    <div class="hotspot-value">{fmt_float(width, 1)}%</div>
                </div>
                """
            )
        cards.append(
            f"""
            <div class="subpanel">
                <h3>{escape(scenario['label'])}</h3>
                <div class="hotspot-list">
                    {''.join(bars)}
                </div>
            </div>
            """
        )

    return f"""
    <section class="panel">
        <h2>Latest Module Wall Shares</h2>
        <div class="subpanel-grid">
            {''.join(cards)}
        </div>
    </section>
    """


def render_cprofile_tables(report: Dict[str, Any]) -> str:
    cards = []
    for scenario in sorted(report["scenarios"], key=lambda item: item["segment_len_mm"]):
        rows = scenario["cprofile_hotspots"]
        if not rows:
            cards.append(
                f"""
                <div class="subpanel">
                    <h3>{escape(scenario['label'])}</h3>
                    <p class="empty-state">No cProfile hotspot data in this snapshot.</p>
                </div>
                """
            )
            continue

        table_rows = []
        for row in rows[:8]:
            file_ref = f"{row.get('file', '?')}:{row.get('line', '?')}"
            table_rows.append(
                "<tr>"
                f"<td>{escape(str(row.get('function', 'unknown')))}</td>"
                f"<td>{escape(file_ref)}</td>"
                f"<td>{fmt_float(float(row.get('cumulative_seconds', 0.0)), 3)}</td>"
                f"<td>{fmt_float(float(row.get('total_seconds', 0.0)), 3)}</td>"
                "</tr>"
            )
        cards.append(
            f"""
            <div class="subpanel">
                <h3>{escape(scenario['label'])}</h3>
                <div class="table-wrap compact">
                    <table>
                        <thead>
                            <tr>
                                <th>Function</th>
                                <th>Location</th>
                                <th>Cumulative s</th>
                                <th>Total s</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(table_rows)}
                        </tbody>
                    </table>
                </div>
            </div>
            """
        )

    return f"""
    <section class="panel">
        <h2>Latest cProfile Top Lines</h2>
        <div class="subpanel-grid">
            {''.join(cards)}
        </div>
    </section>
    """


def render_history_table(reports: List[Dict[str, Any]]) -> str:
    rows = []
    for report in sorted(reports, key=lambda item: item["collected_at"], reverse=True):
        for scenario in sorted(report["scenarios"], key=lambda item: item["segment_len_mm"]):
            rows.append(
                "<tr>"
                f"<td>{escape(report['name'])}</td>"
                f"<td>{escape(report['collected_at_label'])}</td>"
                f"<td>{escape(scenario['label'])}</td>"
                f"<td>{fmt_float(scenario['steps_per_second'])}</td>"
                f"<td>{escape(fmt_delta(scenario.get('delta_vs_previous')))}</td>"
                f"<td>{escape(fmt_delta(scenario.get('delta_vs_baseline')))}</td>"
                f"<td>{fmt_float(scenario['slower_than_realtime'])}x</td>"
                f"<td>{fmt_float(scenario['target_pct'])}%</td>"
                f"<td>{escape(scenario['termination_reason'])}</td>"
                "</tr>"
            )

    return f"""
    <section class="panel">
        <h2>Tracked Profiling Snapshots</h2>
        <div class="table-wrap history-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Report</th>
                        <th>Collected</th>
                        <th>Scenario</th>
                        <th>Median steps/s</th>
                        <th>Vs previous</th>
                        <th>Vs baseline</th>
                        <th>Wall s / sim s</th>
                        <th>% of target</th>
                        <th>Termination</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
    </section>
    """


def build_client_payload(
    reports: List[Dict[str, Any]],
    target_steps_per_second: float,
) -> Dict[str, Any]:
    return {
        "target_steps_per_second": target_steps_per_second,
        "default_metric": DEFAULT_METRIC,
        "metrics": PLOT_METRICS,
        "reports": [
            {
                "name": report["name"],
                "path": report["path"],
                "collected_at_label": report["collected_at_label"],
                "scenarios": report["scenarios"],
            }
            for report in reports
        ],
    }


def render_html(reports: List[Dict[str, Any]], target_steps_per_second: float) -> str:
    if not reports:
        raise ValueError("No valid profiling reports were found.")

    annotate_progress(reports)
    latest = reports[-1]
    all_scenarios = [scenario for report in reports for scenario in report["scenarios"]]
    best = max(all_scenarios, key=lambda scenario: scenario["steps_per_second"])
    best_gap = min(all_scenarios, key=lambda scenario: scenario["slower_than_realtime"])
    dominant_hotspots = [scenario for scenario in latest["scenarios"] if scenario["top_module_name"]]
    hotspot_summary = (
        f"{dominant_hotspots[0]['top_module_name']} dominates latest profile"
        if dominant_hotspots
        else "Latest profile has no module hotspot rows"
    )
    generated_at = escape(human_time(dt.datetime.now()))
    best_summary = (
        f"Best current result is {fmt_float(best['steps_per_second'])} steps/s on "
        f"{best['label']}, still {fmt_float(best_gap['slower_than_realtime'])}x slower than realtime."
    )
    system_context = latest["metadata"].get("system_context") or {}
    comparability = system_context.get("comparability", {})
    power_status = system_context.get("power_status", {})
    power_scheme = system_context.get("power_scheme", {})
    performance = system_context.get("performance_snapshot", {})
    power_bits = [
        str(comparability.get("power_source", "unknown")).upper(),
        power_scheme.get("name"),
    ]
    battery_percent = power_status.get("battery_percent")
    if battery_percent is not None:
        power_bits.append(f"{battery_percent}% battery")
    power_summary = ", ".join(bit for bit in power_bits if bit)
    policy_bits = []
    max_state = comparability.get("active_processor_max_state_pct")
    if max_state is not None:
        policy_bits.append(f"max state {int(max_state)}%")
    freq_pct = performance.get("percent_of_max_frequency")
    if freq_pct is not None:
        policy_bits.append(f"freq {fmt_float(float(freq_pct), 1)}%")
    perf_pct = performance.get("percent_processor_performance")
    if perf_pct is not None:
        policy_bits.append(f"perf {fmt_float(float(perf_pct), 1)}%")
    policy_summary = ", ".join(policy_bits) or "No processor policy snapshot recorded."
    notes = comparability.get("notes", [])
    warnings = comparability.get("warnings", [])
    first_note = str(notes[0]) if notes else ""
    if "Access denied" in first_note:
        first_note = "Thermal sensors are not accessible through the OS on this machine."
    if warnings:
        comparability_summary = "; ".join(str(item) for item in warnings)
    elif first_note:
        comparability_summary = f"No obvious power-policy cap. {first_note}"
    else:
        comparability_summary = "No obvious battery or power-policy limit was recorded."

    metric_cards = [
        render_metric_card(
            "Target",
            f"{fmt_int(int(target_steps_per_second))} steps/s",
            "1 s wall / 1 s simulated at dt = 1 us",
            "amber",
        ),
        render_metric_card(
            "Reports Tracked",
            fmt_int(len(reports)),
            "JSON snapshots folded into this dashboard",
            "teal",
        ),
        render_metric_card(
            "Best Throughput",
            f"{fmt_float(best['steps_per_second'])} steps/s",
            best["label"],
            "steel",
        ),
        render_metric_card(
            "Best Realtime Gap",
            f"{fmt_float(best_gap['slower_than_realtime'])}x slower",
            "Lower is better",
            "teal",
        ),
    ]
    data_json = json.dumps(
        build_client_payload(reports, target_steps_per_second),
        separators=(",", ":"),
    ).replace("</", "<\\/")
    script = """
    <script>
    (function () {
        const payload = JSON.parse(document.getElementById("dashboard-data").textContent);
        const reports = payload.reports || [];
        const latest = reports[reports.length - 1] || { scenarios: [] };
        const metricMap = new Map((payload.metrics || []).map((metric) => [metric.key, metric]));
        const palette = ["#486a7a", "#b07a4f", "#7a8f72", "#7e8fb0", "#8b7d6b", "#5c8f8a"];
        const state = {
            metric: payload.default_metric || "slower_than_realtime",
            yMin: null,
            yMax: null,
            activeModule: null,
        };

        const metricSelect = document.getElementById("metric-select");
        const yMinInput = document.getElementById("y-min-input");
        const yMaxInput = document.getElementById("y-max-input");
        const applyAxisButton = document.getElementById("apply-axis-button");
        const resetAxisButton = document.getElementById("reset-axis-button");
        const chartDescription = document.getElementById("chart-description");
        const plotNode = document.getElementById("performance-plot");
        const legendNode = document.getElementById("plot-legend");
        const moduleChipRow = document.getElementById("module-chip-row");
        const moduleDetail = document.getElementById("module-detail");

        function escapeHtml(value) {
            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#39;");
        }

        function formatNumber(value, digits) {
            return Number(value).toLocaleString(undefined, {
                minimumFractionDigits: digits,
                maximumFractionDigits: digits,
            });
        }

        function metricMeta(metricKey) {
            return metricMap.get(metricKey) || { digits: 2, suffix: "", guidance: "" };
        }

        function formatMetric(value, metricKey) {
            if (!Number.isFinite(value)) {
                return "n/a";
            }
            const metric = metricMeta(metricKey);
            return formatNumber(value, Number(metric.digits || 0)) + (metric.suffix || "");
        }

        function buildSeries() {
            const labels = Array.from(
                new Set(reports.flatMap((report) => (report.scenarios || []).map((scenario) => scenario.label)))
            );
            return labels
                .map((label) => {
                    const points = [];
                    reports.forEach((report, reportIndex) => {
                        const scenario = (report.scenarios || []).find((item) => item.label === label);
                        if (!scenario) {
                            return;
                        }
                        const value = Number(scenario[state.metric]);
                        if (!Number.isFinite(value)) {
                            return;
                        }
                        points.push({ xIndex: reportIndex, reportName: report.name, value: value });
                    });
                    return { label: label, points: points };
                })
                .filter((series) => series.points.length > 0);
        }

        function renderPlot() {
            const series = buildSeries();
            const values = series.flatMap((item) => item.points.map((point) => point.value));
            if (!values.length) {
                plotNode.innerHTML = "";
                chartDescription.textContent = "No data is available for the selected metric.";
                legendNode.innerHTML = "";
                return;
            }

            const width = 1040;
            const height = 380;
            const marginLeft = 92;
            const marginRight = 36;
            const marginTop = 28;
            const marginBottom = 82;
            const plotWidth = width - marginLeft - marginRight;
            const plotHeight = height - marginTop - marginBottom;
            const metric = metricMeta(state.metric);
            let minValue = Number.isFinite(state.yMin) ? state.yMin : Math.min(...values);
            let maxValue = Number.isFinite(state.yMax) ? state.yMax : Math.max(...values);

            if (maxValue <= minValue) {
                const bump = Math.abs(maxValue || 1.0) * 0.08 || 1.0;
                maxValue = minValue + bump;
            } else {
                const padding = (maxValue - minValue) * 0.08;
                if (!Number.isFinite(state.yMin)) {
                    minValue -= padding;
                }
                if (!Number.isFinite(state.yMax)) {
                    maxValue += padding;
                }
            }

            function xPos(index) {
                if (reports.length === 1) {
                    return marginLeft + plotWidth / 2;
                }
                return marginLeft + (plotWidth * index) / (reports.length - 1);
            }

            function yPos(value) {
                return marginTop + plotHeight - ((value - minValue) / (maxValue - minValue)) * plotHeight;
            }

            const gridLines = [];
            for (let index = 0; index < 5; index += 1) {
                const value = minValue + ((maxValue - minValue) * index) / 4;
                const y = yPos(value);
                gridLines.push(
                    '<line x1="' + marginLeft + '" y1="' + y.toFixed(2) + '" x2="' + (width - marginRight) + '" y2="' + y.toFixed(2) + '" class="grid-line" />'
                );
                gridLines.push(
                    '<text x="' + (marginLeft - 12) + '" y="' + (y + 5).toFixed(2) + '" class="axis-label" text-anchor="end">' +
                        escapeHtml(formatMetric(value, state.metric)) +
                        "</text>"
                );
            }

            const xLabels = [];
            reports.forEach((report, reportIndex) => {
                const x = xPos(reportIndex);
                xLabels.push(
                    '<line x1="' + x.toFixed(2) + '" y1="' + marginTop + '" x2="' + x.toFixed(2) + '" y2="' + (height - marginBottom) + '" class="grid-vertical" />'
                );
                xLabels.push(
                    '<text x="' + x.toFixed(2) + '" y="' + (height - marginBottom + 24) + '" class="axis-label x-label" text-anchor="end" transform="rotate(-28 ' +
                        x.toFixed(2) +
                        " " +
                        (height - marginBottom + 24) +
                        ')">' +
                        escapeHtml(report.name) +
                        "</text>"
                );
            });

            const lines = [];
            const legendItems = [];
            series.forEach((item, index) => {
                const color = palette[index % palette.length];
                const polyline = item.points
                    .map((point) => xPos(point.xIndex).toFixed(2) + "," + yPos(point.value).toFixed(2))
                    .join(" ");
                const circles = item.points
                    .map((point) => {
                        const title = item.label + " | " + point.reportName + " | " + formatMetric(point.value, state.metric);
                        return (
                            '<circle cx="' +
                            xPos(point.xIndex).toFixed(2) +
                            '" cy="' +
                            yPos(point.value).toFixed(2) +
                            '" r="4.8" fill="' +
                            color +
                            '"><title>' +
                            escapeHtml(title) +
                            "</title></circle>"
                        );
                    })
                    .join("");
                lines.push(
                    '<polyline points="' +
                    polyline +
                    '" fill="none" stroke="' +
                    color +
                    '" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />' +
                    circles
                );
                legendItems.push(
                    '<div class="legend-item"><span class="legend-swatch" style="background:' +
                    color +
                    '"></span>' +
                    escapeHtml(item.label) +
                    "</div>"
                );
            });

            plotNode.innerHTML =
                '<rect x="' +
                marginLeft +
                '" y="' +
                marginTop +
                '" width="' +
                plotWidth +
                '" height="' +
                plotHeight +
                '" class="plot-bg" />' +
                gridLines.join("") +
                xLabels.join("") +
                lines.join("") +
                '<text x="' + marginLeft + '" y="' + (marginTop - 8) + '" class="axis-title">' + escapeHtml(metric.label) + "</text>";
            legendNode.innerHTML = legendItems.join("");
            chartDescription.innerHTML =
                "<strong>" +
                escapeHtml(metric.label) +
                "</strong>. " +
                escapeHtml(metric.guidance || "") +
                " Current y-axis: " +
                escapeHtml(formatMetric(minValue, state.metric)) +
                " to " +
                escapeHtml(formatMetric(maxValue, state.metric)) +
                ".";
        }

        function latestModules() {
            const grouped = new Map();
            (latest.scenarios || []).forEach((scenario) => {
                (scenario.module_breakdown || []).forEach((module) => {
                    if (!grouped.has(module.key)) {
                        grouped.set(module.key, { key: module.key, label: module.label, wallSharePct: 0.0 });
                    }
                    const entry = grouped.get(module.key);
                    entry.wallSharePct = Math.max(entry.wallSharePct, Number(module.wall_share_pct || 0.0));
                });
            });
            return Array.from(grouped.values()).sort((left, right) => right.wallSharePct - left.wallSharePct);
        }

        function renderModuleSelector() {
            const modules = latestModules();
            if (!modules.length) {
                moduleChipRow.innerHTML = '<p class="empty-state">No module hotspot data is available in the latest snapshot.</p>';
                moduleDetail.innerHTML = "";
                return;
            }
            if (!state.activeModule || !modules.find((module) => module.key === state.activeModule)) {
                state.activeModule = modules[0].key;
            }
            moduleChipRow.innerHTML = modules
                .map((module) => {
                    const activeClass = module.key === state.activeModule ? " active" : "";
                    return (
                        '<button type="button" class="module-chip' +
                        activeClass +
                        '" data-module="' +
                        escapeHtml(module.key) +
                        '"><span>' +
                        escapeHtml(module.label) +
                        '</span><span class="module-chip-value">' +
                        escapeHtml(formatNumber(module.wallSharePct, 1)) +
                        "%</span></button>"
                    );
                })
                .join("");
            moduleChipRow.querySelectorAll(".module-chip").forEach((button) => {
                button.addEventListener("click", function () {
                    state.activeModule = button.dataset.module;
                    renderModuleSelector();
                    renderModuleDetail();
                });
            });
        }

        function renderModuleDetail() {
            if (!state.activeModule) {
                moduleDetail.innerHTML = "";
                return;
            }

            const summary = latestModules().find((module) => module.key === state.activeModule);
            const cards = (latest.scenarios || [])
                .map((scenario) => {
                    const module = (scenario.module_breakdown || []).find((entry) => entry.key === state.activeModule);
                    const subhotspots = ((scenario.module_subhotspots || {})[state.activeModule]) || [];
                    const details = module ? module.details || [] : [];
                    const components = module && module.components && module.components.length
                        ? module.components.join(", ")
                        : "No grouped module rows.";
                    const subhotspotTable = subhotspots.length
                        ? (
                            '<div class="table-wrap compact"><table><thead><tr><th>Sub-bucket</th><th>Wall share</th><th>Avg call us</th><th>Calls</th></tr></thead><tbody>' +
                            subhotspots.slice(0, 8).map((row) =>
                                "<tr>" +
                                "<td>" + escapeHtml(row.name) + "</td>" +
                                "<td>" + escapeHtml(formatNumber(Number(row.wall_share_pct || 0.0), 2)) + "%</td>" +
                                "<td>" + escapeHtml(formatNumber(Number(row.avg_call_us || 0.0), 3)) + "</td>" +
                                "<td>" + escapeHtml(String(row.calls || 0)) + "</td>" +
                                "</tr>"
                            ).join("") +
                            "</tbody></table></div>"
                        )
                        : '<p class="empty-state">No measured sub-buckets for this module in this scenario.</p>';
                    const detailTable = details.length
                        ? (
                            '<div class="table-wrap compact"><table><thead><tr><th>Function</th><th>Location</th><th>Cumulative s</th><th>Total s</th><th>Calls</th></tr></thead><tbody>' +
                            details.slice(0, 8).map((row) =>
                                "<tr>" +
                                "<td>" + escapeHtml(row.function) + "</td>" +
                                "<td>" + escapeHtml(row.location) + "</td>" +
                                "<td>" + escapeHtml(formatNumber(Number(row.cumulative_seconds || 0.0), 3)) + "</td>" +
                                "<td>" + escapeHtml(formatNumber(Number(row.total_seconds || 0.0), 3)) + "</td>" +
                                "<td>" + escapeHtml(String(row.total_calls || 0)) + "</td>" +
                                "</tr>"
                            ).join("") +
                            "</tbody></table></div>"
                        )
                        : '<p class="empty-state">No matching cProfile rows for this module in this scenario.</p>';
                    return (
                        '<div class="detail-card">' +
                        "<h3>" + escapeHtml(scenario.label) + "</h3>" +
                        '<div class="detail-meta">' +
                        "<div>Module wall share: <strong>" + escapeHtml(module ? formatNumber(module.wall_share_pct, 1) + "%" : "n/a") + "</strong></div>" +
                        "<div>Grouped rows: " + escapeHtml(components) + "</div>" +
                        "</div>" +
                        '<h4>Measured sub-buckets</h4>' +
                        subhotspotTable +
                        '<h4>Matching cProfile rows</h4>' +
                        detailTable +
                        "</div>"
                    );
                })
                .join("");

            moduleDetail.innerHTML =
                '<div class="detail-summary"><h3>' +
                escapeHtml(summary ? summary.label : state.activeModule) +
                "</h3><p>Highest wall share in the latest snapshot: <strong>" +
                escapeHtml(summary ? formatNumber(summary.wallSharePct, 1) + "%" : "n/a") +
                "</strong>. The cards below expose the heaviest matching cProfile functions and lines for each scenario.</p></div>" +
                '<div class="detail-grid">' +
                cards +
                "</div>";
        }

        metricSelect.addEventListener("change", function () {
            state.metric = metricSelect.value;
            renderPlot();
        });
        applyAxisButton.addEventListener("click", function () {
            const parsedMin = Number(yMinInput.value);
            const parsedMax = Number(yMaxInput.value);
            state.yMin = Number.isFinite(parsedMin) ? parsedMin : null;
            state.yMax = Number.isFinite(parsedMax) ? parsedMax : null;
            renderPlot();
        });
        resetAxisButton.addEventListener("click", function () {
            yMinInput.value = "";
            yMaxInput.value = "";
            state.yMin = null;
            state.yMax = null;
            renderPlot();
        });

        renderPlot();
        renderModuleSelector();
        renderModuleDetail();
    })();
    </script>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SPARC Performance Dashboard</title>
    <style>
        :root {{
            --page: #f4efe8;
            --panel: #fffdfa;
            --panel-alt: #faf6ef;
            --line: #ddd4c7;
            --line-strong: #cdbfac;
            --text: #20282d;
            --muted: #6a706e;
            --steel: #70889a;
            --teal: #486a7a;
            --amber: #b07a4f;
            --sage: #7a8f72;
            --shadow: 0 14px 28px rgba(34, 40, 45, 0.06);
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: "Aptos", "Segoe UI", "Trebuchet MS", sans-serif;
            color: var(--text);
            background: var(--page);
        }}
        .shell {{ max-width: 1180px; margin: 0 auto; padding: 40px 28px 72px; }}
        .masthead {{
            display: grid;
            grid-template-columns: minmax(0, 2.1fr) minmax(280px, 0.9fr);
            gap: 24px;
            align-items: start;
        }}
        .eyebrow {{
            color: var(--teal);
            font-size: 12px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        h1 {{
            margin: 8px 0 14px;
            font-size: clamp(32px, 4vw, 48px);
            line-height: 1.02;
            letter-spacing: -0.02em;
        }}
        .lead {{
            max-width: 760px;
            margin: 0;
            color: var(--muted);
            font-size: 17px;
            line-height: 1.6;
        }}
        .meta-panel {{
            padding: 18px 20px;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: var(--panel);
            box-shadow: var(--shadow);
        }}
        .meta-list {{
            display: grid;
            gap: 14px;
            margin: 0;
        }}
        .meta-item dt {{
            margin: 0 0 4px;
            color: var(--muted);
            font-size: 11px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .meta-item dd {{
            margin: 0;
            font-size: 14px;
            line-height: 1.5;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin: 22px 0 18px;
        }}
        .metric-card {{
            padding: 16px 18px 18px;
            border-radius: 16px;
            border: 1px solid var(--line);
            background: var(--panel);
            min-height: 0;
            box-shadow: var(--shadow);
        }}
        .metric-card.teal {{ border-top: 4px solid var(--teal); }}
        .metric-card.amber {{ border-top: 4px solid var(--amber); }}
        .metric-card.steel {{ border-top: 4px solid var(--steel); }}
        .metric-label {{ color: var(--muted); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; }}
        .metric-value {{ margin-top: 10px; font-size: 27px; line-height: 1.12; font-weight: 600; }}
        .metric-subtitle {{ margin-top: 10px; color: var(--muted); font-size: 14px; line-height: 1.45; }}
        .panel {{
            margin-top: 18px;
            padding: 22px 24px 24px;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: var(--panel);
            box-shadow: var(--shadow);
        }}
        h2 {{ margin: 0 0 10px; font-size: 22px; letter-spacing: -0.01em; }}
        h3 {{ margin: 0 0 14px; font-size: 18px; }}
        h4 {{ margin: 16px 0 10px; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }}
        .section-note {{ margin: 0 0 16px; color: var(--muted); line-height: 1.55; font-size: 15px; }}
        .section-note.subtle {{ margin-bottom: 12px; font-size: 13px; }}
        .section-head {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 12px;
        }}
        .chart-controls {{
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 10px;
            align-items: end;
            min-width: min(100%, 620px);
        }}
        .control-field {{
            display: grid;
            gap: 6px;
            color: var(--muted);
            font-size: 11px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .control-field select,
        .control-field input,
        .secondary-button {{
            min-height: 40px;
            padding: 0 12px;
            border-radius: 12px;
            border: 1px solid var(--line);
            background: #fffdfa;
            color: var(--text);
            font: inherit;
        }}
        .secondary-button {{
            cursor: pointer;
        }}
        .table-wrap {{
            overflow: auto;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: #ffffff;
        }}
        table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
        th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #ece4d8; vertical-align: top; }}
        th {{ color: var(--muted); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; background: var(--panel-alt); }}
        td {{ color: var(--text); font-size: 14px; line-height: 1.45; }}
        tr:last-child td {{ border-bottom: none; }}
        .subpanel-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }}
        .subpanel {{ padding: 18px; border-radius: 14px; background: var(--panel-alt); border: 1px solid var(--line); }}
        .hotspot-list {{ display: grid; gap: 10px; }}
        .hotspot-row {{ display: grid; grid-template-columns: 96px 1fr 56px; gap: 10px; align-items: center; }}
        .hotspot-name {{ font-size: 14px; color: var(--text); }}
        .hotspot-track {{ position: relative; height: 8px; overflow: hidden; border-radius: 999px; background: #e7e1d7; }}
        .hotspot-fill {{ position: absolute; inset: 0 auto 0 0; border-radius: inherit; background: var(--teal); }}
        .hotspot-value {{ font-family: "Consolas", monospace; font-size: 13px; }}
        .compact table {{ min-width: 0; }}
        .trend-panel {{ padding-bottom: 18px; }}
        .trend-svg {{ width: 100%; height: auto; border-radius: 14px; background: var(--panel-alt); }}
        .plot-bg {{ fill: var(--panel-alt); }}
        .grid-line {{ stroke: #ddd4c7; stroke-dasharray: 2 6; }}
        .grid-vertical {{ stroke: #eee6da; stroke-dasharray: 2 8; }}
        .axis-label {{ fill: var(--muted); font-size: 11px; font-family: "Consolas", monospace; }}
        .axis-title {{ fill: var(--muted); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }}
        .x-label {{ font-size: 11px; }}
        .trend-legend {{ display: flex; flex-wrap: wrap; gap: 10px 16px; color: var(--muted); font-size: 13px; margin-top: 10px; }}
        .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
        .legend-swatch {{ width: 10px; height: 10px; border-radius: 999px; }}
        .module-layout {{ display: grid; grid-template-columns: minmax(220px, 260px) minmax(0, 1fr); gap: 16px; align-items: start; }}
        .module-rail {{ display: grid; gap: 10px; }}
        .module-chip {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            width: 100%;
            padding: 12px 14px;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: #fffdfa;
            color: var(--muted);
            text-align: left;
            cursor: pointer;
        }}
        .module-chip.active {{
            border-color: var(--teal);
            background: #f4f8fa;
            color: var(--text);
        }}
        .module-chip-value {{ font-family: "Consolas", monospace; font-size: 12px; }}
        .module-detail {{ display: grid; gap: 14px; }}
        .detail-summary,
        .detail-card {{
            padding: 18px;
            border-radius: 14px;
            background: var(--panel-alt);
            border: 1px solid var(--line);
        }}
        .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }}
        .detail-meta {{ margin: 10px 0 14px; display: grid; gap: 6px; color: var(--muted); font-size: 13px; line-height: 1.5; }}
        .snapshot-badge {{
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid var(--line);
            background: #fffdfa;
            color: var(--muted);
            font-size: 13px;
            white-space: nowrap;
        }}
        .empty-state {{ color: var(--muted); font-style: italic; }}
        .history-wrap {{ max-height: 320px; }}
        .footer-note {{ margin-top: 16px; color: var(--muted); font-size: 13px; line-height: 1.6; }}
        strong {{ color: var(--text); }}
        @media (max-width: 900px) {{
            .shell {{ padding: 26px 18px 56px; }}
            .masthead {{ grid-template-columns: 1fr; }}
            .metric-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .section-head {{ flex-direction: column; align-items: stretch; }}
            .chart-controls {{ grid-template-columns: repeat(2, minmax(0, 1fr)); min-width: 0; }}
            .module-layout {{ grid-template-columns: 1fr; }}
            .module-rail {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
        }}
        @media (max-width: 560px) {{
            .metric-grid {{ grid-template-columns: 1fr; }}
            h1 {{ font-size: 32px; }}
            .chart-controls {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="shell">
        <header class="masthead">
            <div>
                <div class="eyebrow">Conservative Performance Program</div>
                <h1>SPARC Realtime Optimization Dashboard</h1>
                <p class="lead">
                    Repeatable profiling snapshots for the local simulation code on this PC.
                    The benchmark stays conservative by design: improve throughput without
                    changing exported data, simulation quality, or physics behavior. {escape(best_summary)}
                </p>
            </div>
            <aside class="meta-panel">
                <dl class="meta-list">
                    <div class="meta-item">
                        <dt>Generated</dt>
                        <dd>{generated_at}</dd>
                    </div>
                    <div class="meta-item">
                        <dt>Latest snapshot</dt>
                        <dd>{escape(latest['name'])}</dd>
                    </div>
                    <div class="meta-item">
                        <dt>Primary bottleneck</dt>
                        <dd>{escape(hotspot_summary)}</dd>
                    </div>
                    <div class="meta-item">
                        <dt>Power context</dt>
                        <dd>{escape(power_summary or 'Unavailable')}</dd>
                    </div>
                    <div class="meta-item">
                        <dt>Processor policy</dt>
                        <dd>{escape(policy_summary)}</dd>
                    </div>
                    <div class="meta-item">
                        <dt>Comparability</dt>
                        <dd>{escape(comparability_summary)}</dd>
                    </div>
                </dl>
            </aside>
        </header>
        <div class="metric-grid">
            {''.join(metric_cards)}
        </div>
        {render_plot_panel()}
        {render_verification_panel(latest)}
        {render_latest_table(latest)}
        {render_module_panel(latest)}
        {render_history_table(reports)}

        <p class="footer-note">
            Latest report path: <strong>{escape(latest['path'])}</strong>.
            Report files are discovered from the profiling JSON schema only, so unrelated JSON artifacts are ignored.
        </p>
    </div>
    <script id="dashboard-data" type="application/json">{data_json}</script>
    {script}
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    reports: List[Dict[str, Any]] = []
    for path in collect_input_paths(args.input_glob):
        report = load_report(path, args.target_steps_per_second)
        if report is not None:
            reports.append(report)

    if not reports:
        raise SystemExit("No valid profiling reports were found for the requested inputs.")

    output_path = pathlib.Path(args.output)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        render_html(reports, args.target_steps_per_second),
        encoding="utf-8",
    )
    print(f"Wrote {display_path(output_path)} from {len(reports)} profiling report(s).")


if __name__ == "__main__":
    main()
