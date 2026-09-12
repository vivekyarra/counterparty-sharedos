# Counterparty — 90-second judge demo

## Goal

Make the invisible security architecture visible as a market outcome.

The judge should leave with one sentence:

> **Counterparty creates the first trustworthy signal for an unknown seller, then makes every verified trade improve the next buying decision.**

## 0:00–0:15 — Show the problem

Say:

> Every seller in an agent marketplace can describe itself. The buyer still has scarce credits and no reason to believe the claim. Static reputation has a fatal cold-start problem: on day one, everybody is unknown.

Run:

```bash
python scripts/arena_demo.py
```

Point to:

```text
seller-alpha: UNPROVEN
seller-beta:  UNPROVEN
```

## 0:15–0:35 — Show the active proof

Say:

> A Counterparty Trust Snapshot does not just read a database. The Router gets one ticket to our Probe. The Probe gets one different ticket to exactly one seller. The Router can never spend its ticket directly on that seller.

Point to the SharedOS path:

```text
Router --messages.request--> Probe --messages.request--> seller-alpha
```

Then point to the outcome:

```text
bounded canary: PASS
seller-alpha: TRY_SMALL [PROVISIONAL]
```

For seller-beta the demo intentionally returns the wrong nonce:

```text
seller-beta canary: FAIL
seller-beta: AVOID
```

Say:

> That is cold start solved without pretending the canary is task history. Protocol evidence stays separate and is visibly labeled provisional.

## 0:35–0:55 — Show the first safe spend

The demo runs Safe Best Execution across:

- seller-alpha — passing canary
- seller-beta — failed canary
- seller-gamma — no evidence

Point to:

```text
Safe Best Execution -> seller-alpha
route tier: PROVISIONAL
```

Say:

> Counterparty can now route the first small purchase instead of deadlocking on zero history. The recommendation is actionable but still honestly provisional.

## 0:55–1:15 — Show the evidence compounding

The demo verifies paid deliveries from seller-alpha under a deterministic schema and assertions.

Point to:

```text
seller-alpha: BUY [VERIFIED]
Safe Best Execution -> seller-alpha
route tier: VERIFIED
```

Say:

> The purchase creates stronger task-specific evidence. That makes the next best-execution decision better. Every verified trade can improve the next trade.

## 1:15–1:30 — Close on the moat

Say:

> Counterparty is not another agent competing for tasks. It is the trust and best-execution layer every agent can buy in the middle of a task. Trust Snapshot creates the first evidence, Verify Delivery upgrades it, and Best Execution turns it into spend. SharedOS makes the separation enforceable instead of aspirational.

End with:

> **Before your agent spends a credit, Counterparty proves who can do the job.**

## Judge follow-ups

### “Can the buyer fake a passing canary?”

No. The Router creates the nonce; the Probe observes the raw target reply; the backend validates a server-owned contract. The buyer cannot choose the nonce, assertions, success count, or stored trust score.

### “Does one canary mean the seller is good at my task?”

No. Canary evidence is stored separately and only creates a `PROVISIONAL` signal. Real task deliveries create the `VERIFIED` signal.

### “Can the Router call the seller directly?”

No. Its messaging grant names `counterparty-probe` as the exact recipient. The Probe's separate grant names the seller service as the exact recipient. Contract tests exercise both refusals.

### “What if the Probe ticket is replayed?”

`maxUses` is atomic at the SharedOS authorization layer, and the backend independently deduplicates the canary by `probe_id` plus evidence fingerprint.

### “What happens if nobody has evidence?”

Safe Best Execution returns `INCONCLUSIVE` plus a machine-actionable next step telling the buyer to purchase Trust Snapshot on candidate sellers. The uncertainty becomes a revenue-generating evidence-acquisition action instead of a dead end.
