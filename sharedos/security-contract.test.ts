import assert from "node:assert/strict";
import test from "node:test";

import { counterpartyTools } from "./tools.js";

import {
  CapabilityAuthorizer,
  agentExecutionCapability,
  InMemoryGrantUsageStore,
  SharedOSKernel,
  type AccessContext,
  type CapabilityGrant,
  type JsonObject,
  type ToolHandler,
} from "@aicoo/sharedos";

const OWNER = { kind: "human", userId: "owner" } as const;
const BUYER = { kind: "agent", agentId: "buyer" } as const;
const PURPOSE = "counterparty.verify-and-route-sharednet-services";
const RESOURCE = { namespace: "counterparty", path: ["services", "trust_snapshot"], owner: OWNER };

const handler: ToolHandler = {
  definition: {
    name: "counterparty.trust_snapshot",
    description: "test service",
    namespace: "counterparty",
    source: "native",
    readWrite: "read",
    inputSchema: { type: "object" },
    requiredCapability: { resource: RESOURCE, action: "invoke" },
    annotations: { readOnly: true },
  },
  parseArguments: (value) => value,
  async invoke(_context, call) {
    return {
      callId: call.id,
      tool: call.tool,
      status: "succeeded",
      output: { verdict: "UNPROVEN" },
      completedAt: new Date().toISOString(),
    };
  },
};

function access(purpose = PURPOSE): AccessContext {
  return {
    namespaceId: "counterparty-arena",
    actor: BUYER,
    authority: OWNER,
    owner: OWNER,
    purpose,
    traceId: crypto.randomUUID(),
    enabledToolNamespaces: ["counterparty"],
    now: new Date().toISOString(),
  };
}

function grant(maxUses = 1): CapabilityGrant {
  return {
    id: "grant-buyer-trust",
    namespaceId: "counterparty-arena",
    subject: BUYER,
    issuer: OWNER,
    capabilities: [{ resource: RESOURCE, actions: ["invoke"], scope: "exact" }],
    constraints: { purposes: [PURPOSE], maxUses },
    issuedAt: new Date().toISOString(),
  };
}

function kernel(grants: CapabilityGrant[]) {
  const k = new SharedOSKernel({
    grantSource: {
      async load(ctx) {
        return grants.filter(
          (g) => g.namespaceId === ctx.namespaceId && JSON.stringify(g.subject) === JSON.stringify(ctx.actor) && JSON.stringify(g.issuer) === JSON.stringify(ctx.authority),
        );
      },
    },
    authorizer: new CapabilityAuthorizer({ usageStore: new InMemoryGrantUsageStore() }),
  });
  k.registerTool(handler);
  return k;
}

function call(ctx: AccessContext) {
  return {
    id: crypto.randomUUID(),
    tool: "counterparty.trust_snapshot",
    arguments: { service_id: "target" },
    traceId: ctx.traceId,
    requestedAt: new Date().toISOString(),
  };
}

test("deny-by-default hides and refuses the service without a grant", async () => {
  const k = kernel([]);
  const ctx = access();
  assert.deepEqual(await k.listTools(ctx), []);
  const result = await k.invokeTool(ctx, call(ctx));
  assert.equal(result.status, "denied");
});

test("purpose mismatch does not inherit authority", async () => {
  const k = kernel([grant(1)]);
  const ctx = access("some-other-purpose");
  assert.deepEqual(await k.listTools(ctx), []);
  const result = await k.invokeTool(ctx, call(ctx));
  assert.equal(result.status, "denied");
});

test("maxUses is consumed atomically: one allowed invocation, then denial", async () => {
  const k = kernel([grant(1)]);
  const ctx = access();
  const visible = await k.listTools(ctx);
  assert.equal(visible.length, 1);
  assert.equal(visible[0]?.name, "counterparty.trust_snapshot");

  const first = await k.invokeTool(ctx, call(ctx));
  assert.equal(first.status, "succeeded");

  const second = await k.invokeTool(ctx, call(ctx));
  assert.equal(second.status, "denied");
});

test("Counterparty service can execute as a bounded SharedOS turn", async () => {
  const router = { kind: "agent", agentId: "counterparty/router" } as const;
  const owner = OWNER;
  const serviceGrant: CapabilityGrant = {
    id: "grant-router-service",
    namespaceId: "counterparty-arena",
    subject: router,
    issuer: owner,
    capabilities: [{ resource: RESOURCE, actions: ["invoke"], scope: "exact" }],
    constraints: { purposes: [PURPOSE] },
    issuedAt: new Date().toISOString(),
  };
  const executionGrant: CapabilityGrant = {
    id: "grant-router-execution",
    namespaceId: "counterparty-arena",
    subject: router,
    issuer: owner,
    capabilities: [agentExecutionCapability(router, owner)],
    constraints: { purposes: [PURPOSE] },
    issuedAt: new Date().toISOString(),
  };

  const k = kernel([serviceGrant, executionGrant]);
  const { SharedOSExecutor, StandardRuntime } = await import("@aicoo/sharedos");
  const { CounterpartyRouterDriver } = await import("./router-driver.js");
  const turns = new SharedOSExecutor(k, new StandardRuntime(new CounterpartyRouterDriver()), {
    defaultMaxSteps: 4,
    defaultMaxToolCalls: 2,
    defaultTimeoutMs: 5_000,
  });
  const ctx: AccessContext = {
    ...access(),
    actor: router,
    traceId: crypto.randomUUID(),
  };
  const tools = await k.listTools(ctx);
  const result = await turns.execute({
    version: "1",
    executionId: crypto.randomUUID(),
    agent: router,
    context: ctx,
    tools: [...tools],
    message: {
      version: "1",
      id: crypto.randomUUID(),
      sender: BUYER,
      receiver: router,
      purpose: PURPOSE,
      payload: { service: "trust_snapshot", input: { service_id: "target" } },
      traceId: ctx.traceId,
      createdAt: new Date().toISOString(),
    },
  });
  assert.equal(result.status, "succeeded");
});

test("verify_delivery strips caller-supplied evidence fields and fails closed without host evidence", async () => {
  const tools = counterpartyTools({
    baseUrl: "http://127.0.0.1:9",
    internalToken: "x".repeat(32),
    deliveryResolver: {
      async resolve() {
        return undefined;
      },
    },
  });
  const verify = tools.find((tool) => tool.definition.name === "counterparty.verify_delivery");
  if (verify === undefined) throw new Error("verify tool missing");

  const parsed = verify.parseArguments({
    delivery_id: "immutable-1",
    provider_id: "forged-provider",
    output: { forged: true },
    assertions: [{ path: "/forged", op: "eq", value: true }],
  });
  assert.deepEqual(parsed, { delivery_id: "immutable-1" });

  const ctx = access();
  const result = await verify.invoke(
    ctx,
    {
      id: crypto.randomUUID(),
      tool: "counterparty.verify_delivery",
      arguments: parsed as JsonObject,
      traceId: ctx.traceId,
      requestedAt: new Date().toISOString(),
    },
    new AbortController().signal,
  );
  assert.equal(result.status, "succeeded");
  if (result.status !== "succeeded") throw new Error("verify tool did not succeed");
  assert.deepEqual(result.output, {
    state: "INCONCLUSIVE",
    reason: "No immutable host-owned evidence exists for this delivery ID.",
    reputation_updated: false,
  });
});
