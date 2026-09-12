from scripts.arena_host import sharednet_reach_args


def test_sharednet_reach_uses_selected_seat_from_environment():
    args = sharednet_reach_args("npx")
    assert args == ["npx", "-y", "sharednet@latest", "reach", "public", "--json"]
    assert "--as" not in args
