"""Bounded publication journals and explicit recovery of interrupted renames.

Catalog contents are local operator trust inputs, not signed attestations.
Recovery never installs the candidate or overwrites an existing live version.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter
from pathlib import Path

from milyonus.skills.repair import (
    MAX_RECEIPT_BYTES,
    _read_file,
    _refuse_revoked_oracles,
    _repair_catalog_lock,
)

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_HASH = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")


def tree_digest(parent: int, name: str) -> str:
    """Hash bytes, paths, modes and symlink targets without following links."""
    entries = []
    total = 0

    def walk(directory, prefix, depth):
        nonlocal total
        if depth > 16:
            raise ValueError("skill tree exceeds recovery depth limit")
        entries.append((prefix, "directory", stat.S_IMODE(os.fstat(directory).st_mode)))
        with os.scandir(directory) as scan:
            names = []
            for entry in scan:
                names.append(entry.name)
                if len(names) + len(entries) > 1024:
                    raise ValueError("skill tree exceeds recovery entry limit")
            names.sort()
        for entry in names:
            if len(entries) >= 1024:
                raise ValueError("skill tree exceeds recovery entry limit")
            path = f"{prefix}/{entry}"
            info = os.stat(entry, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                entries.append((path, "symlink", os.readlink(entry, dir_fd=directory)))
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(entry, _DIR, dir_fd=directory)
                try:
                    walk(child, path, depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, "rb") as stream:
                    current = os.fstat(stream.fileno())
                    if not stat.S_ISREG(current.st_mode):
                        raise ValueError("skill tree contains a non-regular file")
                    digest = hashlib.sha256()
                    while chunk := stream.read(65536):
                        total += len(chunk)
                        if total > 64 * 1024 * 1024:
                            raise ValueError("skill tree exceeds recovery byte limit")
                        digest.update(chunk)
                entries.append((path, "file", stat.S_IMODE(current.st_mode), digest.hexdigest()))
            else:
                raise ValueError("skill tree contains an unsupported entry")

    root = os.open(name, _DIR, dir_fd=parent)
    try:
        walk(root, "", 0)
    finally:
        os.close(root)
    return hashlib.sha256(json.dumps(entries, ensure_ascii=True).encode()).hexdigest()


def write_journal(catalog: int, transaction: Path, name: str, previous: str | None) -> None:
    directory = os.open(transaction.name, _DIR, dir_fd=catalog)
    try:
        record = {
            "schema_version": 1,
            "name": name,
            "previous": previous,
            "candidate": tree_digest(directory, "new"),
        }
        # Flush candidate files and their directory before permitting a rename.
        new = os.open("new", _DIR, dir_fd=directory)
        try:
            for filename in os.listdir(new):
                fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=new)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.fsync(new)
        finally:
            os.close(new)
        fd = os.open(
            "publication.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
        os.fsync(catalog)
    finally:
        os.close(directory)


def sync_renames(catalog: int, transaction: Path) -> None:
    directory = os.open(transaction.name, _DIR, dir_fd=catalog)
    try:
        os.fsync(directory)
        os.fsync(catalog)
    finally:
        os.close(directory)


def _record(directory: int) -> dict:
    record = json.loads(_read_file(directory, "publication.json", 4096))
    if (
        not isinstance(record, dict)
        or set(record) != {"schema_version", "name", "previous", "candidate"}
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or not isinstance(record["name"], str)
        or not _NAME.fullmatch(record["name"])
        or not isinstance(record["candidate"], str)
        or not _HASH.fullmatch(record["candidate"])
        or (
            record["previous"] is not None
            and (not isinstance(record["previous"], str) or not _HASH.fullmatch(record["previous"]))
        )
    ):
        raise ValueError("invalid publication journal")
    return record


def _check_oracles(catalog: int, transaction: int) -> None:
    previous = os.open("previous", _DIR, dir_fd=transaction)
    try:
        try:
            raw = _read_file(previous, "replays.json", MAX_RECEIPT_BYTES)
        except FileNotFoundError:
            return
        receipt = json.loads(raw)
        tasks = receipt.get("tasks") if isinstance(receipt, dict) else None
        if (
            not isinstance(tasks, dict)
            or not tasks
            or any(
                not isinstance(value, str) or not _HASH.fullmatch(value) for value in tasks.values()
            )
        ):
            raise ValueError("invalid previous repair receipt")
        _refuse_revoked_oracles(catalog, tasks.values())
    finally:
        os.close(previous)


def recover_publications(root: Path, *, apply: bool = False) -> list[dict]:
    """Inspect by default; explicitly restore only hash-matched missing targets.

    Keep journals and candidates for inspection. Unknown legacy transactions,
    conflicting targets, ambiguity and revoked receipts always remain untouched.
    """
    rows = []
    with _repair_catalog_lock(root) as catalog:
        for name in sorted(os.listdir(catalog)):
            if not name.startswith(".publish-"):
                continue
            row = {"transaction": name, "name": None, "status": "unrecognized", "restored": False}
            rows.append(row)
            directory = None
            try:
                directory = os.open(name, _DIR, dir_fd=catalog)
                record = _record(directory)
                row["name"] = record["name"]
                try:
                    os.stat(record["name"], dir_fd=catalog, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    row["status"] = "live_present"
                    continue
                if record["previous"] is None:
                    row["status"] = "no_previous"
                    continue
                if (
                    tree_digest(directory, "previous") != record["previous"]
                    or tree_digest(directory, "new") != record["candidate"]
                ):
                    raise ValueError("publication tree hash mismatch")
                _check_oracles(catalog, directory)
                row["status"] = "recoverable"
            except (OSError, ValueError, RecursionError) as exc:
                row["error"] = str(exc)
            finally:
                if directory is not None:
                    os.close(directory)
        counts = Counter(row["name"] for row in rows if row["name"] is not None)
        for row in rows:
            if row["status"] != "recoverable":
                continue
            if counts[row["name"]] > 1:
                row["status"] = "ambiguous"
                continue
            if apply:
                directory = os.open(row["transaction"], _DIR, dir_fd=catalog)
                try:
                    os.rename("previous", row["name"], src_dir_fd=directory, dst_dir_fd=catalog)
                    row.update(status="restored", restored=True)
                    os.fsync(directory)
                    os.fsync(catalog)
                except OSError as exc:
                    row.update(status="recovery_failed", error=str(exc))
                finally:
                    os.close(directory)
    return rows
