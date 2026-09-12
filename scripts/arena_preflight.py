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


def fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"user-agent": "counterparty-arena-preflight/0.3"})
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 -- operator-supplied HTTPS deployment URL
        return json.loads(response.read().decode("utf-8"))


def run(live: bool) -> tuple[list[Check], dict[str, object]]:
    checks: list[Check] = []
    token = env("COUNTERPARTY_INTERNAL_TOKEN")
    checks.append(Check("private ingress token", len(token) >= 32, "configured" if len(token) >= 32 else "missing or shorter than 32 chars"))

    for name in ("SHAREDOS_TENANT_ID", "SHAREDOS_OWNER_ADDRESS", "SHAREDNET_NODE_ID"):
        value = env(name)
        checks.append(Check(name, bool(value), "configured" if value else "missing"))

    addresses: dict[str, str] = {}
    for name, default in DEFAULT_ADDRESSES.items():
        value = env(name)
        addresses[name] = value
        ok = bool(value) and value != default
        checks.append(Check(name, ok, "production address configured" if ok else "missing or still using repository placeholder"))

    public_url = env("COUNTERPARTY_PUBLIC_URL").rstrip("/")
    checks.append(Check("COUNTERPARTY_PUBLIC_URL", bool(public_url), public_url or "missing"))

    remote: dict[str, object] = {}
    if live and public_url:
        if not public_url.startswith("https://"):
            checks.append(Check("HTTPS deployment", False, "COUNTERPARTY_PUBLIC_URL must use https://"))
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
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                checks.append(Check("remote deployment", False, f"unreachable or invalid: {exc}"))

    return checks, remote


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed Shared OS Arena deployment preflight")
    parser.add_argument("--live", action="store_true", help="Also fetch the deployed health and agent-card endpoints")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human checklist")
    args = parser.parse_args()

    checks, remote = run(args.live)
    ok = all(check.ok for check in checks)
    payload = {
        "ready": ok,
        "purpose": PURPOSE,
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
