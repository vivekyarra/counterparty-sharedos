import assert from "node:assert/strict";
import test from "node:test";

import { ledgerPaymentMatches } from "./sharednet-cli.js";

const expected = {
  txnId: "txn_Payment001",
  payerSeat: "i_Buyer00001",
  payee: "p_Payee00001",
  amount: 4,
  roomId: "rom_ArenaRoom01",
  requestId: "req-001",
  service: "trust_snapshot",
} as const;

const transfer = {
  id: "txn_Payment001",
  amount: 4,
  memo: "Counterparty trust_snapshot req-001",
  room_id: "rom_ArenaRoom01",
  addressed_to: "p_Payee00001",
  by_instance_id: "i_Buyer00001",
};

test("ledger payment matches only the requesting SharedNet seat", () => {
  assert.equal(ledgerPaymentMatches(transfer, expected), true);
  assert.equal(
    ledgerPaymentMatches(
      { ...transfer, by_instance_id: "i_Thief000001" },
      expected,
    ),
    false,
  );
});

test("ledger payment remains bound to txn, amount, payee, room, memo and payer", () => {
  assert.equal(ledgerPaymentMatches({ ...transfer, amount: 7 }, expected), false);
  assert.equal(ledgerPaymentMatches({ ...transfer, addressed_to: "p_Other000001" }, expected), false);
  assert.equal(ledgerPaymentMatches({ ...transfer, room_id: "rom_OtherRoom01" }, expected), false);
  assert.equal(ledgerPaymentMatches({ ...transfer, memo: "Counterparty trust_snapshot another-request" }, expected), false);
});
