from pathlib import Path

from fastapi.testclient import TestClient

from counterparty.app import create_app
from counterparty.storage import CounterpartyStore

TOKEN = "flywheel-test-token-0123456789abcdef012345"
MAX_PROMOTION_DELIVERIES = 32


def client(tmp_path: Path) -> TestClient:
    app = create_app(
        CounterpartyStore(tmp_path / "flywheel.sqlite3"),
        internal_token=TOKEN,
        require_internal_auth=True,
    )
    return TestClient(app, headers={"x-counterparty-internal-token": TOKEN})


def good_probe(probe_id: str, provider_id: str, nonce: str) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "provider_id": provider_id,
        "nonce": nonce,
        "output": {"counterparty_probe_id": nonce, "ack": True},
        "latency_ms": 120,
    }


def test_canary_breaks_cold_start_without_pretending_task_history(tmp_path):
    c = client(tmp_path)
    before = c.post("/v1/trust-snapshot", json={"service_id": "seller-a"}).json()
    assert before["verdict"] == "UNPROVEN"
    assert before["evidence_tier"] == "UNPROVEN"

    nonce = "nonce-12345678"
    proof = c.post(
        "/v1/probe-observation",
        json=good_probe("probe-1", "seller-a", nonce),
    ).json()
    assert proof["state"] == "PASS"
    assert proof["protocol_reputation_updated"] is True

    after = c.post("/v1/trust-snapshot", json={"service_id": "seller-a"}).json()
    assert after["verdict"] == "TRY_SMALL"
    assert after["action"] == "BUY_SMALL_THEN_VERIFY"
    assert after["evidence_tier"] == "PROVISIONAL"
    assert after["observations"] == 0
    assert after["protocol_evidence"]["observations"] == 1


def test_safe_best_execution_can_route_after_one_protocol_canary(tmp_path):
    c = client(tmp_path)
    nonce = "nonce-abcdefgh"
    assert c.post(
        "/v1/probe-observation",
        json=good_probe("probe-route-1", "canary-passed", nonce),
    ).json()["state"] == "PASS"

    result = c.post(
        "/v1/best-execution",
        json={
            "task": "research a current fact",
            "budget_credits": 20,
            "mode": "safe",
            "candidates": [
                {"service_id": "canary-passed", "price_credits": 8, "task_fit": 0.9},
                {"service_id": "totally-unknown", "price_credits": 3, "task_fit": 0.9},
            ],
        },
    ).json()
    assert result["state"] == "PASS"
    assert result["recommended"] == "canary-passed"
    assert result["evidence_tier"] == "PROVISIONAL"
    assert result["recommendation_strength"] == "PROVISIONAL"
    assert result["next_action"]["service"] == "verify_delivery"


def test_unproven_safe_routing_upsells_active_trust_snapshot(tmp_path):
    c = client(tmp_path)
    result = c.post(
        "/v1/best-execution",
        json={
            "task": "translate this",
            "budget_credits": 20,
            "mode": "safe",
            "candidates": [
                {"service_id": "unknown-a", "price_credits": 5, "task_fit": 0.9},
                {"service_id": "unknown-b", "price_credits": 6, "task_fit": 0.8},
            ],
        },
    ).json()
    assert result["state"] == "INCONCLUSIVE"
    assert result["next_action"]["service"] == "trust_snapshot"
    assert result["next_action"]["price_credits"] == 4
    assert set(result["next_action"]["targets"]) == {"unknown-a", "unknown-b"}


def test_probe_replay_is_suppressed_and_wrong_nonce_is_a_failure(tmp_path):
    c = client(tmp_path)
    nonce = "nonce-replay-123"
    payload = good_probe("probe-replay", "seller-a", nonce)
    first = c.post("/v1/probe-observation", json=payload).json()
    second = c.post("/v1/probe-observation", json=payload).json()
    assert first["protocol_reputation_updated"] is True
    assert second["protocol_reputation_updated"] is False
    assert second["replay_suppressed"] is True

    bad = c.post(
        "/v1/probe-observation",
        json={
            "probe_id": "probe-wrong-nonce",
            "provider_id": "seller-b",
            "nonce": "nonce-expected-1",
            "output": {"counterparty_probe_id": "nonce-forged-2", "ack": True},
            "latency_ms": 20,
        },
    ).json()
    assert bad["state"] == "FAIL"
    snapshot = c.post("/v1/trust-snapshot", json={"service_id": "seller-b"}).json()
    assert snapshot["verdict"] == "AVOID"
    assert snapshot["evidence_tier"] == "REJECTED"
    assert snapshot["protocol_evidence"]["failures"] == 1

    routed = c.post(
        "/v1/best-execution",
        json={
            "task": "do a bounded task",
            "budget_credits": 20,
            "mode": "safe",
            "candidates": [
                {"service_id": "seller-b", "price_credits": 1, "task_fit": 1.0},
                {"service_id": "unknown-c", "price_credits": 8, "task_fit": 0.7},
            ],
        },
    ).json()
    assert routed["state"] == "INCONCLUSIVE"
    rejected = next(row for row in routed["ranked"] if row["service_id"] == "seller-b")
    assert rejected["evidence_tier"] == "REJECTED"
    assert routed["next_action"]["targets"] == ["unknown-c"]


def test_verified_deliveries_upgrade_provisional_signal_to_buy(tmp_path):
    c = client(tmp_path)
    nonce = "nonce-upgrade-123"
    c.post(
        "/v1/probe-observation",
        json=good_probe("probe-upgrade", "seller-a", nonce),
    )

    schema = {
        "type": "object",
        "properties": {"ok": {"const": True}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    assertions = [{"path": "/ok", "op": "eq", "value": True}]
    snapshot = c.post("/v1/trust-snapshot", json={"service_id": "seller-a"}).json()
    verified_count = 0
    while snapshot["verdict"] != "BUY" and verified_count < MAX_PROMOTION_DELIVERIES:
        verified = c.post(
            "/v1/verify-delivery",
            json={
                "delivery_id": f"paid-{verified_count}",
                "provider_id": "seller-a",
                "task": "bounded paid task",
                "task_type": "general",
                "output": {"ok": True},
                "expected_schema": schema,
                "assertions": assertions,
            },
        ).json()
        assert verified["state"] == "PASS"
        assert verified["reputation_updated"] is True
        verified_count += 1
        snapshot = c.post("/v1/trust-snapshot", json={"service_id": "seller-a"}).json()

    assert snapshot["evidence_tier"] == "VERIFIED"
    assert snapshot["verdict"] == "BUY"
    assert snapshot["observations"] == verified_count
    assert 1 <= verified_count <= MAX_PROMOTION_DELIVERIES

    routed = c.post(
        "/v1/best-execution",
        json={
            "task": "bounded paid task",
            "budget_credits": 20,
            "mode": "safe",
            "candidates": [
                {"service_id": "seller-a", "price_credits": 8, "task_fit": 0.9},
                {"service_id": "unknown", "price_credits": 2, "task_fit": 1.0},
            ],
        },
    ).json()
    assert routed["recommended"] == "seller-a"
    assert routed["evidence_tier"] == "VERIFIED"
    assert routed["recommendation_strength"] == "VERIFIED"
