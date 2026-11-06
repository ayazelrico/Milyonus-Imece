"""Freeze a common compact prompt so adaptation is the only changed factor."""

import json

import pytest
from evals.imece import prepare_pair, run


@pytest.mark.parametrize("factor", ["adaptive_production", "skip_clean_revision"])
async def test_both_compact_arms_isolate_treatment_without_dispatch(tmp_path, monkeypatch, factor):
    monkeypatch.setattr(
        run, "discover_codex", lambda _: {"executable": "fake", "version": "test", "sha256": "test"}
    )
    monkeypatch.setattr(run, "oracle_guard", lambda _: [])

    def forbidden(**kwargs):
        raise AssertionError("preparation must not construct a model adapter")

    monkeypatch.setattr(run, "CodexAgentFn", forbidden)
    configs = []
    for enabled in (False, True):
        config = tmp_path / f"{enabled}.toml"
        settings = {"adaptive_production": "true", "skip_clean_revision": "true"}
        settings[factor] = str(enabled).lower()
        config.write_text(
            "[imece]\nmax_parallel=1\n" + "".join(f"{k}={v}\n" for k, v in settings.items())
        )
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
    assert pair["treatments"]["factors"] == [factor]
    assert pair["treatments"]["single_factor"] is True
    assert pair["cli_prompt_treatments"]["baseline"] == pair["cli_prompt_treatments"]["candidate"]
    assert pair["cli_prompt_treatments"]["baseline"]["kind"] == "compact-text-only"
