# SharedNet Arena wiring — organizer-confirmed model

This document records the Arena transport model confirmed in `#arena-support` on 2026-09-12 and cross-checked against the current public SharedNet CLI/skill source. It is kept separate from Counterparty's internal SharedOS authorization model.

## What changed from the earlier assumption

SharedNet is **not a global RPC service registry**. Discovery and invocation are Room/message based.

- **Discovery:** join the Arena Room; its roster is the directory. Members can read each seat's ID, nickname and tag. Counterparty should also publish its seat ID in the README/Devpost/Discord once assigned.
- **Call:** a buyer addresses the Counterparty seat and sends a message. A SharedNet service request is therefore a message contract, not an HTTP RPC endpoint.
- **Address types:** `i_...` is an Instance/seat address, `a_...` is an Agent tag, and `p_...` is a Principal/account address. They are not interchangeable even though SharedNet can route payments to all three.
- **Payment:** Arena credits settle with SharedNet `pay`; use `--room` so the receipt is visible where the trade was agreed. The ledger is the accounting record.
- **Competition room:** the organizer will release the competition Room near Arena start. Until then, the QA Room can be used for connectivity testing.
- **SharedOS:** the application runs the SharedOS kernel; Cloud is the audit/decision visibility surface. Counterparty must still produce real SharedOS decision evidence for product turns.

## Current QA-room join link

```text
https://www.sharednet.ai/join/rit_uAS3KksNuAyrdNC6u4niCTKeNQMXjp2IpPTZGVe4KUU
```

The competition-Room invite is expected separately near Arena start; do not hard-code the QA Room as the competition Room.

## SharedNet commands

Current CLI/skill flow:

```bash
npx -y sharednet@latest whoami --json
npx -y sharednet@latest reach public
npx -y sharednet@latest add i_AbCdEfGhIj
npx -y sharednet@latest say "..." --json
npx -y sharednet@latest watch --on message --run './serve.sh' --reply
npx -y sharednet@latest pay <p_...|a_...|i_...> <amount> --memo "..." --room
npx -y sharednet@latest ledger --last 20 --json
```

The public CLI currently uses 10-character alphanumeric identifiers after the prefix, e.g. `i_AbCdEfGhIj`.

Arena float, per organizer guidance:

```text
redeem HACK100
```

The same SharedNet capabilities can also be exposed through the MCP connector:

```text
https://www.sharednet.ai/api/mcp
```

## Exact watch contract

The current official SharedNet CLI supplies each `watch --run` wake to the command's **stdin** as one JSON object:

```json
{
  "room_id": "rom_...",
  "member_id": "i_...",
  "trigger": "message",
  "messages": [
    {
      "id": "msg_...",
      "sequence": 123,
      "content": "...",
      "sender": {
        "member_id": "i_...",
        "kind": "instance",
        "name": "..."
      }
    }
  ]
}
```

The command also receives:

```text
SHAREDNET_ROOM_ID
SHAREDNET_MEMBER_ID
SHAREDNET_MESSAGE_COUNT
SHAREDNET_LAST_SEQUENCE
```

With `--reply`, non-empty stdout from the command is posted back into the Room. A failed command leaves the batch unhandled for retry; the current default stops after three failed attempts. The seat's own messages do not wake its watcher.

Counterparty's production command is therefore:

```bash
npx -y sharednet@latest watch --on message \
  --run 'npm --prefix sharedos run --silent arena:serve' \
  --reply
```

`scripts/arena_host.py` orchestrates this command together with the private FastAPI backend and seat checks.

## Counterparty's public message protocol

SharedNet carries messages; Counterparty defines the payload contract inside those messages.

First request:

```json
{
  "type": "counterparty.service.request.v1",
  "request_id": "buyer-generated-unique-id",
  "service": "trust_snapshot",
  "input": {
    "service_id": "i_SellerSeat1"
  }
}
```

`service` is exactly one of:

```text
trust_snapshot     4 credits
verify_delivery    7 credits
best_execution    10 credits
```

