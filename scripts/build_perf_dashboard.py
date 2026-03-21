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
        top_module = None
        if module_hotspots:
            top_module = max(
                module_hotspots,
                key=lambda row: float(row.get("wall_share_pct", 0.0)),
            )

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
                "cprofile_hotspots": scenario.get("cprofile_hotspots") or [],
                "top_module_name": top_module.get("name") if top_module else None,
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
        "metadata": data["metadata"],
        "action": data.get("action", {}),
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


def build_trend_svg(reports: List[Dict[str, Any]]) -> str:
    points_by_label: Dict[str, List[Dict[str, Any]]] = {}
    for report_index, report in enumerate(reports):
        for scenario in report["scenarios"]:
            points_by_label.setdefault(scenario["label"], []).append(
                {
                    "x_index": report_index,
                    "slower_than_realtime": scenario["slower_than_realtime"],
                }
            )

    if not points_by_label:
        return '<p class="empty-state">No trend data available.</p>'

    width = 1040
    height = 360
    margin_left = 86
    margin_right = 36
    margin_top = 30
    margin_bottom = 72
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    all_values = [
        point["slower_than_realtime"]
        for points in points_by_label.values()
        for point in points
        if math.isfinite(point["slower_than_realtime"])
    ]
    max_value = max(all_values, default=1.0)
    max_value = max(max_value, 1.0)
    y_cap = max(math.ceil(max_value * 1.15), 2)

    def x_pos(index: int) -> float:
        if len(reports) == 1:
            return margin_left + plot_width / 2
        return margin_left + (plot_width * index / (len(reports) - 1))

    def y_pos(value: float) -> float:
        return margin_top + plot_height - (value / y_cap) * plot_height

    grid_lines = []
    for fraction in range(0, 5):
        value = y_cap * fraction / 4
        y = y_pos(value)
        grid_lines.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" '
            f'y2="{y:.2f}" class="grid-line" />'
        )
        grid_lines.append(
            f'<text x="{margin_left - 12}" y="{y + 5:.2f}" class="axis-label" '
            f'text-anchor="end">{escape(fmt_float(value, 1))}x</text>'
        )

    report_labels = []
    for index, report in enumerate(reports):
        x = x_pos(index)
        report_labels.append(
            f'<line x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{height - margin_bottom}" '
            f'class="grid-vertical" />'
        )
        report_labels.append(
            f'<text x="{x:.2f}" y="{height - margin_bottom + 24}" class="axis-label x-label" '
            f'text-anchor="end" transform="rotate(-28 {x:.2f} {height - margin_bottom + 24})">'
            f"{escape(report['name'])}</text>"
        )

    colors = ["#ff7b54", "#28c2b7", "#f2c14e", "#6ab04c", "#f76f8e", "#4d96ff"]
    series_markup = []
    legend_markup = []
    for index, label in enumerate(sorted(points_by_label)):
        color = colors[index % len(colors)]
        points = points_by_label[label]
        polyline = " ".join(
            f"{x_pos(point['x_index']):.2f},{y_pos(point['slower_than_realtime']):.2f}"
            for point in points
        )
        circles = "".join(
            f'<circle cx="{x_pos(point["x_index"]):.2f}" cy="{y_pos(point["slower_than_realtime"]):.2f}" '
            f'r="4.8" fill="{color}" />'
            for point in points
        )
        series_markup.append(
            f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3.5" '
            f'stroke-linecap="round" stroke-linejoin="round" />{circles}'
        )
        legend_markup.append(
            f'<div class="legend-item"><span class="legend-swatch" style="background:{color}"></span>'
            f"{escape(label)}</div>"
        )

    return f"""
    <div class="trend-card">
        <div class="section-kicker">Progress Toward Realtime</div>
        <h2>Wall Seconds Needed for 1 Simulated Second</h2>
        <p class="section-note">Lower is better. The conservative target is <strong>1.0x</strong>.</p>
        <svg viewBox="0 0 {width} {height}" class="trend-svg" role="img" aria-label="Performance trend chart">
            <rect x="{margin_left}" y="{margin_top}" width="{plot_width}" height="{plot_height}" class="plot-bg" />
            {''.join(grid_lines)}
            {''.join(report_labels)}
            {' '.join(series_markup)}
            <text x="{margin_left}" y="{margin_top - 8}" class="axis-title">x slower than realtime</text>
        </svg>
        <div class="trend-legend">{''.join(legend_markup)}</div>
    </div>
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
        <div class="section-kicker">Latest Snapshot</div>
        <h2>{escape(report['name'])}</h2>
        <p class="section-note">
            Collected {escape(human_time(report['collected_at']))}. Steps={fmt_int(int(metadata.get('steps', 0)))},
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
        <div class="section-kicker">Primary Bottlenecks</div>
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
        <div class="section-kicker">Function Hotspots</div>
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
                f"<td>{escape(human_time(report['collected_at']))}</td>"
                f"<td>{escape(scenario['label'])}</td>"
                f"<td>{fmt_float(scenario['steps_per_second'])}</td>"
                f"<td>{fmt_float(scenario['slower_than_realtime'])}x</td>"
                f"<td>{fmt_float(scenario['target_pct'])}%</td>"
                f"<td>{escape(scenario['termination_reason'])}</td>"
                "</tr>"
            )

    return f"""
    <section class="panel">
        <div class="section-kicker">History</div>
        <h2>Tracked Profiling Snapshots</h2>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Report</th>
                        <th>Collected</th>
                        <th>Scenario</th>
                        <th>Median steps/s</th>
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


