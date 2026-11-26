"""Autonomous AST Self-Patching Code Surgeon (PLAN-SINGULARITY S5).

Performs real Python `ast` structural & security static analysis and synthesizes
AST-verified unified micro-patches (`difflib.unified_diff`) for auto-fixable defects:

  - SEC-001 (critical): dynamic `eval()` / `exec()` execution
  - SEC-002 (high): `subprocess.*(..., shell=True)` command injection surface
  - SEC-003 (high): unsafe `yaml.load(...)` without `SafeLoader` (auto-patchable → `yaml.safe_load`)
                    or `pickle.loads(...)` deserialization
  - SEC-004 (critical): hardcoded credential literals (`ghp_`, `sk-`, `AKIA`) (auto-patchable)
  - REL-001 (medium): bare `except:` swallowing system interrupts (auto-patchable → `except Exception:`)
  - REL-002 (medium): mutable default argument `def f(x=[])` / `x={}`
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_CRED_LITERAL_RE = re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{16})\b")

_SEVERITY_PENALTY: dict[str, int] = {
    "critical": 28,
    "high": 18,
    "medium": 10,
    "low": 4,
}


@dataclass(slots=True)
class SurgeonFinding:
    rule_id: str
    severity: str
    line: int
    message: str
    auto_fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SurgeonReport:
    filename: str
    valid_python: bool
    health_score: int
    grade: str
    findings: list[SurgeonFinding] = field(default_factory=list)
    patched_source: str = ""
    unified_diff: str = ""
    patch_ast_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "valid_python": self.valid_python,
            "health_score": self.health_score,
            "grade": self.grade,
            "findings": [f.to_dict() for f in self.findings],
            "patched_source": self.patched_source,
            "unified_diff": self.unified_diff,
            "patch_ast_verified": self.patch_ast_verified,
        }


def _grade(score: int) -> str:
    if score >= 95:
        return "A+"
    if score >= 88:
        return "A"
    if score >= 78:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return f"{node.func.value.id}.{node.func.attr}"
    return ""


def analyze_and_patch(source: str, *, filename: str = "snippet.py") -> SurgeonReport:
    """AST-scan Python source for defects and synthesize a verified unified patch."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return SurgeonReport(
            filename=filename,
            valid_python=False,
            health_score=0,
            grade="F",
            findings=[
                SurgeonFinding(
                    "SYN-001", "critical", exc.lineno or 1, f"SyntaxError: {exc.msg}", False
                )
            ],
        )

    findings: list[SurgeonFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            cname = _call_name(node)
            if cname in ("eval", "exec"):
                findings.append(
                    SurgeonFinding(
                        "SEC-001",
                        "critical",
                        node.lineno,
                        f"Dynamic `{cname}()` execution creates arbitrary code injection risk.",
                        auto_fixable=False,
                    )
                )
            elif cname.startswith("subprocess."):
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        findings.append(
                            SurgeonFinding(
                                "SEC-002",
                                "high",
                                node.lineno,
                                f"`{cname}(..., shell=True)` exposes shell injection surface.",
                                auto_fixable=False,
                            )
                        )
            elif cname == "yaml.load":
                has_safe = any(
                    kw.arg == "Loader"
                    and isinstance(kw.value, (ast.Name, ast.Attribute))
                    and "Safe" in ast.dump(kw.value)
                    for kw in node.keywords
                )
                if not has_safe:
                    findings.append(
                        SurgeonFinding(
                            "SEC-003",
                            "high",
                            node.lineno,
                            "Unsafe `yaml.load()` without SafeLoader — replace with `yaml.safe_load()`.",
                            auto_fixable=True,
                        )
                    )
            elif cname in ("pickle.loads", "pickle.load"):
                findings.append(
                    SurgeonFinding(
                        "SEC-003",
                        "high",
                        node.lineno,
                        f"Untrusted `{cname}()` permits arbitrary object deserialization RCE.",
                        auto_fixable=False,
                    )
                )

        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(
                SurgeonFinding(
                    "REL-001",
                    "medium",
                    node.lineno,
                    "Bare `except:` swallows KeyboardInterrupt and SystemExit — narrow to `except Exception:`.",
                    auto_fixable=True,
                )
            )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    findings.append(
                        SurgeonFinding(
                            "REL-002",
                            "medium",
                            node.lineno,
                            f"Mutable default argument in `{node.name}()` leaks state across calls.",
                            auto_fixable=False,
                        )
                    )

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _CRED_LITERAL_RE.search(node.value):
                findings.append(
                    SurgeonFinding(
                        "SEC-004",
                        "critical",
                        node.lineno,
                        "Hardcoded secret credential literal detected in source code.",
                        auto_fixable=True,
                    )
                )

    findings.sort(key=lambda f: (f.line, f.rule_id))
    penalty = sum(_SEVERITY_PENALTY.get(f.severity, 5) for f in findings)
    score = max(0, 100 - penalty)

    # Synthesize safe micro-patches for auto_fixable findings.
    patched_lines: list[str] = []
    for raw_line in source.splitlines(keepends=True):
        line = raw_line
        # Fix bare except: preserving indentation & trailing comments.
        line = re.sub(r"^(\s*)except\s*:", r"\1except Exception:", line)
        # Fix unsafe yaml.load(x) -> yaml.safe_load(x) when no Loader kwarg is present.
        if "yaml.load(" in line and "Loader=" not in line:
            line = line.replace("yaml.load(", "yaml.safe_load(")
        # Redact hardcoded credential literals cleanly.
        if _CRED_LITERAL_RE.search(line):
            line = _CRED_LITERAL_RE.sub("REDACTED_USE_ENV_VAR", line)
        patched_lines.append(line)

    patched_source = "".join(patched_lines)
    patch_ok = False
    if patched_source != source:
        try:
            ast.parse(patched_source, filename=filename)
            patch_ok = True
        except SyntaxError:
            patched_source = source
            patch_ok = False
    else:
        patch_ok = True

    udiff = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            patched_source.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )

    return SurgeonReport(
        filename=filename,
        valid_python=True,
        health_score=score,
        grade=_grade(score),
        findings=findings,
        patched_source=patched_source,
        unified_diff=udiff,
        patch_ast_verified=patch_ok,
    )
