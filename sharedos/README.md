# SharedOS integration

This directory is the authoritative product boundary for Arena deployment. The Python service is intentionally private behind it.

## Security invariants

1. `resolveContext` derives actor/authority/owner/purpose from authenticated server-side state. No request body carries authority.
2. Tools are invisible without matching grants and are re-authorized at invocation.
3. Bounded grants use a durable atomic `GrantUsageStore`; a missing store must fail closed.
4. The router has product-service authority but no target-agent call authority.
5. The probe has exact target authority with bounded uses; judge and attestor cannot invoke the target.
6. `verify_delivery` accepts only an immutable `delivery_id`; provider/output/task contract come from `TrustedDeliveryResolver` backed by host-owned state.
7. Missing evidence produces `INCONCLUSIVE`, never an optimistic pass.
8. Escalation is registered but separately granted; it does not widen the current turn's authority.
9. The Python backend requires a private internal token; it is not the SharedNet surface.

## Purpose

`counterparty.verify-and-route-sharednet-services`

## Product agents

- `counterparty-router`
- `counterparty-probe`
- `counterparty-judge`
- `counterparty-attestor`

These IDs are deliberately path-segment-safe. SharedOS execution capabilities encode the agent address into a resource path, so `/` must not appear inside an agent ID.

## Local contract test

```bash
npm install
npm run check
```

The contract suite proves deny-by-default discovery, purpose isolation, atomic `maxUses`, a real bounded router turn, Router/Probe/Judge/Attestor role isolation, probe exhaustion after three calls, separately granted escalation, and immutable-delivery evidence stripping.

The package pins `@aicoo/sharedos@0.1.0-alpha.5` exactly because SharedOS is a prerelease surface.

## Deployment wiring still required

The event deployment must supply durable grant/usage/audit stores, authenticated `resolveContext`, final Cloud/SharedNet addresses, and the `TrustedDeliveryResolver` that binds delivery IDs to immutable SharedNet execution records. Those are deployment facts, not safe defaults to fake in source control.

The SharedOS Cloud audit is the hackathon's authoritative audit trail. Counterparty's application hash-chain is complementary evidence, not a replacement.
