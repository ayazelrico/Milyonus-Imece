"""Autonomous Self-Healing Skill Immune System (PLAN-HYPERNOVA H7).

Protects procedural memory (`SKILL.md` directories) against supply-chain drift,
silent tampering, accidental secret leakage, and malformed YAML frontmatter:
  1. `seal_manifest(skills_dir)` — hashes every installed `SKILL.md` into
     `.immune-manifest.json` (`0o600`).
  2. `scan_skills_health(skills_dir)` — checks SHA-256 tamper drift, security
     scanner findings (`danger`/`caution`), frontmatter integrity, secret leaks,
     and duplicate skill names, producing a 0–100 Health Score.
  3. `quarantine_skill(skills_dir, name, reason)` — atomically isolates a
     compromised skill into `.quarantine/<name>-<ts>/` with a forensic report.
  4. `heal_skill(skills_dir, name)` — repairs broken frontmatter, redacts leaked
     secrets, verifies zero `danger` findings (refusing fail-closed on RCE),
     and re-seals the manifest baseline.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import skills_dir as default_skills_dir
from milyonus.security.redact import redact
from milyonus.skills.model import SkillMeta, SkillParseError, parse_skill_md, render_skill_md
from milyonus.skills.scanner import scan_skill

MANIFEST_FILENAME = ".immune-manifest.json"
QUARANTINE_DIRNAME = ".quarantine"


@dataclass(slots=True)
class SkillHealthEntry:
    name: str
    path: str
    status: str  # "healthy" | "warn" | "tampered" | "compromised"
    sha256: str
    baseline_sha256: str | None
    issues: list[str] = field(default_factory=list)
    healable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ImmuneScanReport:
    skills_root: str
    health_score: int
    total_skills: int
    healthy_count: int
    warn_count: int
    tampered_count: int
    compromised_count: int
    manifest_sealed: bool
    quarantined_count: int
    entries: list[SkillHealthEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skills_root": self.skills_root,
            "health_score": self.health_score,
            "total_skills": self.total_skills,
            "healthy_count": self.healthy_count,
            "warn_count": self.warn_count,
            "tampered_count": self.tampered_count,
            "compromised_count": self.compromised_count,
            "manifest_sealed": self.manifest_sealed,
            "quarantined_count": self.quarantined_count,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass(slots=True)
class HealResult:
    ok: bool
    name: str
    actions: list[str] = field(default_factory=list)
    new_sha256: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_skill_files(root: Path) -> list[tuple[str, Path]]:
    if not root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or not child.is_dir() or child.is_symlink():
            continue
        sm = child / "SKILL.md"
        if sm.is_file() and not sm.is_symlink():
            found.append((child.name, sm))
    return found


def _read_manifest(root: Path) -> dict[str, str]:
    mf = root / MANIFEST_FILENAME
    if not mf.is_file() or mf.is_symlink():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        digests = data.get("digests")
        return {str(k): str(v) for k, v in digests.items()} if isinstance(digests, dict) else {}
    except (OSError, ValueError):
        return {}


def seal_manifest(root: Path | None = None) -> dict[str, Any]:
    """Seal SHA-256 baselines for every clean skill under `root` into `.immune-manifest.json`."""
    target = root or default_skills_dir()
    target.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    skipped_danger: list[str] = []
    for name, sm in _iter_skill_files(target):
        raw = sm.read_text(encoding="utf-8")
        findings = scan_skill(raw)
        if any(f.verdict == "danger" for f in findings):
            skipped_danger.append(name)
            continue
        digests[name] = _sha256_text(raw)
    payload = {
        "schema_version": "milyonus.immune.manifest.v1",
        "sealed_at": round(time.time(), 3),
        "digests": digests,
    }
    mf = target / MANIFEST_FILENAME
    mf.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(mf, 0o600)
    return {
        "manifest_path": str(mf),
        "sealed_count": len(digests),
        "skipped_compromised": skipped_danger,
        "digests": digests,
    }


def scan_skills_health(root: Path | None = None) -> ImmuneScanReport:
    """Audit all installed skills for tampering, RCE/injection drift, leaks, and schema rot."""
    target = root or default_skills_dir()
    baseline = _read_manifest(target)
    qdir = target / QUARANTINE_DIRNAME
    q_count = sum(1 for p in qdir.iterdir() if p.is_dir()) if qdir.is_dir() else 0

    entries: list[SkillHealthEntry] = []
    seen_meta_names: dict[str, str] = {}

    for folder_name, sm in _iter_skill_files(target):
        raw = sm.read_text(encoding="utf-8")
        digest = _sha256_text(raw)
        expected = baseline.get(folder_name)
        issues: list[str] = []
        status = "healthy"
        healable = False

        # 1. Security scan (danger -> compromised, never healable if active RCE).
        findings = scan_skill(raw)
        danger = [f for f in findings if f.verdict == "danger"]
        caution = [f for f in findings if f.verdict == "caution"]
        if danger:
            status = "compromised"
            for f in danger:
                issues.append(f"danger:{f.signal} ({f.detail})")
        elif caution:
            status = "warn"
            for f in caution:
                issues.append(f"caution:{f.signal}")

        # 2. Tamper drift check against sealed baseline.
        if expected is not None and expected != digest:
            issues.append(f"hash_drift (expected {expected[:12]}…, got {digest[:12]}…)")
            if status != "compromised":
                status = "tampered"

        # 3. Secret leakage check.
        if redact(raw) != raw:
            issues.append("secret_literal_detected")
            healable = True
            if status == "healthy":
                status = "warn"

        # 4. Frontmatter parse & name collision check.
        try:
            parsed = parse_skill_md(raw, sm.parent)
            if parsed.meta.name in seen_meta_names:
                issues.append(f"duplicate_name_collision:{parsed.meta.name}")
                if status == "healthy":
                    status = "warn"
            seen_meta_names[parsed.meta.name] = folder_name
        except SkillParseError as exc:
            issues.append(f"frontmatter_error:{exc}")
            healable = True
            if status == "healthy":
                status = "warn"

        if status == "compromised":
            healable = False

        entries.append(
            SkillHealthEntry(
                name=folder_name,
                path=str(sm),
                status=status,
                sha256=digest,
                baseline_sha256=expected,
                issues=issues,
                healable=healable,
            )
        )

    total = len(entries)
    healthy = sum(1 for e in entries if e.status == "healthy")
    warn = sum(1 for e in entries if e.status == "warn")
    tampered = sum(1 for e in entries if e.status == "tampered")
    compromised = sum(1 for e in entries if e.status == "compromised")

    if total == 0:
        score = 100
    else:
        raw_score = (healthy * 100 + warn * 70 + tampered * 35 + compromised * 0) / total
        score = int(round(max(0.0, min(100.0, raw_score))))

    return ImmuneScanReport(
        skills_root=str(target),
        health_score=score,
        total_skills=total,
        healthy_count=healthy,
        warn_count=warn,
        tampered_count=tampered,
        compromised_count=compromised,
        manifest_sealed=bool(baseline),
        quarantined_count=q_count,
        entries=entries,
    )


def quarantine_skill(
    name: str,
    *,
    root: Path | None = None,
    reason: str = "immune_quarantine",
) -> dict[str, Any]:
    """Atomically isolate a compromised/tampered skill directory into `.quarantine/`."""
    target = root or default_skills_dir()
    if "/" in name or "\\" in name or ".." in name or name.startswith("."):
        raise ValueError("invalid skill name")
    src = target / name
    if not src.is_dir() or src.is_symlink():
        raise FileNotFoundError(f"skill not found: {name}")
    qroot = target / QUARANTINE_DIRNAME
    qroot.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = int(time.time())
    dest = qroot / f"{name}-{stamp}"
    shutil.move(str(src), str(dest))
    incident = {
        "skill": name,
        "quarantined_at": stamp,
        "reason": reason,
        "quarantine_path": str(dest),
    }
    (dest / "INCIDENT.json").write_text(json.dumps(incident, indent=2), encoding="utf-8")
    return incident


def heal_skill(
    name: str,
    *,
    root: Path | None = None,
    reseal: bool = True,
) -> HealResult:
    """Auto-heal broken frontmatter & accidental secret leaks; fail-closed on RCE/danger."""
    target = root or default_skills_dir()
    if "/" in name or "\\" in name or ".." in name or name.startswith("."):
        return HealResult(ok=False, name=name, message="invalid skill name")
    sm = target / name / "SKILL.md"
    if not sm.is_file() or sm.is_symlink():
        return HealResult(ok=False, name=name, message=f"skill not found: {name}")

    raw = sm.read_text(encoding="utf-8")
    actions: list[str] = []

    # 1. Redact accidental secret literals (and strip adjacent leaked secret labels).
    import re

    cleaned = redact(raw)
    if cleaned != raw:
        cleaned = re.sub(
            r"\b(?:api[_-]?key|secret|token|password|credential)\s*[:=]\s*(\[REDACTED[^\]]*\])",
            r"\1",
            cleaned,
            flags=re.IGNORECASE,
        )
        actions.append("redacted_secret_literals")

    # 2. Fail closed if danger-level RCE/exfil signals remain.
    findings = scan_skill(cleaned)
    danger = [f for f in findings if f.verdict == "danger"]
    if danger:
        sigs = ", ".join(f.signal for f in danger)
        return HealResult(
            ok=False,
            name=name,
            actions=actions,
            message=f"refused auto-heal: danger findings remain ({sigs}) — quarantine instead",
        )

    # 3. Repair missing/broken YAML frontmatter cleanly.
    try:
        parse_skill_md(cleaned, sm.parent)
        final_text = cleaned
    except SkillParseError:
        body_text = cleaned
        if body_text.startswith("---"):
            parts = body_text.split("---", 2)
            body_text = parts[-1].strip()
        meta = SkillMeta(
            name=name,
            description=f"Auto-healed skill '{name}'",
            version="1.0.0",
            tags=["healed"],
            category="general",
            provenance="immune-healed",
        )
        final_text = render_skill_md(meta, body_text or f"Procedure for {name}.")
        actions.append("repaired_frontmatter")

    if final_text != raw:
        sm.write_text(final_text, encoding="utf-8")
    else:
        actions.append("verified_already_clean")

    new_digest = _sha256_text(final_text)
    if reseal:
        seal_manifest(target)
        actions.append("resealed_manifest")

    return HealResult(
        ok=True,
        name=name,
        actions=actions,
        new_sha256=new_digest,
        message=f"healed skill '{name}' ({', '.join(actions)})",
    )
