import { createHash, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

import {
  CapabilityAuthorizer,
  SharedOSExecutor,
  SharedOSKernel,
  StandardRuntime,
  createEscalationTool,
  type AccessContext,
  type Address,
  type JsonObject,
  type JsonValue,
  type MessageEnvelope,
  type MessageRequestRouter,
  type MessageTransport,
} from "@aicoo/sharedos";

import { ArenaStore } from "./arena-store.js";
import {
  COUNTERPARTY_PROBE,
  COUNTERPARTY_ROUTER,
  probeExecutionGrant,
  probeMessageGrant,
  routerExecutionGrant,
  routerProbeMessageGrant,
  routerServiceGrant,
} from "./grants.js";
import { CounterpartyRoleDriver } from "./router-driver.js";
import {
  SHAREDNET_ADDRESS_PATTERN,
  SHAREDNET_SEAT_PATTERN,
  SHAREDNET_TXN_PATTERN,
  SharedNetCli,
  type SharedNetMessage,
  type SharedNetWatchBatch,
} from "./sharednet-cli.js";
import {
  COUNTERPARTY_PURPOSE,
  counterpartyTools,
} from "./tools.js";

const PRICES = {
  trust_snapshot: 4,
  verify_delivery: 7,
  best_execution: 10,
} as const;

type ServiceName = keyof typeof PRICES;

interface ArenaServiceRequest {
  readonly type: "counterparty.service.request.v1";
  readonly request_id: string;
  readonly service: ServiceName;
  readonly input: JsonObject;
  readonly payment_txn_id?: string;
}

interface ParsedRequest {
  readonly senderSeat: string;
  readonly sourceMessageId: string;
  readonly request: ArenaServiceRequest;
}

function asObject(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonical(item)).join(",")}]`;
  const object = value as Record<string, unknown>;
  return `{${Object.keys(object)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonical(object[key])}`)
    .join(",")}}`;
}

function requestFingerprint(parsed: ParsedRequest): string {
  return createHash("sha256")
    .update(
      canonical({
        sender: parsed.senderSeat,
        request_id: parsed.request.request_id,
        service: parsed.request.service,
        input: parsed.request.input,
      }),
    )
    .digest("hex");
}

function parseRequest(message: SharedNetMessage): ParsedRequest | undefined {
  const senderSeat = message.sender?.member_id;
  if (senderSeat === undefined || !SHAREDNET_SEAT_PATTERN.test(senderSeat)) return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(message.content) as unknown;
  } catch {
    return undefined;
  }
  const object = asObject(parsed);
  if (object?.type !== "counterparty.service.request.v1") return undefined;
  const requestId = object.request_id;
  const service = object.service;
  const input = asObject(object.input);
  const payment = object.payment_txn_id;
  if (
    typeof requestId !== "string" ||
    !/^[A-Za-z0-9._:-]{1,100}$/.test(requestId) ||
    typeof service !== "string" ||
    !(service in PRICES) ||
    input === undefined ||
    (payment !== undefined && typeof payment !== "string")
  ) {
    return undefined;
  }
  return {
    senderSeat,
    sourceMessageId: message.id,
    request: {
      type: "counterparty.service.request.v1",
      request_id: requestId,
      service: service as ServiceName,
      input: input as JsonObject,
      ...(typeof payment === "string" ? { payment_txn_id: payment } : {}),
    },
  };
}

function validateInput(request: ArenaServiceRequest): string | undefined {
  if (request.service === "trust_snapshot") {
    const serviceId = request.input.service_id;
    if (typeof serviceId !== "string" || !SHAREDNET_SEAT_PATTERN.test(serviceId)) {
      return "trust_snapshot input.service_id must be the seller's exact SharedNet i_ seat address";
    }
  }
  if (request.service === "verify_delivery") {
    const deliveryId = request.input.delivery_id;
    if (typeof deliveryId !== "string" || deliveryId.length < 1 || deliveryId.length > 200) {
      return "verify_delivery input.delivery_id must be a non-empty immutable delivery id";
    }
  }
  if (request.service === "best_execution") {
    const candidates = request.input.candidates;
    if (!Array.isArray(candidates) || candidates.length < 1 || candidates.length > 32) {
      return "best_execution requires 1-32 candidate services";
    }
  }
  return undefined;
}

function responseBase(request: ArenaServiceRequest): JsonObject {
  return {
    request_id: request.request_id,
    service: request.service,
    price_credits: PRICES[request.service],
  };
}

