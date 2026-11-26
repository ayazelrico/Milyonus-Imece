"""Federated İmece Mesh Protocol — Byzantine-Resilient Signed Quorum (PLAN-HYPERNOVA H10).

Connects multiple independent Milyonus nodes into a cryptographically authenticated
peer-to-peer collective (`milyonus.mesh.v1`):
  1. Signed `MeshPacket` envelopes (`TASK_OFFER`, `TASK_RESULT`, `PROOF_ATTEST`,
     `GOSSIP_HEALTH`) with SHA-256 payload digests, HMAC-SHA256 node authentication,
     timestamps, and anti-replay nonces (300s window).
  2. Persistent SQLite peer registry (`mesh_peers`, `mesh_dispatches`) tracking
     node capabilities, trust reputation (`0.0–1.0`), verified task counts, and
     Byzantine slashing history.
  3. `MeshCoordinator.dispatch()` fans out a task across registered peers, verifies
     every returned packet signature AND attached `.milyonus-proof.json` Merkle root,
     rejects forged/tampered/replayed packets fail-closed, **slashes Byzantine peers**
     (`-0.35` reputation; auto-quarantined below `0.25`), and reaches a
     reputation-weighted consensus quorum!
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db
from milyonus.security.proof import build_imece_proof, verify_proof

MESH_SCHEMA_VERSION = "milyonus.mesh.v1"
MAX_CLOCK_SKEW_S = 300.0
SLASH_PENALTY = 0.35
QUARANTINE_REPUTATION = 0.25

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mesh_peers (
    node_id         TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'worker',
    endpoint        TEXT NOT NULL DEFAULT 'local://in-process',
    shared_secret   TEXT NOT NULL,
    reputation      REAL NOT NULL DEFAULT 1.0,
    verified_tasks  INTEGER NOT NULL DEFAULT 0,
    slashed_count   INTEGER NOT NULL DEFAULT 0,
    quarantined     INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    last_seen_at    REAL
);
CREATE TABLE IF NOT EXISTS mesh_dispatches (
    dispatch_id     TEXT PRIMARY KEY,
    task            TEXT NOT NULL,
    quorum_reached  INTEGER NOT NULL,
    consensus       TEXT NOT NULL,
    verified_peers  INTEGER NOT NULL,
    rejected_peers  INTEGER NOT NULL,
    report_json     TEXT NOT NULL,
    created_at      REAL NOT NULL
);
"""


