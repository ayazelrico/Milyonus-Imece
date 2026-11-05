import json
import sys
from pathlib import Path

import pytest

import milyonus.imece.codex as codex
from milyonus.imece.agents import AgentSpec


@pytest.mark.parametrize("compact", [False, True])
async def test_compact_profile_uses_frozen_file_and_cleans_it(tmp_path, monkeypatch, compact):
    monkeypatch.setattr(codex, "oracle_guard", lambda _: [])
    binary = tmp_path / "fake-codex"
    binary.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import json,sys
from pathlib import Path
paths=[x.split('=',1)[1] for x in sys.argv if x.startswith('model_instructions_file=')]
text=Path(json.loads(paths[0])).read_text() if paths else 'builtin'
print(json.dumps({'type':'turn.started'}))
payload=json.dumps({'instructions':text,'path':json.loads(paths[0]) if paths else None})
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':payload}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1,'cached_input_tokens':0}}))
"""
    )
    binary.chmod(0o755)
    agent = codex.CodexAgentFn(
        model="fake",
        executable=str(binary),
        protected_paths=(tmp_path,),
        compact_instructions=compact,
    )
    reply = await agent(AgentSpec("test", "role", "goal", "context", ["answer"]))
    data = json.loads(reply.text)
    assert data["instructions"] == (codex.TEXT_ONLY_INSTRUCTIONS if compact else "builtin")
    if compact:
        assert not Path(data["path"]).exists()


def test_compact_profile_rejects_non_boolean_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "oracle_guard", lambda _: [])
    with pytest.raises(ValueError, match="boolean"):
        codex.CodexAgentFn(
            model="fake",
            executable="unused",
            protected_paths=(tmp_path,),
            compact_instructions="yes",
        )


async def test_compact_instruction_file_removed_after_cli_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "oracle_guard", lambda _: [])
    captured = tmp_path / "captured-path.json"
    binary = tmp_path / "failing-codex"
    binary.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import json,sys
from pathlib import Path
value=next(x.split('=',1)[1] for x in sys.argv if x.startswith('model_instructions_file='))
"""
        + f"Path({str(captured)!r}).write_text(value)\n"
        + "raise SystemExit(1)\n"
    )
    binary.chmod(0o755)
    agent = codex.CodexAgentFn(
        model="fake", executable=str(binary), protected_paths=(tmp_path,), compact_instructions=True
    )
    with pytest.raises(codex.CodexError, match="exited 1"):
        await agent(AgentSpec("test", "role", "goal", "context", ["answer"]))
    assert captured.exists()
    assert not Path(json.loads(captured.read_text())).exists()


@pytest.mark.parametrize("extra", [None, "adaptive", "implementation"])
def test_compact_effect_is_only_isolated_when_other_factors_match(extra):
    from copy import deepcopy

    from evals.imece.protocol import describe_treatments

    base = {
        "settings": {"adaptive_production": False},
        "implementation_hash": "same",
        "cli_prompt_treatment": {"kind": "builtin", "instructions_hash": None},
    }
    candidate = deepcopy(base)
    candidate["cli_prompt_treatment"] = {"kind": "compact-text-only", "instructions_hash": "hash"}
    if extra == "adaptive":
        candidate["settings"]["adaptive_production"] = True
    if extra == "implementation":
        candidate["implementation_hash"] = "different"
    result = describe_treatments(base, candidate)
    assert result["isolated_compact_prompt"] is (extra is None)
    assert result["single_factor"] is (extra is None)
