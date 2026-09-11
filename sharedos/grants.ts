import {
  agentExecutionCapability,
  type Address,
  type CapabilityGrant,
} from "@aicoo/sharedos";

import { COUNTERPARTY_PURPOSE } from "./tools.js";

// Agent IDs deliberately contain no path separators. SharedOS execution grants
// encode the address ID as a ResourceRef path segment, where '/' and '\\' are
// invalid by contract.
export const COUNTERPARTY_ROUTER = { kind: "agent", agentId: "counterparty-router" } as const;
export const COUNTERPARTY_PROBE = { kind: "agent", agentId: "counterparty-probe" } as const;
export const COUNTERPARTY_JUDGE = { kind: "agent", agentId: "counterparty-judge" } as const;
export const COUNTERPARTY_ATTESTOR = { kind: "agent", agentId: "counterparty-attestor" } as const;

function addressIdentifier(address: Address): string {
  switch (address.kind) {
    case "human":
      return address.userId;
    case "agent":
      return address.agentId;
    case "group":
      return address.conversationId;
    case "service":
      return address.serviceId;
  }
}

/** Execute exactly the Counterparty router for the product purpose. */
export function routerExecutionGrant(
  owner: Address,
  namespaceId: string,
  id: string,
  maxUses = 1,
): CapabilityGrant {
  return {
    id,
    namespaceId,
    subject: COUNTERPARTY_ROUTER,
    issuer: owner,
    capabilities: [agentExecutionCapability(COUNTERPARTY_ROUTER, owner)],
    constraints: { purposes: [COUNTERPARTY_PURPOSE], maxUses },
    issuedAt: new Date().toISOString(),
  };
}

/** Router product-internal authority. It gets no target-service invocation authority. */
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

/** Probe authority is exact-target and bounded. It cannot write evidence or attestations. */
export function probeTargetGrant(
  owner: Address,
  namespaceId: string,
  targetServiceKey: string,
  maxUses = 3,
): CapabilityGrant {
  return {
    id: `grant-probe-${targetServiceKey}`,
    namespaceId,
    subject: COUNTERPARTY_PROBE,
    issuer: owner,
    capabilities: [
      {
        resource: {
          namespace: "sharednet",
          path: ["services", targetServiceKey],
          owner,
        },
        actions: ["invoke"],
        scope: "exact",
      },
    ],
    constraints: { purposes: [COUNTERPARTY_PURPOSE], maxUses },
    issuedAt: new Date().toISOString(),
  };
}

/** Judge can read only one evaluation's sealed evidence and cannot invoke the target. */
export function judgeEvidenceGrant(
  owner: Address,
  namespaceId: string,
  evaluationId: string,
  maxUses = 8,
): CapabilityGrant {
  return {
    id: `grant-judge-${evaluationId}`,
    namespaceId,
    subject: COUNTERPARTY_JUDGE,
    issuer: owner,
    capabilities: [
      {
        resource: {
          namespace: "counterparty.evidence",
          path: ["evaluations", evaluationId],
          owner,
        },
        actions: ["read"],
        scope: "exact",
      },
    ],
    constraints: { purposes: [COUNTERPARTY_PURPOSE], maxUses },
    issuedAt: new Date().toISOString(),
  };
}

/** Attestor can create exactly one receipt for one evaluation; it cannot probe targets. */
export function attestorReceiptGrant(
  owner: Address,
  namespaceId: string,
  evaluationId: string,
): CapabilityGrant {
  return {
    id: `grant-attestor-${evaluationId}`,
    namespaceId,
    subject: COUNTERPARTY_ATTESTOR,
    issuer: owner,
    capabilities: [
      {
        resource: {
          namespace: "counterparty.attestations",
          path: ["evaluations", evaluationId],
          owner,
        },
        actions: ["create"],
        scope: "exact",
      },
    ],
    constraints: { purposes: [COUNTERPARTY_PURPOSE], maxUses: 1 },
    issuedAt: new Date().toISOString(),
  };
}

/** Escalation is separately granted; it never grants the missing authority itself. */
export function escalationGrant(
  subject: Address,
  owner: Address,
  namespaceId: string,
): CapabilityGrant {
  return {
    id: `grant-escalation-${subject.kind}-${addressIdentifier(subject)}`,
    namespaceId,
    subject,
    issuer: owner,
    capabilities: [
      {
        resource: { namespace: "sharedos", path: ["escalation"], owner },
        actions: ["request"],
        scope: "exact",
      },
    ],
    constraints: { purposes: [COUNTERPARTY_PURPOSE] },
    issuedAt: new Date().toISOString(),
  };
}
