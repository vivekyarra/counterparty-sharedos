from scripts.arena_preflight import CANONICAL_AGENT_ADDRESSES, run


def configure_ready(monkeypatch):
    monkeypatch.setenv("COUNTERPARTY_INTERNAL_TOKEN", "preflight-token-0123456789abcdef0123456789")
    monkeypatch.setenv("SHAREDNET_NODE_ID", "i_Counter001")
    monkeypatch.setenv("SHAREDNET_PAYEE_ADDRESS", "p_Payee00001")
    monkeypatch.setenv("SHAREDOS_AUDIT_CONFIRMED", "1")
    monkeypatch.setenv("SHAREDNET_EXTERNAL_CALL_CONFIRMED", "true")
    for name in (
        "COUNTERPARTY_ROUTER_ADDRESS",
        "COUNTERPARTY_PROBE_ADDRESS",
        "COUNTERPARTY_JUDGE_ADDRESS",
        "COUNTERPARTY_ATTESTOR_ADDRESS",
        "COUNTERPARTY_PUBLIC_URL",
        "SHAREDOS_TENANT_ID",
        "SHAREDOS_OWNER_ADDRESS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_preflight_does_not_require_tenant_owner_or_fake_production_role_ids(monkeypatch):
    configure_ready(monkeypatch)
    checks, _ = run(False)
    assert all(check.ok for check in checks)
    names = {check.name for check in checks}
    assert "SHAREDOS_TENANT_ID" not in names
    assert "SHAREDOS_OWNER_ADDRESS" not in names
    assert "SHAREDNET_NODE_ID" in names
    assert "SHAREDNET_PAYEE_ADDRESS" in names
    for role, address in CANONICAL_AGENT_ADDRESSES.items():
        check = next(item for item in checks if item.name == f"SharedOS {role} address")
        assert check.ok is True
        assert check.detail == address


def test_preflight_rejects_role_identity_that_does_not_match_runtime(monkeypatch):
    configure_ready(monkeypatch)
    monkeypatch.setenv("COUNTERPARTY_ROUTER_ADDRESS", "agent-counterparty-router-prod")
    checks, _ = run(False)
    router = next(check for check in checks if check.name == "SharedOS router address")
    assert router.ok is False
    assert "counterparty-router" in router.detail


def test_preflight_accepts_explicit_canonical_role_identity(monkeypatch):
    configure_ready(monkeypatch)
    monkeypatch.setenv("COUNTERPARTY_ROUTER_ADDRESS", "counterparty-router")
    checks, _ = run(False)
    router = next(check for check in checks if check.name == "SharedOS router address")
    assert router.ok is True


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


def test_preflight_requires_instance_seat_for_node_id(monkeypatch):
    configure_ready(monkeypatch)
    monkeypatch.setenv("SHAREDNET_NODE_ID", "a_Counter001")
    checks, _ = run(False)
    node = next(check for check in checks if check.name == "SHAREDNET_NODE_ID")
    assert node.ok is False
