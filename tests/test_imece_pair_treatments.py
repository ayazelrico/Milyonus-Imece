"""Freeze a common compact prompt so adaptation is the only changed factor."""

import json

from evals.imece import prepare_pair, run


async def test_both_compact_arms_isolate_adaptive_treatment_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        run, "discover_codex", lambda _: {"executable": "fake", "version": "test", "sha256": "test"}
    )
    monkeypatch.setattr(run, "oracle_guard", lambda _: [])

    def forbidden(**kwargs):
        raise AssertionError("preparation must not construct a model adapter")

    monkeypatch.setattr(run, "CodexAgentFn", forbidden)
    configs = []
    for adaptive in (False, True):
        config = tmp_path / f"{adaptive}.toml"
        config.write_text(f"[imece]\nmax_parallel=1\nadaptive_production={str(adaptive).lower()}\n")
        configs.append(config)
    args = prepare_pair.make_parser().parse_args(
        [
            "--model",
            "fake",
            "--out-dir",
            str(tmp_path / "pair"),
            "--baseline-config",
            str(configs[0]),
            "--candidate-config",
            str(configs[1]),
            "--baseline-compact-cli-instructions",
            "--candidate-compact-cli-instructions",
            "--task",
            "stable_unique",
            "--repeats",
            "1",
        ]
    )
    assert await prepare_pair.main(args) == 0
    pair = json.loads((args.out_dir / "pair.json").read_text())
    assert pair["model_calls"] == 0
    assert pair["treatments"]["factors"] == ["adaptive_production"]
    assert pair["treatments"]["single_factor"] is True
    assert pair["cli_prompt_treatments"]["baseline"] == pair["cli_prompt_treatments"]["candidate"]
    assert pair["cli_prompt_treatments"]["baseline"]["kind"] == "compact-text-only"