function paymentRequired(request: ArenaServiceRequest, payee: string): JsonObject {
  const memo = `Counterparty ${request.service} ${request.request_id}`;
  return {
    type: "counterparty.payment_required.v1",
    ...responseBase(request),
    state: "PAYMENT_REQUIRED",
    payee,
    memo,
    instruction: `sharednet pay ${payee} ${PRICES[request.service]} --memo ${JSON.stringify(memo)} --room`,
  };
}

function accessContext(owner: Address, namespaceId: string, actor: Address, traceId: string): AccessContext {
  return {
    namespaceId,
    actor,
    authority: owner,
    owner,
    purpose: COUNTERPARTY_PURPOSE,
    traceId,
    now: new Date().toISOString(),
    enabledToolNamespaces:
      actor.kind === "agent" && actor.agentId === COUNTERPARTY_PROBE.agentId
        ? ["messages"]
        : ["counterparty", "messages"],
  };
}

function maxSequence(batch: SharedNetWatchBatch): number {
  const envValue = Number(process.env.SHAREDNET_LAST_SEQUENCE ?? "");
  const fromMessages = batch.messages.reduce(
    (max, message) => (Number.isSafeInteger(message.sequence) ? Math.max(max, message.sequence) : max),
    0,
  );
  return Number.isSafeInteger(envValue) && envValue >= 0 ? Math.max(envValue, fromMessages) : fromMessages;
}

