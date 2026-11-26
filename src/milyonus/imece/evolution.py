"""Swarm DNA & Evolutionary Prompt/Strategy Genome (PLAN-HYPERNOVA H5).

Evolves multi-agent collective & prompt strategies via a real seeded genetic algorithm:
  - Structured `SwarmGenome` chromosomes (style, temperature, verification_bias,
    decomposition_depth, red_team_intensity, scale_agents, modular prompt traits),
  - Tournament selection (k=3), top-2 elitism, uniform crossover, bounded mutation,
  - Deterministic objective multi-criteria fitness evaluation (or pluggable custom oracle),
  - Full phylogenetic lineage persisted in SQLite (`evolution_runs`, `evolution_genomes`),
  - Direct champion export into a verified `SkillForgeSpec` (`SKILL.md`).
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db
from milyonus.skills.forge import SkillForgeSpec, slugify_skill_name

STYLES = ("structured", "adversarial", "minimal", "socratic", "formal-proof")
TRAIT_POOL = (
    "verify-edge-cases",
    "cite-evidence-hashes",
    "red-team-assumptions",
    "fail-closed-on-ambiguity",
    "minimize-token-overhead",
    "decompose-before-coding",
    "assert-invariants",
    "prefer-reversible-steps",
    "isolate-side-effects",
    "check-negative-controls",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_runs (
    run_id          TEXT PRIMARY KEY,
    task            TEXT NOT NULL,
    seed            INTEGER NOT NULL,
    generations     INTEGER NOT NULL,
    population_size INTEGER NOT NULL,
    best_genome_id  TEXT NOT NULL,
    best_fitness    REAL NOT NULL,
    history_json    TEXT NOT NULL,
    created_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_genomes (
    genome_id      TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    generation     INTEGER NOT NULL,
    fitness        REAL NOT NULL,
    parent_a       TEXT,
    parent_b       TEXT,
    mutations_json TEXT NOT NULL,
    genome_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evo_genomes_run ON evolution_genomes(run_id, generation);
"""


@dataclass(slots=True)
class SwarmGenome:
    genome_id: str
    generation: int
    system_style: str
    temperature: float
    verification_bias: float
    decomposition_depth: int
    red_team_intensity: float
    scale_agents: int
    traits: list[str] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)
    mutations: list[str] = field(default_factory=list)
    fitness: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render_system_directive(self) -> str:
        trait_lines = "\n".join(f"- {t.replace('-', ' ').capitalize()}" for t in self.traits)
        return (
            f"Strategy style: {self.system_style} (temp={self.temperature:.2f}, "
            f"depth={self.decomposition_depth}, scale={self.scale_agents})\n"
            f"Verification bias: {self.verification_bias:.2f} | Red-team intensity: {self.red_team_intensity:.2f}\n"
            f"Active behavioral genes:\n{trait_lines or '- Standard disciplined execution'}\n"
        )

    def to_skill_spec(self, *, name: str | None = None, task: str = "") -> SkillForgeSpec:
        sname = slugify_skill_name(name or f"evolved-{self.system_style}-{self.genome_id[-6:]}")
        body = (
            "## Evolved Strategy Profile\n"
            f"Evolved across generation `{self.generation}` (fitness `{self.fitness:.4f}`) "
            f"for task domain: {task or 'general engineering'}.\n\n"
            "## Strategy Genes\n"
            f"{self.render_system_directive()}\n"
            "## Verification Gate\n"
            "- Enforce independent verification before claiming completion.\n"
            "- Keep all tool actions reversible unless explicitly approved.\n"
        )
        return SkillForgeSpec(
            name=sname,
            description=f"Evolved {self.system_style} Swarm DNA genome (fitness {self.fitness:.3f})",
            body=body,
            tags=["evolved", "swarm-dna", self.system_style],
            category="evolved",
        )


