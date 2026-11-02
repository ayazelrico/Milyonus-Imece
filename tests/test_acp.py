"""ACP server: initialize, session/new, and a streaming session/prompt — driven
over an in-memory pipe with a scripted provider (no editor, no API)."""

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from milyonus.acp.server import ACPServer
from milyonus.config.schema import MilyonusConfig
from milyonus.memory.store import MemoryStore
from milyonus.providers.base import CompletionRequest, StreamEvent, ToolCall, Usage

pytestmark = pytest.mark.asyncio


class ScriptedProvider:
    name = "fake"
    model = "fake"

    def __init__(self, text: str):
        self._text = text

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(kind="text", delta=self._text)
        yield StreamEvent(kind="usage", usage=Usage(input_tokens=3, output_tokens=2))
        yield StreamEvent(kind="done", stop_reason="end_turn")


async def _drive(server, messages):
    """Feed JSON-RPC messages through the server, collect all written lines."""
    reader = asyncio.StreamReader()
    for m in messages:
        reader.feed_data((json.dumps(m) + "\n").encode())
    reader.feed_eof()

    written: list[dict] = []

    class FakeWriter:
        def write(self, data):
            for line in data.decode().splitlines():
                if line.strip():
                    written.append(json.loads(line))

        async def drain(self):
            return None

    await server.serve(reader, FakeWriter())
    return written


def _server(tmp_path):
    cfg = MilyonusConfig()
    return ACPServer(
        cfg,
        provider=ScriptedProvider("Merhaba editör"),
        mem_store=MemoryStore(tmp_path / "state.db"),
    )


async def test_initialize(tmp_path):
    server = _server(tmp_path)
    out = await _drive(
        server,
        [
            {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": 1}},
        ],
    )
    assert out[0]["id"] == 0
    assert out[0]["result"]["protocolVersion"] == 1
    assert "agentCapabilities" in out[0]["result"]


async def test_session_new(tmp_path):
    server = _server(tmp_path)
    out = await _drive(
        server,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": str(tmp_path)}},
        ],
    )
    assert out[0]["result"]["sessionId"].startswith("sess_")


async def test_prompt_streams_and_stops(tmp_path):
    server = _server(tmp_path)
    out = await _drive(
        server,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": str(tmp_path)}},
        ],
    )
    sid = out[0]["result"]["sessionId"]
    out = await _drive(
        server,
        [
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/prompt",
                "params": {"sessionId": sid, "prompt": [{"type": "text", "text": "selam"}]},
            },
        ],
    )
    # A streaming update with the assistant text, then a result with stopReason.
    updates = [m for m in out if m.get("method") == "session/update"]
    assert any(u["params"]["update"]["content"]["text"] == "Merhaba editör" for u in updates)
    results = [m for m in out if "result" in m]
    assert results[-1]["result"]["stopReason"] == "end_turn"


async def test_unknown_method_errors(tmp_path):
    server = _server(tmp_path)
    out = await _drive(
        server,
        [
            {"jsonrpc": "2.0", "id": 9, "method": "does/not/exist", "params": {}},
        ],
    )
    assert out[0]["error"]["code"] == -32601


async def test_prompt_unknown_session(tmp_path):
    server = _server(tmp_path)
    out = await _drive(
        server,
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {"sessionId": "nope", "prompt": [{"type": "text", "text": "x"}]},
            },
        ],
    )
    assert "error" in out[0]


@pytest.mark.parametrize(
    "decision,exists", [("allow_once", True), ("reject_once", False), ("forged", False)]
)
async def test_permission_roundtrip_is_required_before_writing(tmp_path, decision, exists):
    class WritingProvider:
        name = model = "fake"

        async def stream(self, request):
            if any(m.role == "tool" for m in request.messages):
                yield StreamEvent(kind="text", delta="done")
            else:
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        "c", "write_file", {"path": "approved.txt", "content": "ok"}
                    ),
                )
            yield StreamEvent(kind="usage", usage=Usage(3, 2))
            yield StreamEvent(kind="done")

    server = _server(tmp_path)
    server.provider = WritingProvider()
    sid = server._session_new({"cwd": str(tmp_path)})["sessionId"]
    reader = asyncio.StreamReader()
    written = []

    class Writer:
        def write(self, data):
            msg = json.loads(data)
            written.append(msg)
            if msg.get("method") == "session/request_permission":
                assert not (tmp_path / "approved.txt").exists()
                reader.feed_data(
                    (
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": msg["id"],
                                "result": {
                                    "outcome": {"outcome": "selected", "optionId": decision}
                                },
                            }
                        )
                        + "\n"
                    ).encode()
                )
            if msg.get("id") == 2 and "result" in msg:
                reader.feed_eof()

        async def drain(self):
            pass

    reader.feed_data(
        (
            json.dumps(
                {
                    "id": 2,
                    "method": "session/prompt",
                    "params": {"sessionId": sid, "prompt": [{"type": "text", "text": "write"}]},
                }
            )
            + "\n"
        ).encode()
    )
    await asyncio.wait_for(server.serve(reader, Writer()), 3)
    assert (tmp_path / "approved.txt").exists() is exists
    assert not server._permissions


async def test_cancel_interrupts_a_live_provider(tmp_path):
    reader = asyncio.StreamReader()
    server = _server(tmp_path)
    sid = server._session_new({"cwd": str(tmp_path)})["sessionId"]
    stopped = asyncio.Event()

    class SlowProvider:
        name = model = "fake"

        async def stream(self, request):
            reader.feed_data(
                (
                    json.dumps({"method": "session/cancel", "params": {"sessionId": sid}}) + "\n"
                ).encode()
            )
            try:
                await asyncio.sleep(10)
                yield StreamEvent(kind="done")
            finally:
                stopped.set()

    server.provider = SlowProvider()
    written = []

    class Writer:
        def write(self, data):
            msg = json.loads(data)
            written.append(msg)
            if msg.get("id") == 2:
                reader.feed_eof()

        async def drain(self):
            pass

    reader.feed_data(
        (
            json.dumps(
                {"id": 2, "method": "session/prompt", "params": {"sessionId": sid, "prompt": []}}
            )
            + "\n"
        ).encode()
    )
    await asyncio.wait_for(server.serve(reader, Writer()), 3)
    assert stopped.is_set()
    assert any(m.get("result", {}).get("stopReason") == "cancelled" for m in written)
