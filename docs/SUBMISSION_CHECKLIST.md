# Shared OS Hackathon submission checklist

The repository can make the product technically ready, but several eligibility requirements live outside source control.

The current organizer-confirmed SharedNet model is documented in [`docs/SHAREDNET_ARENA.md`](SHAREDNET_ARENA.md): Arena discovery is the Room roster, service invocation is a message, and payment uses SharedNet addresses/ledger rather than a global service registry.

## Product requirements

- [x] At least one callable agent service (Counterparty has three).
- [x] Plain-language service descriptions, input/output contracts, Arena credit prices.
- [x] Engineering design targets delivery well under five minutes.
- [x] One SharedOS purpose string.
- [x] Deny-by-default / exact capability design.
- [x] Bounded `maxUses` design and contract test.
- [x] SharedNet message envelope mapped to the existing SharedOS Router payload.
- [x] Audit-ready product-agent addresses exposed by agent card.
- [ ] **Run real Counterparty product turns through the SharedOS-governed host and confirm the decision events/turns are visible in SharedOS Cloud audit.** Source code alone does not satisfy this.
- [ ] Join the SharedNet QA Room with the organizer-provided join link and obtain the representative `i*...` seat/node ID.
- [ ] Obtain/confirm the real SharedNet payee address (`p*...`, `a*...`, or approved `i*...` target) used for Arena receipts.
- [ ] Verify another SharedNet seat can message Counterparty and receive a service reply.
- [ ] Verify a real room-visible payment/receipt path for one Counterparty service; do not trust buyer-authored `paid` text.
- [ ] Join the competition Room when its invite is released (organizer guidance: two hours before competition).
- [ ] Keep the product service loop reachable for the full Arena window.

## Submission fields still requiring owner/event data

- [ ] Personal agent's SharedNet node/seat ID.
- [ ] Final product-agent SharedOS addresses used to locate the audit turns.
- [ ] Discord **username** of team lead (do not substitute a display name unless they are identical).
- [x] Public repository link: `https://github.com/vivekyarra/counterparty-sharedos`.
- [ ] Optional <=2 minute demo video.

## Operational SharedNet values (not all are Devpost fields)

- [ ] `SHAREDNET_NODE_ID=i*...`
- [ ] `SHAREDNET_PAYEE_ADDRESS=p*...|a*...|i*...`
- [ ] `SHAREDOS_AUDIT_CONFIRMED=1` only after a real turn is visible in Cloud audit.
- [ ] `SHAREDNET_EXTERNAL_CALL_CONFIRMED=1` only after a different seat successfully calls Counterparty.
- [ ] Redeem the Arena float with `HACK100` using the authenticated SharedNet CLI/connector.

## Arena obligations for the representative personal agent

- [ ] Online for the full Arena.
- [ ] Round 1: try at least three other products.
- [ ] Round 1: post at least one specific disagreement for each product tried.
- [ ] Round 1: submit a ranking.
- [ ] Round 2: spend at least 80/100 credits.
- [ ] Round 2: spend across at least three different products.
- [ ] No person sends messages, ranks, buys, sells, delivers, or manually fixes the agent during Arena.

## Stop/go command

After the real values and evidence exist:

```bash
python scripts/arena_preflight.py --live
```

A public HTTPS URL is optional for the message-based Arena transport. If `COUNTERPARTY_PUBLIC_URL` is configured, `--live` validates it strictly. The mandatory go/no-go evidence is the real SharedNet seat/payee identity plus confirmed SharedOS audit and external SharedNet call.
