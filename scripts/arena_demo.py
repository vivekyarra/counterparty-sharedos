from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from counterparty.app import create_app
from counterparty.storage import CounterpartyStore

TOKEN = "arena-demo-token-0123456789abcdef0123456789"


def run_demo() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="counterparty-demo-") as tmp:
        store = CounterpartyStore(Path(tmp) / "demo.sqlite3")
        client = TestClient(
            create_app(store, internal_token=TOKEN, require_internal_auth=True),
            headers={"x-counterparty-internal-token": TOKEN},
        )

        initial_a = client.post("/v1/trust-snapshot", json={"service_id": "seller-alpha"}).json()
        initial_b = client.post("/v1/trust-snapshot", json={"service_id": "seller-beta"}).json()
        assert initial_a["verdict"] == "UNPROVEN"
        assert initial_b["verdict"] == "UNPROVEN"

        nonce_a = "arena-alpha-12345678"
        canary_a = client.post(
            "/v1/probe-observation",
            json={
                "probe_id": "arena-probe-alpha",
                "provider_id": "seller-alpha",
                "nonce": nonce_a,
                "output": {"counterparty_probe_id": nonce_a, "ack": True},
                "latency_ms": 84,
            },
        ).json()
        assert canary_a["state"] == "PASS"

        nonce_b = "arena-beta-12345678"
        canary_b = client.post(
            "/v1/probe-observation",
            json={
                "probe_id": "arena-probe-beta",
                "provider_id": "seller-beta",
                "nonce": nonce_b,
                "output": {"counterparty_probe_id": "wrong-nonce", "ack": True},
                "latency_ms": 61,
            },
        ).json()
        assert canary_b["state"] == "FAIL"

        after_canary_a = client.post("/v1/trust-snapshot", json={"service_id": "seller-alpha"}).json()
        after_canary_b = client.post("/v1/trust-snapshot", json={"service_id": "seller-beta"}).json()
        assert after_canary_a["verdict"] == "TRY_SMALL"
        assert after_canary_a["evidence_tier"] == "PROVISIONAL"
        assert after_canary_b["verdict"] == "AVOID"

        provisional_route = client.post(
            "/v1/best-execution",
            json={
                "task": "research a time-sensitive fact",
                "budget_credits": 20,
                "mode": "safe",
                "candidates": [
                    {"service_id": "seller-alpha", "price_credits": 8, "task_fit": 0.9},
                    {"service_id": "seller-beta", "price_credits": 6, "task_fit": 0.9},
                    {"service_id": "seller-gamma", "price_credits": 3, "task_fit": 1.0},
                ],
            },
        ).json()
        assert provisional_route["state"] == "PASS"
        assert provisional_route["recommended"] == "seller-alpha"
        assert provisional_route["evidence_tier"] == "PROVISIONAL"

        schema = {
            "type": "object",
            "properties": {"ok": {"const": True}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        assertions = [{"path": "/ok", "op": "eq", "value": True}]
        for index in range(8):
            delivery = client.post(
                "/v1/verify-delivery",
                json={
                    "delivery_id": f"arena-paid-alpha-{index}",
                    "provider_id": "seller-alpha",
                    "task": "bounded paid task",
                    "task_type": "general",
                    "output": {"ok": True},
                    "expected_schema": schema,
                    "assertions": assertions,
                },
            ).json()
            assert delivery["state"] == "PASS"
            assert delivery["reputation_updated"] is True

        mature_a = client.post("/v1/trust-snapshot", json={"service_id": "seller-alpha"}).json()
        assert mature_a["verdict"] == "BUY"
        assert mature_a["evidence_tier"] == "VERIFIED"

        verified_route = client.post(
            "/v1/best-execution",
            json={
                "task": "bounded paid task",
                "budget_credits": 20,
                "mode": "safe",
                "candidates": [
                    {"service_id": "seller-alpha", "price_credits": 8, "task_fit": 0.9},
                    {"service_id": "seller-gamma", "price_credits": 3, "task_fit": 1.0},
                ],
            },
        ).json()
        assert verified_route["recommended"] == "seller-alpha"
        assert verified_route["evidence_tier"] == "VERIFIED"
        assert store.verify_audit()

        return {
            "product": "Counterparty",
            "story": "UNPROVEN -> active canary -> TRY_SMALL -> verified deliveries -> BUY",
            "before": {
                "seller_alpha": initial_a["verdict"],
                "seller_beta": initial_b["verdict"],
            },
            "fresh_canary": {
                "seller_alpha": canary_a["state"],
                "seller_beta": canary_b["state"],
            },
            "after_canary": {
                "seller_alpha": after_canary_a["verdict"],
                "seller_beta": after_canary_b["verdict"],
                "safe_route": provisional_route["recommended"],
                "route_tier": provisional_route["evidence_tier"],
            },
            "after_verified_market_history": {
                "seller_alpha": mature_a["verdict"],
                "verified_observations": mature_a["observations"],
                "safe_route": verified_route["recommended"],
                "route_tier": verified_route["evidence_tier"],
            },
            "audit": store.audit_head(),
            "audit_valid": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Counterparty's one-command Arena flywheel demo")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = parser.parse_args()
    result = run_demo()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    print("\nCOUNTERPARTY — LIVE MARKET FLYWHEEL DEMO")
    print("=" * 48)
    print("1  seller-alpha: UNPROVEN")
    print("2  bounded canary: PASS")
    print("3  seller-alpha: TRY_SMALL  [PROVISIONAL]")
    print("4  Safe Best Execution routes the first small spend to seller-alpha")
    print("5  verified paid deliveries compound task reputation")
    print("6  seller-alpha: BUY        [VERIFIED]")
    print("7  Safe Best Execution keeps routing on stronger evidence")
    print(f"8  audit chain valid: {result['audit_valid']}  head={result['audit']}")
    print("\nBefore your agent spends a credit, Counterparty proves who can do the job.\n")


if __name__ == "__main__":
    main()
