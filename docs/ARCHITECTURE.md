# Counterparty architecture

## Product thesis

Every SharedNet buyer has scarce credits and incomplete information. Counterparty sells three decisions that are valuable in the middle of another agent's task:

1. **Can I trust this service before I buy it?**
2. **Did the service I bought actually satisfy the contract?**
3. **Given my budget, where should I spend next?**

The core moat is not a scalar score. It is the accumulating mapping:

```text
task → provider → delivery → independent evidence → outcome → reputation → next purchasing decision
```

## Security invariant

> **Unknown is not safe.**

Every probe returns `PASS`, `FAIL`, or `INCONCLUSIVE`. Timeouts, missing authority, unavailable providers, malformed schemas, source-fetch failures, insufficient observations, and parser failures must not be promoted to success.

## Trust boundary

```text
UNTRUSTED                                    TRUSTED

SharedNet caller
     │
     │ message / request data only
     ▼
┌─────────────────────┐
│ SharedOS host       │ ← authenticated identity / trusted AccessContext
│                     │ ← trusted GrantSource
│ 3 authorization     │ ← atomic GrantUsageStore
│ gates per tool      │ ← durable AuditSink
└──────────┬──────────┘
           │ exact authorized call
           ▼
┌─────────────────────┐
│ Counterparty core   │ ← private internal token; no public bypass
└──────────┬──────────┘
           │
   ┌───────┼──────────────────────┐
   ▼       ▼                      ▼
verify   evidence/reputation    routing
```

A model response, target-agent message, HTTP body, service description, or claimed reputation never carries authority.

## Product agents

### Router

Can read Counterparty scorecards and produce a buying recommendation. It cannot invoke target services, mutate evidence, or mint grants.

### Probe

Receives narrow target-scoped authority for one evaluation purpose. `maxUses` bounds how many requests it can send to that exact target. It cannot alter the judge's decision or reputation database.

### Judge

Consumes sealed evidence. It has no target-call authority, preventing it from changing the experiment after seeing a result.

### Attestor

Publishes/returns the final receipt. It cannot invoke the target or rewrite evidence.

This separation makes the SharedOS grant graph part of Counterparty's trust claim rather than decorative integration.

## Evidence pipeline

1. Buyer requests a check under purpose `counterparty.verify-and-route-sharednet-services`.
2. SharedOS authenticates the actor from server-side state and loads grants from the trusted source.
3. Probe receives only the exact target reach required for the test, with bounded uses.
4. Raw observations are converted to typed evidence states.
5. Judge consumes evidence, never target authority.
6. Deterministic verification records an evidence fingerprint.
7. One database transaction inserts a unique reputation observation (if decisive) and its hash-chained audit event.
8. Replays retain an audit record but cannot increment reputation.
9. Router uses task fit, price, latency, trust, observation count, and uncertainty.

## Reputation

A Beta prior (`alpha=2`, `beta=2`) prevents a single lucky success from creating a high-confidence rating. Public trust is shrunk toward neutral when evidence is sparse. `safe` routing uses an approximate lower confidence bound, while `explore` routing permits controlled exploration of unseen services.

The caller never supplies authoritative successes, failures, trust, confidence, or observation counts.

## Storage and concurrency

The hackathon core uses SQLite with WAL mode. Audit updates use `BEGIN IMMEDIATE`, which serializes the hash-chain head and prevents duplicate sequence numbers under concurrency. Reputation observations have both a unique trusted `delivery_id` and a `(service_id, evidence_hash)` uniqueness constraint.

For multi-instance production deployment, use the SharedOS Cloud durable stores / a database with equivalent compare-and-set semantics. Process-local grant usage is not acceptable for bounded grants across multiple nodes.

## Evidence receipts

Each audit record includes:

- monotonic sequence number,
- event ID,
- timestamp,
- event type,
- structured payload,
- previous record hash,
- SHA-256 of the canonicalized record.

A caller receives the resulting hash as `audit_receipt`. `/v1/audit/{receipt}` can resolve it inside the trusted boundary.

Counterparty's application audit is supplementary evidence. The hackathon's authoritative SharedOS decision/turn trail still comes from the SharedOS host/Cloud audit.

## Arena economics

| Service | Credits | Economic rationale |
|---|---:|---|
| Trust Snapshot | 4 | Cheap pre-purchase risk filter. |
| Verify Delivery | 7 | Protects a larger purchase after delivery. |
| Best Execution | 10 | Spend 10 to avoid wasting a materially larger part of the 100-credit budget. |

This creates repeated reasons to buy Counterparty before and after purchases rather than a one-shot demo interaction.

## Immutable delivery evidence

The paid `verify_delivery` tool accepts only `delivery_id`. `TrustedDeliveryResolver` is a host-owned port that must read the immutable SharedNet message/execution record and original task contract. Provider identity, output, expected schema, assertions, and citations never come from the buyer payload on a reputation-bearing call. The Python backend is private to the SharedOS host.
