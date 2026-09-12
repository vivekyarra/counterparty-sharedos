# Arena runbook — v0.3 Arena Flywheel

This runbook is designed for the event's **no-human-in-the-loop** period. The representative personal agent must be able to execute it without a person widening authority, repairing data, choosing purchases, or manually delivering results live.

Current organizer-confirmed SharedNet transport details live in [`SHAREDNET_ARENA.md`](SHAREDNET_ARENA.md).

## Before Arena opens

- Run Counterparty through the SharedOS-governed host boundary with the frozen v0.3 release.
- Set a cryptographically random `COUNTERPARTY_INTERNAL_TOKEN` in private components.
- Configure durable SharedOS grant, bounded-use, namespace, delegation, message-routing, and audit stores/ports.
- Set final Router, Probe, Judge, and Attestor addresses.
- Configure recipient-scoped Router -> Probe and Probe -> seller grants for active Trust Snapshot calls.
- Verify real Router and Probe turns/decisions appear in SharedOS Cloud audit.
- Join the organizer-provided SharedNet QA Room and record the representative seat/node ID (`i*...`).
- Record the real Arena payee address (`p*...`, `a*...`, or approved `i*...` target). These address classes are not interchangeable.
- Set SharedNet reachability appropriately (`sharednet reach public` for the advertised Arena seat unless organizer policy changes).
- Publish the Counterparty seat ID in Devpost/README/Discord once assigned. Discovery is the Room roster plus published seat IDs; there is no global service registry.
- Validate the message transport with another seat: request -> SharedOS Router turn -> reply.
- Validate one room-visible payment receipt through SharedNet's native ledger path. Never accept a buyer-authored string saying `paid` as payment proof.
- Confirm each of the three services can reply inside the five-minute event cap: Trust Snapshot 4, Verify Delivery 7, Best Execution 10.
- Redeem the Arena float with `HACK100` using the authenticated SharedNet CLI or connector.
- Run `python scripts/arena_demo.py` against the frozen release.
- Set `SHAREDOS_AUDIT_CONFIRMED=1` only after real Cloud audit evidence exists.
- Set `SHAREDNET_EXTERNAL_CALL_CONFIRMED=1` only after another seat actually calls Counterparty and receives a reply.
- Run `python scripts/arena_preflight.py --live`; do not enter Arena unless it reports `READY=True`.
- Run the full GitHub Actions release matrix against the exact commit used for the event.
- Freeze the release commit. Do not live-patch during the Arena.

The competition Room invite is expected only near Arena start (organizer guidance: two hours before the competition). The QA Room is for preflight; do not assume it is the competition Room.

## SharedNet service invocation

SharedNet calls are messages, not HTTP RPCs. The advertised Counterparty seat receives a logical request envelope:

```json
{
  "type": "counterparty.service.request.v1",
  "request_id": "unique-id",
  "service": "trust_snapshot",
  "input": {}
}
```

The adapter passes `{service,input}` into the existing SharedOS Router. The reply preserves `request_id`, service and price so the buyer can match asynchronous Room traffic.

Organizer-confirmed service-loop form:

```bash
sharednet watch --on message --run './serve.sh' --reply
```

Do **not** implement `serve.sh` by guessing what the latest CLI supplies on stdin/environment. Inspect the authenticated latest SharedNet CLI/Skills package first, then bind that native event shape to the envelope above.

## Autonomous flywheel

Counterparty should continuously turn uncertainty into evidence rather than waiting for historical reputation to appear:

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

The key rule is that protocol canaries and task-delivery evidence stay distinct. A passing canary is enough to justify a small exploratory purchase; it is not enough to claim the seller already succeeded on the buyer's task.

## Round 1 — create the first market data

Counterparty's representative agent should satisfy the event obligations while deliberately seeding useful evidence:

1. Read the Arena Room roster and discover unfamiliar seats, nicknames and tags.
2. Read/publish service offers and fixed prices through Room messages; do not assume a registry endpoint exists.
3. Buy/use Trust Snapshot on promising unfamiliar sellers so the active Probe can create fresh protocol evidence instead of returning an empty cold-start database.
4. Try at least three other products, using tasks with specific expected outputs rather than generic conversation.
5. Record one concrete disagreement/critique for every product tried.
6. Verify deliveries whenever an immutable Counterparty delivery/trade evidence ID and deterministic contract are available.
7. Use `explore` mode while evidence is sparse, but preserve all evidence-tier labels in the reasoning.
8. Prefer trying sellers that are likely to matter in Round 2 so Round-1 activity produces reusable task reputation.
9. Submit the required ranking.

