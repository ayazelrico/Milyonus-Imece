"""Flight Recorder: Black-Box Session DVR & Anomaly Detector (PLAN-HYPERNOVA H8).

Aviation-grade, tamper-evident execution black box (`milyonus.flight.v1`) for
debugging, replaying, and comparing agent runs without spending a single API token:
  1. Hash-chained `FlightFrame` sequence (SHA-256 over prev_hash + canonical frame),
  2. Automatic secret redaction (`security.redact`) across every captured frame,
  3. Built-in post-mortem anomaly detector (`tool_loop`, `latency_spike`,
     `tool_failure_burst`, `empty_assistant_turn`, `chain_tamper`),
  4. Deterministic `diff_flights(a, b)` pinpointing exact divergence frame,
     tool delta, token delta, and latency delta.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

from milyonus.memory.store import MemoryStore
from milyonus.security.redact import redact

FLIGHT_SCHEMA_VERSION = "milyonus.flight.v1"
_GENESIS = "0" * 64


@dataclass(slots=True)
class FlightFrame:
    seq: int
    ts: float
    kind: str  # "session.meta" | "message.user" | "message.assistant" | "tool.result" | "memory.anchor"
    label: str
    data: dict[str, Any]
    tokens_delta: int = 0
    latency_ms: int = 0
    prev_hash: str = ""
    frame_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FlightAnomaly:
    code: str
    severity: str  # "high" | "medium" | "low"
    frame_seq: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash_frame(prev_hash: str, frame_core: dict[str, Any]) -> str:
    body = json.dumps(frame_core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [_redact_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _redact_obj(v) for k, v in obj.items()}
    return obj


class FlightRecorder:
    """Append-only hash-chained flight frame builder."""

    def __init__(self, subject_id: str, *, kind: str = "session") -> None:
        self.subject_id = subject_id
        self.kind = kind
        self.created_at = round(time.time(), 3)
        self._prev = _GENESIS
        self._frames: list[FlightFrame] = []

    def append(
        self,
        *,
        kind: str,
        label: str,
        data: dict[str, Any],
        tokens_delta: int = 0,
        latency_ms: int = 0,
        ts: float | None = None,
    ) -> FlightFrame:
        seq = len(self._frames) + 1
        stamp = round(float(ts if ts is not None else time.time()), 3)
        clean_data = _redact_obj(data)
        core = {
            "seq": seq,
            "ts": stamp,
            "kind": kind,
            "label": label,
            "data": clean_data,
            "tokens_delta": int(tokens_delta),
            "latency_ms": int(latency_ms),
        }
        fhash = _hash_frame(self._prev, core)
        frame = FlightFrame(
            seq=seq,
            ts=stamp,
            kind=kind,
            label=label,
            data=clean_data,
            tokens_delta=int(tokens_delta),
            latency_ms=int(latency_ms),
            prev_hash=self._prev,
            frame_hash=fhash,
        )
        self._prev = fhash
        self._frames.append(frame)
        return frame

    def build(self) -> dict[str, Any]:
        total_tokens = sum(f.tokens_delta for f in self._frames)
        total_latency = sum(f.latency_ms for f in self._frames)
        recording: dict[str, Any] = {
            "schema_version": FLIGHT_SCHEMA_VERSION,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "created_at": self.created_at,
            "frame_count": len(self._frames),
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency,
            "head_hash": self._prev,
            "frames": [f.to_dict() for f in self._frames],
        }
        recording["anomalies"] = [a.to_dict() for a in detect_anomalies(recording)]
        return recording


def record_from_session(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    tool_results: list[dict[str, Any]] | None = None,
    memory_store: MemoryStore | None = None,
) -> dict[str, Any]:
    """Build a complete black-box Flight Recording from persisted session messages & tool outputs."""
    rec = FlightRecorder(session_id, kind="web_session")
    if memory_store is not None:
        rec.append(
            kind="memory.anchor",
            label="memory_ledger_anchor",
            data={
                "ledger_head": memory_store.ledger_head(),
                "ledger_intact": memory_store.verify_ledger(),
                "active_count": len(memory_store.active()),
            },
        )
    for idx, msg in enumerate(messages):
        role = str(msg.get("role") or "unknown")
        content = str(msg.get("content") or "")
        rec.append(
            kind=f"message.{role}",
            label=f"{role}#{idx}",
            data={
                "id": str(msg.get("id", idx)),
                "role": role,
                "chars": len(content),
                "preview": content[:320],
            },
            tokens_delta=max(1, len(content) // 4) if content else 0,
            ts=float(msg.get("created_at") or time.time()),
        )
    for tr in tool_results or []:
        tname = str(tr.get("tool_name") or "tool")
        out = str(tr.get("content") or "")
        rec.append(
            kind="tool.result",
            label=tname,
            data={
                "call_id": tr.get("call_id"),
                "tool_name": tname,
                "ok": bool(tr.get("ok", False)),
                "chars": len(out),
                "preview": out[:240],
            },
            tokens_delta=max(1, len(out) // 4) if out else 0,
            latency_ms=int(tr.get("duration_ms") or 0),
        )
    return rec.build()


def verify_flight(recording: dict[str, Any]) -> tuple[bool, list[str]]:
    """Verify the entire SHA-256 hash chain of a `.milyonus-flight.json` recording."""
    errors: list[str] = []
    if not isinstance(recording, dict) or recording.get("schema_version") != FLIGHT_SCHEMA_VERSION:
        return False, [f"invalid schema_version (expected {FLIGHT_SCHEMA_VERSION})"]
    frames = recording.get("frames")
    if not isinstance(frames, list):
        return False, ["frames must be a list"]

    prev = _GENESIS
    for idx, f in enumerate(frames, start=1):
        if not isinstance(f, dict):
            errors.append(f"frame[{idx}] is not an object")
            continue
        core = {
            "seq": f.get("seq"),
            "ts": f.get("ts"),
            "kind": f.get("kind"),
            "label": f.get("label"),
            "data": f.get("data"),
            "tokens_delta": f.get("tokens_delta"),
            "latency_ms": f.get("latency_ms"),
        }
        expected = _hash_frame(prev, core)
        if f.get("prev_hash") != prev or f.get("frame_hash") != expected:
            errors.append(f"frame seq={f.get('seq')} hash chain broken")
        prev = str(f.get("frame_hash") or "")
    if recording.get("head_hash") != prev:
        errors.append("head_hash mismatch")
    return len(errors) == 0, errors


def detect_anomalies(recording: dict[str, Any]) -> list[FlightAnomaly]:
    """Automatically diagnose runaway tool loops, latency spikes, failure bursts, and tampers."""
    anomalies: list[FlightAnomaly] = []
    ok, errs = verify_flight(recording)
    if not ok:
        anomalies.append(
            FlightAnomaly(
                code="chain_tamper",
                severity="high",
                frame_seq=0,
                message="; ".join(errs),
            )
        )

    frames = recording.get("frames") or []
    tool_frames = [f for f in frames if isinstance(f, dict) and f.get("kind") == "tool.result"]

    # 1. Runaway tool loop: >=3 consecutive calls to the exact same tool.
    streak = 0
    last_tool = ""
    for f in tool_frames:
        tname = str((f.get("data") or {}).get("tool_name") or f.get("label") or "")
        if tname == last_tool:
            streak += 1
        else:
            last_tool = tname
            streak = 1
        if streak == 3:
            anomalies.append(
                FlightAnomaly(
                    code="tool_loop",
                    severity="high",
                    frame_seq=int(f.get("seq") or 0),
                    message=f"Runaway loop suspected: tool '{tname}' invoked 3+ times consecutively.",
                )
            )

    # 2. Tool failure burst (>=2 failed tools).
    failures = [f for f in tool_frames if not bool((f.get("data") or {}).get("ok", True))]
    if len(failures) >= 2:
        anomalies.append(
            FlightAnomaly(
                code="tool_failure_burst",
                severity="medium",
                frame_seq=int(failures[-1].get("seq") or 0),
                message=f"{len(failures)} tool executions failed in this flight.",
            )
        )

    # 3. Latency spikes (>3x median and >=500ms).
    latencies = [int(f.get("latency_ms") or 0) for f in frames if int(f.get("latency_ms") or 0) > 0]
    if len(latencies) >= 2:
        med = statistics.median(latencies)
        for f in frames:
            lat = int(f.get("latency_ms") or 0)
            if lat >= 500 and med > 0 and lat > med * 3.0:
                anomalies.append(
                    FlightAnomaly(
                        code="latency_spike",
                        severity="medium",
                        frame_seq=int(f.get("seq") or 0),
                        message=f"Frame #{f.get('seq')} ({f.get('label')}) latency {lat}ms > 3x median ({med:.0f}ms).",
                    )
                )

    # 4. Empty assistant turn.
    for f in frames:
        if (
            f.get("kind") == "message.assistant"
            and int((f.get("data") or {}).get("chars") or 0) == 0
        ):
            anomalies.append(
                FlightAnomaly(
                    code="empty_assistant_turn",
                    severity="medium",
                    frame_seq=int(f.get("seq") or 0),
                    message=f"Empty assistant reply at frame #{f.get('seq')}.",
                )
            )

    return anomalies


def diff_flights(flight_a: dict[str, Any], flight_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two black-box flight recordings frame-by-frame to pinpoint divergence."""
    fa = flight_a.get("frames") or []
    fb = flight_b.get("frames") or []
    first_div: int | None = None
    div_detail = "identical frame signatures"
    for i in range(max(len(fa), len(fb))):
        if i >= len(fa):
            first_div = i + 1
            div_detail = (
                f"flight_b has extra frame #{i + 1} ({fb[i].get('kind')}:{fb[i].get('label')})"
            )
            break
        if i >= len(fb):
            first_div = i + 1
            div_detail = (
                f"flight_a has extra frame #{i + 1} ({fa[i].get('kind')}:{fa[i].get('label')})"
            )
            break
        if fa[i].get("kind") != fb[i].get("kind") or fa[i].get("label") != fb[i].get("label"):
            first_div = i + 1
            div_detail = (
                f"frame #{i + 1} diverged: {fa[i].get('kind')}:{fa[i].get('label')} "
                f"vs {fb[i].get('kind')}:{fb[i].get('label')}"
            )
            break

    tools_a = [str(f.get("label")) for f in fa if f.get("kind") == "tool.result"]
    tools_b = [str(f.get("label")) for f in fb if f.get("kind") == "tool.result"]
    return {
        "subject_a": flight_a.get("subject_id"),
        "subject_b": flight_b.get("subject_id"),
        "first_divergence_seq": first_div,
        "divergence_detail": div_detail,
        "frames_delta": len(fb) - len(fa),
        "tokens_delta": int(flight_b.get("total_tokens") or 0)
        - int(flight_a.get("total_tokens") or 0),
        "latency_ms_delta": int(flight_b.get("total_latency_ms") or 0)
        - int(flight_a.get("total_latency_ms") or 0),
        "tools_a": tools_a,
        "tools_b": tools_b,
    }
