"""Shared machinery for the `--check-shrink --base-tree` relocation check (#1858).

A ratchet's shrink explainer looks in the HEAD tree for a vanished baseline entry's own path
and function name. Code that MOVED (under tests/, outside SCAN_ROOTS, into archived/, behind a
pragma, or into a renamed function) leaves nothing there and reads as "deleted: explained".
With a checkout of the base commit the question can be asked of the code instead: per site text,
did the number of COUNTED sites drop between base and head while the number of UNCOUNTED sites
rose by at least as much? Then the site was hidden, not fixed.

What differs per validator is passed in, never copied: its SCAN_ROOTS and extra path exclusions
(`counted_by_path`), how a file's findings are extracted (the `extract` callback), and how a
report entry is built (`make_entry`, because each validator has its own `UnexplainedShrink`).
Used by db_clock_date_window_validator, log_error_arg_order_validator and error_swallow_validator.
"""

from __future__ import annotations

import filecmp
import os
from collections import Counter
from pathlib import Path

# Directories the walk never enters. Unlike each validator's `_iter_py` it does NOT skip
# `archived`: a site moved into `archived/` left the count without being fixed, so the head
# census has to be able to see it there.
CENSUS_SKIP_DIRS = {"node_modules", ".git", "__pycache__", "worktrees", ".claude"}

RELOCATED_HINT = (
    "If this is a genuine fix whose regression test copies the exact buggy text, reword the\n"
    "      test's copy or mark it with the validator's pragma; the match is on site text."
)

NO_BASE_TREE_SUCCESS = (
    "No unexplained shrink visible from the head tree alone. Code that MOVED or was renamed was NOT\n"
    "checked: pass --base-tree <checkout of the base commit> for that."
)


def counted_by_path(rel: str, scan_roots, excluded_names=()) -> bool:
    """Would a validator's `_counts` look at a file with this repo-relative path at all?

    Mirrors each validator's `_iter_py` (under `scan_roots`, `archived` skipped) plus `_counts`'
    own exclusions: tests, and any basename in `excluded_names`. Each validator pins its
    wrapper against its own `_counts` with `test_counted_by_path_agrees_with_counts`.
    """
    parts = rel.split("/")
    return (
        len(parts) > 1
        and parts[0] in scan_roots
        and not any(p in CENSUS_SKIP_DIRS or p == "archived" for p in parts[:-1])
        and "tests" not in parts[:-1]
        and not parts[-1].startswith("test_")
        and parts[-1] not in excluded_names
    )


def changed_py(base_root: Path, head_root: Path) -> set[str]:
    """Repo-relative .py paths whose bytes differ between the two trees (or exist in only one).

    A file identical in both trees adds the same sites to base and head, so it cancels out of
    every base-vs-head comparison; skipping it keeps the walk to a few seconds.
    """

    def listing(root: Path) -> dict[str, Path]:
        found = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in CENSUS_SKIP_DIRS)
            for fn in filenames:
                if fn.endswith(".py"):
                    path = Path(dirpath) / fn
                    found[path.relative_to(root).as_posix()] = path
        return found

    base, head = listing(base_root), listing(head_root)
    return {
        rel
        for rel in base.keys() | head.keys()
        if rel not in base or rel not in head or not filecmp.cmp(base[rel], head[rel], shallow=False)
    }


def census(root: Path, rels: set[str], extract) -> list[tuple[str, str, int, str, bool]]:
    """Every finding site under `root`: (rel, qualname, lineno, text, counted).

    `extract(path, rel)` is the validator's own: it returns `(qualname, lineno, text, counted)`
    for one file, `counted` being what its `_counts` would do with the site (path scanned, no
    pragma). Looks at `rels` anywhere in the checkout, not only SCAN_ROOTS, so a site that left
    the scan roots is still seen.
    """
    sites = []
    seen: set[Path] = set()
    for rel in sorted(rels):
        path = root / rel
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        for qualname, lineno, text, counted in extract(path, rel):
            sites.append((rel, qualname, lineno, text, counted))
    return sites


def relocated_sites(baseline, base_root: Path, head_root: Path, extract, make_entry) -> list:
    """Baselined sites whose text left the COUNT without leaving the code.

    A site still counted somewhere (a move inside SCAN_ROOTS, a rename) is still ratcheted, and
    one that no longer appears at all was fixed or deleted; neither is reported. Matching on
    text is the simplest rule that survives a move or rename -- its limit is that an unrelated
    new uncounted site with identical text can pair with a genuine fix (see RELOCATED_HINT).
    `make_entry(key, lineno, text)` builds the validator's own report row, reason "relocated".
    """
    changed = changed_py(base_root, head_root)
    base_sites = census(base_root, changed, extract)
    head_sites = census(head_root, changed, extract)

    def tally(sites, counted):
        return Counter(text for _r, _q, _l, text, c in sites if c is counted)

    lost = tally(base_sites, True) - tally(head_sites, True)
    hidden = tally(head_sites, False) - tally(base_sites, False)
    budget = {text: min(n, hidden[text]) for text, n in lost.items() if hidden[text] > 0}

    out = []
    for rel, qualname, lineno, text, counted in sorted(base_sites):
        key = f"{rel}::{qualname}"
        if counted and key in baseline and budget.get(text, 0) > 0:
            budget[text] -= 1
            out.append(make_entry(key, lineno, text))
    return out


def merge_relocated(found: list, relocated: list) -> list:
    """Add `relocated` entries, skipping the ones the head-tree check already reported.

    A key already reported N times by the head-tree check has N of its relocated entries
    swallowed, so one lost site is never reported twice.
    """
    already = Counter(u.key for u in found)
    merged = list(found)
    for u in relocated:
        if already[u.key] > 0:
            already[u.key] -= 1
            continue
        merged.append(u)
    return merged
