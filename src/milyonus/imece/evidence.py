"""Local content-addressed evidence for explicitly deterministic contracts.

No model can opt itself into reuse. Caller must certify determinism, and the
executor must supply a pinned runtime identity. Infrastructure failures are not
cacheable. This cache is never mounted into the sandbox.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, fields
from pathlib import Path

from milyonus.imece.execution import ExecutionResult


def evidence_key(files: dict[str, str], oracle: str, environment: dict, policy: str) -> str:
    value = {"files": files, "oracle": oracle, "environment": environment, "policy": policy}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class EvidenceCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS evidence (key TEXT PRIMARY KEY, result TEXT, checksum TEXT)"
        )
        self.hits = self.misses = 0

    def close(self):
        self.db.close()

    @staticmethod
    def _reusable(result: ExecutionResult, key: str) -> bool:
        return (
            result.passed is True
            and type(result.returncode) is int
            and result.returncode == 0
            and isinstance(result.output, str)
            and result.backend == "docker"
            and result.evidence_id == key
            and type(result.reused) is bool
            and type(result.output_truncated) is bool
            and result.failure_class is None
        )

    def get(self, key: str) -> ExecutionResult | None:
        row = self.db.execute("SELECT result,checksum FROM evidence WHERE key=?", (key,)).fetchone()
        if (
            row
            and isinstance(row[0], str)
            and hashlib.sha256(row[0].encode()).hexdigest() == row[1]
        ):
            try:
                payload = json.loads(row[0])
                if not isinstance(payload, dict) or set(payload) != {
                    field.name for field in fields(ExecutionResult)
                }:
                    raise ValueError("incomplete cached execution result")
                result = ExecutionResult(**payload)
                if self._reusable(result, key):
                    self.hits += 1
                    return result
            except (TypeError, ValueError):
                pass
        self.misses += 1
        return None

    def put(self, key: str, result: ExecutionResult):
        # Process exit codes can describe an unavailable image or daemon as well
        # as a failing assertion. Only a successful verification is reusable.
        if not self._reusable(result, key):
            return
        value = json.dumps(asdict(result), sort_keys=True)
        self.db.execute(
            "INSERT OR REPLACE INTO evidence VALUES (?,?,?)",
            (key, value, hashlib.sha256(value.encode()).hexdigest()),
        )
        self.db.commit()