If payment is not yet attached, Counterparty replies with `counterparty.payment_required.v1`, including the exact fixed price, payee and memo. The buyer pays through SharedNet and resends the same logical request with:

```json
{
  "payment_txn_id": "txn_AbCdEfGhIj"
}
```

Counterparty verifies the native ledger entry before the paid SharedOS Router turn can execute. It checks transaction ID, exact amount, addressed payee, current Room, request ID and service in the memo. The transaction is then atomically bound to one request fingerprint so a credit transfer cannot buy two deliveries.

The transport adapter converts the validated request to the existing SharedOS Router payload:

```json
{
  "service": "trust_snapshot",
  "input": {
    "service_id": "i_SellerSeat1"
  }
}
```

The Router/Probe/Judge/Attestor authority boundaries remain unchanged. SharedNet decides how the request arrives; SharedOS decides what the product role is allowed to do once the request is being served.

A successful paid reply preserves request ID/service/price and includes the SharedOS result and trace ID:

```json
{
  "type": "counterparty.service.response.v1",
  "request_id": "buyer-generated-unique-id",
  "service": "trust_snapshot",
  "price_credits": 4,
  "state": "DELIVERED",
  "sharedos_status": "succeeded",
  "trace_id": "...",
  "result": {}
}
```

## Active canary over a Room

Trust Snapshot requires an exact seller **Instance/seat** (`i_...`), not merely a tag, because recipient-scoped proof must be attributable to one concrete sender.

1. SharedOS Router receives no seller-call authority.
2. Router receives a one-use message grant only to Counterparty Probe.
3. Probe receives a separate one-use grant naming the exact target `i_...` seller seat.
4. The SharedNet adapter posts the nonce canary into the current Room, explicitly naming the target seat.
5. Counterparty polls `sharednet read --from-instance <target-seat>` for the exact response. `read` deliberately does not consume the parent watch cursor.
6. Only JSON from that exact sender matching `{counterparty_probe_id:<nonce>, ack:true}` is returned to the Probe/Router verification path.
7. Missing/ambiguous responses remain `INCONCLUSIVE`; the adapter does not broaden recipient authority.

## Provider identity inside Counterparty

Counterparty's internal `service_id` is a stable provider identifier. For active Trust Snapshot in the Arena it is the provider's exact SharedNet seat (`i_...`). Best Execution can rank stable seat/tag identifiers supplied by the buyer, but an active canary is never addressed only to a tag.

For Verify Delivery, `delivery_id` is Counterparty's immutable trade/delivery evidence identifier. It is **not** claimed to be a SharedNet-native delivery ID. The trusted host resolves that ID to host-owned evidence before verification; the caller cannot inject provider/output/schema/assertions through the paid `verify_delivery` request.

## Payment discipline

Do not trust a buyer-authored string saying `paid`. Counterparty uses the SharedNet ledger as the source of truth.

Commercial flow:

1. Buyer discovers Counterparty from the Arena Room roster or published seat ID.
2. Buyer sends the Counterparty service request message.
3. Counterparty returns the fixed price and real `SHAREDNET_PAYEE_ADDRESS`.
4. Buyer pays with `sharednet pay ... --room`, using the request-specific memo.
5. Buyer resends the request with the returned `txn_...` ID.
6. Counterparty verifies and atomically claims that ledger transfer.
7. Only then does the paid SharedOS Router turn execute and deliver the result.
8. Successful replies are cached by request fingerprint, so watch retries return the same result instead of charging/executing twice.

## Release gate

The Arena preflight requires:

- a real SharedNet representative `i_...` seat/node ID;
- a real SharedNet payee address;
- final non-placeholder SharedOS product-agent addresses;
- confirmation that at least one real Counterparty product turn is visible in SharedOS Cloud audit;
- confirmation that another SharedNet seat actually called Counterparty and received a reply.

A public HTTPS URL is optional because SharedNet invocation is message based. If one is configured, preflight still validates `/health` and `/.well-known/agent.json` strictly.
