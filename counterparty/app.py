from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .models import (
    Assertion,
    BestExecutionRequest,
    CandidateScore,
    DeliveryVerificationRequest,
    EvidenceState,
    ProbeObservationRequest,
    ProbeResult,
    TrustSnapshotRequest,
)
from .routing import rank
from .storage import CounterpartyStore
from .verification import (
    aggregate,
    assertions_probe,
    citations_probe,
    contradiction_probe,
    injection_probe,
    schema_probe,
)

PURPOSE = "counterparty.verify-and-route-sharednet-services"
SERVICES = [
    {
        "name": "trust_snapshot",
        "price_credits": 4,
        "description": "Active pre-purchase trust check: under SharedOS, Counterparty canary-tests the seller with a bounded Probe turn, then combines fresh protocol proof with server-owned delivery reputation.",
        "input": {"service_id": "SharedNet service ID", "task_type": "optional task class"},
        "output": {"trust_score": "0-100", "confidence": "0-1", "verdict": "BUY|TRY_SMALL|CAUTION|UNPROVEN|AVOID", "fresh_probe": "SharedOS-host metadata when active probing runs"},
    },
    {
        "name": "verify_delivery",
        "price_credits": 7,
        "description": "Verify a service delivery using JSON Schema, deterministic assertions, manipulation checks, and strict PASS/FAIL/INCONCLUSIVE semantics.",
        "input": {"delivery_id": "immutable SharedNet delivery ID"},
        "output": {"state": "PASS|FAIL|INCONCLUSIVE", "probes": "evidence[]", "audit_receipt": "sha256"},
    },
    {
        "name": "best_execution",
        "price_credits": 10,
        "description": "Rank candidate agent services by expected utility using task evidence first and bounded protocol-canary evidence for safe cold-start routing.",
        "input": {"task": "string", "budget_credits": "int", "candidates": "[{service_id,price_credits,task_fit}]"},
        "output": {"recommended": "service_id?", "ranked": "candidate scores", "evidence_tier": "VERIFIED|PROVISIONAL", "state": "PASS|INCONCLUSIVE"},
    },
]


