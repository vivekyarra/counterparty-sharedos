from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from counterparty.app import create_app
from counterparty.storage import CounterpartyStore

TOKEN = "arena-rehearsal-token-0123456789abcdef0123456789"
MAX_PROMOTION_DELIVERIES = 32


def main(output: Path | None = None) -> int:
    with tempfile.TemporaryDirectory() as td:
        store = CounterpartyStore(Path(td) / "rehearsal.sqlite3")
        c = TestClient(create_app(store, internal_token=TOKEN, require_internal_auth=True), headers={"x-counterparty-internal-token": TOKEN})

        tried_products = ["research-agent", "code-review-agent", "translation-agent"]
        disagreements = {
            "research-agent": "citation syntax is not independent verification",
            "code-review-agent": "claimed confidence exceeds the supplied deterministic evidence",
            "translation-agent": "delivery contract did not specify terminology preservation",
        }
        ranking = ["research-agent", "translation-agent", "code-review-agent"]

        alpha_nonce = "rehearsal-alpha-nonce"
        alpha_probe = c.post("/v1/probe-observation", json={
            "probe_id": "rehearsal-alpha", "provider_id": "seller-alpha", "nonce": alpha_nonce,
            "output": {"counterparty_probe_id": alpha_nonce, "ack": True}, "latency_ms": 80,
        }).json()
        beta_probe = c.post("/v1/probe-observation", json={
            "probe_id": "rehearsal-beta", "provider_id": "seller-beta", "nonce": "rehearsal-beta-nonce",
            "output": {"counterparty_probe_id": "wrong-beta-nonce", "ack": True}, "latency_ms": 20,
        }).json()

        first_route = c.post("/v1/best-execution", json={
            "task": "buy a bounded service", "budget_credits": 20, "mode": "safe",
            "candidates": [
                {"service_id": "seller-alpha", "price_credits": 8, "task_fit": 0.9},
                {"service_id": "seller-beta", "price_credits": 1, "task_fit": 1.0},
                {"service_id": "seller-gamma", "price_credits": 3, "task_fit": 0.95},
            ],
        }).json()

        deliveries = 0
        snapshot = c.post("/v1/trust-snapshot", json={"service_id": "seller-alpha"}).json()
        while snapshot["verdict"] != "BUY" and deliveries < MAX_PROMOTION_DELIVERIES:
            result = c.post("/v1/verify-delivery", json={
                "delivery_id": f"rehearsal-delivery-{deliveries}",
                "provider_id": "seller-alpha", "task": "return ok=true", "task_type": "general",
                "output": {"ok": True},
                "expected_schema": {"type": "object", "properties": {"ok": {"const": True}}, "required": ["ok"], "additionalProperties": False},
                "assertions": [{"path": "/ok", "op": "eq", "value": True}],
            }).json()
            if result["state"] != "PASS" or not result["reputation_updated"]:
                raise RuntimeError("verification failed during rehearsal")
            deliveries += 1
            snapshot = c.post("/v1/trust-snapshot", json={"service_id": "seller-alpha"}).json()

        final_route = c.post("/v1/best-execution", json={
            "task": "buy a bounded service", "budget_credits": 20, "mode": "safe",
            "candidates": [
                {"service_id": "seller-alpha", "price_credits": 8, "task_fit": 0.9},
                {"service_id": "seller-beta", "price_credits": 1, "task_fit": 1.0},
                {"service_id": "seller-gamma", "price_credits": 3, "task_fit": 0.95},
            ],
        }).json()

        round2_spend = [
            {"product": "research-agent", "credits": 30},
            {"product": "code-review-agent", "credits": 25},
            {"product": "translation-agent", "credits": 25},
        ]
        spent = sum(x["credits"] for x in round2_spend)
        distinct = len({x["product"] for x in round2_spend})

        checks = {
            "round1_three_products_tried": len(tried_products) >= 3,
            "round1_specific_disagreement_each": all(p in disagreements and disagreements[p] for p in tried_products),
            "round1_ranking_submitted": len(ranking) == len(tried_products),
            "alpha_canary_passed": alpha_probe["state"] == "PASS",
            "beta_canary_rejected": beta_probe["state"] == "FAIL",
            "safe_first_route_is_alpha": first_route.get("recommended") == "seller-alpha" and first_route.get("evidence_tier") == "PROVISIONAL",
            "verified_promotion_reached_buy": snapshot["verdict"] == "BUY" and snapshot["evidence_tier"] == "VERIFIED",
            "safe_final_route_is_verified_alpha": final_route.get("recommended") == "seller-alpha" and final_route.get("evidence_tier") == "VERIFIED",
            "round2_spend_at_least_80": spent >= 80,
            "round2_spend_across_three_products": distinct >= 3,
            "audit_chain_valid": store.verify_audit(),
        }
        report = {
            "ready": all(checks.values()),
            "checks": checks,
            "promotion_deliveries": deliveries,
            "round2_simulated_external_spend": {"credits": spent, "distinct_products": distinct, "purchases": round2_spend},
            "first_route": {k: first_route.get(k) for k in ("state", "recommended", "evidence_tier", "recommendation_strength")},
            "final_route": {k: final_route.get(k) for k in ("state", "recommended", "evidence_tier", "recommendation_strength")},
            "audit_events": store.audit_head()["count"],
            "note": "Autonomous Arena obligations are simulated locally; this is not evidence of real SharedNet participation or real credit spend.",
        }
        rendered = json.dumps(report, indent=2, sort_keys=True)
        print(rendered)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n")
        return 0 if report["ready"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deterministic two-round Arena rehearsal")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.output))
