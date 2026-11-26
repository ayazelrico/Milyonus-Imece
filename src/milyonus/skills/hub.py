"""External skill hub sources and upstream drift checks (PLAN §5.3).

Supported source locators:
  - github:<owner>/<repo>[@<ref>][:<path>]   -> raw.githubusercontent.com
  - well-known:<host>/<skill-name>           -> https://<host>/.well-known/skills/<name>/SKILL.md
  - https://...                              -> direct SKILL.md URL

Security guarantees:
  - Every URL (including every redirect hop) passes `security.ssrf.check_url`
    (fail-closed, blocks private/loopback/metadata hosts).
  - Downloaded SKILL.md size is bounded (<= 256 KB) and parsed strictly.
  - Every hub skill runs through `skills.scanner.scan_skill`: a `danger`
    verdict is NEVER installable even with `force=True`.
  - Installed hub skills record `.source.json` (`source_id`, `url`, `sha256`,
    `installed_at`) so `milyonus skills check` detects upstream content drift.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx

from milyonus.config.paths import skills_dir
from milyonus.security.ssrf import check_url
from milyonus.skills.manage import ManageResult, SkillManager
from milyonus.skills.model import SkillParseError, parse_skill_md
from milyonus.skills.scanner import may_install, scan_skill, worst_verdict

_MAX_SKILL_BYTES = 256_000
_MAX_REDIRECTS = 5
_GH_RE = re.compile(
    r"^github:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
    r"(?:@(?P<ref>[A-Za-z0-9_./-]+))?(?::(?P<path>[A-Za-z0-9_./-]+))?$"
)
_WK_RE = re.compile(
    r"^well-known:(?P<host>[A-Za-z0-9.-]+(?::\d+)?)/(?P<name>[A-Za-z0-9][A-Za-z0-9_-]{0,63})$"
)

FetchFn = Callable[[str], Awaitable[str]]


@dataclass(slots=True)
class DriftReport:
    name: str
    source_id: str
    status: str  # "up_to_date" | "drifted" | "error"
    local_sha256: str
    remote_sha256: str | None = None
    detail: str = ""


def resolve_source_url(source: str) -> tuple[str, str]:
    """Resolve a hub locator into (canonical_source_id, https_url)."""
    src = source.strip()
    if m := _GH_RE.match(src):
        owner = m.group("owner")
        repo = m.group("repo")
        ref = m.group("ref") or "main"
        raw_path = (m.group("path") or "SKILL.md").lstrip("/")
        if ".." in raw_path.split("/"):
            raise ValueError("path traversal in github skill path")
        if not raw_path.endswith("SKILL.md"):
            raw_path = raw_path.rstrip("/") + "/SKILL.md"
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{raw_path}"
        return f"github:{owner}/{repo}@{ref}:{raw_path}", url

    if m := _WK_RE.match(src):
        host = m.group("host")
        name = m.group("name")
        url = f"https://{host}/.well-known/skills/{name}/SKILL.md"
        return f"well-known:{host}/{name}", url

    if src.startswith("https://") or src.startswith("http://"):
        return src, src

    raise ValueError(
        "unsupported skill source — use github:owner/repo[@ref][:path], "
        "well-known:host/name, or an https:// URL"
    )


async def fetch_skill_text(url: str) -> str:
    """Fetch a SKILL.md over HTTP(S), re-validating SSRF on every redirect hop."""
    current = check_url(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            resp = await client.get(
                current,
                headers={"User-Agent": "milyonus-agent/5.5.0"},
            )
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise ValueError("redirect without Location header")
                current = check_url(urljoin(current, loc))
                continue
            resp.raise_for_status()
            raw = resp.content
            if len(raw) > _MAX_SKILL_BYTES:
                raise ValueError(f"skill exceeds {_MAX_SKILL_BYTES} byte limit")
            return raw.decode("utf-8")
    raise ValueError("too many redirects")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def install_from_hub(
    source: str,
    *,
    live_dir: Path | None = None,
    force: bool = False,
    fetch: FetchFn | None = None,
) -> ManageResult:
    """Download, security-scan, and install a skill from a hub source."""
    try:
        source_id, url = resolve_source_url(source)
        fetcher = fetch or fetch_skill_text
        text = await fetcher(url)
    except Exception as exc:  # noqa: BLE001 - report clean error to caller/CLI
        return ManageResult(False, f"fetch failed: {exc}")

    if len(text.encode("utf-8")) > _MAX_SKILL_BYTES:
        return ManageResult(False, f"skill exceeds {_MAX_SKILL_BYTES} byte limit")

    # 1. Security scan BEFORE parsing/installing; danger cannot be forced.
    findings = scan_skill(text)
    if not may_install(findings, force=force):
        verdict = worst_verdict(findings)
        sigs = ", ".join(f.signal for f in findings)
        return ManageResult(False, f"security scan blocked ({verdict}): {sigs}")

    # 2. Strict frontmatter validation.
    try:
        parsed = parse_skill_md(text, Path("<hub>"))
    except SkillParseError as exc:
        return ManageResult(False, f"invalid SKILL.md: {exc}")

    target_root = live_dir or skills_dir()
    manager = SkillManager(live_dir=target_root)
    try:
        target = manager._path(target_root, parsed.meta.name)  # noqa: SLF001
    except ValueError as exc:
        return ManageResult(False, str(exc), parsed.meta.name)

    # Stamp provenance as hub while preserving exact upstream hash in .source.json.
    parsed.meta.provenance = "hub"
    upstream_hash = _sha256(text)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(text, encoding="utf-8")
    (target / ".source.json").write_text(
        json.dumps(
            {
                "source_id": source_id,
                "url": url,
                "sha256": upstream_hash,
                "installed_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return ManageResult(
        True,
        f"installed hub skill '{parsed.meta.name}' from {source_id} ({upstream_hash[:12]})",
        parsed.meta.name,
    )


async def check_drift(
    *,
    live_dir: Path | None = None,
    fetch: FetchFn | None = None,
) -> list[DriftReport]:
    """Check every hub-installed skill against its upstream content hash."""
    root = live_dir or skills_dir()
    if not root.exists():
        return []
    fetcher = fetch or fetch_skill_text
    reports: list[DriftReport] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        meta_path = entry / ".source.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            source_id = str(meta["source_id"])
            url = str(meta["url"])
            local_hash = str(meta["sha256"])
        except (OSError, ValueError, KeyError) as exc:
            reports.append(
                DriftReport(
                    name=entry.name,
                    source_id="(corrupt .source.json)",
                    status="error",
                    local_sha256="",
                    detail=str(exc),
                )
            )
            continue
        try:
            remote_text = await fetcher(url)
            remote_hash = _sha256(remote_text)
        except Exception as exc:  # noqa: BLE001
            reports.append(
                DriftReport(
                    name=entry.name,
                    source_id=source_id,
                    status="error",
                    local_sha256=local_hash,
                    detail=str(exc),
                )
            )
            continue
        status = "up_to_date" if remote_hash == local_hash else "drifted"
        reports.append(
            DriftReport(
                name=entry.name,
                source_id=source_id,
                status=status,
                local_sha256=local_hash,
                remote_sha256=remote_hash,
            )
        )
    return reports
