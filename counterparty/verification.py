from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from .models import Assertion, EvidenceState, ProbeResult

INJECTION_MARKERS = [
    "ignore previous instructions",
    "reveal system prompt",
    "bypass safety",
    "disable safeguards",
    "developer message",
    "system message",
    "grant me permission",
    "override authorization",
]


def schema_probe(output: Any, schema: dict[str, Any] | None) -> ProbeResult:
    if not schema:
        return ProbeResult(probe="schema", state=EvidenceState.INCONCLUSIVE, reason="No expected schema supplied")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return ProbeResult(
            probe="schema",
            state=EvidenceState.INCONCLUSIVE,
            reason="Expected schema is invalid",
            evidence={"schema_error": exc.message[:500]},
        )
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(output), key=lambda e: list(e.absolute_path))
    if errors:
        sample = [
            {"path": "/" + "/".join(str(p) for p in e.absolute_path), "message": e.message[:500]}
            for e in errors[:10]
        ]
        return ProbeResult(
            probe="schema",
            state=EvidenceState.FAIL,
            score=0,
            reason=f"Output violates schema ({len(errors)} validation error(s))",
            evidence={"errors": sample},
        )
    return ProbeResult(probe="schema", state=EvidenceState.PASS, score=1, reason="Output satisfies JSON Schema 2020-12")


def injection_probe(output: Any) -> ProbeResult:
    try:
        text = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str).lower()
    except Exception:
        text = str(output).lower()
    hits = sorted({m for m in INJECTION_MARKERS if m in text})
    if hits:
        return ProbeResult(
            probe="prompt_manipulation",
            state=EvidenceState.FAIL,
            score=0,
            reason="Suspicious instruction-manipulation markers present",
            evidence={"markers": hits},
        )
    return ProbeResult(probe="prompt_manipulation", state=EvidenceState.PASS, score=1, reason="No known prompt-manipulation markers detected")


def contradiction_probe(output: Any) -> ProbeResult:
    if isinstance(output, dict):
        verdict = str(output.get("verdict", output.get("state", ""))).upper()
        confidence = output.get("confidence")
        if verdict in {"PASS", "APPROVE", "BUY", "SUCCESS"} and isinstance(confidence, (int, float)) and confidence < 0.2:
            return ProbeResult(probe="self_consistency", state=EvidenceState.FAIL, score=0, reason="Positive verdict conflicts with very low confidence")
        if verdict in {"FAIL", "REJECT", "AVOID"} and isinstance(confidence, (int, float)) and confidence > 0.98 and output.get("reason") in {None, ""}:
            return ProbeResult(probe="self_consistency", state=EvidenceState.FAIL, score=0, reason="Extreme negative certainty has no supporting reason")
    return ProbeResult(probe="self_consistency", state=EvidenceState.PASS, score=1, reason="No deterministic contradiction detected")


def _resolve_path(doc: Any, path: str) -> tuple[bool, Any]:
    if path in {"", "/"}:
        return True, doc
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path.strip("/").split("/") if p != ""]
    cur = doc
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def assertions_probe(output: Any, assertions: list[Assertion]) -> ProbeResult:
    if not assertions:
        return ProbeResult(probe="assertions", state=EvidenceState.INCONCLUSIVE, reason="No deterministic assertions supplied")
    failures: list[dict[str, Any]] = []
    for assertion in assertions:
        exists, actual = _resolve_path(output, assertion.path)
        ok = False
        if assertion.op == "exists":
            ok = exists
        elif exists and assertion.op == "eq":
            ok = actual == assertion.value
        elif exists and assertion.op == "ne":
            ok = actual != assertion.value
        elif exists and assertion.op == "contains":
            try:
                ok = assertion.value in actual
            except TypeError:
                ok = False
        elif exists and assertion.op == "gte":
            try:
                ok = actual >= assertion.value
            except TypeError:
                ok = False
        elif exists and assertion.op == "lte":
            try:
                ok = actual <= assertion.value
            except TypeError:
                ok = False
        if not ok:
            failures.append({"path": assertion.path, "op": assertion.op, "expected": assertion.value, "actual": actual if exists else "<missing>"})
    if failures:
        return ProbeResult(
            probe="assertions",
            state=EvidenceState.FAIL,
            score=max(0.0, 1.0 - len(failures) / len(assertions)),
            reason=f"{len(failures)}/{len(assertions)} deterministic assertion(s) failed",
            evidence={"failures": failures[:10]},
        )
    return ProbeResult(probe="assertions", state=EvidenceState.PASS, score=1, reason=f"All {len(assertions)} deterministic assertion(s) passed")


def citations_probe(urls: list[Any]) -> ProbeResult:
    # URL reachability/content verification is performed by the bounded SharedOS
    # probe agent in deployment. The core never pretends syntactic URLs are proof.
    if not urls:
        return ProbeResult(probe="citations", state=EvidenceState.INCONCLUSIVE, reason="No citations supplied")
    hosts = sorted({str(getattr(u, "host", "") or "") for u in urls})
    return ProbeResult(
        probe="citations",
        state=EvidenceState.INCONCLUSIVE,
        reason="Citation URLs were supplied but have not yet been independently fetched by the SharedOS probe agent",
        evidence={"count": len(urls), "hosts": hosts[:20]},
    )


def aggregate(probes: list[ProbeResult]) -> tuple[EvidenceState, float, float]:
    # Safety invariant: missing evidence NEVER becomes PASS.
    if any(p.state == EvidenceState.FAIL for p in probes):
        state = EvidenceState.FAIL
    elif any(p.state == EvidenceState.INCONCLUSIVE for p in probes):
        state = EvidenceState.INCONCLUSIVE
    else:
        state = EvidenceState.PASS

    scored = [p.score for p in probes if p.score is not None]
    score = sum(scored) / len(scored) if scored else 0.0
    coverage = len(scored) / len(probes) if probes else 0.0
    # Confidence reflects evidence coverage, not merely passing scores.
    if state == EvidenceState.PASS:
        confidence = min(score, coverage)
    elif state == EvidenceState.FAIL:
        confidence = coverage
    else:
        confidence = coverage * 0.5
    return state, round(score, 4), round(confidence, 4)
