"""A broken or contradictory model verdict never promotes memory."""

import json

import pytest

from milyonus.memory.pipeline import MemoryPipeline
from milyonus.memory.store import MemoryStore
from milyonus.memory.verifier import ModelVerifier
from milyonus.providers.base import ProviderError, StreamEvent


class VerifierProvider:
    def __init__(self, value):
        self.value = value

    async def stream(self, request):
        if isinstance(self.value, Exception):
            raise self.value
        yield StreamEvent(kind="text", delta=json.dumps(self.value))


@pytest.mark.parametrize(
    "value", [ProviderError("offline"), {"approved": "false"}, [], {"approved": True}]
)
async def test_verifier_failure_preserves_quarantine_without_negative_claim(tmp_path, value):
    s = MemoryStore(tmp_path / "state.db")
    p = MemoryPipeline(s, verifier=ModelVerifier(VerifierProvider(value)))
    mid = p.propose("A harmless project fact.", source_kind="agent-observed")
    assert await p.process_one(mid) == "pending"
    assert not s.negatives()


async def test_contradiction_overrides_approved_flag(tmp_path):
    s = MemoryStore(tmp_path / "state.db")
    p = MemoryPipeline(
        s,
        verifier=ModelVerifier(
            VerifierProvider(
                {
                    "approved": True,
                    "is_instruction": False,
                    "source_competent": True,
                    "contradicts": True,
                    "reason": "contradiction",
                }
            )
        ),
    )
    mid = p.propose("A harmless project fact.", source_kind="agent-observed")
    assert await p.process_one(mid) == "rejected"
    assert s.get(mid).verdict == "contradiction"


async def test_acp_surface_uses_model_verification(tmp_path, monkeypatch):
    from milyonus.acp.server import ACPServer
    from milyonus.config.schema import MilyonusConfig

    monkeypatch.setattr(
        "milyonus.memory.factory.build_provider",
        lambda *a, **kw: VerifierProvider({"approved": "false"}),
    )
    store = MemoryStore(tmp_path / "state.db")
    server = ACPServer(MilyonusConfig(), provider=VerifierProvider({}), mem_store=store)
    sid = server._session_new({"cwd": str(tmp_path)})["sessionId"]
    loop = server._build_loop(server._sessions[sid])
    text = await loop.tools.get("memory_propose").handler(
        {"content": "The project uses Python.", "source_kind": "user-direct"}
    )
    assert "quarantined" in text
    assert not store.active()
