from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEAT_PREFIX = "i_"


def command(name: str) -> str:
    if os.name == "nt":
        return f"{name}.cmd"
    return name


def sharednet_reach_args(npx: str) -> list[str]:
    """Build the current SharedNet reach command.

    `reach` does not accept `--as`. The launcher sets SHAREDNET_SEAT before
    invoking it, so the CLI selects the exact Arena seat from trusted process
    environment instead of an unsupported command-line option.
    """
    return [npx, "-y", "sharednet@latest", "reach", "public", "--json"]


def run_json(args: list[str], env: dict[str, str]) -> dict:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object from {' '.join(args)}")
    return value


def wait_health(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok") is True and payload.get("version") == "0.3.0":
                    return
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Counterparty backend did not become healthy: {last_error}")


def validate_environment() -> dict[str, str]:
    env = os.environ.copy()
    token = env.get("COUNTERPARTY_INTERNAL_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("COUNTERPARTY_INTERNAL_TOKEN must be at least 32 characters")
    payee = env.get("SHAREDNET_PAYEE_ADDRESS", "").strip()
    if len(payee) != 12 or payee[:2] not in {"p_", "a_", "i_"} or not payee[2:].isalnum():
        raise RuntimeError("SHAREDNET_PAYEE_ADDRESS must be a real p_, a_, or i_ SharedNet address")
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen Counterparty Arena provider loop")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument(
        "--redeem-hack100",
        action="store_true",
        help="Redeem the organizer HACK100 credit code before starting the service loop",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Optional SharedNet watch bound for QA. Omit during the Arena.",
    )
    args = parser.parse_args()
    if not 1 <= args.backend_port <= 65535:
        raise RuntimeError("--backend-port must be between 1 and 65535")
    if args.max_runs is not None and args.max_runs < 1:
        raise RuntimeError("--max-runs must be at least 1")

    env = validate_environment()
    npx = command("npx")

    who = run_json([npx, "-y", "sharednet@latest", "whoami", "--json"], env)
    account = who.get("account")
    seat = who.get("seat")
    if not isinstance(account, dict):
        raise TypeError("SharedNet is not logged in on this machine. Run `npx -y sharednet@latest login` first.")
    if not isinstance(seat, dict):
        raise TypeError("This checkout is not seated in a SharedNet Room. Join the QA/Arena Room first.")
    member_id = str(seat.get("member_id") or "")
    room_id = str(seat.get("room_id") or "")
    if len(member_id) != 12 or not member_id.startswith(SEAT_PREFIX) or not member_id[2:].isalnum():
        raise RuntimeError(f"SharedNet did not select one valid i_ seat: {member_id!r}")
    if not room_id.startswith("rom_"):
        raise RuntimeError(f"SharedNet seat has no valid Room: {room_id!r}")

    env["SHAREDNET_SEAT"] = member_id
    env["SHAREDNET_NODE_ID"] = member_id
    env["SHAREDNET_ROOM_ID"] = room_id
    backend_url = f"http://127.0.0.1:{args.backend_port}"
    env["COUNTERPARTY_BACKEND_URL"] = backend_url

    # An Arena product must be addressable by other Room participants. The
    # current SharedNet `reach` verb selects the seat via SHAREDNET_SEAT and
    # intentionally has no --as option.
    subprocess.run(
        sharednet_reach_args(npx),
        cwd=ROOT,
        env=env,
        check=True,
    )

    if args.redeem_hack100:
        redeemed = run_json(
            [npx, "-y", "sharednet@latest", "redeem", "HACK100", "--as", member_id, "--json"],
            env,
        )
        print(json.dumps({"arena_float": redeemed}, sort_keys=True), flush=True)

    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "counterparty.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.backend_port),
        ],
        cwd=ROOT,
        env=env,
    )

    def stop_backend(*_: object) -> None:
        if backend.poll() is None:
            backend.terminate()

    signal.signal(signal.SIGINT, stop_backend)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_backend)

    try:
        wait_health(backend_url)
        print(
            json.dumps(
                {
                    "counterparty": "ready",
                    "sharednet_seat": member_id,
                    "room_id": room_id,
                    "backend": backend_url,
                    "purpose": "counterparty.verify-and-route-sharednet-services",
                },
                sort_keys=True,
            ),
            flush=True,
        )

        service_command = f'{command("npm")} --prefix sharedos run --silent arena:serve'
        watch_args = [
            npx,
            "-y",
            "sharednet@latest",
            "watch",
            "--on",
            "message",
            "--run",
            service_command,
            "--reply",
            "--as",
            member_id,
        ]
        if args.max_runs is not None:
            watch_args.extend(["--max-runs", str(args.max_runs)])
        watch = subprocess.run(watch_args, cwd=ROOT, env=env, check=False)
        return watch.returncode
    finally:
        stop_backend()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
            backend.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
