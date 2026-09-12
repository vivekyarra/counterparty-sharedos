import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { ArenaStore } from "./arena-store.js";
import { runArenaBatch } from "./arena-service.js";
import type { SharedNetWatchBatch } from "./sharednet-cli.js";

function withArenaEnv<T>(fn: () => Promise<T>): Promise<T> {
  const old = {
    token: process.env.COUNTERPARTY_INTERNAL_TOKEN,
    payee: process.env.SHAREDNET_PAYEE_ADDRESS,
    db: process.env.COUNTERPARTY_ARENA_DB,
  };
  const root = mkdtempSync(join(tmpdir(), "counterparty-arena-test-"));
  process.env.COUNTERPARTY_INTERNAL_TOKEN = "test-arena-token-0123456789abcdef0123456789";
  process.env.SHAREDNET_PAYEE_ADDRESS = "p_Payee00001";
  process.env.COUNTERPARTY_ARENA_DB = join(root, "arena.sqlite3");
  return fn().finally(() => {
    if (old.token === undefined) delete process.env.COUNTERPARTY_INTERNAL_TOKEN;
    else process.env.COUNTERPARTY_INTERNAL_TOKEN = old.token;
    if (old.payee === undefined) delete process.env.SHAREDNET_PAYEE_ADDRESS;
    else process.env.SHAREDNET_PAYEE_ADDRESS = old.payee;
    if (old.db === undefined) delete process.env.COUNTERPARTY_ARENA_DB;
    else process.env.COUNTERPARTY_ARENA_DB = old.db;
    rmSync(root, { recursive: true, force: true });
  });
}

function batch(content: string): SharedNetWatchBatch {
  return {
    room_id: "rom_ArenaRoom01",
    member_id: "i_Counter001",
    trigger: "message",
    messages: [
      {
        id: "msg_Buyer00001",
        sequence: 42,
        content,
        sender: { member_id: "i_Buyer00001", kind: "instance", name: "buyer" },
      },
    ],
  };
}

test("Arena watcher ignores ordinary Room conversation", async () => {
  await withArenaEnv(async () => {
    const response = await runArenaBatch(batch("Does anyone know a good verifier?"));
    assert.equal(response, undefined);
  });
});

test("unpaid Trust Snapshot returns exact SharedNet payment contract", async () => {
  await withArenaEnv(async () => {
    const response = await runArenaBatch(
      batch(
        JSON.stringify({
          type: "counterparty.service.request.v1",
          request_id: "req-001",
          service: "trust_snapshot",
          input: { service_id: "i_Seller0001" },
        }),
      ),
    );
    assert.ok(response);
    assert.equal(response.type, "counterparty.payment_required.v1");
    assert.equal(response.request_id, "req-001");
    assert.equal(response.service, "trust_snapshot");
    assert.equal(response.price_credits, 4);
    assert.equal(response.payee, "p_Payee00001");
    assert.match(String(response.memo), /req-001/);
    assert.match(String(response.instruction), /sharednet pay p_Payee00001 4/);
  });
});

test("Trust Snapshot refuses a tag where an exact seller seat is required", async () => {
  await withArenaEnv(async () => {
    const response = await runArenaBatch(
      batch(
        JSON.stringify({
          type: "counterparty.service.request.v1",
          request_id: "req-002",
          service: "trust_snapshot",
          input: { service_id: "a_Seller0001" },
        }),
      ),
    );
    assert.ok(response);
    assert.equal(response.state, "INVALID_REQUEST");
    assert.match(String(response.reason), /exact SharedNet i_ seat/);
  });
});

test("durable payment binding is idempotent but cannot be replayed across requests", () => {
  const root = mkdtempSync(join(tmpdir(), "counterparty-store-test-"));
  try {
    const store = new ArenaStore(join(root, "arena.sqlite3"));
    const first = store.claimPayment({
      txnId: "txn_Payment001",
      requestId: "req-one",
      fingerprint: "fp-one",
      service: "trust_snapshot",
      amount: 4,
      roomId: "rom_ArenaRoom01",
    });
    assert.equal(first, "claimed");
    assert.equal(
      store.claimPayment({
        txnId: "txn_Payment001",
        requestId: "req-one",
        fingerprint: "fp-one",
        service: "trust_snapshot",
        amount: 4,
        roomId: "rom_ArenaRoom01",
      }),
      "same_request",
    );
    assert.equal(
      store.claimPayment({
        txnId: "txn_Payment001",
        requestId: "req-two",
        fingerprint: "fp-two",
        service: "trust_snapshot",
        amount: 4,
        roomId: "rom_ArenaRoom01",
      }),
      "conflict",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