def render_html(reports: List[Dict[str, Any]], target_steps_per_second: float) -> str:
    if not reports:
        raise ValueError("No valid profiling reports were found.")

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
        render_metric_card(
            "Latest Hotspot",
            hotspot_summary,
            latest["name"],
            "amber",
        ),
    ]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SPARC Performance Dashboard</title>
    <style>
        :root {{
            --bg: #0d1117;
            --panel: rgba(14, 23, 33, 0.84);
            --panel-border: rgba(255, 255, 255, 0.08);
            --text: #e7edf4;
            --muted: #94a7b8;
            --steel: #6ea8d9;
            --teal: #28c2b7;
            --amber: #ff7b54;
            --gold: #f2c14e;
            --shadow: 0 20px 50px rgba(0, 0, 0, 0.32);
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: "Bahnschrift", "Trebuchet MS", sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at top left, rgba(40, 194, 183, 0.16), transparent 34%),
                radial-gradient(circle at top right, rgba(255, 123, 84, 0.14), transparent 28%),
                linear-gradient(160deg, #091018 0%, #111a25 52%, #0b1016 100%);
        }}
        .shell {{ max-width: 1380px; margin: 0 auto; padding: 32px 24px 64px; }}
        .hero {{
            padding: 30px 32px;
            border: 1px solid var(--panel-border);
            border-radius: 28px;
            background:
                linear-gradient(140deg, rgba(110, 168, 217, 0.12), rgba(40, 194, 183, 0.08) 40%, rgba(255, 123, 84, 0.10) 100%),
                rgba(10, 16, 24, 0.84);
            box-shadow: var(--shadow);
        }}
        .eyebrow {{
            display: inline-flex; gap: 10px; align-items: center; padding: 6px 12px; border-radius: 999px;
            background: rgba(255, 255, 255, 0.05); color: var(--gold); font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase;
        }}
        h1 {{ margin: 16px 0 12px; font-size: clamp(34px, 5vw, 62px); line-height: 0.98; letter-spacing: 0.02em; }}
        .hero p {{ max-width: 980px; color: var(--muted); font-size: 17px; line-height: 1.55; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 24px; }}
        .metric-card {{
            padding: 18px 18px 20px; border-radius: 22px; border: 1px solid rgba(255, 255, 255, 0.06);
            background: rgba(255, 255, 255, 0.04); min-height: 160px;
        }}
        .metric-card.teal {{ background: linear-gradient(155deg, rgba(40, 194, 183, 0.18), rgba(255, 255, 255, 0.04)); }}
        .metric-card.amber {{ background: linear-gradient(155deg, rgba(255, 123, 84, 0.18), rgba(255, 255, 255, 0.04)); }}
        .metric-card.steel {{ background: linear-gradient(155deg, rgba(110, 168, 217, 0.18), rgba(255, 255, 255, 0.04)); }}
        .metric-label {{ color: var(--muted); font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }}
        .metric-value {{ margin-top: 16px; font-size: 29px; line-height: 1.14; font-weight: 700; }}
        .metric-subtitle {{ margin-top: 14px; color: var(--muted); font-size: 14px; line-height: 1.45; }}
        .panel {{ margin-top: 24px; padding: 26px 28px 28px; border: 1px solid var(--panel-border); border-radius: 26px; background: var(--panel); box-shadow: var(--shadow); }}
        .section-kicker {{ color: var(--gold); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; }}
        h2 {{ margin: 10px 0 10px; font-size: 28px; }}
        h3 {{ margin: 0 0 16px; font-size: 20px; }}
        .section-note {{ margin: 0 0 18px; color: var(--muted); line-height: 1.55; }}
        .table-wrap {{ overflow-x: auto; border-radius: 18px; border: 1px solid rgba(255, 255, 255, 0.05); background: rgba(255, 255, 255, 0.025); }}
        table {{ width: 100%; border-collapse: collapse; min-width: 860px; }}
        th, td {{ padding: 14px 16px; text-align: left; border-bottom: 1px solid rgba(255, 255, 255, 0.05); vertical-align: top; }}
        th {{ color: var(--gold); font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; background: rgba(255, 255, 255, 0.03); }}
        td {{ color: var(--text); font-size: 15px; }}
        tr:last-child td {{ border-bottom: none; }}
        .subpanel-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; }}
        .subpanel {{ padding: 20px; border-radius: 22px; background: rgba(255, 255, 255, 0.035); border: 1px solid rgba(255, 255, 255, 0.06); }}
        .hotspot-list {{ display: grid; gap: 12px; }}
        .hotspot-row {{ display: grid; grid-template-columns: 110px 1fr 66px; gap: 10px; align-items: center; }}
        .hotspot-name {{ font-size: 14px; color: var(--muted); }}
        .hotspot-track {{ position: relative; height: 11px; overflow: hidden; border-radius: 999px; background: rgba(255, 255, 255, 0.08); }}
        .hotspot-fill {{ position: absolute; inset: 0 auto 0 0; border-radius: inherit; background: linear-gradient(90deg, var(--amber), var(--gold)); }}
        .hotspot-value {{ font-family: "Consolas", monospace; font-size: 13px; }}
        .compact table {{ min-width: 0; }}
        .trend-card {{ display: grid; gap: 10px; }}
        .trend-svg {{ width: 100%; height: auto; border-radius: 20px; background: rgba(255, 255, 255, 0.02); }}
        .plot-bg {{ fill: rgba(255, 255, 255, 0.02); }}
        .grid-line {{ stroke: rgba(255, 255, 255, 0.10); stroke-dasharray: 4 6; }}
        .grid-vertical {{ stroke: rgba(255, 255, 255, 0.05); stroke-dasharray: 3 8; }}
        .axis-label {{ fill: var(--muted); font-size: 12px; font-family: "Consolas", monospace; }}
        .axis-title {{ fill: var(--gold); font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; }}
        .x-label {{ font-size: 11px; }}
        .trend-legend {{ display: flex; flex-wrap: wrap; gap: 12px 18px; color: var(--muted); font-size: 14px; }}
        .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
        .legend-swatch {{ width: 12px; height: 12px; border-radius: 999px; }}
        .empty-state {{ color: var(--muted); font-style: italic; }}
        .footer-note {{ margin-top: 26px; color: var(--muted); font-size: 14px; line-height: 1.55; }}
        strong {{ color: var(--text); }}
    </style>
</head>
<body>
    <div class="shell">
        <section class="hero">
            <div class="eyebrow">Conservative Performance Program</div>
            <h1>SPARC Realtime Optimization Dashboard</h1>
            <p>
                This dashboard folds together repeatable profiling snapshots for the local simulation code.
                The current program is conservative by design: improve throughput on this PC without dropping
                physics outputs, exported data, or simulation quality. Generated {escape(human_time(dt.datetime.now()))}
                from {fmt_int(len(reports))} compatible profile reports.
            </p>
            <div class="metric-grid">
                {''.join(metric_cards)}
            </div>
        </section>

        {build_trend_svg(reports)}
        {render_latest_table(latest)}
        {render_hotspot_bars(latest)}
        {render_cprofile_tables(latest)}
        {render_history_table(reports)}

        <p class="footer-note">
            Latest report path: <strong>{escape(latest['path'])}</strong>.
            Report files are discovered from the profiling JSON schema only, so unrelated JSON artifacts are ignored.
        </p>
    </div>
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
