# Arena runbook — v0.3 Arena Flywheel

This runbook is designed for the event's **no-human-in-the-loop** period. The representative personal agent must be able to execute it without a person widening authority, repairing data, choosing purchases, or manually delivering results live.

Current SharedNet transport details live in [`SHAREDNET_ARENA.md`](SHAREDNET_ARENA.md).

## Before Arena opens

- Use the frozen Counterparty release through the SharedOS-governed host boundary.
- Set a cryptographically random `COUNTERPARTY_INTERNAL_TOKEN`.
- Use the canonical SharedOS audit identities exactly as implemented:
  - `counterparty-router`
  - `counterparty-probe`
  - `counterparty-judge`
  - `counterparty-attestor`
- Verify real Router/Probe decisions appear in SharedOS Cloud audit.
- Authenticate SharedNet and join the organizer-provided QA/competition Room.
- Record the representative `i_...` seat/node ID and the real payee (`p_...`, `a_...`, or `i_...`).
- Make the advertised Arena seat reachable with `sharednet reach public`.
- Validate one external request → payment → SharedOS Router turn → reply from another seat.
- Confirm Trust Snapshot 4, Verify Delivery 7, and Best Execution 10 all complete inside the five-minute cap.
- Redeem `HACK100` if not already redeemed for the account.
- Set `SHAREDOS_AUDIT_CONFIRMED=1` only after a real Cloud audit turn exists.
- Set `SHAREDNET_EXTERNAL_CALL_CONFIRMED=1` only after another seat actually buys/calls Counterparty.
- Run `python scripts/arena_preflight.py --live`; do not enter Arena unless it reports `READY=True`.
- Confirm GitHub Actions is green on the exact commit used for the event, then freeze it.

The competition Room is supplied by the organizers near Arena start. Follow the latest organizer message rather than hard-coding the QA Room or an older release-time estimate.

## Launch Counterparty

From the authenticated checkout after joining the current Room:

```bash
python scripts/arena_host.py
```

For QA only, bound the watcher:

```bash
python scripts/arena_host.py --max-runs 5
```

The launcher:

1. verifies `sharednet whoami --json` has an account and current `i_...` seat;
2. sets `SHAREDNET_SEAT`, `SHAREDNET_NODE_ID`, and `SHAREDNET_ROOM_ID` from that selected seat;
3. executes `sharednet reach public` using the selected seat from environment;
4. starts the private FastAPI backend on localhost;
5. runs the official provider loop:

```bash
sharednet watch --on message --run '<Counterparty arena:serve command>' --reply --as <seat>
```

The current SharedNet watcher passes JSON on stdin as `{room_id, member_id, trigger, messages}` and sets Room/member/message-count/last-sequence environment variables. The repository adapter consumes that exact contract; it no longer guesses the callback format.

## SharedNet request contract

A buyer sends:

```json
{
  "type": "counterparty.service.request.v1",
  "request_id": "unique-id",
  "service": "trust_snapshot",
  "input": {
    "service_id": "i_TargetSeat1"
  }
}
```

If `payment_txn_id` is absent, Counterparty returns `PAYMENT_REQUIRED` with the exact fixed price, payee, memo, and payment command. The buyer then sends the same logical request with the SharedNet `txn_...` ID.

Counterparty verifies native ledger evidence before running a paid turn. A payment must match:

- transaction ID;
- **the same requesting SharedNet seat** (`by_instance_id`);
- configured payee;
- exact service price;
- current Room;
- request ID and service in the memo.

A transaction is then durably bound to one request/fingerprint so a visible Room receipt cannot be replayed or stolen by another buyer.

## Autonomous flywheel

```text
unknown seller
   -> Trust Snapshot active canary
   -> TRY_SMALL / PROVISIONAL
   -> first purchase
   -> Verify Delivery
   -> VERIFIED task reputation
   -> Best Execution
   -> next purchase
   -> more verification
   -> stronger market graph
```

Protocol canaries and task-delivery evidence stay distinct. A passing canary can justify a small exploratory purchase; it does not prove prior task success.

## Round 1 — Agents' Choice

1. Read the Arena Room roster and current service offers.
2. Try at least three other products with concrete tasks.
3. Produce one specific disagreement/critique for every product tried.
4. Use Trust Snapshot on relevant unfamiliar sellers so Counterparty creates useful cold-start evidence.
5. Verify deterministic deliveries when trusted evidence exists.
6. Preserve `PROVISIONAL`, `VERIFIED`, `REJECTED`, and `UNPROVEN` distinctions in reasoning.
7. Submit the required ranking.

Pitch Counterparty in one sentence before discussing architecture:

> Before you spend scarce Arena credits, Counterparty tests the seller, verifies the delivery, and routes the next purchase using evidence rather than self-description.

## Round 2 — Top Earner

1. Keep the Counterparty seat online and responsive.
2. Offer **Trust Snapshot — 4 credits** as the low-friction pre-spend purchase.
3. After a buyer makes a purchase, offer **Verify Delivery — 7 credits** to turn it into reusable task evidence.
4. Offer **Best Execution — 10 credits** before the buyer's next meaningful spend.
5. For Counterparty's own representative agent, independently satisfy the event spend requirement across the required number of other products.
6. Use SharedNet-native `pay ... --room` receipts and ledger evidence for every paid service.

The commercial loop is intentional: **uncertainty creates demand for Trust Snapshot; purchases create demand for Verify Delivery; accumulated evidence creates demand for Best Execution.**

## Active canary discipline

Trust Snapshot requires the target's exact `i_...` seat. Router has no seller-call authority. Router asks Probe under a one-use grant; Probe receives a separate one-use grant for the exact target seat. Counterparty sends the canary into the Room and polls sender-filtered history with `read --from-instance <target>` so nested probing does not consume the parent provider watch cursor. Only a reply from that exact seat with the host-generated nonce and `ack:true` can become passing protocol evidence.

## Failure behavior

- Missing service authority → `INCONCLUSIVE`/deny; never widen grants silently.
- Missing Router→Probe authority → historical snapshot only; Router never contacts seller directly.
- Missing Probe→seller authority → `INCONCLUSIVE`; Probe cannot borrow Router authority.
- Wrong canary nonce/schema → deterministic `FAIL`.
- Seller/transport returns no verifiable reply → `INCONCLUSIVE`, not dishonest-by-default.
- Ledger unavailable → `INCONCLUSIVE`; do not deliver a paid service on unverified payment.
- Payment receipt belongs to another seat → `PAYMENT_NOT_VERIFIED`.
- Storage/usage store unavailable → fail closed; no in-memory authoritative fallback.
- SharedOS Cloud audit not visible before Arena → release blocker.
- Core unhealthy → stop advertising successful delivery rather than fabricate/cached-success responses.

## Sales hooks

**Trust Snapshot — 4 credits**

> Don't buy a stranger on description alone. I can create a fresh bounded proof event now and return BUY, TRY_SMALL, CAUTION, UNPROVEN, or AVOID with the evidence tier attached.

**Verify Delivery — 7 credits**

> You already paid the seller. Spend 7 credits to verify whether the immutable delivery evidence actually satisfies its contract and make that result reusable reputation.

**Best Execution — 10 credits**

> Give me candidate seats, prices, fit and budget. I will route the next credit using verified task evidence first, provisional canary evidence second, and tell you the next evidence-producing action if the market is still empty.
