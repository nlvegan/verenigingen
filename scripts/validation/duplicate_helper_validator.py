#!/usr/bin/env python3
"""Ratchet on private helpers -- functions AND methods -- defined in more than one file.

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

Restricted to PRIVATE (leading-underscore) helpers on purpose. Frappe requires
`execute` in every report, `get_context` in every page, `run_tests` in every suite --
counting those reports 273 names whose top four are framework contract, not
duplication. The underscore restriction is what keeps this to real names.

METHODS COUNT, since 2026-08-21. Restricting the scan to module-level functions is
what let the same defect redden trunk twice: `_get_company_with_current_fy` existed in
three files -- one already fixed, with a comment naming the exact error string -- and
all three copies were METHODS, so the ratchet was blind to every one of them (#445).
The three Mollie/donation fixture helpers in #444 were methods too. That change takes
the census from 71 names / 190 definitions to 567 / 1948.

Usage:
    python scripts/validation/duplicate_helper_validator.py              # ratchet check
    python scripts/validation/duplicate_helper_validator.py --report     # clone families
    python scripts/validation/duplicate_helper_validator.py --drift      # the work-list
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


def _rel(path: str) -> str:
    """Repo-relative, so output is the same wherever the checkout lives."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_python_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _private_helpers(path: str) -> List[Tuple[str, str]]:
    """(name, source) for each private helper in `path`, module-level OR method.

    Methods count. Restricting this to module-level functions is what let the
    2026-08-21 red trunk happen twice: `_get_company_with_current_fy` existed in
    THREE files -- one of them already fixed, with a comment naming the exact error
    string -- and every copy was a METHOD, so the ratchet could not see any of them
    (#445). The same was true of the three Mollie/donation fixture helpers in #444.

    Only one nesting level down, and only inside a class. A closure defined inside a
    function is scoped to that function and cannot be the copy-paste hazard this
    ratchet exists for.
    """
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

    def _emit(node, out):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        # Dunders stay excluded: `__init__` in 400 classes is Python's contract,
        # not duplication -- the same reason `execute`/`get_context` are excluded.
        if not node.name.startswith("_") or node.name.startswith("__"):
            return
        try:
            out.append((node.name, ast.unparse(node)))
        except Exception:
            out.append((node.name, ""))

    out: List[Tuple[str, str]] = []
    for node in tree.body:
        _emit(node, out)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                _emit(child, out)
    return out



def _by_name(root: str) -> Dict[str, List[Tuple[str, str]]]:
    found: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for path in _iter_python_files(root):
        seen_here = set()
        for name, body in _private_helpers(path):
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
        worst = 1.0
        for i in range(len(copies)):
            for j in range(i + 1, len(copies)):
                a, b = copies[i][1], copies[j][1]
                # Two bodies that both failed to unparse are "" == "", and
                # SequenceMatcher("", "").ratio() is 1.0 -- which would invent a
                # perfect clone family out of two parse failures. None today, but
                # the scan now walks 1948 definitions instead of 190.
                if not a or not b:
                    worst = 0.0
                    continue
                if a == b:
                    exact += 1
                    best = 1.0
                    continue
                ratio = difflib.SequenceMatcher(None, a, b).ratio()
                best = max(best, ratio)
                worst = min(worst, ratio)
                if ratio >= CLONE_RATIO:
                    clones += 1
        if exact + clones:
            dirs = sorted({os.path.dirname(_rel(p)) for p, _ in copies})
            families.append(
                (exact + clones, len(copies), exact, round(best, 2), name, dirs, round(worst, 3))
            )
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
        "# Private helpers -- module-level functions AND methods -- defined in more",
        "# than one file. The ratchet baseline for",
        "# scripts/validation/duplicate_helper_validator.py. Format:",
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
        "# --report for the similarity view before consolidating anything, and --drift",
        "# for the band that matters most: near-identical copies with NO exact pair,",
        "# i.e. a fix that already landed in one of them.",
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
    parser.add_argument(
        "--drift",
        action="store_true",
        help="near-identical copies with NO exact pair -- where a fix landed once",
    )
    args = parser.parse_args()

    if args.drift:
        # The band worth triaging. A family whose copies are still byte-identical is
        # merely duplicated; one where EVERY pair is >=90% similar and NO pair is
        # identical has been EDITED IN ONE PLACE and not the others -- the shape of
        # #394 (two copies fixed, a third missed), #399 (a sibling query 40 lines
        # below its fixed twin) and #444.
        #
        # The filter is on the WORST pair, deliberately. Filtering on the best one
        # is nearly free for a large family and says almost nothing: `_make_member`
        # has 45 copies and 990 pairs, of which 1% reach 0.90 and the minimum
        # similarity is 0.05 -- 45 independently written fixtures, not a fix that
        # landed once. Keying on the worst pair drops it, and takes the band from
        # 89 families to a set where the inference is actually true.
        drifted = [f for f in clone_families() if f[2] == 0 and f[6] >= CLONE_RATIO]
        print(f"{'pairs':>5} {'files':>5} {'worst':>6} {'best':>6}  helper")
        for pairs, files, _exact, best, name, dirs, worst in drifted:
            # `best` is rounded to 2dp, so a 0.997 family printed as 1.00 under a
            # header promising "no exact pair". Show 3dp.
            print(f"{pairs:>5} {files:>5} {worst:>6.3f} {best:>6.3f}  {name}")
            for d in dirs[:4]:
                print(f"{'':>26}{d}/")
        print(
            f"\n{len(drifted)} families in which EVERY copy is >={CLONE_RATIO:.0%} similar to "
            "every other and none is identical -- i.e. an edit landed in one of them."
        )
        return 0

    if args.report:
        families = clone_families()
        print(f"{'pairs':>5} {'files':>5} {'exact':>5} {'best':>5}  helper")
        for pairs, files, exact, best, name, dirs, _worst in families:
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
            for p in sorted(_rel(x) for x in where):
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
