# Counterparty v0.3 — Arena Flywheel

> **Before your agent spends a credit, Counterparty proves who can do the job.**

Counterparty is the **trust, verification, and best-execution layer for SharedNet**. It turns scarce-credit agent markets from “every seller describes itself” into a market where buyers can demand fresh proof, verify delivery, and route the next credit using evidence that compounds after every trade.

The product is deliberately narrow: exactly three paid services, one SharedOS purpose string, bounded role-specific authority, replay-safe evidence, and a real SharedNet Room provider loop.

## 30-second judge story

```text
UNKNOWN SELLER
     │
     │  Trust Snapshot — 4 credits
     ▼
BOUNDED ACTIVE CANARY
Router ──messages.request──> Probe ──exact one-use target authority──> Seller
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
     └──────────── routes the next credit with stronger evidence
```

Counterparty does not pretend a canary proves task quality. Protocol evidence and real-delivery evidence remain separate.

## Arena services

| Service | Price | What the buyer gets |
|---|---:|---|
| `trust_snapshot` | **4 credits** | Fresh pre-purchase evidence. Returns `BUY / TRY_SMALL / CAUTION / UNPROVEN / AVOID`, evidence tier, confidence, protocol evidence, and audit receipt. |
| `verify_delivery` | **7 credits** | Independent post-purchase verification. Returns `PASS / FAIL / INCONCLUSIVE`, evidence details, replay status, reputation-update status, and audit receipt. |
| `best_execution` | **10 credits** | Ranked providers under a credit budget, preferring VERIFIED task evidence and discounting PROVISIONAL canary evidence. |

The commercial loop is:

**Trust Snapshot creates evidence → Best Execution routes a first spend → Verify Delivery strengthens evidence → stronger evidence drives the next Best Execution.**

## How another agent calls Counterparty on SharedNet

Organizer guidance clarified that Arena discovery is **Room-based**, not a global service registry, and calls are **messages**, not RPCs.

Counterparty joins the Arena Room with a public SharedNet seat (`i_...`). Other agents discover that seat from the Room roster or the published seat ID, then send a request message such as:

```json
{
  "type": "counterparty.service.request.v1",
  "request_id": "buyer-generated-unique-id",
  "service": "trust_snapshot",
  "input": {
    "service_id": "i_TargetSeat1"
  }
}
```

The live provider loop uses the official SharedNet watcher contract:

```bash
sharednet watch --on message --run '<command>' --reply
```

The watcher passes JSON on stdin as:

```json
{
  "room_id": "rom_...",
  "member_id": "i_...",
  "trigger": "message",
  "messages": []
}
```

For a paid request, Counterparty returns the fixed price and the configured SharedNet payee address. The buyer pays through SharedNet with the request ID in the memo. Counterparty verifies the payment from SharedNet ledger evidence before executing the paid SharedOS Router turn; buyer-authored text saying “paid” is never accepted as proof.

SharedNet address classes are intentionally kept distinct:

- `i_...` — live Instance/seat; this is what another agent calls.
- `a_...` — agent/tag address.
- `p_...` — principal/account address; suitable for payment.

All three can be payment targets when SharedNet allows it, but they are not treated as interchangeable identities inside Counterparty.

## SharedOS is load-bearing

The active proof flow depends on explicit authority separation:

```text
SharedNet buyer
      │
      ▼
Counterparty Router
  product decision authority
  service tools
  one bounded ticket to Counterparty Probe
  NO direct seller-call authority
      │
      ▼
Counterparty Probe
  exact target authority
  bounded maxUses
  NO reputation-write authority
  NO attestation authority
      │
      ▼
Target SharedNet seat
```

Roles:

```text
counterparty-router     decision/product-service authority; no seller-call authority
counterparty-probe      bounded exact-target seller-call authority only
counterparty-judge      sealed-evidence authority; no seller calls
counterparty-attestor   receipt authority only; no seller calls
```

Purpose string:

```text
counterparty.verify-and-route-sharednet-services
```

The Router generates the canary nonce and asks only the Probe. The Probe is the only role allowed to contact the target seller. For Arena transport, the target service identifier is mapped to the seller's exact SharedNet `i_...` seat. Canary replies are accepted only from that seat.

## Evidence semantics

Counterparty stores two evidence classes separately:

- **Protocol canary evidence**: proves a seller answered a bounded current challenge correctly. It can produce `PROVISIONAL` evidence and justify a small first purchase.
- **Verified delivery evidence**: proves an actual buyer delivery satisfied its host-owned task contract. It produces the stronger `VERIFIED` task reputation.

Trust invariants:

- Missing evidence never becomes `PASS`.
- A canary must match a server-generated nonce and server-owned schema/assertions.
- Buyers cannot submit their own trust score or reputation counts.
- Failed-canary majority becomes `REJECTED` and is not routeable in safe mode.
- Repeated canaries and deliveries cannot increment reputation twice.
- Verification/reputation/audit writes are transactional.
- SharedOS authorization is deny-by-default and bounded grants use atomic `maxUses` consumption.
- Escalation is separately granted and never silently widens authority.
- The private FastAPI core is not the public SharedNet surface.

## Live Arena provider implementation

The merged Arena release includes the real provider boundary, not just an API demo:

- `sharedos/arena-service.ts` — paid SharedNet request → SharedOS Router turn orchestration.
- `sharedos/sharednet-cli.ts` — SharedNet CLI transport, sender-scoped canary polling, and ledger access.
- `sharedos/arena-store.ts` — durable SharedOS grant usage/audit plus replay-safe payment/request binding.
- `sharedos/arena-service.test.ts` — service-loop and payment-boundary tests.
- `scripts/arena_host.py` — cross-platform launcher for the private backend and SharedNet watcher.
- `docs/SHAREDNET_ARENA.md` — organizer-confirmed Room/message/payment model.

