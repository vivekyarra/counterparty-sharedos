import type {
  AccessContext,
  JsonObject,
  JsonValue,
  ToolCall,
  ToolHandler,
  ToolResult,
} from "@aicoo/sharedos";

export const COUNTERPARTY_NAMESPACE = "counterparty";
export const COUNTERPARTY_PURPOSE = "counterparty.verify-and-route-sharednet-services";

export interface TrustedDelivery {
  readonly delivery_id: string;
  readonly provider_id: string;
  readonly task: string;
  readonly task_type?: string;
  readonly output: JsonValue;
  readonly expected_schema?: JsonObject;
  readonly assertions?: readonly JsonObject[];
  readonly cited_urls?: readonly string[];
  readonly independent_checks?: readonly JsonObject[];
}

export interface TrustedDeliveryResolver {
  resolve(context: AccessContext, deliveryId: string, signal: AbortSignal): Promise<TrustedDelivery | undefined>;
}

export interface CounterpartyBackendOptions {
  readonly baseUrl: string;
  readonly internalToken: string;
  readonly deliveryResolver: TrustedDeliveryResolver;
}

function completed(call: ToolCall, output: unknown): ToolResult {
  return {
    callId: call.id,
    tool: call.tool,
    status: "succeeded",
    output: output as JsonObject,
    completedAt: new Date().toISOString(),
  };
}

async function callBackend(
  options: CounterpartyBackendOptions,
  endpoint: string,
  body: JsonObject,
  signal: AbortSignal,
): Promise<JsonObject> {
  const response = await fetch(new URL(endpoint, options.baseUrl), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-counterparty-internal-token": options.internalToken,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    throw new Error(`counterparty backend returned ${response.status}`);
  }
  return (await response.json()) as JsonObject;
}

function proxyTool(
  options: CounterpartyBackendOptions,
  spec: {
    readonly name: string;
    readonly endpoint: string;
    readonly description: string;
    readonly readWrite: "read" | "write";
    readonly inputSchema: JsonObject;
    readonly capabilityPath?: readonly string[];
  },
): ToolHandler {
  const serviceName = spec.name.split(".").at(-1) ?? spec.name;
  return {
    definition: {
      name: spec.name,
      description: spec.description,
      namespace: COUNTERPARTY_NAMESPACE,
      source: "native",
      readWrite: spec.readWrite,
      inputSchema: spec.inputSchema,
      requiredCapability: {
        resource: {
          namespace: COUNTERPARTY_NAMESPACE,
          path: [...(spec.capabilityPath ?? ["services", serviceName])],
        },
        action: "invoke",
      },
      annotations: { readOnly: spec.readWrite === "read" },
    },
    parseArguments(arguments_: JsonObject) {
      return arguments_;
    },
    async invoke(_context: AccessContext, call: ToolCall, signal: AbortSignal): Promise<ToolResult> {
      const output = await callBackend(options, spec.endpoint, call.arguments, signal);
      return completed(call, output);
    },
  };
}

function trustedVerifyDeliveryTool(options: CounterpartyBackendOptions): ToolHandler {
  const name = "counterparty.verify_delivery";
  return {
    definition: {
      name,
      description: "Verify one immutable SharedNet delivery. The caller supplies only its delivery ID; host-owned evidence is resolved before evaluation.",
      namespace: COUNTERPARTY_NAMESPACE,
      source: "native",
      readWrite: "write",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["delivery_id"],
        properties: {
          delivery_id: { type: "string", minLength: 1, maxLength: 200 },
        },
      },
      requiredCapability: {
        resource: { namespace: COUNTERPARTY_NAMESPACE, path: ["services", "verify_delivery"] },
        action: "invoke",
      },
      annotations: { readOnly: false },
    },
    parseArguments(arguments_: JsonObject) {
      const deliveryId = arguments_.delivery_id;
      if (typeof deliveryId !== "string" || deliveryId.length === 0 || deliveryId.length > 200) {
        throw new TypeError("delivery_id must be a non-empty string no longer than 200 characters");
      }
      return { delivery_id: deliveryId };
    },
    async invoke(context: AccessContext, call: ToolCall, signal: AbortSignal): Promise<ToolResult> {
      const deliveryId = String(call.arguments.delivery_id ?? "");
      const trusted = await options.deliveryResolver.resolve(context, deliveryId, signal);
      if (trusted === undefined || trusted.delivery_id !== deliveryId) {
        return completed(call, {
          state: "INCONCLUSIVE",
          reason: "No immutable host-owned evidence exists for this delivery ID.",
          reputation_updated: false,
        });
      }
      const body: JsonObject = {
        delivery_id: trusted.delivery_id,
        provider_id: trusted.provider_id,
        task: trusted.task,
        task_type: trusted.task_type ?? "general",
        output: trusted.output,
        ...(trusted.expected_schema === undefined ? {} : { expected_schema: trusted.expected_schema }),
        ...(trusted.assertions === undefined ? {} : { assertions: [...trusted.assertions] }),
        ...(trusted.cited_urls === undefined ? {} : { cited_urls: [...trusted.cited_urls] }),
        ...(trusted.independent_checks === undefined ? {} : { independent_checks: [...trusted.independent_checks] }),
      };
      const output = await callBackend(options, "/v1/verify-delivery", body, signal);
      return completed(call, output);
    },
  };
}

export function counterpartyTools(options: CounterpartyBackendOptions): readonly ToolHandler[] {
  return [
    proxyTool(options, {
      name: "counterparty.trust_snapshot",
      endpoint: "/v1/trust-snapshot",
      description: "Return Counterparty's evidence-backed trust decision after the Router's optional active canary completes.",
      readWrite: "read",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["service_id"],
        properties: {
          service_id: { type: "string", minLength: 1, maxLength: 200 },
          task_type: { type: "string", minLength: 1, maxLength: 100 },
        },
      },
    }),
    // Internal step of the paid Trust Snapshot flow. It shares the exact
    // trust_snapshot capability; the buyer never supplies these fields because
    // resolveContext fixes the actor to the Router and the driver constructs
    // them only from a Probe-agent reply.
    proxyTool(options, {
      name: "counterparty.record_probe",
      endpoint: "/v1/probe-observation",
      description: "Persist one host-observed bounded capability canary without treating it as task-delivery evidence.",
      readWrite: "write",
      capabilityPath: ["services", "trust_snapshot"],
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["probe_id", "provider_id", "nonce", "output", "latency_ms"],
        properties: {
          probe_id: { type: "string", minLength: 1, maxLength: 200 },
          provider_id: { type: "string", minLength: 1, maxLength: 200 },
          nonce: { type: "string", minLength: 8, maxLength: 200 },
          output: {},
          latency_ms: { type: "integer", minimum: 0, maximum: 300000 },
        },
      },
    }),
    trustedVerifyDeliveryTool(options),
    proxyTool(options, {
      name: "counterparty.best_execution",
      endpoint: "/v1/best-execution",
      description: "Choose where to spend Arena credits using task evidence first and bounded protocol-canary evidence to break cold start safely.",
      readWrite: "read",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["task", "budget_credits", "candidates"],
        properties: {
          task: { type: "string", minLength: 1, maxLength: 12000 },
          task_type: { type: "string", minLength: 1, maxLength: 100 },
          budget_credits: { type: "integer", minimum: 1, maximum: 100 },
          mode: { type: "string", enum: ["safe", "explore"] },
          candidates: { type: "array", minItems: 1, maxItems: 32 },
        },
      },
    }),
  ];
}
