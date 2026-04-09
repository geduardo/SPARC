#!/usr/bin/env python3
"""Start a local realtime smoke session plus dashboard server."""

from __future__ import annotations

import argparse
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import pathlib
import sys
import threading
import urllib.parse
import webbrowser


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wedm import WireEDMEnv
from wedm.realtime import RuntimeControlState, RuntimeController
from wedm.realtime.server import RealtimeSessionServer


class QuietStaticHandler(SimpleHTTPRequestHandler):
    """Static-file handler that suppresses per-request logs."""

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a local realtime smoke setup: one websocket simulation session "
            "plus one static dashboard server."
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
        default=100.0,
        help="Requested session slowdown factor (default: 100.0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Deterministic reset seed for the smoke environment (default: 123).",
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


def build_smoke_env(seed: int) -> WireEDMEnv:
    env = WireEDMEnv()
    env.reset(seed=seed)
    env.state.workpiece_position = 70.0
    env.state.wire_position = 10.0
    env.state.target_position = 5_000.0
    env.state.voltage = 40.0
    return env


def build_smoke_controller() -> RuntimeController:
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


def start_dashboard_server(host: str, port: int) -> tuple[ThreadingHTTPServer, threading.Thread]:
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
    env = build_smoke_env(args.seed)
    controller = build_smoke_controller()

    http_server, http_thread = start_dashboard_server(args.host, args.http_port)
    http_port = int(http_server.server_address[1])

    realtime_server = RealtimeSessionServer(
        env,
        controller,
        host=args.host,
        port=args.ws_port,
        slowdown_factor=args.slowdown_factor,
        max_control_steps=args.max_control_steps,
    )
    await realtime_server.start()

    browser_host = resolve_browser_host(args.host)
    websocket_url = f"ws://{browser_host}:{realtime_server.bound_port}"
    dashboard_url = (
        f"http://{browser_host}:{http_port}/dashboard.html"
        f"?live={urllib.parse.quote(websocket_url, safe='')}"
    )

    print("Realtime smoke setup is running.")
    print(f"Dashboard: {dashboard_url}")
    print(f"WebSocket: {websocket_url}")
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


if __name__ == "__main__":
    main()
