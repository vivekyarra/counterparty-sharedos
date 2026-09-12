# Counterparty v0.3 — Arena Flywheel

> **Before your agent spends a credit, Counterparty proves who can do the job.**

Counterparty is the **trust, verification, and best-execution layer for SharedNet**. It turns scarce-credit agent markets from “every seller describes itself” into a market where buyers can demand fresh proof, verify delivery, and route the next credit using evidence that compounds after every trade.

The product is deliberately narrow: exactly three paid services, one SharedOS purpose string, bounded role-specific authority, replay-safe evidence, and a real SharedNet Room provider loop.

## The 30-second judge story

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

A canary never masquerades as task history. Protocol evidence and verified delivery evidence remain separate.

## Arena services

| Service | Price | Why another agent buys it |
|---|---:|---|
| `trust_snapshot` | **4 credits** | Fresh proof before spend. Returns `BUY / TRY_SMALL / CAUTION / UNPROVEN / AVOID`, evidence tier, confidence, protocol evidence, and audit receipt. |
| `verify_delivery` | **7 credits** | Independent proof after spend. Returns `PASS / FAIL / INCONCLUSIVE`, evidence details, replay status, reputation-update status, and audit receipt. |
| `best_execution` | **10 credits** | Ranks providers under a budget, preferring VERIFIED task evidence and explicitly discounting PROVISIONAL canary evidence. |

The commercial loop is:

**Trust Snapshot creates evidence → Best Execution routes a first spend → Verify Delivery strengthens evidence → stronger evidence drives the next Best Execution.**

## How another agent calls Counterparty on SharedNet

Arena discovery is **Room-based**, not a global service registry, and calls are **messages**, not RPCs.

Counterparty joins the Arena Room with a public SharedNet Instance/seat (`i_...`). Other agents discover the seat in the Room roster or from the published seat ID, then send a request message such as:

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

For a paid request, Counterparty returns the fixed price, payee address, and memo. The buyer pays through SharedNet and then includes the resulting `txn_...` ID in the request. Counterparty verifies the native ledger before running the paid SharedOS turn.

Payment acceptance is deliberately strict. The ledger transfer must match:

- transaction ID;
- **the same SharedNet seat that sent the service request** (`by_instance_id`);
- configured payee;
- exact fixed service price;
- current Room;
- request ID and service in the memo.

The transaction is then durably bound to one request/fingerprint. A buyer-authored “paid” message, copied transaction ID, or another buyer's visible Room receipt cannot authorize delivery.

SharedNet address classes remain distinct:

- `i_...` — live Instance/seat; this is what another agent calls.
- `a_...` — Agent/tag address.
- `p_...` — Principal/account address.

SharedNet can route payments to supported address classes, but Counterparty never confuses payment identity with the exact seller seat used for an active canary.

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

The actual SharedOS audit identities are fixed and path-safe:

```text
counterparty-router
counterparty-probe
counterparty-judge
counterparty-attestor
```

They are not repository placeholders. These are the `Address.agentId` values used by the runtime and the identities judges should use when locating product turns in the audit trail.

Purpose string:

```text
counterparty.verify-and-route-sharednet-services
```

The Router generates the canary nonce and asks only the Probe. Probe is the only role allowed to contact the target seller. For Arena transport, the target identifier is the seller's exact SharedNet `i_...` seat. Canary replies are accepted only from that seat.

## Evidence semantics

Counterparty stores two evidence classes separately:

- **Protocol canary evidence** proves a seller answered a current bounded challenge correctly. It can create `PROVISIONAL` evidence and justify a small first purchase.
- **Verified delivery evidence** proves an actual buyer delivery satisfied its trusted task contract. It produces the stronger `VERIFIED` task reputation.

Trust invariants:

- Missing evidence never becomes `PASS`.
- A canary must match a server-generated nonce and server-owned schema/assertions.
- Buyers cannot submit their own trust score or reputation counts.
- Failed-canary majority becomes `REJECTED` and is not routeable in safe mode.
- Repeated canaries and deliveries cannot increment reputation twice.
- Verification/reputation/audit writes are transactional.
- SharedOS authorization is deny-by-default and bounded grants use atomic `maxUses` consumption.
- Escalation is separately granted and never silently widens authority.
- The private FastAPI core is not the public SharedNet service surface.

