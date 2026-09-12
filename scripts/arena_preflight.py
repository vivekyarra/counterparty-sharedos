from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

PURPOSE = "counterparty.verify-and-route-sharednet-services"
DEFAULT_ADDRESSES = {
    "COUNTERPARTY_ROUTER_ADDRESS": "counterparty-router",
    "COUNTERPARTY_PROBE_ADDRESS": "counterparty-probe",
    "COUNTERPARTY_JUDGE_ADDRESS": "counterparty-judge",
    "COUNTERPARTY_ATTESTOR_ADDRESS": "counterparty-attestor",
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
    # Organizer guidance distinguishes i* seat, a* tag, and p* account
    # addresses. Keep validation intentionally loose because exact separators
    # are a SharedNet transport concern and can change independently.
    return len(value) >= 3 and value[0].lower() in {"i", "a", "p"}


def fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"user-agent": "counterparty-arena-preflight/0.3"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def run(live: bool) -> tuple[list[Check], dict[str, object]]:
    checks: list[Check] = []
    token = env("COUNTERPARTY_INTERNAL_TOKEN")
    checks.append(Check("private ingress token", len(token) >= 32, "configured" if len(token) >= 32 else "missing or shorter than 32 chars"))

    # SharedNet Arena transport is room/message based. The representative seat
    # is what other agents address; credits settle to a p*/a*/i* payee address.
    # A SharedOS tenant ID/owner address is deliberately NOT required here: the
    # current SharedOS model keeps the kernel in the application and uses Cloud
    # for decision/audit visibility.
    node_id = env("SHAREDNET_NODE_ID")
    checks.append(Check("SHAREDNET_NODE_ID", sharednet_address(node_id), node_id or "missing"))

    payee = env("SHAREDNET_PAYEE_ADDRESS")
    checks.append(Check("SHAREDNET_PAYEE_ADDRESS", sharednet_address(payee), payee or "missing"))

    checks.append(
        Check(
            "SharedOS Cloud audit confirmed",
            truthy("SHAREDOS_AUDIT_CONFIRMED"),
            "confirmed" if truthy("SHAREDOS_AUDIT_CONFIRMED") else "set SHAREDOS_AUDIT_CONFIRMED=1 only after a real product turn is visible in Cloud audit",
        )
    )
    checks.append(
        Check(
            "SharedNet external call confirmed",
            truthy("SHAREDNET_EXTERNAL_CALL_CONFIRMED"),
            "confirmed" if truthy("SHAREDNET_EXTERNAL_CALL_CONFIRMED") else "set SHAREDNET_EXTERNAL_CALL_CONFIRMED=1 only after another seat calls Counterparty and receives a reply",
        )
    )

    addresses: dict[str, str] = {}
    for name, default in DEFAULT_ADDRESSES.items():
        value = env(name)
        addresses[name] = value
        ok = bool(value) and value != default
        checks.append(Check(name, ok, "production address configured" if ok else "missing or still using repository placeholder"))

    # A public HTTPS URL is useful for liveness/agent-card proof, but SharedNet
    # Arena calls are messages, not HTTP RPCs. Therefore it is optional. When a
    # URL is supplied in --live mode, validate it strictly.
    public_url = env("COUNTERPARTY_PUBLIC_URL").rstrip("/")
    checks.append(Check("COUNTERPARTY_PUBLIC_URL (optional)", True, public_url or "not required for SharedNet message transport"))

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
                expected = {
                    "router": addresses["COUNTERPARTY_ROUTER_ADDRESS"],
                    "probe": addresses["COUNTERPARTY_PROBE_ADDRESS"],
                    "judge": addresses["COUNTERPARTY_JUDGE_ADDRESS"],
                    "attestor": addresses["COUNTERPARTY_ATTESTOR_ADDRESS"],
                }
                checks.append(Check("production agent addresses", card_addresses == expected, str(card_addresses)))
                sharednet = card.get("sharednet")
                if isinstance(sharednet, dict):
                    checks.append(Check("agent-card SharedNet seat", sharednet.get("seat_id") == node_id, str(sharednet.get("seat_id"))))
                    checks.append(Check("agent-card payee", sharednet.get("payee_address") == payee, str(sharednet.get("payee_address"))))
                else:
                    checks.append(Check("agent-card SharedNet metadata", False, "missing sharednet object"))
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                checks.append(Check("remote deployment", False, f"unreachable or invalid: {exc}"))

    return checks, remote


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed Shared OS / SharedNet Arena deployment preflight")
    parser.add_argument("--live", action="store_true", help="Also validate the optional deployed health and agent-card endpoints")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human checklist")
    args = parser.parse_args()

    checks, remote = run(args.live)
    ok = all(check.ok for check in checks)
    payload = {
        "ready": ok,
        "purpose": PURPOSE,
        "transport": "SharedNet Room message",
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
