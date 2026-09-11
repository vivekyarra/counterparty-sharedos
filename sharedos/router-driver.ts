import {
  type AgentTurnDecision,
  type AgentTurnDriver,
  type AgentTurnInput,
  type AgentTurnRequest,
  type JsonObject,
  type JsonValue,
} from "@aicoo/sharedos";

const SERVICE_TO_TOOL = {
  trust_snapshot: "counterparty.trust_snapshot",
  verify_delivery: "counterparty.verify_delivery",
  best_execution: "counterparty.best_execution",
} as const;

type ServiceName = keyof typeof SERVICE_TO_TOOL;

function asObject(value: JsonValue): JsonObject | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : undefined;
}

/**
 * A deterministic product-agent driver.
 *
 * Counterparty does not need an LLM to route paid service calls. This keeps the
 * paid path cheap, reproducible, and robust under Arena load while still running
 * as a bounded SharedOS turn. Semantic/probe agents can be added behind the same
 * boundary without changing the buyer contract.
 */
export class CounterpartyRouterDriver implements AgentTurnDriver {
  async open(request: AgentTurnRequest) {
    const payload = asObject(request.message.payload);
    const service = payload?.service;
    const input = payload?.input;

    const serviceName =
      typeof service === "string" && service in SERVICE_TO_TOOL
        ? (service as ServiceName)
        : undefined;
    const toolName = serviceName === undefined ? undefined : SERVICE_TO_TOOL[serviceName];
    const toolAvailable = toolName !== undefined && request.tools.some((tool) => tool.name === toolName);
    let called = false;

    return {
      next: async (turnInput: AgentTurnInput): Promise<AgentTurnDecision> => {
        if (!called) {
          called = true;
          if (toolName === undefined || asObject(input as JsonValue) === undefined) {
            return {
              type: "complete",
              output: {
                state: "INCONCLUSIVE",
                reason: "Malformed Counterparty service request. Expected {service,input}.",
              },
            };
          }
          if (!toolAvailable) {
            return {
              type: "complete",
              output: {
                state: "INCONCLUSIVE",
                reason: "Required service capability is not available in this turn.",
              },
            };
          }
          return {
            type: "tool_call",
            call: {
              id: crypto.randomUUID(),
              tool: toolName,
              arguments: asObject(input as JsonValue) ?? {},
              traceId: request.context.traceId,
              requestedAt: new Date().toISOString(),
            },
          };
        }

        if (turnInput.type !== "tool_result") {
          return {
            type: "complete",
            output: { state: "INCONCLUSIVE", reason: "No tool result was returned." },
          };
        }

        if (turnInput.result.status !== "succeeded") {
          return {
            type: "complete",
            output: {
              state: "INCONCLUSIVE",
              reason: "Counterparty service execution did not succeed.",
              tool_status: turnInput.result.status,
            },
          };
        }

        return { type: "complete", output: turnInput.result.output };
      },
    };
  }
}
