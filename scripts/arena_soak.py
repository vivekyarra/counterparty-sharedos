from __future__ import annotations

import argparse
import asyncio
import json
import random
import tempfile
import time
from pathlib import Path

import httpx

from counterparty.app import create_app
from counterparty.storage import CounterpartyStore

TOKEN = "arena-soak-token-0123456789abcdef0123456789"


def make_payload(i: int, rng: random.Random) -> tuple[str, dict[str, object]]:
    provider = f"soak-seller-{i % 29:02d}"
    kind = i % 4
    if kind == 0:
        nonce = f"soak-nonce-{i:012d}"
        return "/v1/probe-observation", {
            "probe_id": f"soak-probe-{i}", "provider_id": provider, "nonce": nonce,
            "output": {"counterparty_probe_id": nonce, "ack": True}, "latency_ms": rng.randint(5, 200),
        }
    if kind == 1:
        return "/v1/verify-delivery", {
            "delivery_id": f"soak-delivery-{i}", "provider_id": provider, "task": "return ok=true",
            "output": {"ok": True},
            "expected_schema": {"type": "object", "properties": {"ok": {"const": True}}, "required": ["ok"]},
            "assertions": [{"path": "/ok", "op": "eq", "value": True}],
        }
    if kind == 2:
        return "/v1/trust-snapshot", {"service_id": provider, "task_type": "general"}
    candidates = [
        {"service_id": f"soak-seller-{(i+j) % 29:02d}", "price_credits": 3 + (j % 8), "task_fit": round(0.55 + (j % 4) * 0.1, 2)}
        for j in range(6)
    ]
    return "/v1/best-execution", {"task": "soak routing", "budget_credits": 25, "mode": "safe", "candidates": candidates}


async def segment(db: Path, start: int, count: int, concurrency: int, rng: random.Random) -> tuple[list[float], list[int]]:
    store = CounterpartyStore(db)
    app = create_app(store, internal_token=TOKEN, require_internal_auth=True)
    transport = httpx.ASGITransport(app=app)
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: list[int] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://counterparty.local", headers={"x-counterparty-internal-token": TOKEN}, timeout=20) as c:
        async def one(i: int) -> None:
            async with sem:
                path, body = make_payload(i, rng)
                t0 = time.perf_counter()
                r = await c.post(path, json=body)
                latencies.append((time.perf_counter() - t0) * 1000)
                statuses.append(r.status_code)
                if r.status_code != 200:
                    raise RuntimeError(f"{path} returned {r.status_code}: {r.text[:200]}")
        await asyncio.gather(*(one(i) for i in range(start, start + count)))
    if not store.verify_audit():
        raise RuntimeError("audit chain invalid after restart segment")
    return latencies, statuses


async def main(events: int, concurrency: int, virtual_seconds: int, restarts: int, wall_seconds: int, output: Path | None) -> int:
    rng = random.Random(20260912)
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "arena-soak.sqlite3"
        all_latencies: list[float] = []
        all_statuses: list[int] = []
        began = time.perf_counter()
        completed = 0
        cycle = 0
        target_segments = max(1, restarts + 1)
        while True:
            if wall_seconds > 0:
                if time.perf_counter() - began >= wall_seconds and completed > 0:
                    break
                batch = min(250, max(1, events))
            else:
                if completed >= events:
                    break
                remaining = events - completed
                batch = min(remaining, max(1, (events + target_segments - 1) // target_segments))
            lat, status = await segment(db, completed, batch, concurrency, rng)
            all_latencies.extend(lat)
            all_statuses.extend(status)
            completed += batch
            cycle += 1
            if wall_seconds == 0 and cycle >= target_segments and completed < events:
                target_segments = 10**9

        wall = time.perf_counter() - began
        store = CounterpartyStore(db)
        ordered = sorted(all_latencies)

        def pct(p: float) -> float:
            idx = min(len(ordered) - 1, int((len(ordered) - 1) * p))
            return ordered[idx]

        report = {
            "mode": "wall-clock" if wall_seconds > 0 else "accelerated-two-hour-equivalent",
            "virtual_seconds": virtual_seconds,
            "wall_target_seconds": wall_seconds,
            "events": completed,
            "concurrency": concurrency,
            "restart_segments": cycle,
            "wall_seconds": round(wall, 3),
            "http_non_200": sum(1 for s in all_statuses if s != 200),
            "latency_ms": {"p50": round(pct(.50), 3), "p95": round(pct(.95), 3), "p99": round(pct(.99), 3), "max": round(max(all_latencies), 3)},
            "audit_chain_valid": store.verify_audit(),
            "audit_events": store.audit_head()["count"],
            "ready": bool(all_statuses) and all(s == 200 for s in all_statuses) and store.verify_audit(),
            "note": "Accelerated mode schedules a two-hour-equivalent event volume without claiming two hours of wall-clock uptime. Use --wall-seconds 7200 for a literal two-hour soak outside CI.",
        }
        rendered = json.dumps(report, indent=2, sort_keys=True)
        print(rendered)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n")
        return 0 if report["ready"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Counterparty Arena accelerated or literal wall-clock soak")
    p.add_argument("--events", type=int, default=2400)
    p.add_argument("--concurrency", type=int, default=48)
    p.add_argument("--virtual-seconds", type=int, default=7200)
    p.add_argument("--restarts", type=int, default=7)
    p.add_argument("--wall-seconds", type=int, default=0)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.events, a.concurrency, a.virtual_seconds, a.restarts, a.wall_seconds, a.output)))
