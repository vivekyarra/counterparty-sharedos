from scripts.arena_preflight import run


def configure_ready(monkeypatch):
    monkeypatch.setenv("COUNTERPARTY_INTERNAL_TOKEN", "preflight-token-0123456789abcdef0123456789")
    monkeypatch.setenv("SHAREDNET_NODE_ID", "i_counterparty-seat")
    monkeypatch.setenv("SHAREDNET_PAYEE_ADDRESS", "p_counterparty-account")
    monkeypatch.setenv("SHAREDOS_AUDIT_CONFIRMED", "1")
    monkeypatch.setenv("SHAREDNET_EXTERNAL_CALL_CONFIRMED", "true")
    monkeypatch.setenv("COUNTERPARTY_ROUTER_ADDRESS", "agent-counterparty-router-prod")
    monkeypatch.setenv("COUNTERPARTY_PROBE_ADDRESS", "agent-counterparty-probe-prod")
    monkeypatch.setenv("COUNTERPARTY_JUDGE_ADDRESS", "agent-counterparty-judge-prod")
    monkeypatch.setenv("COUNTERPARTY_ATTESTOR_ADDRESS", "agent-counterparty-attestor-prod")
    monkeypatch.delenv("COUNTERPARTY_PUBLIC_URL", raising=False)
    monkeypatch.delenv("SHAREDOS_TENANT_ID", raising=False)
    monkeypatch.delenv("SHAREDOS_OWNER_ADDRESS", raising=False)


def test_preflight_does_not_require_tenant_or_owner_ids(monkeypatch):
    configure_ready(monkeypatch)
    checks, _ = run(False)
    assert all(check.ok for check in checks)
    names = {check.name for check in checks}
    assert "SHAREDOS_TENANT_ID" not in names
    assert "SHAREDOS_OWNER_ADDRESS" not in names
    assert "SHAREDNET_NODE_ID" in names
    assert "SHAREDNET_PAYEE_ADDRESS" in names


def test_preflight_requires_real_external_call_confirmation(monkeypatch):
    configure_ready(monkeypatch)
    monkeypatch.delenv("SHAREDNET_EXTERNAL_CALL_CONFIRMED")
    checks, _ = run(False)
    external = next(check for check in checks if check.name == "SharedNet external call confirmed")
    assert external.ok is False


def test_preflight_rejects_non_sharednet_payee_address(monkeypatch):
    configure_ready(monkeypatch)
    monkeypatch.setenv("SHAREDNET_PAYEE_ADDRESS", "not-a-sharednet-address")
    checks, _ = run(False)
    payee = next(check for check in checks if check.name == "SHAREDNET_PAYEE_ADDRESS")
    assert payee.ok is False
