# Counterparty

> **Before your agent spends a credit, Counterparty proves who can do the job.**

Counterparty is an evidence-backed **trust, delivery-verification, and best-execution layer for SharedNet agents**. It is built for the Shared OS Hackathon's agent economy: buyers have scarce credits, sellers make claims about their own services, and autonomous agents need an independent way to decide who deserves a purchase.

The product is deliberately not another general-purpose agent. It is market infrastructure for other agents.

## Arena services

| Service | Price | What the buyer gets |
|---|---:|---|
| `counterparty.trust_snapshot` | **4 credits** | Server-owned reputation, evidence count, uncertainty, latency history, and BUY/CAUTION/UNPROVEN/AVOID verdict. |
| `counterparty.verify_delivery` | **7 credits** | Post-purchase verification with JSON Schema, deterministic assertions, manipulation checks, audit receipt, and `PASS / FAIL / INCONCLUSIVE`. |
| `counterparty.best_execution` | **10 credits** | A budget-aware provider ranking using Counterparty-owned evidence instead of caller-supplied trust claims. |

**Round-1 strategy:** use `explore` routing to test unfamiliar products and collect verified observations.  
**Round-2 strategy:** use `safe` routing, which uses conservative lower-bound reputation and refuses to fabricate confidence for unseen services.

## Why it is SharedOS-native

The permission boundary is load-bearing:

```text
SharedNet buyer
      │
      ▼
SharedOS kernel ── deny by default / purpose / exact-call auth / maxUses
      │
      ├── Router       decision authority, no target-call authority
      ├── Probe        bounded target-call authority only
      ├── Judge        evidence authority only, no target calls
      └── Attestor     receipt authority only, no target calls
      │
      ▼
Counterparty core ── trusted private ingress only
      │
      ├── deterministic verification
      ├── durable evidence/reputation
      ├── replay suppression
      └── tamper-evident audit chain
```

Purpose string:

```text
counterparty.verify-and-route-sharednet-services
```

The SharedOS adapter is pinned to `@aicoo/sharedos@0.1.0-alpha.5` and contract-tested in CI. Registering a tool grants nothing: callers still need the namespace enabled and an exact matching capability grant; invocation is re-authorized immediately before the backend call.

## Trust invariants

Counterparty is intentionally fail-closed.

- **Missing evidence is `INCONCLUSIVE`, never `PASS`.**
- Callers cannot submit their own successes/failures or trust score.
- Best Execution derives trust from Counterparty's durable observation store.
- Only decisive verified deliveries update reputation.
- A trusted `delivery_id` and deterministic evidence fingerprint suppress replay farming.
- A repeated delivery is still audited but cannot increment reputation twice.
- Audit records form a durable SHA-256 hash chain serialized under a database transaction.
- Verification + reputation update + audit receipt are committed atomically.
- `/v1/*` is a private backend surface; direct access fails closed without the SharedOS host's internal token.
- Request/output sizes are bounded.
- Citation-looking strings are never counted as verified merely because they are valid URLs; source verification must come from a bounded probe turn.

## Measured local evidence

Latest local stress command:

```bash
python scripts/stress_test.py --requests 7500 --concurrency 128 --output reports/stress-local.json
```

Result in this environment:

- **7,500 mixed API requests**
- **128 concurrent requests**
- **0 non-200 responses**
- **299 requests/sec**
- **p95 1.04 s**
- **p99 2.03 s**
- **max 5.29 s**
- audit chain remained valid
- 100 concurrent replay attempts produced **exactly one** reputation update

These are local engineering measurements, not a claim about SharedOS Cloud production throughput.

The Python test suite currently has **37 tests** with **94% measured coverage**. CI additionally runs Python 3.11/3.12/3.13, Ruff, Bandit, pip-audit, a concurrent stress/replay job, SharedOS TypeScript contract tests, and a container build.

## Run the core locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export COUNTERPARTY_INTERNAL_TOKEN='replace-with-random-secret'
pytest
uvicorn counterparty.app:app --reload
```

Public liveness/card endpoints:

```text
GET /health
GET /.well-known/agent.json
```

Trusted SharedOS-host backend endpoints:

```text
POST /v1/trust-snapshot
POST /v1/verify-delivery
POST /v1/best-execution
GET  /v1/audit
GET  /v1/audit/{receipt}
```

For direct development calls to `/v1/*`, send:

```text
X-Counterparty-Internal-Token: $COUNTERPARTY_INTERNAL_TOKEN
```

## Repository guide

- `counterparty/` — verification, reputation, routing, durable storage, API.
- `sharedos/` — real SharedOS host adapter, exact SDK pin, grant examples, and authorization contract tests.
- `tests/` — functional and adversarial regression suite.
- `scripts/stress_test.py` — concurrent mixed-load + replay-storm validation.
- `docs/ARCHITECTURE.md` — trust/evidence architecture.
- `docs/THREAT_MODEL.md` — hostile Arena assumptions and controls.
- `docs/ARENA_RUNBOOK.md` — autonomous event-night operating plan.
- `docs/SUBMISSION_CHECKLIST.md` — hackathon eligibility/submission gaps that cannot be solved by source code alone.

## What still requires the real event environment

Source code alone cannot make a submission eligible. Before Arena night the deployment must actually run product-agent turns on **SharedOS Cloud**, appear on **SharedNet**, produce the real SharedOS audit trail, use the final product-agent addresses, and remain reachable for the full Arena. The personal representative agent also has event obligations documented in `docs/SUBMISSION_CHECKLIST.md`.

## License

MIT. See `NOTICE.md` for research attribution. No third-party project source code is vendored into this repository.
