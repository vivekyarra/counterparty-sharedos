# SharedOS integration — Counterparty v0.3

This directory is Counterparty's authoritative Arena product boundary. The Python/FastAPI service remains private behind it; SharedNet carries market messages, and SharedOS decides which Counterparty role may do what for each turn.

## Load-bearing authority model

1. `resolveContext` derives actor, authority, owner, purpose, and namespace from trusted host state. Request bodies do not carry authority.
2. Tools are invisible without matching grants and are re-authorized on the exact invocation.
3. Bounded grants use a durable atomic `GrantUsageStore`; missing durable usage state fails closed.
4. The Router owns product-service decisions but never receives direct seller-call authority.
5. Active Trust Snapshot gives the Router one recipient-scoped `messages.request` ticket to Counterparty Probe.
6. Probe receives its own execution grant plus one exact recipient-scoped seller ticket; a ticket for seller A cannot be spent on seller B.
7. Probe returns raw observed output only; it cannot write reputation or attestations.
8. `counterparty.record_probe` is available only under the Router's exact `trust_snapshot` capability and deterministically validates the host-generated nonce before protocol evidence is stored.
9. Protocol-canary evidence and task-delivery evidence are stored separately. Canary evidence may unlock `PROVISIONAL` routing but cannot masquerade as verified task history.
10. `verify_delivery` accepts only an immutable delivery ID; provider/output/task contract come from `TrustedDeliveryResolver` backed by host-owned state.
11. Missing evidence produces `INCONCLUSIVE`, never an optimistic pass.
12. Escalation is separately granted and never silently widens the current turn's authority.
13. The Python backend requires a private internal token and is not the public SharedNet surface.

## Purpose

`counterparty.verify-and-route-sharednet-services`

## Product agents

- `counterparty-router`
- `counterparty-probe`
- `counterparty-judge`
- `counterparty-attestor`

These IDs are deliberately path-segment-safe because SharedOS execution capabilities encode agent addresses into resource paths.

## Active Trust Snapshot turn

```text
SharedNet buyer message
        |
        v
Counterparty Router
        |
        | messages.request
        | Router -> Probe, maxUses=1
        v
Counterparty Probe
        |
        | messages.request
        | Probe -> exact target seat, maxUses=1
        v
Target SharedNet seller
        |
        v
raw canary reply from exact target
        |
        v
Router -> counterparty.record_probe -> refreshed trust_snapshot
```

The seller receives a server-generated capability canary containing a nonce and expected response contract. Probe never decides whether it passed; the deterministic backend validates the raw reply. Network authority, evidence observation, and trust judgment stay separate.

## Required host ports

`createCounterpartySharedOSHost` requires the canonical message ports:

- `MessageTransport`
- `MessageRequestRouter`

With those ports configured, SharedOS exposes the canonical `messages.request` affordance. Visibility still depends on the `messages` namespace plus recipient-scoped `sharedos.messaging/send` authority.

## Production grants for one active snapshot

One active Trust Snapshot purchase needs fresh bounded authority for:

- Router execution (`agentExecutionCapability(counterparty-router)`)
- Router product service (`counterparty/services/trust_snapshot`)
- Router -> Probe message (`messageSendCapability(counterparty-probe)`, `maxUses=1`)
- Probe execution (`agentExecutionCapability(counterparty-probe)`)
- Probe -> exact seller seat/service (`messageSendCapability(target)`, `maxUses=1`)

The Router service grant contains no seller recipient. Probe's seller grant contains no reputation-write resource.

## Live Arena service boundary

The repository now includes runnable production wiring around the tested SharedOS host:

- `arena-service.ts` parses Counterparty's SharedNet service envelope, verifies payment, mints request-scoped bounded grants, runs the Router turn, and caches successful replies idempotently.
- `sharednet-cli.ts` adapts the official SharedNet CLI message/ledger/read contract. Active canary replies are accepted only from the exact target `i_...` seat.
- `arena-store.ts` supplies durable SQLite grant usage, audit state, payment/request binding, and trusted delivery records.
- `arena-service.test.ts` exercises the SharedNet message/payment boundary and nested Router/Probe behavior.
- `../scripts/arena_host.py` launches the private backend and official SharedNet watcher loop from an authenticated Arena machine.

SharedNet Room discovery and payment semantics are documented in `../docs/SHAREDNET_ARENA.md`.

## Contract tests

```bash
npm install
npm run check
```

The suite proves:

- deny-by-default discovery
- purpose isolation
- atomic `maxUses`
- bounded Router execution
- Router / Probe / Judge / Attestor authority separation
- separately granted escalation
- immutable-delivery evidence stripping
- Router can message Probe but cannot spend that ticket on a seller
- Probe seller tickets are exact-recipient and single-use
- executable Probe turns perform canonical `messages.request` canaries
- Arena message parsing and payment verification fail closed
- paid requests execute through SharedOS rather than bypassing it

The package pins `@aicoo/sharedos@0.1.0-alpha.5` exactly because SharedOS is a prerelease surface.

## What remains external to source control

The event still requires deployment facts that cannot be safely fabricated in the repository:

- an authenticated SharedNet account and real live seat/node ID;
- a real SharedNet payee address;
- membership in the QA/competition Room as applicable;
- final product-agent addresses used for the event;
- real Counterparty turns visible in the SharedOS Cloud audit trail;
- at least one external SharedNet seat successfully calling Counterparty.

The current organizer guidance does **not** require Counterparty to wait for a separately issued SharedOS tenant ID or owner-address environment variable. The application runs the kernel; Cloud provides the event-visible audit trail. This changes the provisioning path, not the hackathon requirement that judges be able to find real product turns in SharedOS Cloud.

`scripts/arena_preflight.py --live` is the fail-closed stop/go gate for those real deployment facts. Counterparty's application hash-chain and local durable SharedOS audit are complementary evidence; they are not presented as a substitute for the event's Cloud audit trail.
