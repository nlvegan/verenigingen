#!/usr/bin/env python3
"""Ratchet on private module-level helpers defined in more than one file.

A copy-pasted helper is where a fix goes to die. When the same helper exists in
eight files, fixing it in one -- with a comment explaining exactly why the fix was
needed -- leaves seven carrying the bug, and nothing says so. Measured on
2026-08-19, that shape produced four separate defects in a single day:

* `_persist_eur_company` resolved a company by CURRENCY rather than by name. Two
  copies were fixed, with a docstring recording the reason; a third was missed and
  ran a Dutch/EUR suite inside whatever EUR company happened to exist (#394). There
  are EIGHT copies.
* `TEST-Payment-Integration-Company` had two owners; the fix for that (#387) chose a
  name a second file had already owned for two months (#392).
* A GL query scoped by company existed 40 lines above its unscoped sibling, comment
  and all. The sibling returned 8 rows against an expected 2, on three branches
  (#399).

This does not detect clones -- it counts NAMES. Two same-named helpers may be
unrelated (there are 13 `_payment` helpers whose bodies share 6% similarity). That
is fine for a ratchet: the value is that adding a NINTH `_persist_eur_company`
fails, whatever the existing eight are. Use `--report` for the similarity view when
deciding what to consolidate.

Restricted to PRIVATE (leading-underscore) module-level functions on purpose. Frappe
requires `execute` in every report, `get_context` in every page, `run_tests` in every
suite -- counting those reports 273 names whose top four are framework contract, not
duplication. The underscore restriction is what makes this 71 real names.

Usage:
    python scripts/validation/duplicate_helper_validator.py              # ratchet check
    python scripts/validation/duplicate_helper_validator.py --report     # clone families
    python scripts/validation/duplicate_helper_validator.py --update-baseline
"""

import argparse
import ast
import difflib
import os
import sys
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path(__file__).with_name("duplicate_helper_baseline.txt")
SCAN_ROOT = "verenigingen"

# Same set as error_swallow_validator.py and test_quality_enforcer.py. Without it the
# scan counts agent worktrees under .claude/, which is how a sibling validator came to
# walk 12,574 files instead of 1,398.
PRUNE_DIRS = {"node_modules", ".git", "__pycache__", "worktrees", ".claude", "archived"}

# A pair at or above this similarity is treated as a genuine clone in --report.
CLONE_RATIO = 0.90