def _genome_id(genes: dict[str, Any], generation: int, salt: str) -> str:
    raw = json.dumps({"g": generation, "genes": genes, "s": salt}, sort_keys=True)
    return "dna_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def random_genome(rng: random.Random, *, generation: int = 0) -> SwarmGenome:
    style = rng.choice(STYLES)
    temp = round(rng.uniform(0.05, 0.95), 2)
    verif = round(rng.uniform(0.2, 1.0), 2)
    depth = rng.randint(1, 5)
    red = round(rng.uniform(0.1, 1.0), 2)
    scale = rng.choice((17, 32, 64, 128, 250))
    traits = sorted(rng.sample(TRAIT_POOL, k=rng.randint(2, 5)))
    gid = _genome_id(
        {"style": style, "t": temp, "v": verif, "d": depth, "r": red, "sc": scale, "tr": traits},
        generation,
        f"{rng.random():.8f}",
    )
    return SwarmGenome(
        genome_id=gid,
        generation=generation,
        system_style=style,
        temperature=temp,
        verification_bias=verif,
        decomposition_depth=depth,
        red_team_intensity=red,
        scale_agents=scale,
        traits=traits,
    )


def crossover_and_mutate(
    parent_a: SwarmGenome,
    parent_b: SwarmGenome,
    rng: random.Random,
    *,
    generation: int,
    mutation_rate: float = 0.25,
) -> SwarmGenome:
    """Uniform crossover + bounded gene mutation with explicit mutation audit trail."""
    mutations: list[str] = []
    style = rng.choice((parent_a.system_style, parent_b.system_style))
    temp = round(rng.choice((parent_a.temperature, parent_b.temperature)), 2)
    verif = round((parent_a.verification_bias + parent_b.verification_bias) / 2.0, 2)
    depth = rng.choice((parent_a.decomposition_depth, parent_b.decomposition_depth))
    red = round((parent_a.red_team_intensity + parent_b.red_team_intensity) / 2.0, 2)
    scale = rng.choice((parent_a.scale_agents, parent_b.scale_agents))

    union_traits = sorted(set(parent_a.traits) | set(parent_b.traits))
    traits = [t for t in union_traits if rng.random() < 0.65]
    if not traits:
        traits = [rng.choice(TRAIT_POOL)]

    if rng.random() < mutation_rate:
        old = style
        style = rng.choice(STYLES)
        if style != old:
            mutations.append(f"style:{old}->{style}")
    if rng.random() < mutation_rate:
        delta = rng.uniform(-0.15, 0.15)
        temp = round(max(0.05, min(0.95, temp + delta)), 2)
        mutations.append(f"temp:{temp:.2f}")
    if rng.random() < mutation_rate:
        delta = rng.uniform(-0.15, 0.20)
        verif = round(max(0.10, min(1.0, verif + delta)), 2)
        mutations.append(f"verif:{verif:.2f}")
    if rng.random() < mutation_rate:
        depth = max(1, min(5, depth + rng.choice((-1, 1))))
        mutations.append(f"depth:{depth}")
    if rng.random() < mutation_rate:
        delta = rng.uniform(-0.15, 0.20)
        red = round(max(0.10, min(1.0, red + delta)), 2)
        mutations.append(f"red_team:{red:.2f}")
    if rng.random() < mutation_rate:
        candidate = rng.choice(TRAIT_POOL)
        if candidate in traits and len(traits) > 2:
            traits.remove(candidate)
            mutations.append(f"-trait:{candidate}")
        elif candidate not in traits and len(traits) < 6:
            traits.append(candidate)
            traits.sort()
            mutations.append(f"+trait:{candidate}")

    gid = _genome_id(
        {"style": style, "t": temp, "v": verif, "d": depth, "r": red, "sc": scale, "tr": traits},
        generation,
        f"{parent_a.genome_id}:{parent_b.genome_id}:{rng.random():.8f}",
    )
    return SwarmGenome(
        genome_id=gid,
        generation=generation,
        system_style=style,
        temperature=temp,
        verification_bias=verif,
        decomposition_depth=depth,
        red_team_intensity=red,
        scale_agents=scale,
        traits=sorted(set(traits)),
        parent_ids=[parent_a.genome_id, parent_b.genome_id],
        mutations=mutations,
    )