def create_app(store: CounterpartyStore | None = None, internal_token: str | None = None, require_internal_auth: bool | None = None) -> FastAPI:
    if store is None:
        db_path = os.getenv("COUNTERPARTY_DB", str(Path("data") / "counterparty.sqlite3"))
        store = CounterpartyStore(db_path)
    if internal_token is None:
        internal_token = os.getenv("COUNTERPARTY_INTERNAL_TOKEN")
    if require_internal_auth is None:
        require_internal_auth = os.getenv("COUNTERPARTY_REQUIRE_INTERNAL_AUTH", "1") not in {"0", "false", "False"}
    internal_token_valid = bool(internal_token) and len(internal_token) >= 32

    app = FastAPI(
        title="Counterparty",
        version="0.3.0",
        description="Active trust, verification, and best-execution layer for SharedNet agents",
    )
    app.state.store = store

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        max_bytes = int(os.getenv("COUNTERPARTY_MAX_BODY_BYTES", "262144"))
        if request.url.path.startswith("/v1/") and require_internal_auth:
            if not internal_token_valid:
                return JSONResponse(status_code=503, content={"detail": "trusted SharedOS ingress is not securely configured"})
            supplied = request.headers.get("x-counterparty-internal-token", "")
            if not hmac.compare_digest(supplied, internal_token):
                return JSONResponse(status_code=401, content={"detail": "unauthorized ingress"})
        raw_len = request.headers.get("content-length")
        if raw_len and raw_len.isdigit() and int(raw_len) > max_bytes:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
        start = time.perf_counter_ns()
        response = await call_next(request)
        response.headers["X-Counterparty-Latency-Us"] = str((time.perf_counter_ns() - start) // 1000)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        # Public liveness must stay O(1); a hostile health-check flood must not
        # force a full historical hash-chain scan. Full verification is on the
        # trusted /v1/audit surface and in preflight/CI.
        return {"ok": True, "service": "counterparty", "version": "0.3.0", "audit": store.audit_head()}

    @app.get("/.well-known/agent.json")
    def agent_card():
        return {
            "name": "Counterparty",
            "description": "Before your agent spends a credit, Counterparty actively tests who can do the job, verifies what they deliver, and routes the next purchase with compounding evidence.",
            "purpose": PURPOSE,
            "agent_addresses": {
                "router": os.getenv("COUNTERPARTY_ROUTER_ADDRESS", "counterparty-router"),
                "probe": os.getenv("COUNTERPARTY_PROBE_ADDRESS", "counterparty-probe"),
                "judge": os.getenv("COUNTERPARTY_JUDGE_ADDRESS", "counterparty-judge"),
                "attestor": os.getenv("COUNTERPARTY_ATTESTOR_ADDRESS", "counterparty-attestor"),
            },
            "capabilities": ["active_canary", "trust_snapshot", "verify_delivery", "best_execution"],
            "evidence_semantics": ["PASS", "FAIL", "INCONCLUSIVE"],
            "services": SERVICES,
            "market_flywheel": [
                "Trust Snapshot actively probes an unknown seller under a bounded SharedOS grant",
                "A passing canary creates PROVISIONAL evidence and unlocks safe small-spend routing",
                "Verify Delivery converts the purchase into task-specific VERIFIED reputation",
                "Best Execution uses the stronger evidence to route the next credit",
            ],
            "max_delivery_seconds": 300,
        }

    @app.post("/v1/trust-snapshot")
    def trust_snapshot(req: TrustSnapshotRequest):
        rep, median_latency = store.reputation(req.service_id, req.task_type)
        protocol_rep, protocol_latency = store.protocol_reputation(req.service_id)
        score = rep.score_100()
        conservative = rep.conservative_score_100()

        if rep.observations == 0:
            if protocol_rep.observations == 0:
                verdict = "UNPROVEN"
                action = "RUN_CANARY"
            elif protocol_rep.failures > protocol_rep.successes:
                verdict = "AVOID"
                action = "SKIP"
            else:
                verdict = "TRY_SMALL"
                action = "BUY_SMALL_THEN_VERIFY"
        elif score >= 75 and rep.confidence >= 0.5:
            verdict = "BUY"
            action = "BUY"
        elif score >= 55:
            verdict = "CAUTION"
            action = "BUY_SMALL_THEN_VERIFY"
        else:
            verdict = "AVOID"
            action = "SKIP"

        event = store.append_audit(
            "trust_snapshot",
            {
                "service_id": req.service_id,
                "task_type": req.task_type,
                "score": score,
                "conservative_score": conservative,
                "confidence": rep.confidence,
                "observations": rep.observations,
                "protocol_observations": protocol_rep.observations,
                "verdict": verdict,
                "action": action,
            },
        )
        return {
            "service_id": req.service_id,
            "task_type": req.task_type,
            "trust_score": score,
            "conservative_score": conservative,
            "confidence": round(rep.confidence, 4),
            "observations": rep.observations,
            "verdict": verdict,
            "action": action,
            "evidence_tier": "VERIFIED" if rep.observations else ("PROVISIONAL" if protocol_rep.observations else "UNPROVEN"),
            "evidence": {"successes": rep.successes, "failures": rep.failures, "median_latency_ms": median_latency},
            "protocol_evidence": {
                "successes": protocol_rep.successes,
                "failures": protocol_rep.failures,
                "observations": protocol_rep.observations,
                "score": protocol_rep.score_100(),
                "confidence": round(protocol_rep.confidence, 4),
                "median_latency_ms": protocol_latency,
            },
            "audit_receipt": event["hash"],
        }

    @app.post("/v1/probe-observation")
    def probe_observation(req: ProbeObservationRequest):
        # The canary contract is server-owned. Buyers cannot choose an easy
        # assertion or an impossible assertion to inflate/poison another agent.
        expected_schema = {
            "type": "object",
            "properties": {
                "counterparty_probe_id": {"const": req.nonce},
                "ack": {"const": True},
            },
            "required": ["counterparty_probe_id", "ack"],
        }
        assertions = [
            Assertion(path="/counterparty_probe_id", op="eq", value=req.nonce),
            Assertion(path="/ack", op="eq", value=True),
        ]
        probes = [
            schema_probe(req.output, expected_schema),
            assertions_probe(req.output, assertions),
            injection_probe(req.output),
            contradiction_probe(req.output),
        ]
        state, score, confidence = aggregate(probes)
        if state == EvidenceState.INCONCLUSIVE:
            # With a server-owned schema and assertions, a returned reply is
            # always decidable. Preserve fail-closed semantics if that invariant
            # ever changes.
            state = EvidenceState.FAIL

        fingerprint_material = {
            "probe_id": req.probe_id,
            "provider_id": req.provider_id,
            "nonce": req.nonce,
            "output": req.output,
        }
        evidence_hash = hashlib.sha256(
            json.dumps(fingerprint_material, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        event, updated = store.record_protocol_observation(
            probe_id=req.probe_id,
            service_id=req.provider_id,
            outcome=state.value,
            evidence_hash=evidence_hash,
            latency_ms=req.latency_ms,
            audit_payload={
                "probe_id": req.probe_id,
                "provider_id": req.provider_id,
                "state": state.value,
                "score": score,
                "confidence": confidence,
                "evidence_hash": evidence_hash,
                "probe_states": {p.probe: p.state.value for p in probes},
            },
        )
        return {
            "provider_id": req.provider_id,
            "probe_id": req.probe_id,
            "state": state,
            "score": score,
            "confidence": confidence,
            "probes": [p.model_dump(mode="json") for p in probes],
            "protocol_reputation_updated": updated,
            "replay_suppressed": not updated,
            "evidence_hash": evidence_hash,
            "audit_receipt": event["hash"],
        }

    @app.post("/v1/verify-delivery")
    def verify_delivery(req: DeliveryVerificationRequest):
        started = time.perf_counter_ns()
        probes = [
            schema_probe(req.output, req.expected_schema),
            assertions_probe(req.output, req.assertions),
            injection_probe(req.output),
            contradiction_probe(req.output),
        ]
        independent = [ProbeResult(**check.model_dump(mode="python")) for check in req.independent_checks]
        probes.extend(independent)
        # Citation syntax is not evidence. If the trusted host has not attached
        # an independent citation/source check, citations keep the result
        # INCONCLUSIVE instead of being mistaken for proof.
        if req.cited_urls and not any(check.probe == "citations" for check in req.independent_checks):
            probes.append(citations_probe(req.cited_urls))
        state, score, confidence = aggregate(probes)
        latency_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
        fingerprint_material = {
            "delivery_id": req.delivery_id,
            "provider_id": req.provider_id,
            "task": req.task,
            "output": req.output,
            "expected_schema": req.expected_schema,
            "assertions": [a.model_dump(mode="json") for a in req.assertions],
            "cited_urls": [str(u) for u in req.cited_urls],
            "independent_checks": [check.model_dump(mode="json") for check in req.independent_checks],
        }
        evidence_hash = hashlib.sha256(json.dumps(fingerprint_material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        # Global reputation is stricter than the per-call verdict. A manipulation
        # detector can warn/fail a delivery without a task contract, but an
        # attacker must not be able to poison a provider's reputation using an
        # unbound or underspecified task. Decisive reputation requires both the
        # original JSON Schema and deterministic assertions from trusted host evidence.
        reputation_eligible = req.expected_schema is not None and bool(req.assertions)
        event, reputation_updated = store.record_verification(
            delivery_id=req.delivery_id,
            service_id=req.provider_id,
            task_type=req.task_type,
            outcome=state.value,
            evidence_hash=evidence_hash,
            latency_ms=latency_ms,
            audit_payload={
                "delivery_id": req.delivery_id,
                "provider_id": req.provider_id,
                "task_type": req.task_type,
                "state": state.value,
                "score": score,
                "confidence": confidence,
                "evidence_hash": evidence_hash,
                "probe_states": {p.probe: p.state.value for p in probes},
                "reputation_eligible": reputation_eligible,
            },
            reputation_eligible=reputation_eligible,
        )
        replay = state in {EvidenceState.PASS, EvidenceState.FAIL} and not reputation_updated
        return {
            "provider_id": req.provider_id,
            "state": state,
            "score": score,
            "confidence": confidence,
            "probes": [p.model_dump(mode="json") for p in probes],
            "reputation_updated": reputation_updated,
            "replay_suppressed": replay,
            "evidence_hash": evidence_hash,
            "audit_receipt": event["hash"],
        }

    @app.post("/v1/best-execution")
    def best_execution(req: BestExecutionRequest):
        candidate_scores: list[CandidateScore] = []
        for candidate in req.candidates:
            rep, observed_latency = store.reputation(candidate.service_id, req.task_type)
            protocol_rep, protocol_latency = store.protocol_reputation(candidate.service_id)
            if rep.observations > 0:
                trust = rep.conservative_score_100() if req.mode == "safe" else rep.score_100()
                confidence = rep.confidence
                evidence_tier = "VERIFIED"
            elif protocol_rep.observations > 0:
                # Canary evidence proves current protocol responsiveness, not the
                # buyer's domain task. Keep it visibly provisional and shrink it
                # halfway back toward neutral before routing.
                trust = 50.0 + 0.5 * (protocol_rep.score_100() - 50.0)
                confidence = min(0.5, 0.2 + 0.5 * protocol_rep.confidence)
                evidence_tier = "PROVISIONAL"
            else:
                trust = 50.0
                confidence = 0.0
                evidence_tier = "UNPROVEN"

            candidate_scores.append(
                CandidateScore(
                    service_id=candidate.service_id,
                    price_credits=candidate.price_credits,
                    trust_score=trust,
                    confidence=confidence,
                    task_fit=candidate.task_fit,
                    latency_ms=candidate.latency_ms if candidate.latency_ms is not None else observed_latency or protocol_latency or 1000,
                    observations=rep.observations,
                    protocol_observations=protocol_rep.observations,
                    evidence_tier=evidence_tier,
                )
            )

        ranked = rank(candidate_scores, req.budget_credits, req.mode)
        viable = [(c, u) for c, u in ranked if u > -1e8]
        evidence_ready = [x for x in viable if x[0].evidence_tier != "UNPROVEN"]

        def row(c: CandidateScore, u: float) -> dict[str, object]:
            return {
                "service_id": c.service_id,
                "utility": round(u, 4),
                "price_credits": c.price_credits,
                "trust_score": round(c.trust_score, 2),
                "confidence": round(c.confidence, 4),
                "evidence_tier": c.evidence_tier,
                "verified_observations": c.observations,
                "protocol_observations": c.protocol_observations,
            }

        if not viable:
            result: dict[str, object] = {"state": "INCONCLUSIVE", "reason": "No candidate fits the budget", "ranked": []}
        elif req.mode == "safe" and not evidence_ready:
            result = {
                "state": "INCONCLUSIVE",
                "reason": "No in-budget candidate has verified delivery evidence or a fresh protocol canary.",
                "ranked": [row(c, u) for c, u in viable],
                "next_action": {
                    "service": "trust_snapshot",
                    "price_credits": 4,
                    "reason": "Trust Snapshot actively canary-tests an unknown seller under a bounded SharedOS Probe grant.",
                    "targets": [c.service_id for c, _ in viable[:5]],
                },
            }
        else:
            winner = evidence_ready[0] if req.mode == "safe" else viable[0]
            result = {
                "state": "PASS",
                "recommended": winner[0].service_id,
                "expected_utility": round(winner[1], 4),
                "evidence_tier": winner[0].evidence_tier,
                "recommendation_strength": "VERIFIED" if winner[0].evidence_tier == "VERIFIED" else "PROVISIONAL",
                "ranked": [row(c, u) for c, u in viable],
                "next_action": {
                    "service": "verify_delivery",
                    "price_credits": 7,
                    "reason": "After purchase, verify the actual delivery to upgrade provisional protocol evidence into task-specific reputation.",
                },
            }
        event = store.append_audit("best_execution", {"task_hash": hashlib.sha256(req.task.encode()).hexdigest(), "mode": req.mode, "result": result})
        result["audit_receipt"] = event["hash"]
        return result

    @app.get("/v1/audit")
    def audit_events(limit: int = Query(100, ge=1, le=1000)):
        return {"valid": store.verify_audit(), "events": store.audit_events(limit)}

    @app.get("/v1/audit/{receipt}")
    def audit_receipt(receipt: str):
        if len(receipt) != 64 or any(c not in "0123456789abcdef" for c in receipt.lower()):
            raise HTTPException(status_code=400, detail="invalid receipt")
        event = store.get_audit_event(receipt)
        if event is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        return {"valid": store.verify_audit(), "event": event}

    return app


app = create_app()
