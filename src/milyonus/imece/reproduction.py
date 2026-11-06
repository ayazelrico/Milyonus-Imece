"""Bounded diagnostic bundles for operator-enabled capture of generated gate failures."""

from __future__ import annotations

import hashlib
import json
import re

from milyonus.imece.execution import python_files
from milyonus.security.redact import redact


def capture(examples, candidates, checks, reports, executor) -> None:
    scripts = {c.id: c.python for c in checks}
    known = {example["digest"] for example in examples}
    for candidate in candidates:
        if len(examples) >= 3:
            return
        for observation in reports[candidate.id].test_results:
            if observation.get("failure_class") != "candidate_or_oracle_runtime":
                continue
            script = scripts.get(observation["test"])
            if not script:
                continue
            files = python_files(candidate.solution)
            bundle = {
                "files": files,
                "check": script,
                "backend": executor.backend,
                "image": executor.image,
                "timeout": executor.timeout,
            }
            environment = observation.get("environment_id")
            if isinstance(environment, str) and re.fullmatch(r"[0-9a-f]{64}", environment):
                bundle["environment_id"] = environment
            raw = json.dumps(bundle, sort_keys=True, ensure_ascii=False)
            if not files or len(raw.encode()) > 32768 or redact(raw) != raw:
                continue
            digest = hashlib.sha256(raw.encode()).hexdigest()
            if digest not in known:
                examples.append(
                    dict(
                        bundle,
                        digest=digest,
                        candidate=candidate.id,
                        test=observation["test"],
                        returncode=observation["returncode"],
                        evidence_id=observation.get("evidence_id"),
                    )
                )
                known.add(digest)
            break
