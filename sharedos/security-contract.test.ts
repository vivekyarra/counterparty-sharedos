import assert from "node:assert/strict";
import test from "node:test";

import { counterpartyTools } from "./tools.js";
import {
  COUNTERPARTY_ATTESTOR,
  COUNTERPARTY_JUDGE,
  COUNTERPARTY_PROBE,
  COUNTERPARTY_ROUTER,
  attestorReceiptGrant,
  escalationGrant,
  judgeEvidenceGrant,
  probeTargetGrant,
  routerExecutionGrant,
  routerServiceGrant,
} from "./grants.js";

import {
  CapabilityAuthorizer,
  createEscalationTool,
  InMemoryGrantUsageStore,
  SharedOSKernel,
  type AccessContext,
  type Address,
  type CapabilityGrant,
  type JsonObject,
  type ToolHandler,
} from "@aicoo/sharedos";

const OWNER = { kind: "human", userId: "owner" } as const;
const BUYER = { kind: "agent", agentId: "buyer" } as const;
const PURPOSE = "counterparty.verify-and-route-sharednet-services";
const NAMESPACE = "counterparty-arena";
const RESOURCE = { namespace: "counterparty", path: ["services", "trust_snapshot"], owner: OWNER };
const TARGET_RESOURCE = { namespace: "sharednet", path: ["services", "target-a"], owner: OWNER };

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

const targetHandler: ToolHandler = {
  definition: {
    name: "sharednet.target_invoke",
    description: "bounded target service used to prove probe-role isolation",
    namespace: "sharednet",
    source: "native",
    readWrite: "write",
    inputSchema: { type: "object" },
    requiredCapability: { resource: TARGET_RESOURCE, action: "invoke" },
    annotations: { readOnly: false },
  },
  parseArguments: (value) => value,
  async invoke(_context, call) {
    return {
      callId: call.id,
      tool: call.tool,
      status: "succeeded",
      output: { target: "target-a", ok: true },
      completedAt: new Date().toISOString(),
    };
  },
};

function access(purpose = PURPOSE): AccessContext {
  return {
    namespaceId: NAMESPACE,
    actor: BUYER,
    authority: OWNER,
    owner: OWNER,
    purpose,
    traceId: crypto.randomUUID(),
    enabledToolNamespaces: ["counterparty"],
    now: new Date().toISOString(),
  };
}

function roleAccess(actor: Address, enabledToolNamespaces: string[]): AccessContext {
  return {
    namespaceId: NAMESPACE,
    actor,
    authority: OWNER,
    owner: OWNER,
    purpose: PURPOSE,
    traceId: crypto.randomUUID(),
    enabledToolNamespaces,
    now: new Date().toISOString(),
  };
}

function grant(maxUses = 1): CapabilityGrant {
  return {
    id: "grant-buyer-trust",
    namespaceId: NAMESPACE,
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
          (g) =>
            g.namespaceId === ctx.namespaceId &&
            JSON.stringify(g.subject) === JSON.stringify(ctx.actor) &&
            JSON.stringify(g.issuer) === JSON.stringify(ctx.authority),
        );
      },
    },
    authorizer: new CapabilityAuthorizer({ usageStore: new InMemoryGrantUsageStore() }),
  });
  k.registerTool(handler);
  k.registerTool(targetHandler);
  k.registerTool(createEscalationTool());
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

