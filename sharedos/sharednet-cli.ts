import { spawn } from "node:child_process";

import type { JsonObject } from "@aicoo/sharedos";

export interface SharedNetMessage {
  readonly id: string;
  readonly sequence: number;
  readonly content: string;
  readonly sender?: {
    readonly member_id?: string;
    readonly kind?: string;
    readonly name?: string | null;
  };
}

export interface SharedNetWatchBatch {
  readonly room_id: string;
  readonly member_id: string;
  readonly trigger: string;
  readonly messages: readonly SharedNetMessage[];
}

interface SharedNetPage {
  readonly items?: readonly SharedNetMessage[];
  readonly next_cursor?: string | null;
  readonly has_more?: boolean;
}

export interface LedgerItem {
  readonly id?: string;
  readonly amount?: number;
  readonly memo?: string | null;
  readonly room_id?: string | null;
  readonly addressed_to?: string | null;
  readonly by_instance_id?: string | null;
  readonly [key: string]: unknown;
}

interface LedgerPage {
  readonly items?: readonly LedgerItem[];
}

export const SHAREDNET_SEAT_PATTERN = /^i_[0-9A-Za-z]{10}$/;
export const SHAREDNET_ADDRESS_PATTERN = /^(?:p|a|i)_[0-9A-Za-z]{10}$/;
export const SHAREDNET_TXN_PATTERN = /^txn_[0-9A-Za-z]{10}$/;

function parseJson(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed.length === 0) return null;
  return JSON.parse(trimmed) as unknown;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new Error("aborted"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason ?? new Error("aborted"));
      },
      { once: true },
    );
  });
}

export function ledgerPaymentMatches(
  item: LedgerItem | undefined,
  expected: {
    readonly txnId: string;
    readonly payerSeat: string;
    readonly payee: string;
    readonly amount: number;
    readonly roomId: string;
    readonly requestId: string;
    readonly service: string;
  },
): boolean {
  if (item === undefined) return false;
  if (item.id !== expected.txnId) return false;
  if (item.amount !== expected.amount) return false;
  if (item.addressed_to !== expected.payee) return false;
  if (item.room_id !== expected.roomId) return false;
  if (item.by_instance_id !== expected.payerSeat) return false;
  const memo = typeof item.memo === "string" ? item.memo : "";
  return memo.includes(expected.requestId) && memo.includes(expected.service);
}

export class SharedNetCli {
  readonly #seatId: string;
  readonly #roomId: string;
  readonly #initialSequence: number;
  readonly #timeoutMs: number;

  constructor(options: {
    seatId: string;
    roomId: string;
    initialSequence: number;
    timeoutMs?: number;
  }) {
    if (!SHAREDNET_SEAT_PATTERN.test(options.seatId)) {
      throw new Error("SharedNet seat must be an i_ address");
    }
    this.#seatId = options.seatId;
    this.#roomId = options.roomId;
    this.#initialSequence = options.initialSequence;
    this.#timeoutMs = options.timeoutMs ?? 10_000;
  }

  async #run(args: readonly string[], signal?: AbortSignal): Promise<unknown> {
    const program = process.platform === "win32" ? "npx.cmd" : "npx";
    const fullArgs = ["-y", "sharednet@latest", ...args, "--json"];
    return new Promise((resolve, reject) => {
      let stdout = "";
      let stderr = "";
      const child = spawn(program, fullArgs, {
        cwd: process.cwd(),
        env: { ...process.env, SHAREDNET_SEAT: this.#seatId },
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });
      const timer = setTimeout(() => child.kill(), this.#timeoutMs);
      const onAbort = () => child.kill();
      signal?.addEventListener("abort", onAbort, { once: true });
      child.stdout.on("data", (chunk: Buffer) => (stdout += chunk.toString()));
      child.stderr.on("data", (chunk: Buffer) => (stderr += chunk.toString()));
      child.once("error", (error) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        reject(error);
      });
      child.once("close", (code) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        if (signal?.aborted) {
          reject(signal.reason ?? new Error("SharedNet command aborted"));
          return;
        }
        if (code !== 0) {
          reject(new Error(`SharedNet CLI failed (${code ?? "unknown"}): ${stderr.trim() || "no stderr"}`));
          return;
        }
        try {
          resolve(parseJson(stdout));
        } catch (error) {
          reject(new Error(`SharedNet CLI returned invalid JSON: ${String(error)}`));
        }
      });
    });
  }

  async verifyPayment(input: {
    txnId: string;
    payerSeat: string;
    payee: string;
    amount: number;
    requestId: string;
    service: string;
  }, signal?: AbortSignal): Promise<boolean> {
    if (!SHAREDNET_TXN_PATTERN.test(input.txnId)) return false;
    if (!SHAREDNET_SEAT_PATTERN.test(input.payerSeat)) return false;
    if (!SHAREDNET_ADDRESS_PATTERN.test(input.payee)) return false;
    const page = (await this.#run(
      ["ledger", "--last", "100", "--as", this.#seatId],
      signal,
    )) as LedgerPage;
    const item = page.items?.find((candidate) => candidate.id === input.txnId);
    return ledgerPaymentMatches(item, {
      txnId: input.txnId,
      payerSeat: input.payerSeat,
      payee: input.payee,
      amount: input.amount,
      roomId: this.#roomId,
      requestId: input.requestId,
      service: input.service,
    });
  }

  async sendCanary(
    targetSeat: string,
    payload: JsonObject,
    signal?: AbortSignal,
  ): Promise<{ message: SharedNetMessage; payload: JsonObject }> {
    if (!SHAREDNET_SEAT_PATTERN.test(targetSeat)) {
      throw new Error("active canary requires an exact SharedNet i_ seat address");
    }
    if (targetSeat === this.#seatId) {
      throw new Error("Counterparty cannot canary its own SharedNet seat");
    }
    const nonce = payload.counterparty_probe_id;
    if (typeof nonce !== "string" || nonce.length < 8) {
      throw new Error("canary payload is missing the host-generated nonce");
    }

    const outbound = {
      ...payload,
      target_seat: targetSeat,
      instruction:
        `Only SharedNet seat ${targetSeat} should answer this canary. Reply with JSON only: ` +
        JSON.stringify({ counterparty_probe_id: nonce, ack: true }),
    };
    await this.#run(["say", JSON.stringify(outbound), "--as", this.#seatId], signal);

    const deadline = Date.now() + Math.min(this.#timeoutMs, 8_000);
    let after = this.#initialSequence;
    while (Date.now() < deadline) {
      const page = (await this.#run(
        [
          "read",
          "--after",
          String(after),
          "--from-instance",
          targetSeat,
          "--order",
          "asc",
          "--limit",
          "100",
          "--as",
          this.#seatId,
        ],
        signal,
      )) as SharedNetPage;
      for (const message of page.items ?? []) {
        if (Number.isSafeInteger(message.sequence)) after = Math.max(after, message.sequence);
        if (message.sender?.member_id !== targetSeat) continue;
        let parsed: unknown;
        try {
          parsed = parseJson(message.content);
        } catch {
          continue;
        }
        if (
          parsed !== null &&
          typeof parsed === "object" &&
          !Array.isArray(parsed) &&
          (parsed as Record<string, unknown>).counterparty_probe_id === nonce &&
          (parsed as Record<string, unknown>).ack === true
        ) {
          return { message, payload: parsed as JsonObject };
        }
      }
      await sleep(350, signal);
    }
    throw new Error(`target seat ${targetSeat} did not return the exact canary before timeout`);
  }
}
