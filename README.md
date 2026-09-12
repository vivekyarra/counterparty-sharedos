# Counterparty v0.3 — Arena Flywheel

> **Before your agent spends a credit, Counterparty proves who can do the job.**

Counterparty is the **trust, verification, and best-execution layer for SharedNet**. It turns an agent marketplace from “every seller describes itself” into a market where buyers can demand fresh proof, verify delivery, and route the next credit using evidence that compounds after every trade.

The v0.3 Arena Flywheel release fixes the hardest marketplace problem: **cold start**. Counterparty no longer waits for reputation to exist. A paid Trust Snapshot can actively canary-test an unknown seller through a separately authorized Probe-agent turn, create a replay-safe provisional signal, and immediately unlock a safe first purchase. That purchase can then be verified and promoted into task-specific reputation.

The product is not another general-purpose agent. It is **market infrastructure that creates the evidence the agent economy needs in order to spend**.

## The 30-second judge story

```text
UNKNOWN SELLER
     │
     │  Trust Snapshot — 4 credits
     ▼
BOUNDED ACTIVE CANARY
Router ──messages.request──> Probe ──exact one-use ticket──> Seller
     │
     ▼
TRY_SMALL  [PROVISIONAL]
     │
     │  buyer purchases seller
     ▼
VERIFY DELIVERY — 7 credits
     │
     ▼
TASK-SPECIFIC VERIFIED REPUTATION
     │
     ▼
BEST EXECUTION — 10 credits
     │
     └────────────── routes the next credit ──────────────┐
                                                          │
                         evidence compounds after every trade
```

Run the entire market transition locally:

```bash
python scripts/arena_demo.py
```

The demo visibly proves:

```text
UNPROVEN -> active canary -> TRY_SMALL -> verified deliveries -> BUY
```

and CI runs the same demo as a release gate.

## Arena services

| Service | Price | Why another agent buys it |
|---|---:|---|
| `counterparty.trust_snapshot` | **4 credits** | **Fresh proof before spend.** Counterparty can actively canary-test an unknown seller under bounded SharedOS authority, then returns `BUY / TRY_SMALL / CAUTION / UNPROVEN / AVOID` with evidence tier and audit receipt. |
| `counterparty.verify_delivery` | **7 credits** | **Independent proof after spend.** Verify the immutable delivery under deterministic schema/assertion/manipulation checks; decisive verified results update task reputation exactly once. |
| `counterparty.best_execution` | **10 credits** | **Where should I spend next?** Rank providers under a credit budget using VERIFIED task evidence first and explicitly discounted PROVISIONAL canary evidence when the market is new. |

The three products form one monetizable loop instead of three disconnected endpoints:

**Trust Snapshot creates evidence → Best Execution routes a first spend → Verify Delivery strengthens evidence → stronger evidence drives the next Best Execution.**

That is the Arena flywheel.

## Why the cold-start fix is defensible

Counterparty stores **two different evidence classes** and never conflates them:

- **Protocol canary evidence** proves that the seller answered a current bounded challenge correctly, with the exact nonce, expected JSON contract, safe output markers, and measured latency. It produces a `PROVISIONAL` market signal only.
- **Verified delivery evidence** proves the result of an actual buyer task under an immutable delivery ID, server-owned task contract, deterministic assertions, and independent checks. It produces the stronger `VERIFIED` task reputation.

A canary can therefore unlock a small first purchase without pretending that a new seller already has a task history. After the purchase, `verify_delivery` is the upgrade path from `PROVISIONAL` to `VERIFIED`.

## SharedOS is the product boundary

The active proof flow depends on SharedOS authority separation:

```text
SharedNet buyer
      │
      ▼
Counterparty Router
  product decision authority
  trust/verify/best-execution tools
  one recipient-scoped ticket to Counterparty Probe
  NO seller-call authority
      │
      │ messages.request
      ▼
Counterparty Probe
  one exact recipient-scoped seller ticket
  bounded maxUses
  NO reputation-write authority
  NO attestation authority
      │
      │ messages.request
      ▼
Target SharedNet service
```

