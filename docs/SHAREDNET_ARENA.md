# SharedNet Arena wiring — organizer-confirmed model

This document records the Arena transport model confirmed in `#arena-support` on 2026-09-12 and keeps it separate from Counterparty's internal SharedOS authorization model.

## What changed from the earlier assumption

SharedNet is **not a global RPC service registry**. Discovery and invocation are room/message based.

- **Discovery:** join the Arena Room; its roster is the directory. Members can read each seat's ID, nickname, and tag. Counterparty should also publish its seat ID in the README/Devpost/Discord once assigned.
- **Call:** a buyer addresses the Counterparty seat and sends a message. A SharedNet service request is therefore a message contract, not an HTTP RPC endpoint.
- **Address types:** `i*...` is a seat address, `a*...` is a tag/role address, and `p*...` is an account/payment address. They are not interchangeable.
- **Payment:** Arena credits settle with SharedNet `pay`; use `--room` so the receipt is visible where the trade was agreed. The ledger is the accounting record.
- **Competition room:** organizer guidance says the competition room is released two hours before the competition. Until then, the QA room can be used for connectivity testing.
- **SharedOS:** the application runs the SharedOS kernel and sends decision events to Cloud for visibility/audit. Counterparty must still produce real SharedOS decision/audit evidence for its product turns.

## Current QA-room join link

```text
https://www.sharednet.ai/join/rit_uAS3KksNuAyrdNC6u4niCTKeNQMXjp2IpPTZGVe4KUU
```

The competition-room invite is expected separately near Arena start; do not hard-code the QA room as the competition room.

## SharedNet commands confirmed by the organizer

Representative CLI flow:

```bash
sharednet reach public
sharednet add i*...
sharednet say "..."
sharednet watch --on message --run './serve.sh' --reply
sharednet pay <p*...|a*...|i*...> <amount> --memo "..." --room
```

Arena float:

```text
redeem HACK100
```

The same capabilities are available through the SharedNet MCP connector at:

```text
https://www.sharednet.ai/api/mcp
```

The organizer described the connector as exposing room/message, payment/credits, and file-transfer tools so a personal chat agent can participate without a local CLI.

## Counterparty's public message protocol

SharedNet carries messages; Counterparty defines the payload contract inside those messages.

A paid-service request should carry this logical envelope:

```json
{
  "type": "counterparty.service.request.v1",
  "request_id": "buyer-generated-unique-id",
  "service": "trust_snapshot",
  "input": {}
}
```

`service` is exactly one of:

```text
trust_snapshot     4 credits
verify_delivery    7 credits
best_execution    10 credits
```

The transport adapter converts that envelope to the existing SharedOS Router payload:

```json
{
  "service": "trust_snapshot",
  "input": {}
}
```

The Router/Probe/Judge/Attestor authority boundaries remain unchanged. SharedNet decides how the request arrives; SharedOS decides what the product role is allowed to do once the request is being served.

A reply should preserve the request ID and service so the buyer can match asynchronous room messages:

```json
{
  "type": "counterparty.service.response.v1",
  "request_id": "buyer-generated-unique-id",
  "service": "trust_snapshot",
  "price_credits": 4,
  "result": {}
}
```

## Provider identity inside Counterparty

Counterparty's internal `service_id` field is a stable provider identifier. In the Arena, populate it with the provider's SharedNet seat or tag address (`i*...` or `a*...`) instead of pretending SharedNet has a global service-registry ID.

For Verify Delivery, `delivery_id` is Counterparty's immutable trade/delivery evidence identifier. It is **not** claimed to be a SharedNet-native delivery ID. It should be bound by the trusted host to the SharedNet request/thread, provider address, task contract, returned artifact/message, and payment/receipt evidence when those are available.

## Payment discipline

Do not trust a buyer-authored string saying "paid". A production adapter must use SharedNet's payment/ledger evidence as the source of truth.

Commercial flow:

1. Buyer discovers Counterparty from the Arena Room roster or published seat ID.
2. Buyer sends the Counterparty service request message.
3. Counterparty returns/advertises the fixed price and real `SHAREDNET_PAYEE_ADDRESS`.
4. Buyer pays with SharedNet `pay ... --room` using a memo containing the request ID/service.
5. The adapter confirms the ledger/receipt using SharedNet-native evidence.
6. Only then does the paid SharedOS Router turn execute and deliver the result.

The exact `sharednet watch --run` callback stdin/environment schema is intentionally **not guessed in this repository**. Wire `serve.sh` only after inspecting the installed latest CLI/Skills package in the authenticated SharedNet environment.

## Release gate

The Arena preflight now requires:

- a real SharedNet representative seat/node ID;
- a real SharedNet payee address;
- final non-placeholder SharedOS product-agent addresses;
- confirmation that at least one real Counterparty product turn is visible in SharedOS Cloud audit;
- confirmation that another SharedNet seat actually called Counterparty and received a reply.

A public HTTPS URL is optional because SharedNet invocation is message based. If one is configured, preflight still validates `/health` and `/.well-known/agent.json` strictly.
