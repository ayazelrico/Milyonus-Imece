from concurrent.futures import ThreadPoolExecutor

import pytest

from milyonus.providers.base import CompletionRequest, StreamEvent, Usage
from milyonus.web.quota import QuotaProvider
from milyonus.web.store import WebStore


def test_reservations_across_connections(tmp_path):
    path = tmp_path / "web.db"
    WebStore(path).close()

    def attempt(_):
        store = WebStore(path)
        try:
            store.reserve_quota("a", tokens=10, cost=1, token_limit=100, cost_limit=10)
            return True
        except RuntimeError:
            return False
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(attempt, range(200))) == 10
    store = WebStore(path)
    assert store.usage("a")["tokens_used"] == 100
    assert store.usage("a")["cost_usd"] == 10
    # Tenant isolation and cost rejection independent of token rejection.
    store.reserve_quota("b", tokens=1, cost=1, token_limit=100, cost_limit=1)
    with pytest.raises(RuntimeError, match="cost"):
        store.reserve_quota("b", tokens=1, cost=1, token_limit=100, cost_limit=1)
    store.refund_quota("a", period="1900-01", tokens=100, cost=10)
    assert store.usage("a")["tokens_used"] == 100
    store.close()


class FakeProvider:
    name = model = "fake"

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        if self.fail:
            raise RuntimeError("disconnected")
        yield StreamEvent(kind="usage", usage=Usage(input_tokens=10, output_tokens=5))
        yield StreamEvent(kind="done")


async def test_provider_settlement_and_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MILYONUS_WEB_INPUT_USD_PER_MILLION", "2")
    monkeypatch.setenv("MILYONUS_WEB_OUTPUT_USD_PER_MILLION", "4")
    store = WebStore(tmp_path / "web.db")
    provider = FakeProvider()
    quota = QuotaProvider(provider, store, "a")
    request = CompletionRequest(system="test", messages=[], max_output_tokens=50)
    _ = [event async for event in quota.stream(request)]
    assert store.usage("a")["tokens_used"] == 15
    assert store.usage("a")["cost_usd"] == pytest.approx(0.00004)
    provider.fail = True
    with pytest.raises(RuntimeError, match="disconnected"):
        _ = [event async for event in quota.stream(request)]
    assert store.usage("a")["tokens_used"] > 4000
    quota.token_limit = 1
    with pytest.raises(RuntimeError, match="token quota"):
        _ = [event async for event in quota.stream(request)]
    assert provider.calls == 2
    store.close()


def test_cost_limit_requires_prices(tmp_path, monkeypatch):
    monkeypatch.setenv("MILYONUS_WEB_MONTHLY_USD", "10")
    monkeypatch.delenv("MILYONUS_WEB_INPUT_USD_PER_MILLION", raising=False)
    monkeypatch.delenv("MILYONUS_WEB_OUTPUT_USD_PER_MILLION", raising=False)
    store = WebStore(tmp_path / "web.db")
    with pytest.raises(ValueError, match="prices"):
        QuotaProvider(FakeProvider(), store, "a")
    store.close()
