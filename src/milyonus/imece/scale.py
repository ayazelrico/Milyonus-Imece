"""Scale the 10,000-agent reference distribution down (or up) to any size.

10,000 is a representative number. The user picks a total (tens, hundreds, or
thousands of subagents); each block gets a share proportional to its weight in
the reference distribution, but never less than its floor — so no 🔴 function
drops to zero at small scale. The IRADE council (5) is outside this total.

Blocks are one of three kinds:
  - flexible:     imece pool. Idle agents may swarm into another flexible block.
  - independent:  must stay independent of producers. Never lends or borrows.
  - fixed:        neither independent nor pooled (command, human interface).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["flexible", "independent", "fixed"]
Necessity = Literal["mandatory", "conditional", "scale"]  # 🔴 / 🟠 / 🟡

REFERENCE_TOTAL = 10_000
COUNCIL_SIZE = 5


@dataclass(frozen=True, slots=True)
class BlockSpec:
    key: str
    label: str
    weight: int  # agents in the 10,000 reference distribution
    kind: Kind
    necessity: Necessity
    floor: int  # minimum agents at any scale


# Order matters only for display. Weights sum to REFERENCE_TOTAL.
BLOCKS: tuple[BlockSpec, ...] = (
    BlockSpec("production", "İmece üretim havuzu", 4500, "flexible", "mandatory", 2),
    BlockSpec("domain_experts", "Alan uzmanları", 1000, "flexible", "conditional", 0),
    BlockSpec("test_design", "Test tasarımı", 400, "independent", "mandatory", 1),
    BlockSpec("test_exec", "Test yürütme", 1100, "flexible", "mandatory", 1),
    BlockSpec("recon", "Recon / istihbarat", 700, "flexible", "mandatory", 1),
    BlockSpec("red_team", "Kırmızı takım", 400, "independent", "conditional", 1),
    BlockSpec("plan", "Plan", 400, "flexible", "mandatory", 1),
    BlockSpec("command", "Komuta ve operasyon", 300, "fixed", "mandatory", 1),
    BlockSpec("integration", "Entegrasyon", 300, "flexible", "mandatory", 1),
    BlockSpec("evidence_audit", "Kanıt denetimi", 300, "independent", "mandatory", 1),
    BlockSpec("framing", "Çerçeveleme (Kapı 1)", 150, "independent", "mandatory", 5),
    BlockSpec("compliance", "Uyum (etik-hukuk-güvenlik)", 100, "independent", "conditional", 0),
    BlockSpec("polish", "Cilalama ve teslimat", 100, "flexible", "conditional", 0),
    BlockSpec("observer", "Süreç gözlemcisi", 100, "independent", "scale", 1),
    BlockSpec("approval", "Onay Merci (Kapı 3)", 50, "independent", "mandatory", 1),
    BlockSpec("human_interface", "İnsan arayüzü", 50, "fixed", "scale", 0),
    BlockSpec("exploration", "Keşif / yüksek riskli araştırma", 50, "flexible", "conditional", 0),
)

SPECS: dict[str, BlockSpec] = {b.key: b for b in BLOCKS}
MIN_TOTAL = sum(b.floor for b in BLOCKS)
MAX_TOTAL = 100_000

assert sum(b.weight for b in BLOCKS) == REFERENCE_TOTAL


class ScaleError(ValueError):
    """Raised for an impossible total or a forbidden reassignment."""


@dataclass(slots=True)
class Loan:
    source: str
    target: str
    count: int
    reason: str


@dataclass
class Allocation:
    """Agent counts per block, plus a ledger of temporary swarming loans."""

    total: int
    counts: dict[str, int]
    loans: list[Loan] = field(default_factory=list)

    def __getitem__(self, key: str) -> int:
        return self.counts[key]

    def effective(self, key: str) -> int:
        """Count including agents currently on loan in/out."""
        out = sum(ln.count for ln in self.loans if ln.source == key)
        inn = sum(ln.count for ln in self.loans if ln.target == key)
        return self.counts[key] - out + inn

    def borrow(self, source: str, target: str, count: int, reason: str = "") -> int:
        """Move idle flexible agents into another flexible block (swarming).

        Independent blocks can neither lend nor receive: framing, test design,
        red team, evidence audit, compliance, observer and approval must stay
        independent of the producers. Returns how many were actually moved.
        """
        for key in (source, target):
            if key not in SPECS:
                raise ScaleError(f"unknown block: {key}")
            if SPECS[key].kind != "flexible":
                raise ScaleError(
                    f"'{key}' is a {SPECS[key].kind} block — it cannot take part in swarming"
                )
        moved = max(0, min(count, self.effective(source)))
        if moved:
            self.loans.append(Loan(source, target, moved, reason))
        return moved

    def release_loans(self) -> None:
        self.loans.clear()

    def rows(self) -> list[tuple[BlockSpec, int]]:
        return [(b, self.counts[b.key]) for b in BLOCKS]


def allocate(total: int) -> Allocation:
    """Distribute `total` agents across blocks.

    Every block first gets its floor. The rest is shared out in proportion to
    how far each block's ideal (proportional) share sits above its floor, using
    the largest-remainder method so counts are integers and sum exactly.
    """
    if total < MIN_TOTAL:
        raise ScaleError(
            f"at least {MIN_TOTAL} agents are needed so that no mandatory function is empty "
            f"(got {total})"
        )
    if total > MAX_TOTAL:
        raise ScaleError(f"at most {MAX_TOTAL} agents are supported (got {total})")

    counts = {b.key: b.floor for b in BLOCKS}
    remaining = total - MIN_TOTAL
    deficits = {b.key: max(0.0, total * b.weight / REFERENCE_TOTAL - b.floor) for b in BLOCKS}
    deficit_sum = sum(deficits.values())
    if remaining and deficit_sum > 0:
        shares = {k: remaining * d / deficit_sum for k, d in deficits.items()}
        for k, s in shares.items():
            counts[k] += int(s)
        leftover = total - sum(counts.values())
        by_fraction = sorted(
            shares, key=lambda k: (shares[k] - int(shares[k]), SPECS[k].weight), reverse=True
        )
        for k in by_fraction[:leftover]:
            counts[k] += 1
    assert sum(counts.values()) == total
    return Allocation(total=total, counts=counts)
