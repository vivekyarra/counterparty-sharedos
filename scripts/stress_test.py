from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

import httpx

from counterparty.app import create_app
from counterparty.storage import CounterpartyStore

TOKEN = "stress-token-0123456789abcdef0123456789"


def payload(i: int) -> tuple[str, dict]:
    kind = i % 5
    if kind == 0:
        return "/v1/verify-delivery", {
            "delivery_id": f"pass-{i}",
            "provider_id": f"svc-{i % 17}",
            "task": "return a bounded JSON value",
            "output": {"value": i % 10, "confidence": 0.9},
            "expected_schema": {
                "type": "object",
                "properties": {"value": {"type": "integer"}, "confidence": {"type": "number"}},
                "required": ["value", "confidence"],
                "additionalProperties": False,
            },
            "assertions": [{"path": "/value", "op": "gte", "value": 0}],
        }
    if kind == 1:
        return "/v1/verify-delivery", {
            "delivery_id": f"fail-{i}",
            "provider_id": f"svc-{i % 17}",
            "task": "must return value 7",
            "output": {"value": -1},
            "expected_schema": {"type": "object", "properties": {"value": {"const": 7}}, "required": ["value"]},
            "assertions": [{"path": "/value", "op": "eq", "value": 7}],
        }
    if kind == 2:
        return "/v1/verify-delivery", {
            "delivery_id": f"inc-{i}",
            "provider_id": f"svc-{i % 17}",
            "task": "unknown contract",
            "output": {"text": "no schema supplied"},
        }
    if kind == 3:
        return "/v1/trust-snapshot", {"service_id": f"svc-{i % 17}", "task_type": "general"}
    return "/v1/best-execution", {
        "task": "pick a service",
        "budget_credits": 30,
        "mode": "explore",
        "candidates": [
            {"service_id": f"svc-{(i+j) % 17}", "price_credits": 3 + j, "task_fit": 0.5 + (j * 0.1)}
            for j in range(4)
        ],
    }


async def main(total: int, concurrency: int, output: Path | None) -> int:
    with tempfile.TemporaryDirectory() as td:
        store = CounterpartyStore(Path(td) / "stress.sqlite3")
        app = create_app(store, internal_token=TOKEN, require_internal_auth=True)
        transport = httpx.ASGITransport(app=app)
        limits = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        statuses: list[int] = []

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://counterparty.local",
            headers={"x-counterparty-internal-token": TOKEN},
            timeout=20,
        ) as client:
            async def one(i: int):
                async with limits:
                    path, body = payload(i)
                    started = time.perf_counter()
                    response = await client.post(path, json=body)
                    latencies.append((time.perf_counter() - started) * 1000)
                    statuses.append(response.status_code)
                    if response.status_code != 200:
                        raise RuntimeError(f"request {i} returned {response.status_code}: {response.text[:300]}")

            started = time.perf_counter()
            await asyncio.gather(*(one(i) for i in range(total)))
            wall = time.perf_counter() - started

            # Replay storm: 100 concurrent attempts at one already-observed delivery.
            replay_body = {
                "delivery_id": "replay-target",
                "provider_id": "replay-farmer",
                "task": "x",
                "output": {"v": 1},
                "expected_schema": {"type": "object", "properties": {"v": {"const": 1}}, "required": ["v"]},
                "assertions": [{"path": "/v", "op": "eq", "value": 1}],
            }
            replay_results = await asyncio.gather(*(
                client.post("/v1/verify-delivery", json=replay_body) for _ in range(100)
            ))
            updates = sum(1 for r in replay_results if r.json().get("reputation_updated"))
            snapshot = (await client.post("/v1/trust-snapshot", json={"service_id": "replay-farmer"})).json()

        latencies_sorted = sorted(latencies)
        def pct(p: float) -> float:
            idx = min(len(latencies_sorted) - 1, int((len(latencies_sorted)-1) * p))
            return latencies_sorted[idx]

        report = {
            "requests": total,
            "concurrency": concurrency,
            "wall_seconds": round(wall, 3),
            "requests_per_second": round(total / wall, 2),
            "http_non_200": sum(1 for s in statuses if s != 200),
            "latency_ms": {
                "p50": round(pct(.50), 3),
                "p95": round(pct(.95), 3),
                "p99": round(pct(.99), 3),
                "max": round(max(latencies), 3),
                "mean": round(statistics.mean(latencies), 3),
            },
            "audit_chain_valid": store.verify_audit(),
            "audit_events": store.audit_head()["count"],
            "replay_storm": {
                "attempts": 100,
                "reputation_updates": updates,
                "observations": snapshot["observations"],
                "passed": updates == 1 and snapshot["observations"] == 1,
            },
        }
        rendered = json.dumps(report, indent=2, sort_keys=True)
        print(rendered)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n")
        return 0 if report["audit_chain_valid"] and report["http_non_200"] == 0 and report["replay_storm"]["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=int(os.getenv("STRESS_REQUESTS", "2500")))
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("STRESS_CONCURRENCY", "64")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.requests, args.concurrency, args.output)))