The active canary polling path uses sender-filtered SharedNet reads instead of consuming the parent watcher cursor, so a nested Probe cannot steal unrelated Arena messages from the provider loop.

## Engineering evidence

The release gates include:

- Python 3.11 / 3.12 / 3.13 tests
- Ruff
- Bandit
- pip-audit
- coverage >= 90%
- Arena flywheel demo
- concurrent stress + replay storm
- autonomous two-round Arena rehearsal
- accelerated two-hour-equivalent restart soak
- SharedOS TypeScript typecheck + contract suites
- live Arena service-loop/payment-boundary tests
- container build

The hardened CI stress run executes **1,500 mixed requests at concurrency 48 with 0 HTTP failures**. The replay storm produces **exactly one reputation update**. The accelerated soak processes **2,400 events across a 7,200-second-equivalent workload with restart segments** while preserving the audit chain.

These are local engineering measurements, not SharedOS Cloud throughput claims.

Run the deterministic market demo:

```bash
python scripts/arena_demo.py --json
```

## Run the private core locally

```bash
export COUNTERPARTY_INTERNAL_TOKEN='replace-with-a-cryptographically-random-secret'
python -m uvicorn counterparty.app:app --host 127.0.0.1 --port 8000
```

Trusted backend endpoints:

```text
POST /v1/trust-snapshot
POST /v1/probe-observation
POST /v1/verify-delivery
POST /v1/best-execution
GET  /v1/audit
GET  /v1/audit/{receipt}
```

Direct development requests to `/v1/*` require:

```text
X-Counterparty-Internal-Token: $COUNTERPARTY_INTERNAL_TOKEN
```

## Arena launch

The organizer's QA Room is for connectivity testing. The competition Room link is supplied separately near Arena start and must not be hard-coded.

The final Arena host is launched from a SharedNet-authenticated machine with the real seat and account/payment identity. `scripts/arena_host.py` verifies the local SharedNet identity, exposes the seat for reachability, starts the private backend, and runs the official watcher loop.

Exact operational details live in:

```text
docs/SHAREDNET_ARENA.md
docs/ARENA_RUNBOOK.md
docs/SUBMISSION_CHECKLIST.md
```

## Live Arena preflight

Code readiness is not enough for hackathon eligibility:

```bash
python scripts/arena_preflight.py --live
```

The current preflight refuses `READY=true` unless the deployment has the facts that actually matter for the organizer-confirmed Arena model:

- a private internal backend token;
- the representative agent's real SharedNet node/seat ID;
- a real SharedNet payee address;
- non-placeholder Router / Probe / Judge / Attestor product-agent addresses;
- explicit confirmation that real Counterparty turns are visible in the SharedOS Cloud audit;
- explicit confirmation that another SharedNet seat called Counterparty and received a reply.

A public HTTPS URL is **optional** because SharedNet invocation is message-based. When a URL is configured, preflight validates it strictly, including `/health`, `/.well-known/agent.json`, the exact purpose string, product-agent addresses, seat ID, and payee address.

A SharedOS tenant ID or owner-address environment variable is **not** a Counterparty preflight requirement. The latest organizer guidance says participants should use the current SharedOS model rather than wait for tenant provisioning. This does **not** remove the Devpost requirement that judges must be able to find real product turns in the SharedOS Cloud audit trail.

## Arena autonomous loop

**Round 1 — create the first market data**

1. Join the Arena Room and read its roster.
2. Try at least three other products with concrete tasks.
3. Record a specific disagreement/critique for each product tried.
4. Use Trust Snapshot on relevant unfamiliar sellers so cold-start evidence exists before Round 2.
5. Submit the required ranking.

**Round 2 — monetize the graph**

1. Keep Counterparty's public seat online and responsive.
2. Offer the 4-credit Trust Snapshot as the low-friction pre-spend purchase.
3. Use Safe Best Execution to route small initial spends from provisional evidence.
4. Verify real deliveries so sellers can graduate to VERIFIED evidence.
5. Spend the required Arena credits across the required number of other products with the representative personal agent.

The representative agent must operate without a human in the loop during the Arena.

## Release boundary

The **product implementation, SharedOS authority model, payment boundary, SharedNet provider loop, cold-start flywheel, and hardening tests are complete in this repository**.

The remaining eligibility facts are external and must be real, not fabricated:

- authenticated SharedNet account and live `i_...` seat;
- real payee address;
- competition Room membership;
- real Counterparty product turns visible in SharedOS Cloud audit;
- one external SharedNet call proving another seat can buy and receive a Counterparty service;
- final node/seat ID, product-agent addresses, and team-lead Discord username in the submission.

`python scripts/arena_preflight.py --live` is the final stop/go gate.

## Repository guide

- `counterparty/` — deterministic verification, dual-layer reputation, routing, durable SQLite evidence, private API.
- `sharedos/` — SharedOS host, role drivers, bounded grants, SharedNet Arena service loop, durable authority/audit state.
- `scripts/arena_demo.py` — market-transition demo.
- `scripts/arena_rehearsal.py` — autonomous two-round rehearsal.
- `scripts/arena_soak.py` — restart/soak hardening.
- `scripts/arena_preflight.py` — fail-closed live deployment gate.
- `scripts/arena_host.py` — Arena host launcher.
- `docs/SHAREDNET_ARENA.md` — SharedNet Arena transport/payment contract.
- `docs/ARENA_RUNBOOK.md` — no-human-in-the-loop operating plan.
- `docs/SUBMISSION_CHECKLIST.md` — final eligibility checklist.

## License

MIT. See `NOTICE.md` for research attribution. No third-party project source code is vendored into this repository.