async function processRequest(
  parsed: ParsedRequest,
  world: {
    readonly store: ArenaStore;
    readonly cli: SharedNetCli;
    readonly payee: string;
    readonly owner: Address;
    readonly namespaceId: string;
    readonly kernel: SharedOSKernel;
    readonly turns: SharedOSExecutor;
  },
): Promise<JsonObject> {
  const { request } = parsed;
  const invalid = validateInput(request);
  if (invalid !== undefined) {
    return {
      type: "counterparty.service.response.v1",
      ...responseBase(request),
      state: "INVALID_REQUEST",
      reason: invalid,
    };
  }

  const fingerprint = requestFingerprint(parsed);
  try {
    const cached = world.store.cachedResponse(request.request_id, fingerprint);
    if (cached !== undefined) return cached;
  } catch {
    return {
      type: "counterparty.service.response.v1",
      ...responseBase(request),
      state: "REJECTED",
      reason: "request_id was already used for a different request",
    };
  }

  if (request.payment_txn_id === undefined) return paymentRequired(request, world.payee);
  if (!SHAREDNET_TXN_PATTERN.test(request.payment_txn_id)) {
    return {
      type: "counterparty.service.response.v1",
      ...responseBase(request),
      state: "PAYMENT_NOT_VERIFIED",
      reason: "payment_txn_id is not a SharedNet txn_ id",
    };
  }

  let paid = false;
  try {
    paid = await world.cli.verifyPayment({
      txnId: request.payment_txn_id,
      payee: world.payee,
      amount: PRICES[request.service],
      requestId: request.request_id,
      service: request.service,
    });
  } catch (error) {
    return {
      type: "counterparty.service.response.v1",
      ...responseBase(request),
      state: "INCONCLUSIVE",
      reason: `SharedNet ledger unavailable: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
  if (!paid) {
    return {
      type: "counterparty.service.response.v1",
      ...responseBase(request),
      state: "PAYMENT_NOT_VERIFIED",
      reason: "No matching room-visible ledger transfer was found for this request, price and payee",
      expected_payee: world.payee,
    };
  }

  const claim = world.store.claimPayment({
    txnId: request.payment_txn_id,
    requestId: request.request_id,
    fingerprint,
    service: request.service,
    amount: PRICES[request.service],
    roomId: process.env.SHAREDNET_ROOM_ID ?? "",
  });
  if (claim === "conflict") {
    return {
      type: "counterparty.service.response.v1",
      ...responseBase(request),
      state: "REJECTED",
      reason: "That SharedNet payment or request_id is already bound to a different Counterparty request",
    };
  }

  const attempt = randomUUID();
  world.store.storeGrant(
    world.namespaceId,
    routerServiceGrant(world.owner, world.namespaceId, request.service),
  );
  world.store.storeGrant(
    world.namespaceId,
    routerExecutionGrant(world.owner, world.namespaceId, `grant-router-exec-${attempt}`, 1),
  );
  if (request.service === "trust_snapshot") {
    const target = String(request.input.service_id);
    world.store.storeGrant(
      world.namespaceId,
      routerProbeMessageGrant(world.owner, world.namespaceId, `grant-router-probe-${attempt}`, 1),
    );
    world.store.storeGrant(
      world.namespaceId,
      probeExecutionGrant(world.owner, world.namespaceId, `grant-probe-exec-${attempt}`, 1),
    );
    world.store.storeGrant(
      world.namespaceId,
      probeMessageGrant(
        world.owner,
        world.namespaceId,
        target,
        1,
        `grant-probe-target-${attempt}`,
      ),
    );
  }

  const traceId = randomUUID();
  const context = accessContext(world.owner, world.namespaceId, COUNTERPARTY_ROUTER, traceId);
  const tools = await world.kernel.listTools(context);
  const message: MessageEnvelope = {
    version: "1",
    id: randomUUID(),
    sender: { kind: "service", serviceId: parsed.senderSeat },
    receiver: COUNTERPARTY_ROUTER,
    purpose: COUNTERPARTY_PURPOSE,
    payload: { service: request.service, input: request.input },
    traceId,
    createdAt: new Date().toISOString(),
    provenance: {
      source: "sharednet",
      parentIds: [parsed.sourceMessageId],
      metadata: { room_id: process.env.SHAREDNET_ROOM_ID ?? "", sender_seat: parsed.senderSeat },
    },
  };
  const execution = await world.turns.execute({
    version: "1",
    executionId: randomUUID(),
    agent: COUNTERPARTY_ROUTER,
    context,
    tools: [...tools],
    message,
  });

  const response: JsonObject = {
    type: "counterparty.service.response.v1",
    ...responseBase(request),
    payment_txn_id: request.payment_txn_id,
    state: execution.status === "succeeded" ? "DELIVERED" : "INCONCLUSIVE",
    sharedos_status: execution.status,
    trace_id: traceId,
    result:
      execution.status === "succeeded"
        ? (execution.output as JsonValue)
        : ({ state: "INCONCLUSIVE", reason: `SharedOS turn ended ${execution.status}` } as JsonObject),
  };
  if (execution.status === "succeeded") {
    world.store.saveResponse(request.request_id, fingerprint, response);
  }
  return response;
}

export async function runArenaBatch(batch: SharedNetWatchBatch): Promise<JsonObject | undefined> {
  if (!/^rom_[0-9A-Za-z]+$/.test(batch.room_id)) throw new Error("invalid SharedNet room id");
  if (!SHAREDNET_SEAT_PATTERN.test(batch.member_id)) throw new Error("invalid SharedNet member id");

  const payee = (process.env.SHAREDNET_PAYEE_ADDRESS ?? "").trim();
  if (!SHAREDNET_ADDRESS_PATTERN.test(payee)) {
    throw new Error("SHAREDNET_PAYEE_ADDRESS must be a real p_, a_, or i_ SharedNet address");
  }
  const internalToken = (process.env.COUNTERPARTY_INTERNAL_TOKEN ?? "").trim();
  if (internalToken.length < 32) {
    throw new Error("COUNTERPARTY_INTERNAL_TOKEN must be at least 32 characters");
  }
  const dbPath = (process.env.COUNTERPARTY_ARENA_DB ?? "data/counterparty-arena.sqlite3").trim();
  mkdirSync(dirname(dbPath), { recursive: true });
  const store = new ArenaStore(dbPath);
  const namespaceId = (process.env.COUNTERPARTY_NAMESPACE_ID ?? "counterparty-arena").trim();
  const owner: Address = {
    kind: "human",
    userId: (process.env.COUNTERPARTY_OWNER_ID ?? "counterparty-owner").trim(),
  };
  const cli = new SharedNetCli({
    seatId: batch.member_id,
    roomId: batch.room_id,
    initialSequence: maxSequence(batch),
  });

  const pendingReplies = new Map<string, MessageEnvelope>();
  let kernel!: SharedOSKernel;
  let turns!: SharedOSExecutor;

  const messageTransport: MessageTransport = {
    async deliver(_context, envelope, signal) {
      if (
        envelope.receiver.kind === "agent" &&
        envelope.receiver.agentId === COUNTERPARTY_PROBE.agentId
      ) {
        return {
          messageId: envelope.id,
          status: "accepted",
          timestamp: new Date().toISOString(),
          metadata: { transport: "in-process-counterparty-probe" },
        };
      }
      if (envelope.receiver.kind !== "service") {
        throw new Error("Arena transport only supports the Counterparty Probe or a SharedNet seller seat");
      }
      const payload = asObject(envelope.payload);
      if (payload === undefined) throw new Error("seller canary payload must be a JSON object");
      const observed = await cli.sendCanary(envelope.receiver.serviceId, payload as JsonObject, signal);
      const reply: MessageEnvelope = {
        version: "1",
        id: randomUUID(),
        sender: envelope.receiver,
        receiver: envelope.sender,
        purpose: envelope.purpose,
        payload: observed.payload,
        traceId: envelope.traceId,
        createdAt: new Date().toISOString(),
        replyTo: envelope.id,
        provenance: {
          source: "sharednet",
          parentIds: [observed.message.id],
          metadata: {
            room_id: batch.room_id,
            sender_seat: envelope.receiver.serviceId,
            sequence: observed.message.sequence,
          },
        },
      };
      pendingReplies.set(envelope.id, reply);
      return {
        messageId: envelope.id,
        status: "delivered",
        timestamp: new Date().toISOString(),
        metadata: {
          sharednet_message_id: observed.message.id,
          sharednet_sequence: observed.message.sequence,
        },
      };
    },
  };

  const messageRequestRouter: MessageRequestRouter = {
    async resolveReply(_context, request, _delivery, signal) {
      if (
        request.receiver.kind === "agent" &&
        request.receiver.agentId === COUNTERPARTY_PROBE.agentId
      ) {
        const probeContext = accessContext(owner, namespaceId, COUNTERPARTY_PROBE, request.traceId);
        const probeTools = await kernel.listTools(probeContext);
        const probe = await turns.execute({
          version: "1",
          executionId: randomUUID(),
          agent: COUNTERPARTY_PROBE,
          context: probeContext,
          tools: [...probeTools],
          message: request,
          options: { maxSteps: 4, maxToolCalls: 1, timeoutMs: 10_000 },
        }, { signal });
        const output: JsonValue =
          probe.status === "succeeded"
            ? probe.output
            : { state: "INCONCLUSIVE", reason: `Probe turn ended ${probe.status}` };
        return {
          version: "1",
          id: randomUUID(),
          sender: COUNTERPARTY_PROBE,
          receiver: request.sender,
          purpose: request.purpose,
          payload: output,
          traceId: request.traceId,
          createdAt: new Date().toISOString(),
          replyTo: request.id,
        };
      }
      const reply = pendingReplies.get(request.id);
      if (reply === undefined) throw new Error("SharedNet seller reply was not captured");
      pendingReplies.delete(request.id);
      return reply;
    },
  };

  kernel = new SharedOSKernel({
    grantSource: store,
    authorizer: new CapabilityAuthorizer({ usageStore: store }),
    audit: store,
    messageTransport,
    messageRequestRouter,
    createMessageId: () => randomUUID(),
  });
  for (const tool of counterpartyTools({
    baseUrl: process.env.COUNTERPARTY_BACKEND_URL ?? "http://127.0.0.1:8000",
    internalToken,
    deliveryResolver: store,
  })) {
    kernel.registerTool(tool);
  }
  kernel.registerTool(createEscalationTool());
  turns = new SharedOSExecutor(kernel, new StandardRuntime(new CounterpartyRoleDriver()), {
    defaultMaxSteps: 6,
    defaultMaxToolCalls: 3,
    defaultTimeoutMs: 15_000,
  });

  const requests = batch.messages.map(parseRequest).filter((value): value is ParsedRequest => value !== undefined);
  if (requests.length === 0) return undefined;
  const responses: JsonObject[] = [];
  for (const request of requests) {
    responses.push(
      await processRequest(request, { store, cli, payee, owner, namespaceId, kernel, turns }),
    );
  }
  return responses.length === 1
    ? responses[0]
    : {
        type: "counterparty.batch.response.v1",
        responses,
      };
}

async function main(): Promise<void> {
  const raw = readFileSync(0, "utf8").trim();
  if (raw.length === 0) return;
  const batch = JSON.parse(raw) as SharedNetWatchBatch;
  const response = await runArenaBatch(batch);
  if (response !== undefined) process.stdout.write(JSON.stringify(response));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    process.stderr.write(`counterparty arena service failed: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
