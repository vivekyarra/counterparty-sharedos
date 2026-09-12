from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from counterparty.app import create_app
from counterparty.storage import CounterpartyStore

TOKEN = "arena-hardening-token-0123456789abcdef0123456789"


def make_client(db: Path) -> TestClient:
    app = create_app(CounterpartyStore(db), internal_token=TOKEN, require_internal_auth=True)
    return TestClient(app, headers={"x-counterparty-internal-token": TOKEN})


def good_probe(probe_id: str, provider_id: str, nonce: str) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "provider_id": provider_id,
        "nonce": nonce,
        "output": {"counterparty_probe_id": nonce, "ack": True},
        "latency_ms": 25,
    }


def verified_delivery(delivery_id: str, provider_id: str) -> dict[str, object]:
    return {
        "delivery_id": delivery_id,
        "provider_id": provider_id,
        "task": "return ok=true",
        "task_type": "general",
        "output": {"ok": True},
        "expected_schema": {
            "type": "object",
            "properties": {"ok": {"const": True}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "assertions": [{"path": "/ok", "op": "eq", "value": True}],
    }


def test_persistence_and_replay_survive_restart(tmp_path: Path):
    db = tmp_path / "restart.sqlite3"
    c1 = make_client(db)
    nonce = "restart-nonce-12345"
    probe_body = good_probe("restart-probe", "seller-restart", nonce)
    assert c1.post("/v1/probe-observation", json=probe_body).json()["protocol_reputation_updated"] is True
    assert c1.post("/v1/verify-delivery", json=verified_delivery("restart-delivery", "seller-restart")).json()["reputation_updated"] is True
    before = c1.post("/v1/trust-snapshot", json={"service_id": "seller-restart"}).json()
    assert before["evidence_tier"] == "VERIFIED"
    assert before["observations"] == 1
    assert before["protocol_evidence"]["observations"] == 1
    c1.close()

    c2 = make_client(db)
    after = c2.post("/v1/trust-snapshot", json={"service_id": "seller-restart"}).json()
    assert after["evidence_tier"] == "VERIFIED"
    assert after["observations"] == 1
    assert after["protocol_evidence"]["observations"] == 1

    replay_probe = c2.post("/v1/probe-observation", json=probe_body).json()
    replay_delivery = c2.post("/v1/verify-delivery", json=verified_delivery("restart-delivery", "seller-restart")).json()
    assert replay_probe["protocol_reputation_updated"] is False
    assert replay_probe["replay_suppressed"] is True
    assert replay_delivery["reputation_updated"] is False
    assert replay_delivery["replay_suppressed"] is True
    assert c2.get("/v1/audit").json()["valid"] is True


def test_concurrent_cold_start_swarm_never_routes_rejected_seller(tmp_path: Path):
    db = tmp_path / "swarm.sqlite3"
    store = CounterpartyStore(db)
    app = create_app(store, internal_token=TOKEN, require_internal_auth=True)

    async def run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://counterparty.local",
            headers={"x-counterparty-internal-token": TOKEN},
            timeout=20,
        ) as c:
            async def probe(i: int):
                provider = f"seller-{i:02d}"
                nonce = f"swarm-nonce-{i:08d}"
                output_nonce = nonce if i % 2 == 0 else f"wrong-{i:08d}"
                return await c.post(
                    "/v1/probe-observation",
                    json={
                        "probe_id": f"swarm-probe-{i}",
                        "provider_id": provider,
                        "nonce": nonce,
                        "output": {"counterparty_probe_id": output_nonce, "ack": True},
                        "latency_ms": 10 + i,
                    },
                )

            responses = await asyncio.gather(*(probe(i) for i in range(24)))
            assert all(r.status_code == 200 for r in responses)
            states = [r.json()["state"] for r in responses]
            assert states.count("PASS") == 12
            assert states.count("FAIL") == 12

            candidates = [
                {"service_id": f"seller-{i:02d}", "price_credits": 1 if i % 2 else 9, "task_fit": 0.9}
                for i in range(24)
            ]
            result = (await c.post(
                "/v1/best-execution",
                json={"task": "swarm route", "budget_credits": 20, "mode": "safe", "candidates": candidates},
            )).json()
            assert result["state"] == "PASS"
            assert int(result["recommended"].split("-")[-1]) % 2 == 0
            rejected = [row for row in result["ranked"] if row["evidence_tier"] == "REJECTED"]
            assert len(rejected) == 12
            assert all(int(row["service_id"].split("-")[-1]) % 2 == 1 for row in rejected)

    asyncio.run(run())
    assert store.verify_audit() is True


def test_concurrent_storage_contention_keeps_audit_linear_and_exactly_once(tmp_path: Path):
    db = tmp_path / "contention.sqlite3"
    store = CounterpartyStore(db)

    def record(i: int) -> bool:
        event, updated = store.record_verification(
            delivery_id=f"contention-{i}",
            service_id="seller-contention",
            task_type="general",
            outcome="PASS",
            evidence_hash=f"{i:064x}",
            latency_ms=i,
            audit_payload={"delivery_id": f"contention-{i}", "state": "PASS"},
            reputation_eligible=True,
        )
        assert len(event["hash"]) == 64
        return updated

    with ThreadPoolExecutor(max_workers=24) as pool:
        updates = list(pool.map(record, range(96)))
    assert all(updates)
    rep, _ = store.reputation("seller-contention")
    assert rep.observations == 96
    assert store.audit_head()["count"] == 96
    assert store.verify_audit() is True

    def replay(_: int) -> bool:
        _, updated = store.record_verification(
            delivery_id="contention-0",
            service_id="seller-contention",
            task_type="general",
            outcome="PASS",
            evidence_hash=f"{0:064x}",
            latency_ms=0,
            audit_payload={"delivery_id": "contention-0", "state": "PASS"},
            reputation_eligible=True,
        )
        return updated

    with ThreadPoolExecutor(max_workers=24) as pool:
        replay_updates = list(pool.map(replay, range(48)))
    assert sum(replay_updates) == 0
    rep_after, _ = store.reputation("seller-contention")
    assert rep_after.observations == 96
    assert store.verify_audit() is True


def test_ingress_fails_closed_and_body_limit_is_enforced(tmp_path: Path):
    db = tmp_path / "limits.sqlite3"
    app = create_app(CounterpartyStore(db), internal_token=TOKEN, require_internal_auth=True)
    c = TestClient(app)
    unauthorized = c.post("/v1/trust-snapshot", json={"service_id": "x"})
    assert unauthorized.status_code == 401

    authorized = TestClient(app, headers={"x-counterparty-internal-token": TOKEN})
    oversized = {"service_id": "x" * 300000}
    response = authorized.post("/v1/trust-snapshot", json=oversized)
    assert response.status_code == 413
