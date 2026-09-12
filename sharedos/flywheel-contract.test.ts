import assert from "node:assert/strict";
import test from "node:test";

import {
  CapabilityAuthorizer,
  InMemoryGrantUsageStore,
  SharedOSExecutor,
  SharedOSKernel,
  StandardRuntime,
  type AccessContext,
  type Address,
  type CapabilityGrant,
  type JsonObject,
  type MessageEnvelope,
} from "@aicoo/sharedos";

import {
  COUNTERPARTY_PROBE,
  COUNTERPARTY_ROUTER,
  probeExecutionGrant,
  probeMessageGrant,
  routerProbeMessageGrant,
} from "./grants.js";
import { CounterpartyRoleDriver } from "./router-driver.js";

const OWNER = { kind: "human", userId: "owner" } as const;
const TARGET = { kind: "service", serviceId: "target-a" } as const;
const PURPOSE = "counterparty.verify-and-route-sharednet-services";
const NAMESPACE = "counterparty-arena";
const NOW = "2026-09-12T00:00:00.000Z";

function grantSource(grants: CapabilityGrant[]) {
  return {
    async load(ctx: AccessContext) {
      return grants.filter(
        (grant) =>
          grant.namespaceId === ctx.namespaceId &&
          JSON.stringify(grant.subject) === JSON.stringify(ctx.actor) &&
          JSON.stringify(grant.issuer) === JSON.stringify(ctx.authority),
      );
    },
  };
}

function context(actor: Address, traceId = crypto.randomUUID()): AccessContext {
  return {
    namespaceId: NAMESPACE,
    actor,
    authority: OWNER,
    owner: OWNER,
    purpose: PURPOSE,
    traceId,
    now: NOW,
    enabledToolNamespaces: ["messages"],
  };
}

function world(grants: CapabilityGrant[]) {
  let serial = 0;
  const deliveries: MessageEnvelope[] = [];
  const kernel = new SharedOSKernel({
    grantSource: grantSource(grants),
    authorizer: new CapabilityAuthorizer({ usageStore: new InMemoryGrantUsageStore() }),
    createMessageId: () => `message-${++serial}`,
    messageTransport: {
      async deliver(_context, message) {
        deliveries.push(message);
        return { messageId: message.id, status: "accepted", timestamp: NOW };
      },
    },
    messageRequestRouter: {
      async resolveReply(_context, request) {
        const payload = request.payload as JsonObject;
        const nonce = typeof payload.counterparty_probe_id === "string"
          ? payload.counterparty_probe_id
          : "not-a-canary";
        return {
          version: "1",
          id: `reply-${request.id}`,
          sender: request.receiver,
          receiver: request.sender,
          purpose: request.purpose,
          traceId: request.traceId,
          createdAt: NOW,
          replyTo: request.id,
          payload: { counterparty_probe_id: nonce, ack: true },
        };
      },
    },
  });
  return { kernel, deliveries };
}

function messageCall(ctx: AccessContext, recipient: Address, payload: JsonObject) {
  return {
    id: crypto.randomUUID(),
    tool: "messages.request",
    arguments: { recipient, payload },
    traceId: ctx.traceId,
    requestedAt: NOW,
  };
}

test("Router can message the Probe but cannot spend that ticket on a seller", async () => {
  const { kernel, deliveries } = world([
    routerProbeMessageGrant(OWNER, NAMESPACE, "router-to-probe", 1),
  ]);
  const ctx = context(COUNTERPARTY_ROUTER);
  assert.deepEqual((await kernel.listTools(ctx)).map((tool) => tool.name), ["messages.request"]);

  const wrongRecipient = await kernel.invokeTool(
    ctx,
    messageCall(ctx, TARGET, { operation: "forbidden-direct-seller-call" }),
  );
  assert.equal(wrongRecipient.status, "denied");
  assert.equal(deliveries.length, 0);

  const allowed = await kernel.invokeTool(
    ctx,
    messageCall(ctx, COUNTERPARTY_PROBE, { operation: "trust_canary" }),
  );
  assert.equal(allowed.status, "succeeded");
  assert.equal(deliveries.length, 1);
  assert.deepEqual(deliveries[0]?.receiver, COUNTERPARTY_PROBE);
});

test("Probe target ticket is recipient-scoped and single-use", async () => {
  const { kernel, deliveries } = world([
    probeMessageGrant(OWNER, NAMESPACE, TARGET.serviceId, 1),
  ]);
  const ctx = context(COUNTERPARTY_PROBE);
  const first = await kernel.invokeTool(
    ctx,
    messageCall(ctx, TARGET, { counterparty_probe_id: "nonce-12345678" }),
  );
  assert.equal(first.status, "succeeded");
  assert.equal(deliveries.length, 1);

  const second = await kernel.invokeTool(
    ctx,
    messageCall(ctx, TARGET, { counterparty_probe_id: "nonce-87654321" }),
  );
  assert.equal(second.status, "denied");
  assert.equal(deliveries.length, 1);
});

test("executable Probe turn performs a canonical messages.request canary", async () => {
  const { kernel, deliveries } = world([
    probeExecutionGrant(OWNER, NAMESPACE, "probe-exec", 1),
    probeMessageGrant(OWNER, NAMESPACE, TARGET.serviceId, 1),
  ]);
  const runtime = new StandardRuntime(new CounterpartyRoleDriver());
  const turns = new SharedOSExecutor(kernel, runtime, {
    defaultMaxSteps: 4,
    defaultMaxToolCalls: 1,
    defaultTimeoutMs: 5_000,
  });
  const ctx = context(COUNTERPARTY_PROBE, "probe-trace");
  const tools = await kernel.listTools(ctx);
  assert.deepEqual(tools.map((tool) => tool.name), ["messages.request"]);

  const nonce = "nonce-12345678";
  const result = await turns.execute({
    version: "1",
    executionId: crypto.randomUUID(),
    agent: COUNTERPARTY_PROBE,
    context: ctx,
    tools: [...tools],
    message: {
      version: "1",
      id: "probe-message",
      sender: COUNTERPARTY_ROUTER,
      receiver: COUNTERPARTY_PROBE,
      purpose: PURPOSE,
      payload: {
        operation: "trust_canary",
        target: TARGET,
        probe_id: "probe-1",
        nonce,
      },
      traceId: ctx.traceId,
      createdAt: NOW,
    },
  });

  assert.equal(result.status, "succeeded", JSON.stringify(result));
  if (result.status !== "succeeded") return;
  const output = result.output as JsonObject;
  assert.equal(output.state, "OBSERVED");
  assert.equal(output.probe_id, "probe-1");
  assert.equal(output.provider_id, TARGET.serviceId);
  assert.equal(output.nonce, nonce);
  assert.deepEqual(output.output, { counterparty_probe_id: nonce, ack: true });
  assert.equal(deliveries.length, 1);
  assert.deepEqual(deliveries[0]?.receiver, TARGET);
});
