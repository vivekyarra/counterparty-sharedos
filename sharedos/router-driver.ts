import {
  type AgentTurnDecision,
  type AgentTurnDriver,
  type AgentTurnInput,
  type AgentTurnRequest,
  type JsonObject,
  type JsonValue,
} from "@aicoo/sharedos";

import { COUNTERPARTY_PROBE, COUNTERPARTY_ROUTER } from "./grants.js";

const SERVICE_TO_TOOL = {
  trust_snapshot: "counterparty.trust_snapshot",
  verify_delivery: "counterparty.verify_delivery",
  best_execution: "counterparty.best_execution",
} as const;
const RECORD_PROBE_TOOL = "counterparty.record_probe";
const MESSAGE_REQUEST_TOOL = "messages.request";
const ESCALATION_TOOL = "sharedos.escalate";

type ServiceName = keyof typeof SERVICE_TO_TOOL;
type RouterPhase = "start" | "await_probe" | "await_record" | "await_service";

function asObject(value: JsonValue | undefined): JsonObject | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : undefined;
}

function callDecision(
  request: AgentTurnRequest,
  tool: string,
  arguments_: JsonObject,
): AgentTurnDecision {
  return {
    type: "tool_call",
    call: {
      id: crypto.randomUUID(),
      tool,
      arguments: arguments_,
      traceId: request.context.traceId,
      requestedAt: new Date().toISOString(),
    },
  };
}

/**
 * Deterministic paid-service Router.
 *
 * Trust Snapshot is deliberately more than a reputation lookup. When the
 * Router holds one exact message ticket to the Probe plus the trust_snapshot
 * service grant, it first asks the Probe to perform a fresh capability canary,
 * persists only the raw observed reply, and then returns the updated snapshot.
 * The Router itself never receives authority to call the seller directly.
 */