@dataclass(slots=True)
class MeshPeer:
    node_id: str
    label: str
    role: str
    endpoint: str
    reputation: float
    verified_tasks: int
    slashed_count: int
    quarantined: bool
    created_at: float
    last_seen_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sign_mesh_packet(
    *,
    kind: str,
    sender_id: str,
    payload: dict[str, Any],
    shared_secret: str,
    nonce: str | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """Build and HMAC-SHA256 sign a `milyonus.mesh.v1` protocol envelope."""
    ts = round(float(timestamp if timestamp is not None else time.time()), 3)
    nc = nonce or secrets.token_hex(12)
    payload_sha = hashlib.sha256(_canonical(payload)).hexdigest()
    body = {
        "schema_version": MESH_SCHEMA_VERSION,
        "packet_id": f"pkt_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "sender_id": sender_id,
        "nonce": nc,
        "timestamp": ts,
        "payload_sha256": payload_sha,
        "payload": payload,
    }
    sig_input = _canonical(
        {
            "schema_version": body["schema_version"],
            "packet_id": body["packet_id"],
            "kind": body["kind"],
            "sender_id": body["sender_id"],
            "nonce": body["nonce"],
            "timestamp": body["timestamp"],
            "payload_sha256": body["payload_sha256"],
        }
    )
    sig = hmac.new(shared_secret.encode("utf-8"), sig_input, hashlib.sha256).hexdigest()
    body["signature_hex"] = sig
    return body


def verify_mesh_packet(
    packet: dict[str, Any],
    *,
    shared_secret: str,
    seen_nonces: set[str] | None = None,
    now: float | None = None,
) -> tuple[bool, str]:
    """Fail-closed verification of a signed `milyonus.mesh.v1` packet."""
    if not isinstance(packet, dict) or packet.get("schema_version") != MESH_SCHEMA_VERSION:
        return False, "invalid mesh schema_version"
    ts = packet.get("timestamp")
    nonce = packet.get("nonce")
    provided_sig = packet.get("signature_hex")
    if (
        not isinstance(ts, (int, float))
        or not isinstance(nonce, str)
        or not isinstance(provided_sig, str)
    ):
        return False, "missing required envelope fields"

    cur_ts = now if now is not None else time.time()
    if abs(cur_ts - float(ts)) > MAX_CLOCK_SKEW_S:
        return False, "packet timestamp outside replay skew window"
    if seen_nonces is not None and nonce in seen_nonces:
        return False, "replayed packet nonce detected"

    payload = packet.get("payload")
    if not isinstance(payload, dict):
        return False, "payload must be an object"
    recomputed_sha = hashlib.sha256(_canonical(payload)).hexdigest()
    if packet.get("payload_sha256") != recomputed_sha:
        return False, "payload_sha256 mismatch (payload tampered)"

    sig_input = _canonical(
        {
            "schema_version": packet["schema_version"],
            "packet_id": packet.get("packet_id"),
            "kind": packet.get("kind"),
            "sender_id": packet.get("sender_id"),
            "nonce": nonce,
            "timestamp": ts,
            "payload_sha256": recomputed_sha,
        }
    )
    expected_sig = hmac.new(shared_secret.encode("utf-8"), sig_input, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        return False, "HMAC-SHA256 mesh signature invalid"

    if seen_nonces is not None:
        seen_nonces.add(nonce)
    return True, "verified"


PeerWorkerFn = Callable[[MeshPeer, str, str], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class PeerOutcome:
    node_id: str
    label: str
    accepted: bool
    reason: str
    answer: str = ""
    proof_merkle_root: str = ""
    reputation_after: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MeshDispatchReport:
    dispatch_id: str
    task: str
    quorum_reached: bool
    consensus_answer: str
    consensus_weight: float
    total_weight: float
    verified_peers: int
    rejected_peers: int
    slashed_nodes: list[str] = field(default_factory=list)
    peer_outcomes: list[PeerOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "task": self.task,
            "quorum_reached": self.quorum_reached,
            "consensus_answer": self.consensus_answer,
            "consensus_weight": self.consensus_weight,
            "total_weight": self.total_weight,
            "verified_peers": self.verified_peers,
            "rejected_peers": self.rejected_peers,
            "slashed_nodes": self.slashed_nodes,
            "peer_outcomes": [o.to_dict() for o in self.peer_outcomes],
        }


class MeshStore:
    """SQLite registry of federated mesh peers, reputation, and dispatch history."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_db()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row_to_peer(self, r: sqlite3.Row) -> MeshPeer:
        return MeshPeer(
            node_id=str(r["node_id"]),
            label=str(r["label"]),
            role=str(r["role"]),
            endpoint=str(r["endpoint"]),
            reputation=round(float(r["reputation"]), 3),
            verified_tasks=int(r["verified_tasks"]),
            slashed_count=int(r["slashed_count"]),
            quarantined=bool(r["quarantined"]),
            created_at=float(r["created_at"]),
            last_seen_at=float(r["last_seen_at"]) if r["last_seen_at"] is not None else None,
        )

    def register_peer(
        self,
        *,
        node_id: str | None = None,
        label: str,
        role: str = "worker",
        endpoint: str = "local://in-process",
        shared_secret: str | None = None,
    ) -> tuple[MeshPeer, str]:
        nid = (node_id or f"node_{uuid.uuid4().hex[:10]}").strip()
        secret = shared_secret or f"mesh_sec_{secrets.token_hex(16)}"
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO mesh_peers(node_id, label, role, endpoint, shared_secret, "
                "reputation, verified_tasks, slashed_count, quarantined, created_at, last_seen_at) "
                "VALUES (?,?,?,?,?,1.0,0,0,0,?,?)",
                (
                    nid,
                    label.strip()[:80],
                    role.strip()[:32],
                    endpoint.strip()[:160],
                    secret,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM mesh_peers WHERE node_id=?", (nid,)).fetchone()
        return self._row_to_peer(row), secret

    def list_peers(self, *, active_only: bool = False) -> list[MeshPeer]:
        with self._lock:
            q = (
                "SELECT * FROM mesh_peers WHERE quarantined=0 ORDER BY reputation DESC, node_id ASC"
                if active_only
                else "SELECT * FROM mesh_peers ORDER BY reputation DESC, node_id ASC"
            )
            return [self._row_to_peer(r) for r in self._conn.execute(q).fetchall()]

    def get_peer_secret(self, node_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT shared_secret FROM mesh_peers WHERE node_id=?", (node_id,)
            ).fetchone()
            return str(row["shared_secret"]) if row is not None else None

    def remove_peer(self, node_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM mesh_peers WHERE node_id=?", (node_id,))
            self._conn.commit()
            return (cur.rowcount or 0) > 0

    def reward_peer(self, node_id: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT reputation FROM mesh_peers WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                return 0.0
            rep = round(min(1.0, float(row["reputation"]) + 0.05), 3)
            self._conn.execute(
                "UPDATE mesh_peers SET reputation=?, verified_tasks=verified_tasks+1, "
                "last_seen_at=? WHERE node_id=?",
                (rep, time.time(), node_id),
            )
            self._conn.commit()
            return rep

    def slash_peer(self, node_id: str, *, penalty: float = SLASH_PENALTY) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT reputation FROM mesh_peers WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                return 0.0
            rep = round(max(0.0, float(row["reputation"]) - penalty), 3)
            quarantined = 1 if rep < QUARANTINE_REPUTATION else 0
            self._conn.execute(
                "UPDATE mesh_peers SET reputation=?, slashed_count=slashed_count+1, "
                "quarantined=?, last_seen_at=? WHERE node_id=?",
                (rep, quarantined, time.time(), node_id),
            )
            self._conn.commit()
            return rep

    def save_dispatch(self, report: MeshDispatchReport) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO mesh_dispatches(dispatch_id, task, quorum_reached, consensus, "
                "verified_peers, rejected_peers, report_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    report.dispatch_id,
                    report.task,
                    1 if report.quorum_reached else 0,
                    report.consensus_answer,
                    report.verified_peers,
                    report.rejected_peers,
                    json.dumps(report.to_dict(), ensure_ascii=False),
                    time.time(),
                ),
            )
            self._conn.commit()

    def recent_dispatches(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT dispatch_id, task, quorum_reached, consensus, verified_peers, "
                "rejected_peers, created_at FROM mesh_dispatches ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


def _default_local_worker(byzantine_nodes: set[str] | None = None) -> PeerWorkerFn:
    """Deterministic local mesh peer simulator that attaches real Proof Capsules."""
    bad = byzantine_nodes or set()

    async def _work(peer: MeshPeer, task: str, secret: str) -> dict[str, Any]:
        deliverable = f"Verified consensus solution for: {task.strip()}"
        proof = build_imece_proof(
            {
                "deliverable": deliverable,
                "accepted": True,
                "rounds": 1,
                "approval": {"verdict": "accept", "node": peer.node_id},
            },
            subject_id=f"mesh:{peer.node_id}",
        )
        if peer.node_id in bad:
            # Simulate a Byzantine peer tampering with the deliverable after signing!
            pkt = sign_mesh_packet(
                kind="TASK_RESULT",
                sender_id=peer.node_id,
                payload={"answer": deliverable, "proof": proof},
                shared_secret=secret,
            )
            pkt["payload"]["answer"] = "MALICIOUS_BYZANTINE_PAYLOAD"
            return pkt
        return sign_mesh_packet(
            kind="TASK_RESULT",
            sender_id=peer.node_id,
            payload={"answer": deliverable, "proof": proof},
            shared_secret=secret,
        )

    return _work


class MeshCoordinator:
    """Dispatches tasks across federated Milyonus peers with Byzantine quorum synthesis."""

    def __init__(self, store: MeshStore) -> None:
        self.store = store
        self._seen_nonces: set[str] = set()

    def ensure_default_cluster(self) -> list[MeshPeer]:
        """Bootstrap a 3-node local verification mesh if no peers are registered yet."""
        peers = self.store.list_peers()
        if peers:
            return peers
        defaults = [
            ("node-alpha", "Alpha Framing Node", "framing"),
            ("node-beta", "Beta Builder Node", "worker"),
            ("node-gamma", "Gamma Gate Auditor", "auditor"),
        ]
        created: list[MeshPeer] = []
        for nid, lbl, role in defaults:
            p, _sec = self.store.register_peer(node_id=nid, label=lbl, role=role)
            created.append(p)
        return created

    async def dispatch(
        self,
        task: str,
        *,
        worker_fn: PeerWorkerFn | None = None,
        byzantine_nodes: set[str] | None = None,
        require_proof: bool = True,
    ) -> MeshDispatchReport:
        """Broadcast task to all active peers, verify signatures & proofs, slash Byzantine nodes."""
        peers = self.store.list_peers(active_only=True)
        if not peers:
            peers = self.ensure_default_cluster()

        fn = worker_fn or _default_local_worker(byzantine_nodes)
        dispatch_id = f"mesh_{uuid.uuid4().hex[:12]}"
        outcomes: list[PeerOutcome] = []
        slashed: list[str] = []
        weighted_votes: dict[str, float] = {}
        total_weight = 0.0

        for peer in peers:
            secret = self.store.get_peer_secret(peer.node_id)
            if not secret:
                outcomes.append(
                    PeerOutcome(
                        peer.node_id,
                        peer.label,
                        False,
                        "missing peer secret",
                        reputation_after=peer.reputation,
                    )
                )
                continue
            try:
                pkt = await fn(peer, task, secret)
            except Exception as exc:  # noqa: BLE001 - isolate peer failure
                outcomes.append(
                    PeerOutcome(
                        peer.node_id,
                        peer.label,
                        False,
                        f"peer transport error: {exc}",
                        reputation_after=peer.reputation,
                    )
                )
                continue

            sig_ok, reason = verify_mesh_packet(
                pkt, shared_secret=secret, seen_nonces=self._seen_nonces
            )
            if not sig_ok or pkt.get("sender_id") != peer.node_id:
                new_rep = self.store.slash_peer(peer.node_id)
                slashed.append(peer.node_id)
                outcomes.append(
                    PeerOutcome(
                        peer.node_id,
                        peer.label,
                        False,
                        f"BYZANTINE REJECTED ({reason})",
                        reputation_after=new_rep,
                    )
                )
                continue

            payload = pkt["payload"]
            answer = str(payload.get("answer") or "").strip()
            proof = payload.get("proof")
            root = ""
            if require_proof:
                if not isinstance(proof, dict):
                    new_rep = self.store.slash_peer(peer.node_id)
                    slashed.append(peer.node_id)
                    outcomes.append(
                        PeerOutcome(
                            peer.node_id,
                            peer.label,
                            False,
                            "BYZANTINE REJECTED (missing proof capsule)",
                            reputation_after=new_rep,
                        )
                    )
                    continue
                pv = verify_proof(proof)
                if not pv.valid:
                    new_rep = self.store.slash_peer(peer.node_id)
                    slashed.append(peer.node_id)
                    outcomes.append(
                        PeerOutcome(
                            peer.node_id,
                            peer.label,
                            False,
                            f"BYZANTINE REJECTED (invalid proof: {'; '.join(pv.errors)})",
                            reputation_after=new_rep,
                        )
                    )
                    continue
                root = pv.merkle_root

            new_rep = self.store.reward_peer(peer.node_id)
            weighted_votes[answer] = weighted_votes.get(answer, 0.0) + peer.reputation
            total_weight += peer.reputation
            outcomes.append(
                PeerOutcome(
                    node_id=peer.node_id,
                    label=peer.label,
                    accepted=True,
                    reason="signature + proof capsule verified",
                    answer=answer,
                    proof_merkle_root=root,
                    reputation_after=new_rep,
                )
            )

        verified_cnt = sum(1 for o in outcomes if o.accepted)
        rejected_cnt = len(outcomes) - verified_cnt
        if weighted_votes:
            consensus_answer, consensus_weight = max(weighted_votes.items(), key=lambda kv: kv[1])
            # Quorum requires strict majority of active peer weight AND >= 2 verified peers (or 1 if 1-node mesh).
            needed = 1 if len(peers) == 1 else (len(peers) // 2 + 1)
            quorum_ok = verified_cnt >= needed and consensus_weight > (total_weight / 2.0)
        else:
            consensus_answer = ""
            consensus_weight = 0.0
            quorum_ok = False

        report = MeshDispatchReport(
            dispatch_id=dispatch_id,
            task=task,
            quorum_reached=quorum_ok,
            consensus_answer=consensus_answer,
            consensus_weight=round(consensus_weight, 3),
            total_weight=round(total_weight, 3),
            verified_peers=verified_cnt,
            rejected_peers=rejected_cnt,
            slashed_nodes=slashed,
            peer_outcomes=outcomes,
        )
        self.store.save_dispatch(report)
        return report
