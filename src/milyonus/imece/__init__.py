"""Milyonus-Imece: the İmece-İRADE collective.

Labor in the imece, speed in IRADE, truth at the independent gates. The
question is challenged independently (Kapı 1), the answer is built by the
imece, decisions are sped up by tiered IRADE, the result is tested against
reality (Kapı 2) and approved by someone who never saw the process (Kapı 3).
No layer has to catch its own errors.
"""

from milyonus.imece.orchestrator import Imece, ImeceSettings, RunResult
from milyonus.imece.scale import Allocation, allocate

__all__ = ["Allocation", "Imece", "ImeceSettings", "RunResult", "allocate"]
