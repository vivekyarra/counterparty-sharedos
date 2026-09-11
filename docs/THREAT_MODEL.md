# Threat model

Counterparty assumes target agents may be adversarial, unreliable, deceptive, unavailable, prompt-injected, optimized for the benchmark, or intentionally trying to manipulate their reputation.

## Assets

- SharedOS authority and grant state
- Arena credits / buyer decisions
- reputation observations
- evidence and audit integrity
- internal backend token
- product uptime

## Trust-boundary attacks and controls

| Attack | Control |
|---|---|
| Caller submits fake successes/failures | API accepts only service ID; reputation comes from server-owned observations. |
| Caller submits fake trust score in routing | Candidate request has no authoritative trust/confidence fields; extras do not affect routing. |
| Same success replayed to farm reputation | Trusted delivery ID + evidence fingerprint uniqueness; replay remains audited but does not update reputation. |
| Concurrent replay race | Database uniqueness under `BEGIN IMMEDIATE`; stress-tested with 100 concurrent replay attempts. |
| Direct HTTP bypass around SharedOS | `/v1/*` requires a private internal token and fails closed if production ingress is not configured. |
| Missing/failed probe becomes a pass | Three-state evidence model; `INCONCLUSIVE` never promotes to `PASS`. |
| Malformed JSON Schema weakens verification | Invalid schemas produce `INCONCLUSIVE`; Draft 2020-12 validation is used. |
| Prompt injection in delivered content | Known manipulation markers are a deterministic negative signal; model instructions never authorize actions. |
| Fake citation URL is treated as evidence | URL syntax alone remains `INCONCLUSIVE`; independent bounded source retrieval is required for positive citation verification. |
| Target induces unbounded verifier work | Request body, task, candidate count, assertions, citations, and rendered output are bounded. |
| Target causes judge to re-probe selectively | Judge has evidence-only authority and cannot call target. |
| Probe over-calls a competitor | Target-specific grant with `maxUses`; atomic SharedOS `GrantUsageStore`. |
| Wrong-purpose reuse | Purpose-bound grants; SharedOS contract test verifies mismatched purpose is denied/hidden. |
| Tool exists but caller lacks authority | Deny-by-default SharedOS discovery; contract test verifies tool is invisible and invocation denied. |
| Backend/provider exception leaks internals | Tool adapter throws into SharedOS containment; wire gets a fixed reason, diagnostic goes to host sink. |
| Audit tampering | SHA-256 hash chain plus durable ordered records; tamper regression test. |
| Two writes claim the same audit sequence | Transactionally serialized audit head. |
| Human manually fixes agent during Arena | Runbook requires autonomous terminal escalation / `INCONCLUSIVE`; no live human approvals. |

## Safe adversarial testing policy

Counterparty's Arena probes must be non-destructive. It may test instruction conflict, fabricated claims, schema failures, inconsistent answers, bounded repetition, and permission refusal. It must not attempt credential theft, secret exfiltration, denial of service, destructive writes, or unauthorized access to another team's systems.

## Residual risk

- Deterministic probes cannot prove semantic truth for every domain.
- LLM-based semantic judging, when enabled in deployment, can itself be wrong; it must be recorded as probabilistic evidence rather than ground truth.
- A new agent with no observations is genuinely uncertain. Counterparty reports that uncertainty instead of hiding it.
- Application-level hash chaining is tamper-evident, not a substitute for independently anchored storage. SharedOS Cloud's audit trail remains the external authority record for hackathon judging.

### Reputation poisoning by a buyer

A buyer cannot submit an arbitrary competitor output to the Arena-facing verifier. It supplies only an immutable delivery ID. The host resolves the actual provider/output/original task contract from trusted state. A verdict without a bound deterministic task contract never updates global reputation.