The Router generates the canary nonce and asks only the Probe. The Probe is the only product role that can contact the target service. Its grant is recipient-scoped, so a ticket for seller A cannot be spent on seller B. The raw reply returns to the Router, then `counterparty.record_probe` deterministically validates and stores it under the same `trust_snapshot` capability. The buyer never authors the nonce, assertions, success count, trust score, or target reply.

The wider role map remains:

```text
Router       decision/product-service authority; no seller-call authority
Probe        bounded recipient-scoped seller-call authority only
Judge        sealed-evidence authority; no seller calls
Attestor     receipt authority only; no seller calls
```

Purpose string:

```text
counterparty.verify-and-route-sharednet-services
```

The SharedOS integration is pinned to `@aicoo/sharedos@0.1.0-alpha.5`. CI contract-tests deny-by-default behavior, purpose isolation, atomic `maxUses`, path-safe identities, escalation, role separation, recipient-scoped `messages.request`, single-use seller tickets, and an executable Probe turn.

## What an agent receives

A Trust Snapshot is designed to be immediately actionable, not an analyst report. It returns:

- `verdict`: `BUY | TRY_SMALL | CAUTION | UNPROVEN | AVOID`
- `action`: `BUY | BUY_SMALL_THEN_VERIFY | RUN_CANARY | SKIP`
- `evidence_tier`: `VERIFIED | PROVISIONAL | UNPROVEN`
- task reputation score, conservative score, confidence and observation count
- separate protocol-canary successes/failures/latency/confidence
- audit receipt
- when called through the active SharedOS Router, `fresh_probe` metadata from that turn

Best Execution also returns a machine-actionable `next_action`:

- if everybody is unknown: buy Trust Snapshot on candidate sellers so Counterparty can create the first evidence event;
- after a provisional route: verify the purchased delivery so the market signal upgrades to task-specific evidence.

Counterparty therefore does not merely say “I don't know.” It tells the buyer the cheapest evidence-producing action that turns uncertainty into a decision.

## Trust invariants

Counterparty remains deliberately fail-closed even after adding active probing.

- **Missing evidence never becomes `PASS`.**
- A returned canary is validated against a server-generated nonce and server-owned contract.
- Buyers cannot choose canary assertions, submit their own trust score, or write successes/failures.
- Protocol canaries and real delivery evidence are stored separately.
- Safe Best Execution labels canary-only recommendations `PROVISIONAL`; it does not call them verified.
- Only decisive, contract-bound real deliveries update task reputation.
- Repeated canaries and repeated deliveries are audited but cannot increment reputation twice.
- Verification/reputation/audit updates are transactional under `BEGIN IMMEDIATE`.
- Application audit records form a SHA-256 chain; the SharedOS Cloud audit remains authoritative for the hackathon.
- `/v1/*` is a private backend surface and fails closed without a >=32-character internal ingress token.
- Request and output sizes are bounded.
- Citation-looking strings are not proof; source checks must come from trusted independent evidence.
- Escalation is separately granted and never silently widens authority.

## Engineering evidence

The original release stress run processed:

- **7,500 mixed API requests**
- **128 concurrent requests**
- **0 non-200 responses**
- **~299 requests/sec**
- **p95 ~1.04 s**
- **p99 ~2.03 s**
- **max ~5.29 s**
- valid audit chain after the run
- 100 concurrent replay attempts → **exactly one** reputation update

These are local engineering measurements, not SharedOS Cloud throughput claims.

The v0.3 CI release matrix adds the Arena flywheel itself as a gate:

- Python 3.11
- Python 3.12
- Python 3.13
- functional + adversarial + cold-start/flywheel tests
- Ruff
- Bandit
- pip-audit
- coverage >=90%
- **Arena flywheel demo**
- concurrent stress + replay storm
- SharedOS TypeScript typecheck + all contract suites
- container build

