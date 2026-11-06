"""Runtime metadata is validated, bounded, and its readers are cancellable."""

import asyncio
import sys
from copy import deepcopy

import pytest

from milyonus.imece import execution
from milyonus.imece.execution import PythonExecutor


@pytest.mark.parametrize(
    "bad", ["none", "image_id", "architecture", "daemon_id", "security", "version"]
)
async def test_invalid_docker_metadata_cannot_identify_cached_evidence(monkeypatch, bad):
    image = {"id": "sha256:" + "1" * 64, "os": "linux", "architecture": "arm64"}
    daemon = {
        "id": "daemon",
        "os": "linux",
        "architecture": "aarch64",
        "kernel": "kernel",
        "version": "1",
        "security": ["name=seccomp"],
    }
    if bad == "image_id":
        image["id"] = "unresolved"
    elif bad == "architecture":
        image["architecture"] = None
    elif bad == "daemon_id":
        daemon["id"] = ""
    elif bad == "security":
        daemon["security"] = {"unexpected": True}
    elif bad == "version":
        daemon["version"] = False

    async def metadata(self, *args):
        return None if bad == "none" else deepcopy(image if args[0] == "image" else daemon)

    monkeypatch.setattr(PythonExecutor, "_docker_metadata", metadata)
    assert await PythonExecutor()._docker_identity() is None


@pytest.mark.parametrize("cancel", [False, True])
async def test_metadata_reader_reaps_child_on_overflow_or_cancellation(monkeypatch, cancel):
    # This fixed, trusted test helper replaces the Docker client, not sandbox
    # candidate execution. It must be killed without waiting for its sleep.
    monkeypatch.setattr(execution.shutil, "which", lambda _: sys.executable)
    original = asyncio.create_subprocess_exec
    processes = []
    started = asyncio.Event()

    async def spawn(*args, **kwargs):
        proc = await original(*args, **kwargs)
        processes.append(proc)
        started.set()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    executor = PythonExecutor()
    script = (
        "import time; " + ("" if cancel else "print('x'*20000, flush=True); ") + "time.sleep(30)"
    )
    task = asyncio.create_task(executor._docker_metadata("-c", script))
    await asyncio.wait_for(started.wait(), 2)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await asyncio.wait_for(task, 2) is None
    assert len(processes) == executor.metadata_processes_started == 1
    assert processes[0].returncode is not None and processes[0].returncode != 0
