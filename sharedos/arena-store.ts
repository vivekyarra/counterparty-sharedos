import { DatabaseSync } from "node:sqlite";

import type {
  AccessContext,
  AuditEvent,
  CapabilityGrant,
  GrantSource,
  GrantUsageStore,
  JsonObject,
} from "@aicoo/sharedos";

import type { TrustedDelivery, TrustedDeliveryResolver } from "./tools.js";

type PaymentClaim = "claimed" | "same_request" | "conflict";

const SHAREDOS_AUDIT_ENDPOINT = "https://www.sharedos.ai/v1/audit/events";

export class ArenaStore implements GrantSource, GrantUsageStore, TrustedDeliveryResolver {
  readonly #db: DatabaseSync;

  constructor(path: string) {
    this.#db = new DatabaseSync(path);
    this.#db.exec("PRAGMA journal_mode=WAL");
    this.#db.exec("PRAGMA busy_timeout=5000");
    this.#db.exec(`
      CREATE TABLE IF NOT EXISTS grants (
        namespace_id TEXT NOT NULL,
        grant_id TEXT NOT NULL,
        grant_json TEXT NOT NULL,
        revoked_at TEXT,
        PRIMARY KEY(namespace_id, grant_id)
      );
      CREATE TABLE IF NOT EXISTS grant_usage (
        namespace_id TEXT NOT NULL,
        grant_id TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(namespace_id, grant_id)
      );
      CREATE TABLE IF NOT EXISTS sharedos_audit (
        event_id TEXT PRIMARY KEY,
        at TEXT NOT NULL,
        type TEXT NOT NULL,
        outcome TEXT NOT NULL,
        trace_id TEXT,
        event_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS arena_payments (
        txn_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        service TEXT NOT NULL,
        amount INTEGER NOT NULL,
        room_id TEXT NOT NULL,
        claimed_at TEXT NOT NULL
      );
      CREATE UNIQUE INDEX IF NOT EXISTS arena_payment_request_idx
        ON arena_payments(request_id);
      CREATE TABLE IF NOT EXISTS arena_responses (
        request_id TEXT PRIMARY KEY,
        fingerprint TEXT NOT NULL,
        response_json TEXT NOT NULL,
        completed_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS trusted_deliveries (
        delivery_id TEXT PRIMARY KEY,
        evidence_json TEXT NOT NULL,
        stored_at TEXT NOT NULL
      );
    `);
  }

  storeGrant(namespaceId: string, grant: CapabilityGrant): void {
    this.#db.prepare(
      `INSERT INTO grants(namespace_id, grant_id, grant_json, revoked_at)
       VALUES (?, ?, ?, NULL)
       ON CONFLICT(namespace_id, grant_id)
       DO UPDATE SET grant_json=excluded.grant_json, revoked_at=NULL`,
    ).run(namespaceId, grant.id, JSON.stringify(grant));
  }

  async load(context: AccessContext, signal: AbortSignal): Promise<readonly CapabilityGrant[]> {
    signal.throwIfAborted();
    const rows = this.#db.prepare(
      "SELECT grant_json FROM grants WHERE namespace_id=? AND revoked_at IS NULL",
    ).all(context.namespaceId) as Array<{ grant_json: string }>;
    const actor = JSON.stringify(context.actor);
    const authority = JSON.stringify(context.authority);
    return rows
      .map((row) => JSON.parse(row.grant_json) as CapabilityGrant)
      .filter(
        (grant) =>
          JSON.stringify(grant.subject) === actor && JSON.stringify(grant.issuer) === authority,
      );
  }

  async getUsage(namespaceId: string, grantId: string): Promise<number> {
    const row = this.#db.prepare(
      "SELECT used FROM grant_usage WHERE namespace_id=? AND grant_id=?",
    ).get(namespaceId, grantId) as { used: number } | undefined;
    return row?.used ?? 0;
  }

  async tryConsume(namespaceId: string, grantId: string, maximumUses: number): Promise<boolean> {
    const result = this.#db.prepare(
      `INSERT INTO grant_usage(namespace_id, grant_id, used) VALUES (?, ?, 1)
       ON CONFLICT(namespace_id, grant_id)
       DO UPDATE SET used=used+1 WHERE grant_usage.used < ?`,
    ).run(namespaceId, grantId, maximumUses);
    return result.changes > 0;
  }

  async record(event: AuditEvent): Promise<void> {
    this.#db.prepare(
      `INSERT OR IGNORE INTO sharedos_audit(event_id, at, type, outcome, trace_id, event_json)
       VALUES (?, ?, ?, ?, ?, ?)`,
    ).run(
      event.id,
      event.at,
      event.type,
      event.outcome,
      event.traceId ?? null,
      JSON.stringify(event),
    );

    const sharedOsKey = (process.env.SHAREDOS_KEY ?? "").trim();
    if (sharedOsKey.length === 0) return;

    try {
      const response = await fetch(SHAREDOS_AUDIT_ENDPOINT, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${sharedOsKey}`,
        },
        body: JSON.stringify({ events: [event] }),
        signal: AbortSignal.timeout(5_000),
      });
      if (!response.ok) {
        console.error(`SharedOS Cloud audit upload failed with HTTP ${response.status}`);
      }
    } catch (error) {
      console.error(
        `SharedOS Cloud audit upload failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  claimPayment(input: {
    txnId: string;
    requestId: string;
    fingerprint: string;
    service: string;
    amount: number;
    roomId: string;
  }): PaymentClaim {
    this.#db.exec("BEGIN IMMEDIATE");
    try {
      const existing = this.#db.prepare(
        "SELECT request_id, fingerprint FROM arena_payments WHERE txn_id=? OR request_id=? LIMIT 1",
      ).get(input.txnId, input.requestId) as
        | { request_id: string; fingerprint: string }
        | undefined;
      if (existing !== undefined) {
        this.#db.exec("COMMIT");
        return existing.request_id === input.requestId && existing.fingerprint === input.fingerprint
          ? "same_request"
          : "conflict";
      }
      this.#db.prepare(
        `INSERT INTO arena_payments(txn_id, request_id, fingerprint, service, amount, room_id, claimed_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      ).run(
        input.txnId,
        input.requestId,
        input.fingerprint,
        input.service,
        input.amount,
        input.roomId,
        new Date().toISOString(),
      );
      this.#db.exec("COMMIT");
      return "claimed";
    } catch (error) {
      this.#db.exec("ROLLBACK");
      throw error;
    }
  }

  cachedResponse(requestId: string, fingerprint: string): JsonObject | undefined {
    const row = this.#db.prepare(
      "SELECT fingerprint, response_json FROM arena_responses WHERE request_id=?",
    ).get(requestId) as { fingerprint: string; response_json: string } | undefined;
    if (row === undefined) return undefined;
    if (row.fingerprint !== fingerprint) {
      throw new Error("request_id was already used for a different request");
    }
    return JSON.parse(row.response_json) as JsonObject;
  }

  saveResponse(requestId: string, fingerprint: string, response: JsonObject): void {
    this.#db.prepare(
      `INSERT INTO arena_responses(request_id, fingerprint, response_json, completed_at)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(request_id) DO UPDATE SET
         response_json=CASE WHEN arena_responses.fingerprint=excluded.fingerprint THEN excluded.response_json ELSE arena_responses.response_json END,
         completed_at=CASE WHEN arena_responses.fingerprint=excluded.fingerprint THEN excluded.completed_at ELSE arena_responses.completed_at END`,
    ).run(requestId, fingerprint, JSON.stringify(response), new Date().toISOString());
  }

  storeTrustedDelivery(delivery: TrustedDelivery): void {
    this.#db.prepare(
      `INSERT OR REPLACE INTO trusted_deliveries(delivery_id, evidence_json, stored_at)
       VALUES (?, ?, ?)`,
    ).run(delivery.delivery_id, JSON.stringify(delivery), new Date().toISOString());
  }

  async resolve(
    _context: AccessContext,
    deliveryId: string,
    signal: AbortSignal,
  ): Promise<TrustedDelivery | undefined> {
    signal.throwIfAborted();
    const row = this.#db.prepare(
      "SELECT evidence_json FROM trusted_deliveries WHERE delivery_id=?",
    ).get(deliveryId) as { evidence_json: string } | undefined;
    return row === undefined ? undefined : (JSON.parse(row.evidence_json) as TrustedDelivery);
  }

  auditCount(): number {
    const row = this.#db.prepare("SELECT COUNT(*) AS count FROM sharedos_audit").get() as { count: number };
    return row.count;
  }
}
