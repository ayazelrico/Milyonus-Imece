"""Journal corruption must abort work rather than become an ordinary agent failure."""

import asyncio

import pytest

from milyonus.imece.agents import AgentReply, AgentSpec, FatalAgentStateError, Swarm
from milyonus.imece.journal import AgentJournal


def spec(context="first"):
    return AgentSpec("production", "builder", "solve", context, ["correct"])


@pytest.mark.parametrize("column,value", [("phase", "wrong"), ("reply", "{}")])
async def test_corrupt_replay_aborts_without_dispatching_followup(tmp_path, column, value):
    calls = []

    async def provider(request):
        calls.append(request.context)
        return AgentReply("answer", 4)

    path = tmp_path / "trial.sqlite"
    journal = AgentJournal(path, provider, identity={"trial": 1})
    await journal(spec())
    # Column names come solely from the fixed parametrization above.
    journal.db.execute(f"UPDATE nodes SET {column}=?", (value,))
    journal.close()
    journal = AgentJournal(path, provider, identity={"trial": 1})
    swarm = Swarm(journal, max_parallel=1)
    try:
        with pytest.raises(FatalAgentStateError):
            await swarm.run([spec(), spec("must not dispatch")])
        with pytest.raises(FatalAgentStateError):
            await swarm.run([spec("later batch")])
        assert calls == ["first"]
    finally:
        journal.close()


async def test_missing_node_during_completion_is_fatal(tmp_path):
    calls = []

    async def provider(request):
        calls.append(request.context)
        journal.db.execute("DELETE FROM nodes")
        return AgentReply("answer", 4)

    journal = AgentJournal(tmp_path / "trial.sqlite", provider, identity={})
    try:
        with pytest.raises(FatalAgentStateError, match="no longer running"):
            await Swarm(journal, max_parallel=1).run([spec(), spec("next")])
        assert calls == ["first"]
    finally:
        journal.close()


async def test_cancellation_write_failure_survives_budget_cleanup(tmp_path):
    started = asyncio.Event()

    async def provider(request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            journal.db.close()  # Simulate storage becoming unavailable during interruption.
            raise

    journal = AgentJournal(tmp_path / "trial.sqlite", provider, identity={})
    swarm = Swarm(journal, max_parallel=1)
    task = asyncio.create_task(swarm.run([spec()]))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(FatalAgentStateError, match="interruption write"):
        await task


def test_existing_empty_journal_is_never_bound_to_new_run(tmp_path):
    path = tmp_path / "empty.sqlite"
    path.touch()
    with pytest.raises(FatalAgentStateError, match="missing its identity"):
        AgentJournal(path, None, identity={"new": True})
