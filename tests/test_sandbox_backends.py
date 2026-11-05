"""Sandbox backend selection and fail-closed behaviour."""

from __future__ import annotations

import pytest

from milyonus.security.sandbox import SandboxUnavailable, run_sandboxed, supported_backends
from milyonus.tools.terminal.tools import make_shell_tool


def test_supported_backends_cover_plan():
    assert supported_backends() == ("local", "docker", "ssh", "modal", "daytona")


@pytest.mark.asyncio
async def test_local_backend_runs(tmp_path):
    result = await run_sandboxed("echo hello-sandbox", root=tmp_path, backend="local")
    assert result.exit_code == 0
    assert "hello-sandbox" in result.output


@pytest.mark.asyncio
async def test_ssh_without_target_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("MILYONUS_SANDBOX_SSH_TARGET", raising=False)
    with pytest.raises(SandboxUnavailable, match="MILYONUS_SANDBOX_SSH_TARGET"):
        await run_sandboxed("echo x", root=tmp_path, backend="ssh")


@pytest.mark.asyncio
async def test_modal_without_opt_in_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("MILYONUS_SANDBOX_MODAL", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    with pytest.raises(SandboxUnavailable, match="MILYONUS_SANDBOX_MODAL"):
        await run_sandboxed("echo x", root=tmp_path, backend="modal")


@pytest.mark.asyncio
async def test_daytona_without_creds_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("DAYTONA_API_URL", raising=False)
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    with pytest.raises(SandboxUnavailable, match="DAYTONA_API"):
        await run_sandboxed("echo x", root=tmp_path, backend="daytona")


@pytest.mark.asyncio
async def test_shell_tool_surfaces_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("MILYONUS_SANDBOX_SSH_TARGET", raising=False)
    tool = make_shell_tool(tmp_path, backend="ssh")
    out = await tool.handler({"command": "true"})
    assert out.startswith("[sandbox unavailable]")


def test_unknown_backend_rejected_at_construction(tmp_path):
    with pytest.raises(ValueError, match="not implemented"):
        make_shell_tool(tmp_path, backend="firecracker")
