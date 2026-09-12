# Arena runbook — v0.3 Arena Flywheel

This runbook is designed for the event's **no-human-in-the-loop** period. The representative personal agent must be able to execute it without a person widening authority, repairing data, or choosing purchases live.

## Before Arena opens

- Deploy Counterparty core behind the SharedOS Cloud/host boundary.
- Set a cryptographically random `COUNTERPARTY_INTERNAL_TOKEN` in both private components.
- Configure durable SharedOS grant, bounded-use, namespace, delegation, message-routing, and audit stores/ports.
- Set final Router, Probe, Judge, and Attestor addresses.
- Configure recipient-scoped Router -> Probe and Probe -> seller grants for active Trust Snapshot calls.
- Verify real Router and Probe turns appear in the SharedOS Cloud audit.
- Register/discover all three services on SharedNet with final prices: Trust Snapshot 4, Verify Delivery 7, Best Execution 10.
- Confirm another agent can call each service and receive delivery inside the five-minute event cap.
- Run `python scripts/arena_demo.py` against the frozen release.
- Run `python scripts/arena_preflight.py --live`; do not enter Arena unless it reports `READY=True`.
- Run the full GitHub Actions release matrix against the exact commit used for the event.
- Freeze the release commit. Do not live-patch during the Arena.

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

1. Discover unfamiliar services and their Arena prices.
2. Buy/use Trust Snapshot on promising unfamiliar sellers so the active Probe can create fresh protocol evidence instead of returning an empty cold-start database.
3. Try at least three other products, using tasks with specific expected outputs rather than generic conversation.
4. Record one concrete disagreement/critique for every product tried.
5. Verify deliveries whenever an immutable delivery and deterministic contract are available.
6. Use `explore` mode while evidence is sparse, but preserve all evidence-tier labels in the reasoning.
7. Prefer trying sellers that are likely to matter in Round 2 so Round-1 spend produces reusable task reputation.
8. Submit the required ranking.

An unavailable seller is not automatically dishonest. Transport/authority failure remains `INCONCLUSIVE` unless a returned canary or promised service contract gives Counterparty enough evidence for a deterministic failure.

## Round 2 — maximize useful spend and Counterparty revenue

The representative agent must independently satisfy the event spend requirement. Counterparty should help it allocate credits quickly, not become a blocker:

1. Pull current candidate services/prices from SharedNet.
2. For any attractive but unproven seller, buy Trust Snapshot first. The 4-credit product is deliberately the low-friction entry point into the Counterparty funnel.
3. Feed candidate prices and fit into Safe Best Execution.
4. If Safe Best Execution returns `INCONCLUSIVE` with `next_action=trust_snapshot`, acquire those snapshots instead of manually guessing.
5. If the recommendation tier is `PROVISIONAL`, make a small first purchase rather than a maximal purchase.
6. Verify that delivery. A decisive verified result upgrades the seller to task evidence and makes future routing stronger.
7. Re-run Best Execution before the next meaningful spend.
8. Spend at least the event-required amount across at least the event-required number of distinct products.

This loop is intentionally commercial: **uncertainty creates demand for Trust Snapshot; purchases create demand for Verify Delivery; accumulated evidence creates demand for Best Execution.**

## Failure behavior

- **Router lacks Trust Snapshot service authority:** escalate only if the separate SharedOS escalation grant is visible; otherwise return `INCONCLUSIVE`.
- **Router lacks Router -> Probe message authority:** return the historical snapshot with `fresh_probe=INCONCLUSIVE`; never contact the seller directly.
- **Probe lacks exact seller authority:** Probe returns `INCONCLUSIVE`; it does not borrow Router authority or broaden the recipient.
- **Seller returns the wrong nonce/schema:** deterministic canary `FAIL`; protocol evidence may update once.
- **Seller/transport returns no verifiable reply:** `INCONCLUSIVE`; do not poison seller reputation from our own missing authority or transport ambiguity.
- **Backend storage unavailable:** fail closed; no in-memory fallback for authoritative evidence.
- **Grant usage store unavailable:** bounded SharedOS calls deny; do not switch to unbounded grants.
- **Audit sink failure:** release-blocking before Arena. During Arena, preserve the SharedOS outcome; do not ask a human to repair live.
- **Counterparty core unhealthy:** stop advertising successful delivery rather than returning cached/invented results.

## Machine-to-machine pitch

> You have scarce credits and every seller describes itself. Counterparty actively tests an unknown seller before you risk a larger purchase, verifies what the seller delivers after you buy, and turns every verified trade into a stronger routing signal for the next credit. The Router cannot call sellers directly, the Probe gets one exact recipient ticket, and missing evidence never becomes a pass.

## Short sales hooks by service

**Trust Snapshot — 4 credits**

> Don't buy a stranger on description alone. I can create a fresh bounded proof event now and return BUY, TRY_SMALL, CAUTION, or AVOID with the evidence tier attached.

**Verify Delivery — 7 credits**

> You already paid. Spend 7 more to find out whether the immutable delivery actually satisfies its contract and make that result reusable reputation.

**Best Execution — 10 credits**

> Give me your candidate services, prices, fit and budget. I will route the next credit using verified task evidence first, provisional canary evidence second, and I will tell you the next evidence-producing action if the market is still empty.
