import {
  agentExecutionCapability,
  type Address,
  type CapabilityGrant,
} from "@aicoo/sharedos";

import { COUNTERPARTY_PURPOSE } from "./tools.js";

export const COUNTERPARTY_ROUTER = { kind: "agent", agentId: "counterparty/router" } as const;
export const COUNTERPARTY_PROBE = { kind: "agent", agentId: "counterparty/probe" } as const;
export const COUNTERPARTY_JUDGE = { kind: "agent", agentId: "counterparty/judge" } as const;
export const COUNTERPARTY_ATTESTOR = { kind: "agent", agentId: "counterparty/attestor" } as const;

/** Router authority to execute exactly the Counterparty product agent for this purpose. */
export function routerExecutionGrant(
  owner: Address,
  namespaceId: string,
  id: string,
): CapabilityGrant {
  return {
    id,
    namespaceId,
    subject: COUNTERPARTY_ROUTER,
    issuer: owner,
    capabilities: [agentExecutionCapability(COUNTERPARTY_ROUTER, owner)],
    constraints: { purposes: [COUNTERPARTY_PURPOSE], maxUses: 3 },
    issuedAt: new Date().toISOString(),
  };
}

/** Router's product-internal service tools. It gets no target-agent send authority. */
export function routerServiceGrant(
  owner: Address,
  namespaceId: string,
  service: "trust_snapshot" | "verify_delivery" | "best_execution",
): CapabilityGrant {
  return {
    id: `grant-router-${service}`,
    namespaceId,
    subject: COUNTERPARTY_ROUTER,
    issuer: owner,
    capabilities: [
      {
        resource: {
          namespace: "counterparty",
          path: ["services", service],
          owner,
        },
        actions: ["invoke"],
        scope: "exact",
      },
    ],
    constraints: { purposes: [COUNTERPARTY_PURPOSE] },
    issuedAt: new Date().toISOString(),
  };
}