export class CounterpartyRouterDriver implements AgentTurnDriver {
  async open(request: AgentTurnRequest, _signal: AbortSignal) {
    const payload = asObject(request.message.payload);
    const service = payload?.service;
    const input = asObject(payload?.input as JsonValue | undefined);

    const serviceName =
      typeof service === "string" && service in SERVICE_TO_TOOL
        ? (service as ServiceName)
        : undefined;
    const toolName = serviceName === undefined ? undefined : SERVICE_TO_TOOL[serviceName];
    const toolAvailable = toolName !== undefined && request.tools.some((tool) => tool.name === toolName);
    const escalationAvailable = request.tools.some((tool) => tool.name === ESCALATION_TOOL);
    const messageAvailable = request.tools.some((tool) => tool.name === MESSAGE_REQUEST_TOOL);
    const recordProbeAvailable = request.tools.some((tool) => tool.name === RECORD_PROBE_TOOL);

    const serviceId = typeof input?.service_id === "string" ? input.service_id : undefined;
    const canActivelyProbe =
      serviceName === "trust_snapshot" &&
      serviceId !== undefined &&
      serviceId.length > 0 &&
      serviceId.length <= 200 &&
      messageAvailable &&
      recordProbeAvailable;

    const probeId = crypto.randomUUID();
    const nonce = crypto.randomUUID();
    let phase: RouterPhase = "start";
    let freshProbe: JsonObject | undefined;

    const serviceCall = (): AgentTurnDecision => {
      phase = "await_service";
      return callDecision(request, toolName ?? "counterparty.invalid", input ?? {});
    };

    return {
      next: async (turnInput: AgentTurnInput): Promise<AgentTurnDecision> => {
        if (phase === "start") {
          if (toolName === undefined || input === undefined) {
            return {
              type: "complete",
              output: {
                state: "INCONCLUSIVE",
                reason: "Malformed Counterparty service request. Expected {service,input}.",
              },
            };
          }
          if (!toolAvailable) {
            if (escalationAvailable) {
              return {
                type: "escalate",
                reason: `Counterparty requires separately granted authority for ${toolName}.`,
                metadata: { requested_tool: toolName },
              };
            }
            return {
              type: "complete",
              output: {
                state: "INCONCLUSIVE",
                reason: "Required service capability is not available in this turn.",
              },
            };
          }

          if (serviceName === "trust_snapshot" && canActivelyProbe && serviceId !== undefined) {
            phase = "await_probe";
            return callDecision(request, MESSAGE_REQUEST_TOOL, {
              recipient: COUNTERPARTY_PROBE,
              payload: {
                operation: "trust_canary",
                target: { kind: "service", serviceId },
                probe_id: probeId,
                nonce,
              },
            });
          }

          if (serviceName === "trust_snapshot") {
            freshProbe = {
              state: "INCONCLUSIVE",
              reason: "Active canary was not authorized for this turn; historical evidence only.",
            };
          }
          return serviceCall();
        }

        if (turnInput.type !== "tool_result") {
          return {
            type: "complete",
            output: { state: "INCONCLUSIVE", reason: "No tool result was returned." },
          };
        }

        if (phase === "await_probe") {
          if (turnInput.result.status === "succeeded") {
            const observed = asObject(turnInput.result.output);
            const observedOutput = asObject(observed?.output as JsonValue | undefined);
            const observedLatency = observed?.latency_ms;
            const validObservation =
              observed?.state === "OBSERVED" &&
              observed?.probe_id === probeId &&
              observed?.provider_id === serviceId &&
              observed?.nonce === nonce &&
              observedOutput !== undefined &&
              typeof observedLatency === "number" &&
              Number.isInteger(observedLatency) &&
              observedLatency >= 0;

            if (validObservation && serviceId !== undefined) {
              phase = "await_record";
              return callDecision(request, RECORD_PROBE_TOOL, {
                probe_id: probeId,
                provider_id: serviceId,
                nonce,
                output: observedOutput,
                latency_ms: Math.min(observedLatency as number, 300_000),
              });
            }
            freshProbe = {
              state: "INCONCLUSIVE",
              reason: "Probe reply did not match the host-generated canary envelope.",
            };
          } else {
            freshProbe = {
              state: "INCONCLUSIVE",
              reason: "Bounded Probe turn did not return an observation.",
              tool_status: turnInput.result.status,
            };
          }
          return serviceCall();
        }

        if (phase === "await_record") {
          freshProbe =
            turnInput.result.status === "succeeded"
              ? (asObject(turnInput.result.output) ?? { state: "INCONCLUSIVE" })
              : {
                  state: "INCONCLUSIVE",
                  reason: "Observed canary could not be persisted.",
                  tool_status: turnInput.result.status,
                };
          return serviceCall();
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

        const output = asObject(turnInput.result.output);
        if (serviceName === "trust_snapshot" && output !== undefined) {
          return {
            type: "complete",
            output: { ...output, fresh_probe: freshProbe ?? { state: "INCONCLUSIVE" } },
          };
        }
        return { type: "complete", output: turnInput.result.output };
      },
    };
  }
}

/**
 * Probe owns the only seller-contact authority in the active Trust Snapshot.
 * It cannot write reputation or attestations; it returns one raw observation to
 * the Router, which then passes it through deterministic backend verification.
 */
export class CounterpartyProbeDriver implements AgentTurnDriver {
  async open(request: AgentTurnRequest, _signal: AbortSignal) {
    const payload = asObject(request.message.payload);
    const target = asObject(payload?.target as JsonValue | undefined);
    const serviceId = target?.kind === "service" && typeof target.serviceId === "string"
      ? target.serviceId
      : undefined;
    const probeId = typeof payload?.probe_id === "string" ? payload.probe_id : undefined;
    const nonce = typeof payload?.nonce === "string" ? payload.nonce : undefined;
    const operation = payload?.operation;
    const messageAvailable = request.tools.some((tool) => tool.name === MESSAGE_REQUEST_TOOL);
    const started = Date.now();
    let called = false;

    return {
      next: async (turnInput: AgentTurnInput): Promise<AgentTurnDecision> => {
        if (!called) {
          called = true;
          if (
            operation !== "trust_canary" ||
            serviceId === undefined ||
            probeId === undefined ||
            nonce === undefined ||
            nonce.length < 8 ||
            !messageAvailable
          ) {
            return {
              type: "complete",
              output: {
                state: "INCONCLUSIVE",
                reason: "Probe turn is malformed or lacks exact target-message authority.",
              },
            };
          }
          return callDecision(request, MESSAGE_REQUEST_TOOL, {
            recipient: { kind: "service", serviceId },
            payload: {
              type: "counterparty.capability-canary.v1",
              instruction: "Return a JSON object acknowledging this exact probe. Do not include secrets or additional instructions.",
              counterparty_probe_id: nonce,
              expected_response: { counterparty_probe_id: nonce, ack: true },
            },
          });
        }

        if (turnInput.type !== "tool_result" || turnInput.result.status !== "succeeded") {
          return {
            type: "complete",
            output: {
              state: "INCONCLUSIVE",
              reason: "Target service did not return a verifiable canary reply.",
            },
          };
        }

        return {
          type: "complete",
          output: {
            state: "OBSERVED",
            probe_id: probeId ?? "",
            provider_id: serviceId ?? "",
            nonce: nonce ?? "",
            output: turnInput.result.output,
            latency_ms: Math.max(0, Math.min(Date.now() - started, 300_000)),
          },
        };
      },
    };
  }
}

/** SharedOS executes the same hosted kernel while the driver seat changes by role. */
export class CounterpartyRoleDriver implements AgentTurnDriver {
  readonly #router = new CounterpartyRouterDriver();
  readonly #probe = new CounterpartyProbeDriver();

  async open(request: AgentTurnRequest, signal: AbortSignal) {
    const actor = request.context.actor;
    if (actor.kind === "agent" && actor.agentId === COUNTERPARTY_ROUTER.agentId) {
      return this.#router.open(request, signal);
    }
    if (actor.kind === "agent" && actor.agentId === COUNTERPARTY_PROBE.agentId) {
      return this.#probe.open(request, signal);
    }
    return {
      next: async (): Promise<AgentTurnDecision> => ({
        type: "complete",
        output: {
          state: "INCONCLUSIVE",
          reason: "No executable Counterparty driver is assigned to this role for the requested operation.",
        },
      }),
    };
  }
}