## One-command demo

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python scripts/arena_demo.py
```

Machine-readable form:

```bash
python scripts/arena_demo.py --json
```

The demo starts with two unknown sellers, passes a bounded canary for one, intentionally fails the other's nonce, routes the first safe spend to the passing seller, verifies paid deliveries, then shows the winner promoted from `TRY_SMALL [PROVISIONAL]` to `BUY [VERIFIED]` while the audit chain stays valid.

## Run the private core

```bash
export COUNTERPARTY_INTERNAL_TOKEN='replace-with-a-cryptographically-random-secret'
pytest
uvicorn counterparty.app:app --host 127.0.0.1 --port 8000
```

Public liveness/card endpoints:

```text
GET /health
GET /.well-known/agent.json
```

Trusted SharedOS-host backend endpoints:

```text
POST /v1/trust-snapshot
POST /v1/probe-observation     # internal active-canary record step
POST /v1/verify-delivery
POST /v1/best-execution
GET  /v1/audit
GET  /v1/audit/{receipt}
```

Direct development requests to `/v1/*` must send:

```text
X-Counterparty-Internal-Token: $COUNTERPARTY_INTERNAL_TOKEN
```

## Live Arena preflight

Code readiness is not enough for Shared OS eligibility, so v0.3 includes a fail-closed deployment gate:

```bash
python scripts/arena_preflight.py --live
```

It refuses `READY=true` unless all of these exist and agree:

- private internal token
- SharedOS tenant ID
- SharedOS owner address
- personal agent SharedNet node ID
- non-placeholder Router / Probe / Judge / Attestor production addresses
- HTTPS public deployment URL
- live `/health` reporting v0.3.0
- live agent card with the exact Counterparty purpose string and production addresses

This is intentionally strict. Source code cannot manufacture organizer-issued tenant/node IDs or a SharedOS Cloud audit trail; once those event credentials are provisioned, the preflight turns live completeness into a machine-verifiable release condition.

## Arena autonomous loop

**Round 1 — create the market data**

1. Discover unfamiliar services.
2. Buy Trust Snapshot on candidates; each authorized call can actively create fresh protocol evidence.
3. Use `explore` when the market is still empty.
4. Try other products as required by the event and verify deterministic deliveries.
5. Build the first task-specific reputation graph before the market round.

**Round 2 — monetize the graph**

1. Other agents buy Trust Snapshot before risking larger spends.
2. Safe Best Execution can route a first small purchase from canary evidence instead of deadlocking on zero history.
3. Buyers purchase the recommended provider.
4. Verify Delivery turns that trade into stronger task evidence.
5. The next Best Execution is better because the previous trade happened.

Every transaction can make the next transaction easier to price. That is why Counterparty is positioned as **the trust and best-execution layer for the agent economy**, not as a one-off verifier.

## Repository guide

- `counterparty/` — deterministic verification, dual-layer reputation, routing, durable SQLite evidence, API.
- `sharedos/` — SharedOS host, role drivers, recipient-scoped message grants, SDK contract tests.
- `tests/test_flywheel.py` — cold-start → provisional → verified market transition.
- `scripts/arena_demo.py` — one-command judge demo.
- `scripts/arena_preflight.py` — fail-closed real deployment gate.
- `scripts/stress_test.py` — concurrent mixed load + replay storm.
- `docs/ARCHITECTURE.md` — evidence/authority architecture.
- `docs/THREAT_MODEL.md` — hostile Arena assumptions and controls.
- `docs/ARENA_RUNBOOK.md` — no-human-in-the-loop operating plan.
- `docs/SUBMISSION_CHECKLIST.md` — event eligibility and owner-supplied deployment fields.

## Release boundary

The **product implementation and cold-start market flywheel are in this repository**. Hackathon eligibility still requires the organizer-provisioned SharedOS Cloud tenant/owner data, real product turns in the Cloud audit, final SharedNet node/service registration, and production addresses. `scripts/arena_preflight.py --live` is the stop/go gate for that final external step.

## License

MIT. See `NOTICE.md` for research attribution. No third-party project source code is vendored into this repository.
