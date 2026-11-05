"""Hermes comparison harness — prepare path without a Hermes install."""

from __future__ import annotations

import json

import pytest
from evals.hermes.adapter import available, build_manifest, run_suite
from evals.imece.dataset import load_tasks


def test_manifest_covers_fifty_tasks():
    m = build_manifest(seed=0, repeats=5, model="test-model", revision="t")
    assert len(m["protocol"]["tasks"]) == 50
    assert len(load_tasks()) == 50


@pytest.mark.asyncio
async def test_prepare_without_hermes(tmp_path):
    out = tmp_path / "hermes-prepare.json"
    report = await run_suite(out=out, model="x", prepare_only=True)
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["adapter"] == "hermes"
    assert payload["prepare"]["available"] == available()
    assert report["runs"] == []
