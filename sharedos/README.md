# SharedOS integration — Counterparty v0.3

This directory is the authoritative Arena product boundary. The Python service is intentionally private behind it.

## Load-bearing authority model

1. `resolveContext` derives actor/authority/owner/purpose from authenticated server-side state. No request body carries authority.
2. Tools are invisible without matching grants and are re-authorized on the exact invocation.
3. Bounded grants use a durable atomic `GrantUsageStore`; a missing usage store fails closed.
4. The Router owns product-service decisions but **never** receives seller-call authority.
5. Active Trust Snapshot gives the Router one recipient-scoped `messages.request` ticket to the Counterparty Probe.
6. The Probe receives its own execution grant plus one exact recipient-scoped seller ticket. A ticket for service A cannot be spent on service B.
7. The Probe returns only raw observed output; it cannot write reputation or attestations.
8. `counterparty.record_probe` is available only under the Router's exact `trust_snapshot` service capability and deterministically validates the host-generated nonce before protocol evidence is stored.
9. Protocol-canary evidence is separate from task-delivery evidence. It may unlock a `PROVISIONAL` routing decision but cannot masquerade as verified task history.
10. `verify_delivery` accepts only an immutable `delivery_id`; provider/output/task contract come from `TrustedDeliveryResolver` backed by host-owned state.
11. Missing evidence produces `INCONCLUSIVE`, never an optimistic pass.
12. Escalation is separately granted and never widens the current turn's authority.
13. The Python backend requires a private internal token; it is not the SharedNet surface.

## Purpose

`counterparty.verify-and-route-sharednet-services`

## Product agents

- `counterparty-router`
- `counterparty-probe`
- `counterparty-judge`
- `counterparty-attestor`

These IDs are deliberately path-segment-safe. SharedOS execution capabilities encode an agent address into a resource path, so `/` must not appear inside an agent ID.

## Active Trust Snapshot turn

```text
buyer -> Router
          |
          | messages.request
          | grant: Router -> Counterparty Probe, maxUses=1
          v
        Probe
          |
          | messages.request
          | grant: Probe -> exact target service, maxUses=1
          v
        seller
          |
          v
    raw canary reply
          |
          v
Router -> counterparty.record_probe -> refreshed trust_snapshot
```

The seller receives a server-generated capability canary containing a nonce and expected response contract. The Probe never decides whether it passed; the backend validates the raw reply. This keeps the network authority decision, the evidence observation, and the trust decision as separate concerns.

## Required host ports

`createCounterpartySharedOSHost` now requires both canonical message ports:

- `MessageTransport`
- `MessageRequestRouter`

When those ports are configured, SharedOS adds the canonical `messages.request` affordance to the effective tool catalog. Visibility still depends on the `messages` namespace and a recipient-scoped `sharedos.messaging/send` grant.

## Production grants for one active snapshot

At minimum, one active Trust Snapshot purchase needs fresh bounded grants for:

- Router execution (`agentExecutionCapability(counterparty-router)`)
- Router product service (`counterparty/services/trust_snapshot`)
- Router -> Probe message (`messageSendCapability(counterparty-probe)`, `maxUses=1`)
- Probe execution (`agentExecutionCapability(counterparty-probe)`)
- Probe -> exact seller service (`messageSendCapability(target-service)`, `maxUses=1`)

The Router's service grant has no seller recipient in it. The Probe's seller grant has no reputation-write resource in it.

## Contract tests

```bash
npm install
npm run check
```

The suite proves:

- deny-by-default discovery
- purpose isolation
- atomic `maxUses`
- a bounded real Router turn
- Router / Probe / Judge / Attestor authority separation
- low-level target grant exhaustion
- separately granted escalation
- immutable-delivery evidence stripping
- Router can message the Probe but cannot spend that ticket on a seller
- Probe seller tickets are exact-recipient and single-use
- an executable Probe turn performs a real canonical `messages.request` canary

The package pins `@aicoo/sharedos@0.1.0-alpha.5` exactly because SharedOS is a prerelease surface.

## Deployment wiring still required

The event deployment must supply durable grant/usage/audit stores, authenticated `resolveContext`, `MessageTransport`, `MessageRequestRouter`, final Cloud/SharedNet addresses, and the `TrustedDeliveryResolver` that binds delivery IDs to immutable SharedNet execution records.

Those are deployment facts, not safe defaults to fake in source control. `scripts/arena_preflight.py --live` is the fail-closed gate once organizer-issued tenant/node/address data is available.

The SharedOS Cloud audit is the hackathon's authoritative audit trail. Counterparty's application hash-chain is complementary evidence, not a replacement.
