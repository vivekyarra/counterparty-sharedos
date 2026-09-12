# Shared OS Hackathon submission checklist

The repository can make the product technically ready, but several eligibility requirements live outside source control.

Arena discovery is the SharedNet Room roster, service invocation is a message, and payment uses SharedNet addresses/ledger rather than a global service registry. See [`SHAREDNET_ARENA.md`](SHAREDNET_ARENA.md).

## Product requirements

- [x] At least one callable agent service (Counterparty has three).
- [x] Plain-language service descriptions, input/output contracts, Arena credit prices.
- [x] Engineering design targets delivery well under five minutes.
- [x] One SharedOS purpose string: `counterparty.verify-and-route-sharednet-services`.
- [x] Deny-by-default / exact capability design.
- [x] Bounded `maxUses` design and contract tests.
- [x] SharedNet message envelope mapped to the SharedOS Router turn.
- [x] Canonical SharedOS audit identities fixed in runtime and submission:
  - `counterparty-router`
  - `counterparty-probe`
  - `counterparty-judge`
  - `counterparty-attestor`
- [x] Ledger verification binds txn ID, requesting seat, payee, amount, Room, request ID, and service memo.
- [x] Runnable SharedNet `watch --on message ... --reply` provider loop.
- [ ] **Run real Counterparty product turns and confirm the decision events/turns are visible in SharedOS Cloud audit.** Source code/local audit alone does not satisfy this.
- [ ] Join the SharedNet QA/competition Room from the organizer link and obtain the representative `i_...` seat/node ID.
- [ ] Obtain/confirm the real SharedNet payee address (`p_...`, `a_...`, or `i_...`).
- [ ] Verify another SharedNet seat can message Counterparty, pay, and receive a service reply.
- [ ] Keep the product service loop reachable for the full Arena window.

## Submission fields

- [ ] Personal agent's real SharedNet node/seat ID (`i_...`).
- [x] SharedOS purpose string.
- [x] Product-agent SharedOS addresses: the four canonical IDs above.
- [x] Public repository: `https://github.com/vivekyarra/counterparty-sharedos`.
- [ ] Discord **username** of team lead (do not substitute a display nickname unless identical).
- [ ] Optional <=2 minute video — not required for eligibility.

## Operational SharedNet values

- [ ] `SHAREDNET_NODE_ID=i_...`
- [ ] `SHAREDNET_PAYEE_ADDRESS=p_...|a_...|i_...`
- [ ] `SHAREDOS_AUDIT_CONFIRMED=1` only after a real turn is visible in Cloud audit.
- [ ] `SHAREDNET_EXTERNAL_CALL_CONFIRMED=1` only after a different seat successfully buys/calls Counterparty.
- [ ] Redeem Arena float with `HACK100` using the authenticated SharedNet CLI/connector.

## Arena obligations for the representative personal agent

- [ ] Online for the full Arena.
- [ ] Round 1: try at least three other products.
- [ ] Round 1: post at least one specific disagreement for each product tried.
- [ ] Round 1: submit a ranking.
- [ ] Round 2: spend at least 80/100 credits.
- [ ] Round 2: spend across at least three different products.
- [ ] No person sends messages, ranks, buys, sells, delivers, or manually fixes the agent during Arena.

## Stop/go command

After the real SharedNet identity and external evidence exist:

```bash
python scripts/arena_preflight.py --live
```

A public HTTPS URL is optional for the message-based Arena transport. If `COUNTERPARTY_PUBLIC_URL` is configured, `--live` validates it strictly. The mandatory go/no-go evidence is the real SharedNet seat/payee identity plus confirmed SharedOS Cloud audit and an external SharedNet call.
