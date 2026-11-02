"""Executable reproducibility gate for self-authored Python procedures."""

from __future__ import annotations

import ast
import re
import sys

from milyonus.imece.execution import PythonExecutor, python_files
from milyonus.skills.model import SkillMeta

_TESTS = re.compile(r"^```python\s+test=skill\s*\n(.*?)^```\s*$", re.M | re.S)


async def replay_python(_meta: SkillMeta, body: str) -> bool:
    """Examples are staged, not trusted. A missing runnable check is a refusal.
    Non-Python skills need an explicitly injected domain-specific replay gate.
    """
    try:
        files = python_files(body)
        tests = _TESTS.findall(body)
        if not files or not tests:
            return False
        for test in tests:
            if not any(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(test))):
                return False
        executor = PythonExecutor(backend="macos" if sys.platform == "darwin" else "docker")
        for test in tests:
            if not (await executor.run(files, test)).passed:
                return False
        return True
    except (ValueError, SyntaxError, OSError):
        return False
