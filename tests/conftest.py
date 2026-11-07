"""Tests never enable a live market collector implicitly."""

import pytest


@pytest.fixture(autouse=True)
def no_implicit_market_wan(monkeypatch):
    # Market fixtures explicitly enable this gate and inject a synthetic fetcher.
    # Docker/live gates are separate commands, never evidence from these fixtures.
    monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "0")
