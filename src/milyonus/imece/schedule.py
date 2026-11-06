"""Explicit deterministic trial ordering, shared by execution and inspection."""

from collections.abc import Sequence


def trial_coordinates(task_ids: Sequence[str], repeats: int, *, order: str = "task-major"):
    ids = tuple(task_ids)
    if (
        type(repeats) is not int
        or repeats < 1
        or not ids
        or any(not isinstance(task, str) or not task for task in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("unique nonempty tasks and positive repeats required")
    if order == "task-major":
        return tuple((task, repeat) for task in ids for repeat in range(repeats))
    if order == "repeat-major":
        return tuple((task, repeat) for repeat in range(repeats) for task in ids)
    raise ValueError("trial order must be task-major or repeat-major")
