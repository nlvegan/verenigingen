#!/usr/bin/env python3
"""Shared bench-root resolution for scripts/validation/*.

Why this exists
----------------
Several validators need to find the frappe-bench root -- the directory
holding both ``apps/`` and ``sites/`` -- starting from wherever their own
file, or the checkout under validation, happens to live. Walking up the
filesystem from that starting point finds the bench when the checkout is
``<bench>/apps/<app>`` or a worktree under ``<bench>/.claude/worktrees/...``,
but a worktree created OUTSIDE the bench entirely -- routinely done under
``/tmp`` in this project -- has no bench ancestor at all, so the walk-up
finds nothing.

Before this module existed each caller handled that failure differently and
none of them handled it well:

* ``doctype_name_validator.py`` (#752) falls back to ``start.parent`` and then
  *refuses to run* once its self-check notices zero doctypes loaded -- loud,
  but with no override and a message that did not say what to do about it.
* ``child_table_creation_validator.py`` and
  ``framework/validation_suite_runner.py`` fall back to a directory with no
  ``apps/`` under it, ``DocTypeLoader`` silently loads zero doctypes, and the
  gate reports "no issues found" -- a silent false negative, and a worse
  failure mode than refusing.
* ``import_path_validator.py`` degrades to a search path missing every other
  app, which can make a valid cross-app import look unresolvable.

``git rev-parse --git-common-dir`` answers this regardless of where a linked
worktree lives on disk: it always points at the MAIN checkout's ``.git``
directory (a linked worktree's own ``.git`` is a file pointing back at it),
so walking up from *that* checkout's location finds the bench even when the
worktree being validated has no bench ancestor of its own. Measured 2026-09-02
from a worktree under ``/tmp``: the plain filesystem walk-up finds nothing,
``git rev-parse --git-common-dir`` resolves to
``.../frappe-bench/apps/verenigingen/.git``, and walking up from its parent
reaches ``/home/frappeuser/frappe-bench``, which has both ``apps/`` and
``sites/``.

This closes the "a bench exists somewhere, but not as an ancestor of this
checkout" case. It does NOT create a bench where none exists: the
Code Validation workflow (``.github/workflows/code-validation.yml``) checks
out this app standalone, with no ``apps/``/``sites/`` anywhere and no git
connection to one either, so ``child_table_creation_validator.py`` still
correctly loads zero doctypes there -- that job was never testing child-table
patterns, and this module does not change that.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

Marker = Callable[[Path], bool]


def has_apps_and_sites(candidate: Path) -> bool:
    """The default bench marker: a directory holding both ``apps/`` and ``sites/``."""
    return (candidate / "apps").is_dir() and (candidate / "sites").is_dir()


def _walk_up(start: Path, marker: Marker) -> Path | None:
    for candidate in (start, *start.parents):
        if marker(candidate):
            return candidate
    return None


def _git_common_dir(start: Path) -> Path | None:
    """The MAIN checkout's ``.git`` directory, or None if git can't answer.

    Works from a linked worktree at any location on disk, which a filesystem
    walk-up cannot: that needs a bench ancestor to find, and a worktree under
    ``/tmp`` has none.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output:
        return None
    git_dir = Path(output)
    if not git_dir.is_absolute():
        git_dir = start / git_dir
    return git_dir.resolve()


def find_bench_root(start: Path, marker: Marker = has_apps_and_sites) -> Path | None:
    """The frappe-bench root reachable from ``start``, or None.

    Tries a plain filesystem walk-up first -- cheap, no subprocess, and
    correct for the common in-bench-worktree case -- then falls back to
    resolving the main checkout via git and walking up from there, which is
    what a worktree outside the bench needs.

    ``marker`` lets a caller use a stricter bench signal than "has apps/ and
    sites/ directories" (``import_path_validator.py`` requires
    ``sites/common_site_config.json`` to actually exist); both walks use the
    same marker so the git fallback stays consistent with the plain one.
    """
    found = _walk_up(start, marker)
    if found is not None:
        return found

    git_dir = _git_common_dir(start)
    if git_dir is not None:
        # git_dir is `.../<main-checkout>/.git`; its parent is the checkout
        # itself (e.g. `<bench>/apps/verenigingen`), which DOES have a bench
        # ancestor even when `start` -- the worktree -- does not.
        found = _walk_up(git_dir.parent, marker)
        if found is not None:
            return found

    return None
