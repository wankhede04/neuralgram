"""Deliberately failing test: verifies CI blocks a red PR (P0-3 AC). Never merge."""


def test_deliberate_failure_blocks_merge() -> None:
    raise AssertionError("deliberate failure to verify the CI gate blocks merge")
