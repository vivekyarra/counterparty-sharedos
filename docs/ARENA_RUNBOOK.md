# Arena runbook

This runbook is intentionally designed around the event's **no-human-in-the-loop** period.

## Before Arena opens

- Deploy Counterparty core behind the SharedOS host/Cloud boundary.
- Set a cryptographically random `COUNTERPARTY_INTERNAL_TOKEN` in both private components.
- Configure durable SharedOS grant, bounded-use, namespace, delegation, and audit stores.
- Set final `counterparty/router`, `counterparty/probe`, `counterparty/judge`, and `counterparty/attestor` addresses.
- Verify real product turns appear in SharedOS audit.
- Register/discover the three services on SharedNet with their final prices.
- Confirm `/health` and an end-to-end paid/callable service round trip.
- Run `pytest`, the SharedOS contract suite, and the stress test against the release commit.
- Freeze the release commit used for the Arena. Do not live-patch during the event.

## Round 1 — evidence acquisition

Counterparty's representative agent should satisfy the event obligations while deliberately collecting market evidence:

1. Try at least three other products.
2. For each, use a task that can yield specific evidence rather than generic conversation.
3. Record one concrete disagreement/critique for every product tried.
4. Verify deliveries where a deterministic contract can be expressed.
5. Use `explore` mode for services with no prior observations.
6. Submit the required ranking.

The product must not manufacture a negative score from an unavailable service. Availability failure is its own evidence and should be reported as `INCONCLUSIVE` unless the service contract explicitly promised availability within the tested window.

## Round 2 — market execution

The representative agent must independently satisfy the hackathon spend requirement. Counterparty should help it allocate, not prevent it from spending:

1. Pull candidate services and prices from SharedNet.
2. Buy `Trust Snapshot` / use local observations before larger purchases when useful.
3. Use `safe` Best Execution for candidates with verified history.
4. Spend at least the event-required amount across at least the event-required number of distinct products.
5. Verify high-value deliveries after purchase where possible.

## Failure behavior

- **Missing authority:** terminate with SharedOS escalation / `INCONCLUSIVE`; do not widen authority.
- **Target unavailable:** `INCONCLUSIVE`, no positive reputation update.
- **Backend storage unavailable:** fail closed; no in-memory fallback for authoritative reputation.
- **Grant usage store unavailable:** SharedOS denial is correct; do not switch to unbounded grants.
- **Audit sink failure:** treat as release-blocking before Arena. During Arena, preserve the SharedOS result and diagnostic policy; do not ask a human to repair live.
- **Counterparty core unhealthy:** host should stop advertising successful delivery, not return cached invented results.

## Pitch loop

Counterparty's shortest machine-to-machine pitch:

> You have scarce credits and every seller describes itself. Counterparty gives you independent evidence before you buy, verifies what you received after you buy, and turns verified outcomes into a task-specific reputation signal for the next purchase. Missing evidence is never a pass, and SharedOS bounds every probe.
