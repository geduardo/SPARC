from __future__ import annotations

import argparse
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import pathlib
import threading
import urllib.parse
import webbrowser

from wedm import EnvironmentConfig, WireEDMEnv

from .control import RuntimeControlState, RuntimeController
from .server import RealtimeSessionServer
from .session import MAX_SIM_US_PER_WALL_SECOND


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class QuietStaticHandler(SimpleHTTPRequestHandler):
    """Static-file handler that suppresses per-request logs."""

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local SPARC realtime mode entrypoint: one websocket-backed "
            "simulation session plus one static dashboard server."
        )
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for both websocket and HTTP servers (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8000,
        help="HTTP port for the dashboard server (default: 8000, use 0 for auto).",
    )
    parser.add_argument(
        "--ws-port",
        type=int,
        default=8765,
        help="WebSocket port for the realtime session (default: 8765, use 0 for auto).",
    )
    parser.add_argument(
        "--slowdown-factor",
        type=float,
        default=None,
        help=(
            "Requested slowdown factor in wall-seconds per simulated second. "
            "Defaults to 100.0 when neither pace nor slowdown is provided."
        ),
    )
    parser.add_argument(
        "--pace-us-per-s",
        type=float,
        default=None,
        help=(
            "Requested simulation pace in simulated microseconds per wall second. "
            f"The backend ceiling is {MAX_SIM_US_PER_WALL_SECOND:.0f} us/s."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Deterministic reset seed for the demo environment (default: 123).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Optional JSON file to load EnvironmentConfig from before applying CLI overrides.",
    )
    parser.add_argument(
        "--mechanics-control-mode",
        choices=("position", "velocity"),
        default="position",
        help="Mechanics control mode for the environment (default: position).",
    )
    parser.add_argument(
        "--workpiece-height",
        type=float,
        default=None,
        help="Override EnvironmentConfig.workpiece_height in mm.",
    )
    parser.add_argument(
        "--wire-diameter",
        type=float,
        default=None,
        help="Override EnvironmentConfig.wire_diameter in mm.",
    )
    parser.add_argument(
        "--wire-material",
        type=str,
        default=None,
        help="Override EnvironmentConfig.wire_material.",
    )
    parser.add_argument(
        "--servo-interval",
        type=int,
        default=None,
        help="Override EnvironmentConfig.servo_interval in microseconds.",
    )
    parser.add_argument(
        "--initial-gap",
        type=float,
        default=None,
        help="Override EnvironmentConfig.initial_gap in micrometers.",
    )
    parser.add_argument(
        "--target-cutting-distance",
        type=float,
        default=None,
        help="Override EnvironmentConfig.target_cutting_distance in micrometers.",
    )
    parser.add_argument(
        "--run-seconds",
        type=float,
        default=None,
        help="Auto-stop after this many wall-clock seconds. Omit to run until Ctrl+C.",
    )
    parser.add_argument(
        "--max-control-steps",
        type=int,
        default=None,
        help="Optional cap on published control steps before the session stops.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the dashboard URL in the default browser after startup.",
    )
    return parser


def resolve_browser_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def resolve_requested_slowdown_factor(args: argparse.Namespace) -> float:
    if args.pace_us_per_s is not None and args.slowdown_factor is not None:
        raise ValueError("use either --pace-us-per-s or --slowdown-factor, not both")

    if args.pace_us_per_s is not None:
        pace_us_per_s = float(args.pace_us_per_s)
        if pace_us_per_s <= 0.0:
            raise ValueError("--pace-us-per-s must be positive")
        return 1_000_000.0 / pace_us_per_s

    if args.slowdown_factor is not None:
        slowdown_factor = float(args.slowdown_factor)
        if slowdown_factor <= 0.0:
            raise ValueError("--slowdown-factor must be positive")
        return slowdown_factor

    return 100.0


def build_environment_config(args: argparse.Namespace) -> EnvironmentConfig:
    if args.config:
        config = EnvironmentConfig.from_json(args.config)
    else:
        config = EnvironmentConfig()

    overrides = {}
    for field_name in (
        "workpiece_height",
        "wire_diameter",
        "wire_material",
        "servo_interval",
        "initial_gap",
        "target_cutting_distance",
    ):
        override_value = getattr(args, field_name, None)
        if override_value is not None:
            overrides[field_name] = override_value

    if overrides:
        config = EnvironmentConfig.from_dict({**config.to_dict(), **overrides})

    config.validate()
    if config.dt != 1:
        raise ValueError("realtime mode requires dt=1 us; dt is fixed and not configurable")
    return config


def build_demo_env(
    seed: int,
    *,
    config: EnvironmentConfig,
    mechanics_control_mode: str,
) -> WireEDMEnv:
    env = WireEDMEnv(
        config=config,
        mechanics_control_mode=mechanics_control_mode,
    )
    env.reset(seed=seed)
    return env


def build_demo_controller() -> RuntimeController:
    return RuntimeController(
        RuntimeControlState(
            controller_type="gap",
            target_gap=5.0,
            generator_voltage=80.0,
            current_mode=7,
            on_time=2.0,
            off_time=33.0,
        )
    )


def start_dashboard_server(
    host: str, port: int
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    visualization_dir = REPO_ROOT / "visualization"
    handler = partial(QuietStaticHandler, directory=str(visualization_dir))
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(
        target=httpd.serve_forever,
        name="wedm-realtime-dashboard-http",
        daemon=True,
    )
    thread.start()
    return httpd, thread


async def run(args: argparse.Namespace) -> None:
    requested_slowdown_factor = resolve_requested_slowdown_factor(args)
    env_config = build_environment_config(args)
    env = build_demo_env(
        args.seed,
        config=env_config,
        mechanics_control_mode=args.mechanics_control_mode,
    )
    controller = build_demo_controller()

    http_server, http_thread = start_dashboard_server(args.host, args.http_port)
    http_port = int(http_server.server_address[1])

    realtime_server = RealtimeSessionServer(
        env,
        controller,
        host=args.host,
        port=args.ws_port,
        slowdown_factor=requested_slowdown_factor,
        max_control_steps=args.max_control_steps,
    )
    await realtime_server.start()

    browser_host = resolve_browser_host(args.host)
    websocket_url = f"ws://{browser_host}:{realtime_server.bound_port}"
    dashboard_url = (
        f"http://{browser_host}:{http_port}/dashboard.html"
        f"?live={urllib.parse.quote(websocket_url, safe='')}"
    )
    requested_pace_us_per_s = 1_000_000.0 / requested_slowdown_factor

    print("Realtime mode is running.")
    print(f"Dashboard: {dashboard_url}")
    print(f"WebSocket: {websocket_url}")
    print(
        "Requested pace: "
        f"{requested_pace_us_per_s:.0f} us/s "
        f"(slowdown factor {requested_slowdown_factor:.3f})"
    )
    print(f"Backend pace ceiling: {MAX_SIM_US_PER_WALL_SECOND:.0f} us/s")
    print(
        "Environment: "
        f"workpiece_height={env.config.workpiece_height} mm, "
        f"wire_diameter={env.config.wire_diameter} mm, "
        f"wire_material={env.config.wire_material}, "
        f"initial_gap={env.config.initial_gap} um, "
        f"target_cutting_distance={env.config.target_cutting_distance} um, "
        f"servo_interval={env.config.servo_interval} us, "
        f"mechanics_control_mode={env.mechanics_control_mode}"
    )
    if args.run_seconds is None:
        print("Press Ctrl+C to stop.")
    else:
        print(f"Auto-stopping after {args.run_seconds:.2f} seconds.")

    if args.open_browser:
        webbrowser.open(dashboard_url)

    try:
        if args.run_seconds is None:
            await asyncio.Event().wait()
        else:
            await asyncio.sleep(max(0.0, args.run_seconds))
    finally:
        await realtime_server.stop()
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=5.0)


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except ValueError as exc:
        parser.error(str(exc))