def default_task_fitness(task: str, genome: SwarmGenome) -> float:
    """Deterministic multi-objective fitness oracle calibrated to task semantics.

    Scores genomes on:
      - Security/verification alignment for security/audit/production tasks,
      - Conciseness & token-efficiency (penalizing bloated over-scaling on simple tasks),
      - Precision temperature calibration,
      - Complementary trait synergy without bloat.
    """
    low = task.lower()
    is_security = any(k in low for k in ("security", "audit", "auth", "crypto", "sandbox", "safe"))
    is_code = any(
        k in low for k in ("code", "bug", "refactor", "test", "api", "algorithm", "build")
    )
    is_fast = any(k in low for k in ("quick", "fast", "cheap", "summary", "minimal"))

    score = 0.0
    # 1. Style fit (0..0.22)
    if is_security and genome.system_style in ("adversarial", "formal-proof"):
        score += 0.22
    elif (is_code and genome.system_style in ("structured", "formal-proof")) or (
        is_fast and genome.system_style in ("minimal", "structured")
    ):
        score += 0.21
    else:
        score += 0.14 if genome.system_style == "structured" else 0.11

    # 2. Temperature precision (optimal ~0.15-0.30 for engineering/security) (0..0.18)
    target_temp = 0.15 if (is_security or is_code) else 0.35
    score += max(0.0, 0.18 - abs(genome.temperature - target_temp) * 0.28)

    # 3. Verification & Red-Team rigor (0..0.26)
    score += 0.16 * genome.verification_bias
    red_weight = 0.14 if is_security else 0.08
    score += red_weight * genome.red_team_intensity

    # 4. Decomposition & scale efficiency (0..0.14)
    ideal_depth = 2 if is_fast else 3 if is_code else 4
    score += max(0.0, 0.09 - abs(genome.decomposition_depth - ideal_depth) * 0.025)
    scale_penalty = 0.05 if (is_fast and genome.scale_agents > 64) else 0.0
    score += max(0.0, 0.06 - scale_penalty)

    # 5. Trait synergy & parsimony (0..0.20)
    high_value = {
        "verify-edge-cases",
        "assert-invariants",
        "fail-closed-on-ambiguity",
        "check-negative-controls",
    }
    if is_security:
        high_value |= {"red-team-assumptions", "isolate-side-effects", "cite-evidence-hashes"}
    if is_fast:
        high_value |= {"minimize-token-overhead"}
    hits = len(set(genome.traits) & high_value)
    bloat = max(0, len(genome.traits) - 5) * 0.02
    score += min(0.20, hits * 0.048) - bloat

    return round(max(0.0, min(1.0, score)), 4)


FitnessFn = Callable[[str, SwarmGenome], float]


@dataclass(slots=True)
class EvolutionReport:
    run_id: str
    task: str
    seed: int
    generations: int
    population_size: int
    champion: SwarmGenome
    generation_curve: list[dict[str, Any]]
    top_lineage: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "seed": self.seed,
            "generations": self.generations,
            "population_size": self.population_size,
            "champion": self.champion.to_dict(),
            "generation_curve": self.generation_curve,
            "top_lineage": self.top_lineage,
        }


