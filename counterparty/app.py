from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .models import BestExecutionRequest, CandidateScore, DeliveryVerificationRequest, EvidenceState, ProbeResult, TrustSnapshotRequest
from .routing import rank
from .storage import CounterpartyStore
from .verification import aggregate, assertions_probe, citations_probe, contradiction_probe, injection_probe, schema_probe

PURPOSE = "counterparty.verify-and-route-sharednet-services"
SERVICES = [
    {
        "name": "trust_snapshot",
        "price_credits": 4,
        "description": "Server-owned, evidence-backed pre-purchase trust check for an agent service.",
        "input": {"service_id": "string", "task_type": "string"},
        "output": {"trust_score": "0-100", "confidence": "0-1", "verdict": "BUY|CAUTION|UNPROVEN|AVOID"},
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
        "description": "Rank candidate agent services by expected utility using Counterparty-owned reputation under a credit budget.",
        "input": {"task": "string", "budget_credits": "int", "candidates": "[{service_id,price_credits,task_fit}]"},
        "output": {"recommended": "service_id?", "ranked": "candidate scores", "state": "PASS|INCONCLUSIVE"},
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
        version="0.2.0",
        description="Evidence-backed trust, verification, and best-execution layer for SharedNet agents",
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
        return {"ok": True, "service": "counterparty", "version": "0.2.0", "audit": store.audit_head()}

    @app.get("/.well-known/agent.json")
    def agent_card():
        return {
            "name": "Counterparty",
            "description": "Before your agent spends a credit, Counterparty proves who can do the job.",
            "purpose": PURPOSE,
            "agent_addresses": {
                "router": os.getenv("COUNTERPARTY_ROUTER_ADDRESS", "counterparty/router"),
                "probe": os.getenv("COUNTERPARTY_PROBE_ADDRESS", "counterparty/probe"),
                "judge": os.getenv("COUNTERPARTY_JUDGE_ADDRESS", "counterparty/judge"),
                "attestor": os.getenv("COUNTERPARTY_ATTESTOR_ADDRESS", "counterparty/attestor"),
            },
            "capabilities": ["trust_snapshot", "verify_delivery", "best_execution"],
            "evidence_semantics": ["PASS", "FAIL", "INCONCLUSIVE"],
            "services": SERVICES,
            "max_delivery_seconds": 300,
        }

    @app.post("/v1/trust-snapshot")
    def trust_snapshot(req: TrustSnapshotRequest):
        rep, median_latency = store.reputation(req.service_id, req.task_type)
        score = rep.score_100()
        conservative = rep.conservative_score_100()
        if rep.observations == 0:
            verdict = "UNPROVEN"
        elif score >= 75 and rep.confidence >= 0.5:
            verdict = "BUY"
        elif score >= 55:
            verdict = "CAUTION"
        else:
            verdict = "AVOID"
        event = store.append_audit(
            "trust_snapshot",
            {
                "service_id": req.service_id,
                "task_type": req.task_type,
                "score": score,
                "conservative_score": conservative,
                "confidence": rep.confidence,
                "observations": rep.observations,
                "verdict": verdict,
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
            "evidence": {"successes": rep.successes, "failures": rep.failures, "median_latency_ms": median_latency},
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
            trust = rep.conservative_score_100() if req.mode == "safe" else rep.score_100()
            candidate_scores.append(
                CandidateScore(
                    service_id=candidate.service_id,
                    price_credits=candidate.price_credits,
                    trust_score=trust,
                    confidence=rep.confidence,
                    task_fit=candidate.task_fit,
                    latency_ms=candidate.latency_ms if candidate.latency_ms is not None else observed_latency or 1000,
                    observations=rep.observations,
                )
            )
        ranked = rank(candidate_scores, req.budget_credits, req.mode)
        viable = [(c, u) for c, u in ranked if u > -1e8]
        evidence_ready = [x for x in viable if x[0].observations > 0]
        if not viable:
            result = {"state": "INCONCLUSIVE", "reason": "No candidate fits the budget", "ranked": []}
        elif req.mode == "safe" and not evidence_ready:
            result = {
                "state": "INCONCLUSIVE",
                "reason": "No in-budget candidate has verified observations; use explore mode to rank unproven services",
                "ranked": [
                    {"service_id": c.service_id, "utility": round(u, 4), "price_credits": c.price_credits, "trust_score": c.trust_score, "confidence": c.confidence, "observations": c.observations}
                    for c, u in viable
                ],
            }
        else:
            winner = evidence_ready[0] if req.mode == "safe" else viable[0]
            result = {
                "state": "PASS",
                "recommended": winner[0].service_id,
                "expected_utility": round(winner[1], 4),
                "ranked": [
                    {"service_id": c.service_id, "utility": round(u, 4), "price_credits": c.price_credits, "trust_score": c.trust_score, "confidence": c.confidence, "observations": c.observations}
                    for c, u in viable
                ],
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