function targetCall(ctx: AccessContext) {
  return {
    id: crypto.randomUUID(),
    tool: "sharednet.target_invoke",
    arguments: { task: "safe bounded probe" },
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

test("Counterparty service executes as a bounded SharedOS turn with path-safe agent identity", async () => {
  const k = kernel([
    routerServiceGrant(OWNER, NAMESPACE, "trust_snapshot"),
    routerExecutionGrant(OWNER, NAMESPACE, "grant-router-execution"),
  ]);
  const { SharedOSExecutor, StandardRuntime } = await import("@aicoo/sharedos");
  const { CounterpartyRouterDriver } = await import("./router-driver.js");
  const turns = new SharedOSExecutor(k, new StandardRuntime(new CounterpartyRouterDriver()), {
    defaultMaxSteps: 4,
    defaultMaxToolCalls: 2,
    defaultTimeoutMs: 5_000,
  });
  const ctx = roleAccess(COUNTERPARTY_ROUTER, ["counterparty"]);
  const tools = await k.listTools(ctx);
  const result = await turns.execute({
    version: "1",
    executionId: crypto.randomUUID(),
    agent: COUNTERPARTY_ROUTER,
    context: ctx,
    tools: [...tools],
    message: {
      version: "1",
      id: crypto.randomUUID(),
      sender: BUYER,
      receiver: COUNTERPARTY_ROUTER,
      purpose: PURPOSE,
      payload: { service: "trust_snapshot", input: { service_id: "target" } },
      traceId: ctx.traceId,
      createdAt: new Date().toISOString(),
    },
  });
  assert.equal(result.status, "succeeded", `turn result: ${JSON.stringify(result)}`);
});

test("role grants enforce Router/Probe/Judge/Attestor separation", async () => {
  const grants = [
    routerServiceGrant(OWNER, NAMESPACE, "trust_snapshot"),
    probeTargetGrant(OWNER, NAMESPACE, "target-a", 3),
    judgeEvidenceGrant(OWNER, NAMESPACE, "eval-1"),
    attestorReceiptGrant(OWNER, NAMESPACE, "eval-1"),
  ];
  const k = kernel(grants);

  const routerCtx = roleAccess(COUNTERPARTY_ROUTER, ["sharednet"]);
  assert.deepEqual(await k.listTools(routerCtx), []);
  assert.equal((await k.invokeTool(routerCtx, targetCall(routerCtx))).status, "denied");

  const probeCtx = roleAccess(COUNTERPARTY_PROBE, ["sharednet"]);
  const probeTools = await k.listTools(probeCtx);
  assert.deepEqual(probeTools.map((tool) => tool.name), ["sharednet.target_invoke"]);
  for (let i = 0; i < 3; i += 1) {
    assert.equal((await k.invokeTool(probeCtx, targetCall(probeCtx))).status, "succeeded");
  }
  const exhausted = await k.invokeTool(probeCtx, targetCall(probeCtx));
  assert.equal(exhausted.status, "denied");
  if (exhausted.status === "denied") assert.equal(exhausted.error.code, "grant_exhausted");

  const judgeCtx = roleAccess(COUNTERPARTY_JUDGE, ["sharednet"]);
  assert.equal((await k.invokeTool(judgeCtx, targetCall(judgeCtx))).status, "denied");
  const evidenceDecision = await k.authorize(judgeCtx, {
    resource: {
      namespace: "counterparty.evidence",
      path: ["evaluations", "eval-1"],
      owner: OWNER,
    },
    action: "read",
  });
  assert.equal(evidenceDecision.allowed, true);

  const attestorCtx = roleAccess(COUNTERPARTY_ATTESTOR, ["sharednet"]);
  assert.equal((await k.invokeTool(attestorCtx, targetCall(attestorCtx))).status, "denied");
  const receiptDecision = await k.authorize(attestorCtx, {
    resource: {
      namespace: "counterparty.attestations",
      path: ["evaluations", "eval-1"],
      owner: OWNER,
    },
    action: "create",
  });
  assert.equal(receiptDecision.allowed, true);
});

test("missing service authority escalates only when SharedOS escalation is separately granted", async () => {
  const k = kernel([
    routerExecutionGrant(OWNER, NAMESPACE, "grant-router-execution-escalation"),
    escalationGrant(COUNTERPARTY_ROUTER, OWNER, NAMESPACE),
  ]);
  const { SharedOSExecutor, StandardRuntime } = await import("@aicoo/sharedos");
  const { CounterpartyRouterDriver } = await import("./router-driver.js");
  const turns = new SharedOSExecutor(k, new StandardRuntime(new CounterpartyRouterDriver()), {
    defaultMaxSteps: 4,
    defaultMaxToolCalls: 2,
    defaultTimeoutMs: 5_000,
  });
  const ctx = roleAccess(COUNTERPARTY_ROUTER, ["counterparty", "sharedos"]);
  const tools = await k.listTools(ctx);
  assert.deepEqual(tools.map((tool) => tool.name), ["sharedos.escalate"]);
  const result = await turns.execute({
    version: "1",
    executionId: crypto.randomUUID(),
    agent: COUNTERPARTY_ROUTER,
    context: ctx,
    tools: [...tools],
    message: {
      version: "1",
      id: crypto.randomUUID(),
      sender: BUYER,
      receiver: COUNTERPARTY_ROUTER,
      purpose: PURPOSE,
      payload: { service: "trust_snapshot", input: { service_id: "target" } },
      traceId: ctx.traceId,
      createdAt: new Date().toISOString(),
    },
  });
  assert.equal(result.status, "escalated", `turn result: ${JSON.stringify(result)}`);
});

test("without an escalation grant missing authority terminates INCONCLUSIVE, not escalated", async () => {
  const k = kernel([routerExecutionGrant(OWNER, NAMESPACE, "grant-router-no-escalation")]);
  const { SharedOSExecutor, StandardRuntime } = await import("@aicoo/sharedos");
  const { CounterpartyRouterDriver } = await import("./router-driver.js");
  const turns = new SharedOSExecutor(k, new StandardRuntime(new CounterpartyRouterDriver()), {
    defaultMaxSteps: 4,
    defaultMaxToolCalls: 2,
    defaultTimeoutMs: 5_000,
  });
  const ctx = roleAccess(COUNTERPARTY_ROUTER, ["counterparty", "sharedos"]);
  const tools = await k.listTools(ctx);
  assert.deepEqual(tools, []);
  const result = await turns.execute({
    version: "1",
    executionId: crypto.randomUUID(),
    agent: COUNTERPARTY_ROUTER,
    context: ctx,
    tools: [],
    message: {
      version: "1",
      id: crypto.randomUUID(),
      sender: BUYER,
      receiver: COUNTERPARTY_ROUTER,
      purpose: PURPOSE,
      payload: { service: "trust_snapshot", input: { service_id: "target" } },
      traceId: ctx.traceId,
      createdAt: new Date().toISOString(),
    },
  });
  assert.equal(result.status, "succeeded");
  if (result.status === "succeeded") {
    assert.deepEqual(result.output, {
      state: "INCONCLUSIVE",
      reason: "Required service capability is not available in this turn.",
    });
  }
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
