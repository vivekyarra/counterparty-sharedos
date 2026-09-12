from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

PURPOSE = "counterparty.verify-and-route-sharednet-services"
CANONICAL_AGENT_ADDRESSES = {
    "router": "counterparty-router",
    "probe": "counterparty-probe",
    "judge": "counterparty-judge",
    "attestor": "counterparty-attestor",
}
ADDRESS_ENV = {
    "router": "COUNTERPARTY_ROUTER_ADDRESS",
    "probe": "COUNTERPARTY_PROBE_ADDRESS",
    "judge": "COUNTERPARTY_JUDGE_ADDRESS",
    "attestor": "COUNTERPARTY_ATTESTOR_ADDRESS",
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def env(name: str) -> str:
    return os.getenv(name, "").strip()


def truthy(name: str) -> bool:
    return env(name).lower() in {"1", "true", "yes", "on"}


def sharednet_address(value: str) -> bool:
    return len(value) == 12 and value[:2] in {"i_", "a_", "p_"} and value[2:].isalnum()


def sharednet_seat(value: str) -> bool:
    return len(value) == 12 and value.startswith("i_") and value[2:].isalnum()


def fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"user-agent": "counterparty-arena-preflight/0.3"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def run(live: bool) -> tuple[list[Check], dict[str, object]]:
    checks: list[Check] = []
    token = env("COUNTERPARTY_INTERNAL_TOKEN")
    checks.append(
        Check(
            "private ingress token",
            len(token) >= 32,
            "configured" if len(token) >= 32 else "missing or shorter than 32 chars",
        )
    )

    # Organizer guidance identifies the representative product endpoint by its
    # live SharedNet Instance/seat. Payments may target p_, a_, or i_ addresses.
    node_id = env("SHAREDNET_NODE_ID")
    checks.append(Check("SHAREDNET_NODE_ID", sharednet_seat(node_id), node_id or "missing"))

    payee = env("SHAREDNET_PAYEE_ADDRESS")
    checks.append(Check("SHAREDNET_PAYEE_ADDRESS", sharednet_address(payee), payee or "missing"))

    checks.append(
        Check(
            "SharedOS Cloud audit confirmed",
            truthy("SHAREDOS_AUDIT_CONFIRMED"),
            "confirmed"
            if truthy("SHAREDOS_AUDIT_CONFIRMED")
            else "set SHAREDOS_AUDIT_CONFIRMED=1 only after a real Counterparty turn is visible in SharedOS Cloud audit",
        )
    )
    checks.append(
        Check(
            "SharedNet external call confirmed",
            truthy("SHAREDNET_EXTERNAL_CALL_CONFIRMED"),
            "confirmed"
            if truthy("SHAREDNET_EXTERNAL_CALL_CONFIRMED")
            else "set SHAREDNET_EXTERNAL_CALL_CONFIRMED=1 only after another seat calls Counterparty and receives a reply",
        )
    )

    # These are the actual SharedOS Address.agentId values used by the runtime
    # and therefore the identities judges should search in the audit trail. An
    # environment override may repeat the canonical value, but may not invent a
    # different 'production' identity that the TypeScript runtime never uses.
    for role, canonical in CANONICAL_AGENT_ADDRESSES.items():
        env_name = ADDRESS_ENV[role]
        configured = env(env_name)
        ok = configured in {"", canonical}
        detail = canonical if ok else f"must be {canonical!r}, got {configured!r}"
        checks.append(Check(f"SharedOS {role} address", ok, detail))

    # SharedNet Arena calls are Room messages, not HTTP RPCs. A public URL is
    # optional; when supplied, validate it strictly as additional evidence.
    public_url = env("COUNTERPARTY_PUBLIC_URL").rstrip("/")
    checks.append(
        Check(
            "COUNTERPARTY_PUBLIC_URL (optional)",
            True,
            public_url or "not required for SharedNet message transport",
        )
    )

    remote: dict[str, object] = {}
    if live and public_url:
        if not public_url.startswith("https://"):
            checks.append(Check("HTTPS deployment", False, "COUNTERPARTY_PUBLIC_URL must use https:// when configured"))
        else:
            try:
                health = fetch_json(f"{public_url}/health")
                card = fetch_json(f"{public_url}/.well-known/agent.json")
                remote = {"health": health, "agent_card": card}
                checks.append(Check("remote health", health.get("ok") is True, str(health)))
                checks.append(Check("remote version", health.get("version") == "0.3.0", str(health.get("version"))))
                checks.append(Check("purpose", card.get("purpose") == PURPOSE, str(card.get("purpose"))))
                card_addresses = card.get("agent_addresses")
                checks.append(
                    Check(
                        "canonical SharedOS agent addresses",
                        card_addresses == CANONICAL_AGENT_ADDRESSES,
                        str(card_addresses),
                    )
                )
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                checks.append(Check("remote deployment", False, f"unreachable or invalid: {exc}"))

    return checks, remote


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed Shared OS / SharedNet Arena deployment preflight")
    parser.add_argument("--live", action="store_true", help="Also validate optional deployed health and agent-card endpoints")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human checklist")
    args = parser.parse_args()

    checks, remote = run(args.live)
    ok = all(check.ok for check in checks)
    payload = {
        "ready": ok,
        "purpose": PURPOSE,
        "transport": "SharedNet Room message",
        "sharedos_agent_addresses": CANONICAL_AGENT_ADDRESSES,
        "checks": [{"name": check.name, "ok": check.ok, "detail": check.detail} for check in checks],
        "remote": remote,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("\nCounterparty Arena preflight")
        print("=" * 32)
        for check in checks:
            mark = "PASS" if check.ok else "FAIL"
            print(f"{mark:4}  {check.name}: {check.detail}")
        print(f"\nREADY={ok}\n")
    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