class EvolutionStore:
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

    def save_run(self, report: EvolutionReport, all_genomes: list[SwarmGenome]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO evolution_runs(run_id, task, seed, generations, population_size, "
                "best_genome_id, best_fitness, history_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    report.run_id,
                    report.task,
                    report.seed,
                    report.generations,
                    report.population_size,
                    report.champion.genome_id,
                    report.champion.fitness,
                    json.dumps(report.generation_curve, ensure_ascii=False),
                    time.time(),
                ),
            )
            for g in all_genomes:
                pa = g.parent_ids[0] if len(g.parent_ids) > 0 else None
                pb = g.parent_ids[1] if len(g.parent_ids) > 1 else None
                self._conn.execute(
                    "INSERT OR REPLACE INTO evolution_genomes(genome_id, run_id, generation, "
                    "fitness, parent_a, parent_b, mutations_json, genome_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        g.genome_id,
                        report.run_id,
                        g.generation,
                        g.fitness,
                        pa,
                        pb,
                        json.dumps(g.mutations, ensure_ascii=False),
                        json.dumps(g.to_dict(), ensure_ascii=False),
                    ),
                )
            self._conn.commit()

    def list_runs(self, *, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, task, seed, generations, population_size, best_genome_id, "
                "best_fitness, created_at FROM evolution_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM evolution_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            champ_row = self._conn.execute(
                "SELECT genome_json FROM evolution_genomes WHERE genome_id=?",
                (row["best_genome_id"],),
            ).fetchone()
            return {
                "run_id": row["run_id"],
                "task": row["task"],
                "seed": row["seed"],
                "generations": row["generations"],
                "population_size": row["population_size"],
                "best_genome_id": row["best_genome_id"],
                "best_fitness": row["best_fitness"],
                "generation_curve": json.loads(row["history_json"]),
                "champion": json.loads(champ_row["genome_json"]) if champ_row else None,
                "created_at": row["created_at"],
            }


def evolve_swarm(
    task: str,
    *,
    generations: int = 6,
    population_size: int = 12,
    seed: int = 42,
    fitness_fn: FitnessFn | None = None,
    store: EvolutionStore | None = None,
) -> EvolutionReport:
    """Run seeded genetic evolution over Swarm DNA genomes and persist phylogeny."""
    gens = max(1, min(int(generations), 30))
    pop_size = max(4, min(int(population_size), 60))
    rng = random.Random(seed)
    evaluator = fitness_fn or default_task_fitness
    run_id = f"evo_{uuid.uuid4().hex[:12]}"

    population = [random_genome(rng, generation=0) for _ in range(pop_size)]
    all_seen: list[SwarmGenome] = []
    curve: list[dict[str, Any]] = []

    for gen in range(gens):
        for g in population:
            g.fitness = float(evaluator(task, g))
        population.sort(key=lambda x: (-x.fitness, x.genome_id))
        all_seen.extend(population)
        best = population[0]
        avg = sum(g.fitness for g in population) / len(population)
        curve.append(
            {
                "generation": gen,
                "best_fitness": round(best.fitness, 4),
                "avg_fitness": round(avg, 4),
                "best_genome_id": best.genome_id,
                "best_style": best.system_style,
            }
        )
        if gen == gens - 1:
            break

        # Top-2 elitism + tournament selection (k=3) + crossover/mutation.
        elites = [
            SwarmGenome(
                genome_id=e.genome_id,
                generation=e.generation,
                system_style=e.system_style,
                temperature=e.temperature,
                verification_bias=e.verification_bias,
                decomposition_depth=e.decomposition_depth,
                red_team_intensity=e.red_team_intensity,
                scale_agents=e.scale_agents,
                traits=list(e.traits),
                parent_ids=list(e.parent_ids),
                mutations=list(e.mutations),
                fitness=e.fitness,
            )
            for e in population[:2]
        ]
        next_pop: list[SwarmGenome] = list(elites)
        while len(next_pop) < pop_size:
            pa = max(rng.sample(population, k=min(3, len(population))), key=lambda x: x.fitness)
            pb = max(rng.sample(population, k=min(3, len(population))), key=lambda x: x.fitness)
            child = crossover_and_mutate(pa, pb, rng, generation=gen + 1)
            next_pop.append(child)
        population = next_pop

    champion = max(all_seen, key=lambda x: x.fitness)
    top_lineage = [g.to_dict() for g in sorted(all_seen, key=lambda x: -x.fitness)[:8]]
    report = EvolutionReport(
        run_id=run_id,
        task=task,
        seed=seed,
        generations=gens,
        population_size=pop_size,
        champion=champion,
        generation_curve=curve,
        top_lineage=top_lineage,
    )
    if store is not None:
        store.save_run(report, all_seen)
    return report
