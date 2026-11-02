"""Production surfaces share the independent model-verification boundary."""

from __future__ import annotations

from milyonus.config.schema import MilyonusConfig
from milyonus.memory.pipeline import MemoryPipeline
from milyonus.memory.store import MemoryStore
from milyonus.memory.verifier import ModelVerifier
from milyonus.providers.router import build_provider


def verified_pipeline(
    store: MemoryStore, config: MilyonusConfig, *, semantic=None
) -> MemoryPipeline:
    verifier = ModelVerifier(build_provider(config.provider, model=config.provider.verifier_model))
    return MemoryPipeline(store, config=config.memory, verifier=verifier, semantic=semantic)