def _iter_python_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _module_level_helpers(path: str) -> List[Tuple[str, str]]:
    """(name, source) for each private module-level function in `path`."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        # Parsing someone else's file re-emits their SyntaxWarnings (an invalid
        # escape in a non-raw string, say). Their business, not a finding.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return []

    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_") or node.name.startswith("__"):
            continue
        try:
            out.append((node.name, ast.unparse(node)))
        except Exception:
            out.append((node.name, ""))
    return out


def _by_name(root: str) -> Dict[str, List[Tuple[str, str]]]:
    found: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for path in _iter_python_files(root):
        seen_here = set()
        for name, body in _module_level_helpers(path):
            # Count FILES, not definitions: a helper redefined inside one module is a
            # different (and more obvious) problem.
            if name in seen_here:
                continue
            seen_here.add(name)
            found[name].append((path, body))
    return found


def census(root: str = None) -> Dict[str, int]:
    """helper name -> number of files defining it, for names in more than one."""
    root = root or str(REPO_ROOT / SCAN_ROOT)
    return {name: len(v) for name, v in _by_name(root).items() if len(v) > 1}


def clone_families(root: str = None):
    """(clone_pairs, files, exact_pairs, best_ratio, name, dirs), most-cloned first.

    Only for --report. The ratchet itself never looks at similarity -- comparing
    every pair is quadratic in the number of copies and would make the gate slow
    for no gain.
    """
    root = root or str(REPO_ROOT / SCAN_ROOT)
    families = []
    for name, copies in _by_name(root).items():
        if len(copies) < 2:
            continue
        exact = clones = 0
        best = 0.0
        for i in range(len(copies)):
            for j in range(i + 1, len(copies)):
                a, b = copies[i][1], copies[j][1]
                if a and a == b:
                    exact += 1
                    best = 1.0
                    continue
                ratio = difflib.SequenceMatcher(None, a, b).ratio()
                best = max(best, ratio)
                if ratio >= CLONE_RATIO:
                    clones += 1
        if exact + clones:
            dirs = sorted({os.path.dirname(p) for p, _ in copies})
            families.append((exact + clones, len(copies), exact, round(best, 2), name, dirs))
    families.sort(key=lambda f: (-f[0], -f[1]))
    return families


def regressions(counts: Dict[str, int], baseline: Dict[str, int]) -> Dict[str, int]:
    """Names that are newly duplicated, or that gained a copy.

    Upward only: consolidating is the entire point of this gate and must never be
    what fails it.
    """
    return {k: v for k, v in counts.items() if v > baseline.get(k, 0)}


def load_baseline(path: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, count = line.rpartition("::")
        if name and count.isdigit():
            out[name] = int(count)
    return out


def write_baseline(path: Path, counts: Dict[str, int]) -> None:
    header = [
        "# Private module-level helpers defined in more than one file -- the ratchet",
        "# baseline for scripts/validation/duplicate_helper_validator.py. Format:",
        "#     <helper name>::<number of files defining it>",
        "#",
        "# A change fails only if it duplicates a helper that was not duplicated before,",
        "# or adds a copy of one already listed. Consolidating never fails the gate.",
        "#",
        "# This file should only ever SHRINK. It is a to-do list, not a permission slip:",
        "# each line is a place where a future fix can be applied to one copy and missed",
        "# in the others -- which happened four times on 2026-08-19 alone (#392, #394,",
        "# #399, and a merge collision between two branches fixing the same test).",
        "#",
        "# A high count here does NOT mean the copies are clones; same name, unrelated",
        "# bodies is common (13 `_payment` helpers share 6% similarity). Run with",
        "# --report for the similarity view before consolidating anything.",
        "",
    ]
    body = [f"{name}::{count}" for name, count in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument(
        "--report", action="store_true", help="show clone families instead of ratcheting"
    )
    args = parser.parse_args()

    if args.report:
        families = clone_families()
        print(f"{'pairs':>5} {'files':>5} {'exact':>5} {'best':>5}  helper")
        for pairs, files, exact, best, name, dirs in families:
            print(f"{pairs:>5} {files:>5} {exact:>5} {best:>5}  {name}")
            for d in dirs[:4]:
                print(f"{'':>28}{d}/")
        print(f"\n{len(families)} clone families")
        return 0

    counts = census()

    if args.update_baseline:
        write_baseline(args.baseline, counts)
        print(
            f"baseline written: {len(counts)} duplicated helpers, "
            f"{sum(counts.values()) - len(counts)} redundant copies"
        )
        return 0

    baseline = load_baseline(args.baseline)
    new = regressions(counts, baseline)
    if new:
        print("\n🔴 NEWLY DUPLICATED HELPERS (not in the baseline):")
        print("=" * 60)
        for name, count in sorted(new.items()):
            known = baseline.get(name, 0)
            where = [p for p, _ in _by_name(str(REPO_ROOT / SCAN_ROOT))[name]]
            print(f"\n{name}  (now in {count} files, baseline {known})")
            for p in sorted(where):
                print(f"  {p}")
        print(
            "\nA copy-pasted helper is where a fix goes to die: the next person fixes one\n"
            "of these and the others keep the bug, silently. Import the existing one, or\n"
            "move it to a shared module.\n\n"
            "If the duplication is genuinely intended, record it:\n"
            "    python scripts/validation/duplicate_helper_validator.py --update-baseline"
        )
        return 1

    total = sum(baseline.values()) - len(baseline)
    print(f"✅ No newly duplicated helpers ({len(baseline)} known, {total} redundant copies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
