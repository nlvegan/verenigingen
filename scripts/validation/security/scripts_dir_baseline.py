#!/usr/bin/env python3
"""Shared shrink-only baseline helper for the two API security gates
(api_security_validator.py, insecure_api_detector.py) widening their scan root
onto `scripts/` (#1069).

Why this exists: `verenigingen/api/` has been held to a zero-tolerance bar by
both gates since #972 -- any FAIL there always blocks. `scripts/` never had a
bar at all until #1069 added it as a second scan root, and doing so surfaced
39 (api_security_validator) / 60 (insecure_api_detector) pre-existing findings
across debug/admin/deployment/migration/performance scripts that have never
been triaged for a real security decision (see #1075 for the full breakdown
and remediation backlog).

Fixing all of those with a considered decorator choice is not something a
scan-root PR should do by itself -- each is a judgment call about who should
be allowed to call it. Rather than leave the new scan root failing every
push that happens to touch verenigingen/api/ (the pre-push hook always
full-scans, `pass_filenames: false`), known findings under `scripts/` are
baselined here: tracked, visible in every run's output, but not blocking.
`verenigingen/api/` is NEVER read from this baseline -- it is untouched by
this module and stays zero-tolerance.

This baseline can only SHRINK safely: a finding disappearing (fixed, decorator
added, function removed) does not need this file touched. A genuinely NEW
finding under `scripts/` that is not already in the baseline is NOT absorbed
-- it fails the gate, same as it always would have under `verenigingen/api/`.
Regenerate with each validator's own `--update-baseline` flag after triaging
new debt into #1075 (or a follow-up).
"""
from pathlib import Path
from typing import Iterable, Set, Tuple

SCRIPTS_PREFIX = "scripts/"

BaselineKey = Tuple[str, str, str]  # (file_path, function_name, check_name)


def load_baseline(path: Path) -> Set[BaselineKey]:
    """Read a baseline file of `file::function::check_name` lines."""
    if not path.exists():
        return set()

    keys: Set[BaselineKey] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("::", 2)
        if len(parts) != 3:
            continue
        keys.add((parts[0], parts[1], parts[2]))
    return keys


def write_baseline(path: Path, keys: Iterable[BaselineKey], header: str) -> None:
    """Write a sorted, deduplicated baseline file with an explanatory header."""
    lines = [header, ""]
    lines.extend(f"{file_path}::{function_name}::{check_name}" for file_path, function_name, check_name in sorted(set(keys)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_scripts_path(file_path: str) -> bool:
    """True only for the `scripts/` scan root -- never verenigingen/api/."""
    return file_path.startswith(SCRIPTS_PREFIX)


def partition_by_baseline(
    findings: Iterable[Tuple[str, str, str]], baseline: Set[BaselineKey]
) -> Tuple[list, list]:
    """Split (file_path, function_name, check_name) findings into
    (blocking, known) -- `verenigingen/api/` findings are always blocking
    (baseline never applies there); `scripts/` findings are blocking only if
    their key is not already in the baseline."""
    blocking = []
    known = []
    for key in findings:
        file_path = key[0]
        if is_scripts_path(file_path) and key in baseline:
            known.append(key)
        else:
            blocking.append(key)
    return blocking, known
