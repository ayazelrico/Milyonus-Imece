"""Pre-execution command scanner (PLAN §6 layer 7).

Runs over a shell command before it executes. Detects patterns that should be
hard-blocked (fork bombs, unguarded destructive deletes, pipe-to-interpreter,
disk overwrite) and patterns that warrant confirmation. Distinct from the memory
injection scanner: this looks at *commands about to run*, not text about to be
believed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Severity = Literal["warn", "block"]


@dataclass(slots=True)
class PreExecFinding:
    signal: str
    severity: Severity
    detail: str


_ZW_STRIP_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")

_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("fork_bomb", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (
        "recursive_root_delete",
        re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\s+(--no-preserve-root\s+)?(/|~|\$HOME)(\s|$)", re.I),
        "recursive delete of root or home directory",
    ),
    ("mkfs", re.compile(r"\bmkfs(\.\w+)?\s", re.I), "filesystem format"),
    (
        "disk_overwrite",
        re.compile(r"\bdd\s+if=.*\s+of=/dev/(sd|nvme|disk)", re.I),
        "disk overwrite",
    ),
    (
        "system_chmod_777",
        re.compile(r"\bchmod\s+-R\s+777\s+/(?:$|etc|usr|bin|sbin|var|root)", re.I),
        "recursive chmod 777 on system directory",
    ),
    (
        "pipe_to_shell",
        re.compile(r"(curl|wget)\s+[^\n|]*\|\s*(sudo\s+)?(bash|sh|zsh|python)", re.I),
        "curl|bash-style pattern",
    ),
]

_WARN_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("chmod_777", re.compile(r"chmod\s+-R?\s*777", re.I), "overly broad permissions (777)"),
    ("sudo", re.compile(r"\bsudo\b", re.I), "elevated privilege"),
    ("unguarded_delete", re.compile(r"\brm\s+-[a-z]*r", re.I), "recursive delete"),
    ("db_drop", re.compile(r"\bdrop\s+(table|database)\b", re.I), "database drop"),
]


def scan_command(command: str) -> list[PreExecFinding]:
    normalized = _ZW_STRIP_RE.sub("", command)
    findings: list[PreExecFinding] = []
    for name, pat, detail in _BLOCK_PATTERNS:
        if pat.search(normalized):
            findings.append(PreExecFinding(name, "block", detail))
    for name, pat, detail in _WARN_PATTERNS:
        if pat.search(normalized):
            findings.append(PreExecFinding(name, "warn", detail))
    return findings