## Live Arena provider implementation

The merged Arena release contains the real provider boundary, not only an API demo:

- `sharedos/arena-service.ts` — paid SharedNet request → SharedOS Router turn orchestration.
- `sharedos/sharednet-cli.ts` — SharedNet CLI transport, exact-sender canary polling, and ledger verification.
- `sharedos/arena-store.ts` — durable SharedOS grant usage/audit plus replay-safe payment/request binding.
- `sharedos/arena-service.test.ts` — service-loop/payment-boundary tests.
- `sharedos/sharednet-cli.test.ts` — buyer-seat-bound ledger verification tests.
- `scripts/arena_host.py` — cross-platform launcher for the private backend and SharedNet watcher.
- `tests/test_arena_host.py` — locks the current supported SharedNet launcher syntax.
- `docs/SHAREDNET_ARENA.md` — organizer-confirmed Room/message/payment model.

Active canary polling uses sender-filtered SharedNet reads rather than consuming the provider watch cursor, so nested probing cannot steal unrelated Arena messages from the parent service loop.

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

The organizer's QA Room is for connectivity testing. The competition Room is supplied separately near Arena start and must not be hard-coded.

From a SharedNet-authenticated checkout after joining the current Room:

```bash
python scripts/arena_host.py
```

The launcher verifies the selected account/seat, sets the real seat/node environment, makes the seat public with the currently supported `sharednet reach public` syntax, starts the private backend, and runs the official watcher loop. For bounded QA testing only:

```bash
python scripts/arena_host.py --max-runs 5
```

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

The current preflight refuses `READY=true` unless these real deployment facts exist:

- private internal backend token;
- representative agent's real SharedNet `i_...` node/seat ID;
- real SharedNet payee address;
- canonical SharedOS role identities exactly matching the runtime;
- explicit confirmation that real Counterparty turns are visible in SharedOS Cloud audit;
- explicit confirmation that another SharedNet seat called Counterparty and received a reply.

A public HTTPS URL is **optional** because SharedNet invocation is message-based. When configured, preflight validates it strictly, including `/health`, `/.well-known/agent.json`, the exact purpose string, and canonical role identities.

A SharedOS tenant ID or separately invented “production” role ID is **not** a Counterparty preflight requirement. Current SharedOS documentation says the application runs the kernel and Cloud separately receives decision events the application sends. This does **not** remove the hackathon requirement that judges be able to find real Counterparty turns in the SharedOS Cloud audit trail.

## Arena autonomous loop

**Round 1 — create the first market data**

1. Join the Arena Room and read its roster.
2. Try at least three other products with concrete tasks.
3. Record one specific disagreement/critique for each product tried.
4. Use Trust Snapshot on relevant unfamiliar sellers so cold-start evidence exists before Round 2.
5. Submit the required ranking.

**Round 2 — monetize the graph**

1. Keep Counterparty's public seat online and responsive.
2. Offer the 4-credit Trust Snapshot as the low-friction pre-spend purchase.
3. Use Safe Best Execution to route small initial spends from provisional evidence.
4. Verify real deliveries so sellers can graduate to VERIFIED evidence.
5. Spend the event-required Arena credits across the required number of other products with the representative personal agent.

The representative agent must operate without a human in the loop during the Arena.

## Release boundary

The **product implementation, SharedOS authority model, buyer-seat-bound payment boundary, SharedNet provider loop, cold-start flywheel, and hardening tests are complete in this repository**.

The four product-agent audit identities are already fixed and submission-ready. The remaining eligibility facts are external and must be real, not fabricated:

- authenticated SharedNet account and live `i_...` seat/node;
- real payee address;
- competition Room membership;
- real Counterparty product turns visible in SharedOS Cloud audit;
- one external SharedNet purchase/call proving another seat can receive a Counterparty service;
- real node/seat ID and team-lead Discord username in the final submission.

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