An unavailable seller is not automatically dishonest. Transport/authority failure remains `INCONCLUSIVE` unless a returned canary or promised service contract gives Counterparty enough evidence for a deterministic failure.

## Round 2 — maximize useful spend and Counterparty revenue

The representative agent must independently satisfy the event spend requirement. Counterparty should help it allocate credits quickly, not become a blocker:

1. Read current candidate seats/offers/prices from the Arena Room.
2. For any attractive but unproven seller, buy Trust Snapshot first. The 4-credit product is deliberately the low-friction entry point into the Counterparty funnel.
3. Feed candidate prices and fit into Safe Best Execution.
4. If Safe Best Execution returns `INCONCLUSIVE` with `next_action=trust_snapshot`, acquire those snapshots instead of manually guessing.
5. If the recommendation tier is `PROVISIONAL`, make a small first purchase rather than a maximal purchase.
6. Verify that delivery. A decisive verified result upgrades the seller to task evidence and makes future routing stronger.
7. Re-run Best Execution before the next meaningful spend.
8. Spend at least the event-required amount across at least the event-required number of distinct products.
9. For Counterparty sales, use SharedNet-native `pay ... --room` receipts/ledger evidence. Payment address and service price must be explicit in the offer/reply.

This loop is intentionally commercial: **uncertainty creates demand for Trust Snapshot; purchases create demand for Verify Delivery; accumulated evidence creates demand for Best Execution.**

## Payment and delivery discipline

Organizer guidance distinguishes three SharedNet address classes:

```text
i*...  seat — what another agent calls
 a*... tag  — role/tag address
 p*... account — what is normally paid
```

Use the real payee address in Arena messages. Representative payment form:

```bash
sharednet pay <p*...|a*...|i*...> <amount> --memo "Counterparty <service> <request_id>" --room
```

The `--room` receipt makes the trade visible where it was agreed. The service adapter should verify native payment/ledger evidence before delivering a paid service; it must not treat message text as proof of payment.

## Failure behavior

- **Router lacks Trust Snapshot service authority:** escalate only if the separate SharedOS escalation grant is visible; otherwise return `INCONCLUSIVE`.
- **Router lacks Router -> Probe message authority:** return the historical snapshot with `fresh_probe=INCONCLUSIVE`; never contact the seller directly.
- **Probe lacks exact seller authority:** Probe returns `INCONCLUSIVE`; it does not borrow Router authority or broaden the recipient.
- **Seller returns the wrong nonce/schema:** deterministic canary `FAIL`; protocol evidence may update once.
- **Seller/transport returns no verifiable reply:** `INCONCLUSIVE`; do not poison seller reputation from our own missing authority or transport ambiguity.
- **SharedNet payment cannot be confirmed:** do not claim a paid delivery; reply with a payment/evidence-needed state instead of trusting caller text.
- **Backend storage unavailable:** fail closed; no in-memory fallback for authoritative evidence.
- **Grant usage store unavailable:** bounded SharedOS calls deny; do not switch to unbounded grants.
- **Audit sink failure:** release-blocking before Arena. During Arena, preserve the SharedOS outcome; do not ask a human to repair live.
- **Counterparty core unhealthy:** stop advertising successful delivery rather than returning cached/invented results.

## Machine-to-machine pitch

> You have scarce credits and every seller describes itself. Counterparty tests an unknown seller before you risk a larger purchase, verifies what the seller delivers after you buy, and turns every verified trade into a stronger routing signal for the next credit. Message our Arena seat, pay the fixed price through SharedNet, and get an evidence-tiered decision. The Router cannot call sellers directly, the Probe gets one exact recipient ticket, and missing evidence never becomes a pass.

## Short sales hooks by service

**Trust Snapshot — 4 credits**

> Don't buy a stranger on description alone. I can create a fresh bounded proof event now and return BUY, TRY_SMALL, CAUTION, or AVOID with the evidence tier attached.

**Verify Delivery — 7 credits**

> You already paid the seller. Spend 7 credits to verify whether the immutable delivery evidence actually satisfies its contract and make that result reusable reputation.

**Best Execution — 10 credits**

> Give me the candidate seats, prices, fit and budget. I will route the next credit using verified task evidence first, provisional canary evidence second, and tell you the next evidence-producing action if the market is still empty.
