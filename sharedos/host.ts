/**
 * Counterparty's SharedOS host boundary.
 *
 * The HTTP caller never supplies grants or access context. `resolveContext`
 * must derive identity, authority, owner, purpose and namespace selection from
 * authenticated server-side state. The kernel reloads grants from the trusted
 * GrantSource and re-authorizes every exact tool invocation.
 */
import {
  CapabilityAuthorizer,
  SharedOSExecutor,
  SharedOSKernel,
  StandardRuntime,
  createEscalationTool,
  createKernelSharedOSApi,
  createSharedOSHandler,
  type AccessContext,
  type AuditSink,
  type DelegationChainResolver,
  type GrantSource,
  type GrantUsageStore,
  type MessageRequestRouter,
  type MessageTransport,
  type ToolNamespaceSettingsStore,
  type TurnErrorReporter,
} from "@aicoo/sharedos";

import { CounterpartyRoleDriver } from "./router-driver.js";
import { counterpartyTools, type CounterpartyBackendOptions } from "./tools.js";

export interface CounterpartySharedOSHostDeps {
  readonly grantSource: GrantSource;
  readonly usageStore: GrantUsageStore;
  readonly delegationResolver?: DelegationChainResolver;
  readonly audit: AuditSink;
  readonly toolNamespaceSettings: ToolNamespaceSettingsStore;
  readonly messageTransport: MessageTransport;
  readonly messageRequestRouter: MessageRequestRouter;
  readonly resolveContext: (request: Request) => Promise<AccessContext>;
  readonly backend: CounterpartyBackendOptions;
  readonly onError?: (error: unknown, request: Request, requestId: string) => void;
  readonly onProviderError?: (error: unknown, context: unknown) => void | Promise<void>;
  readonly onTurnError?: TurnErrorReporter;
}

export function createCounterpartySharedOSHost(deps: CounterpartySharedOSHostDeps) {
  const authorizer = new CapabilityAuthorizer({
    usageStore: deps.usageStore,
    ...(deps.delegationResolver === undefined
      ? {}
      : { delegationResolver: deps.delegationResolver }),
  });

  const kernel = new SharedOSKernel({
    grantSource: deps.grantSource,
    authorizer,
    audit: deps.audit,
    toolNamespaceSettings: deps.toolNamespaceSettings,
    messageTransport: deps.messageTransport,
    messageRequestRouter: deps.messageRequestRouter,
    createMessageId: () => crypto.randomUUID(),
    ...(deps.onProviderError === undefined ? {} : { onProviderError: deps.onProviderError }),
  });

  for (const tool of counterpartyTools(deps.backend)) {
    kernel.registerTool(tool);
  }
  // Registration grants nothing. The affordance is visible only when the
  // caller enables the SharedOS namespace and holds a separate escalation grant.
  kernel.registerTool(createEscalationTool());

  const runtime = new StandardRuntime(new CounterpartyRoleDriver(), {
    ...(deps.onTurnError === undefined ? {} : { onTurnError: deps.onTurnError }),
  });
  const turns = new SharedOSExecutor(kernel, runtime, {
    // Active Trust Snapshot: Router -> Probe request, record raw canary, return
    // refreshed snapshot. The nested Probe turn has its own independent budget.
    defaultMaxSteps: 6,
    defaultMaxToolCalls: 3,
    defaultTimeoutMs: 15_000,
    ...(deps.onTurnError === undefined ? {} : { onTurnError: deps.onTurnError }),
  });

  return createSharedOSHandler({
    api: createKernelSharedOSApi({ kernel, turns }),
    resolveContext: deps.resolveContext,
    ...(deps.onError === undefined ? {} : { onError: deps.onError }),
  });
}
