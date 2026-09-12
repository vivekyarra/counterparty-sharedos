from pathlib import Path

ARENA_HOST = Path(__file__).resolve().parents[1] / "scripts" / "arena_host.py"


def test_sharednet_reach_uses_selected_seat_from_environment():
    source = ARENA_HOST.read_text(encoding="utf-8")
    expected = (
        'return [npx, "-y", "sharednet@latest", '
        '"reach", "public", "--json"]'
    )
    assert expected in source
    assert '"reach", "public", "--as"' not in source
    assert 'env["SHAREDNET_SEAT"] = member_id' in source
