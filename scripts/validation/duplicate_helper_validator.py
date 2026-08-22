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

The CENSUS counts names, not clones: two same-named helpers may be unrelated (there
are 13 `_payment` helpers whose bodies share 6% similarity). What FAILS is narrower
than what is counted. A new copy fails only when the name is a real clone family --
at least 25% of its pairs near-identical -- and a name collision is reported without
failing. Blocking on the name alone fired on 60.5% of the last 400 commits that add
a Python file; this fires on 34.1%, and still fails every case the gate was built
for. The whole census stays in the baseline as the to-do list. See clone_share().

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
import copy
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

# A family this fraction of whose pairs are near-identical is a real clone family,
# and adding another copy FAILS the gate. Below it the shared name is treated as a
# coincidence and only reported. See clone_share() for how this was chosen.
CLONE_SHARE = 0.25


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
    except OSError:
        return []
    return helpers_in_source(source)


def helpers_in_source(source: str) -> List[Tuple[str, str, str]]:
    """The same walk, over source text rather than a path.

    Split out so the history replay that measures this gate's firing rate can feed
    blobs straight from `git cat-file`, instead of checking out 400 commits.
    """
    try:
        # Parsing someone else's file re-emits their SyntaxWarnings (an invalid
        # escape in a non-raw string, say). Their business, not a finding.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    def _emit(node, out):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        # Dunders stay excluded: `__init__` in 400 classes is Python's contract,
        # not duplication -- the same reason `execute`/`get_context` are excluded.
        if not node.name.startswith("_") or node.name.startswith("__"):
            return
        try:
            out.append((node.name, ast.unparse(node), _normalised(node)))
        except Exception:
            out.append((node.name, "", ""))

    out: List[Tuple[str, str, str]] = []
    for node in tree.body:
        _emit(node, out)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                _emit(child, out)
    return out



def _normalised(node) -> str:
    """`ast.unparse` of the function with its docstring and annotations removed.

    Two copies that differ ONLY by a reworded docstring or by type annotations have
    not diverged in behaviour, and reporting them as "a fix landed in one of them"
    is noise -- measured, that was 21 of the 32 two-copy families in the first
    version of `--drift`. `_mr` and `_ours` differ only by
    `mid: int, status_id: int=1 -> dict` versus bare parameters; the bodies are
    character-identical.

    Normalising is NOT the same as ignoring. A docstring difference can be the
    signal -- this repo's own rule is that the comment explaining a fix is the
    search query. So the raw form is kept too, and `clone_families` reports
    docstring/annotation-only differences as their own category rather than
    folding them into either "identical" or "drifted".
    """
    clone = copy.deepcopy(node)
    for sub in ast.walk(clone):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = sub.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                sub.body = body[1:] or [ast.Pass()]
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sub.returns = None
            args = sub.args
            for a in (
                list(args.args)
                + list(args.posonlyargs)
                + list(args.kwonlyargs)
                + [args.vararg, args.kwarg]
            ):
                if a is not None:
                    a.annotation = None
    return ast.unparse(clone)


def _by_name(root: str) -> Dict[str, List[Tuple[str, str]]]:
    found: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for path in _iter_python_files(root):
        seen_here = set()
        for name, body, norm in _private_helpers(path):
            # Count FILES, not definitions: a helper redefined inside one module is a
            # different (and more obvious) problem.
            if name in seen_here:
                continue
            seen_here.add(name)
            found[name].append((path, body, norm))
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
        exact = clones = cosmetic = 0
        best = 0.0
        worst = 1.0
        for i in range(len(copies)):
            for j in range(i + 1, len(copies)):
                a, b = copies[i][2], copies[j][2]  # normalised
                raw_a, raw_b = copies[i][1], copies[j][1]
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
                    # Same code, different docstring or annotations. Worth seeing --
                    # this repo's rule is that the comment explaining a fix is the
                    # search query -- but it is not behavioural drift.
                    if raw_a != raw_b:
                        cosmetic += 1
                    continue
                ratio = difflib.SequenceMatcher(None, a, b).ratio()
                best = max(best, ratio)
                worst = min(worst, ratio)
                if ratio >= CLONE_RATIO:
                    clones += 1
        if exact + clones:
            dirs = sorted({os.path.dirname(_rel(p)) for p, _, _ in copies})
            families.append(
                (
                    exact + clones,
                    len(copies),
                    exact,
                    round(best, 2),
                    name,
                    dirs,
                    round(worst, 3),
                    cosmetic,
                )
            )
    families.sort(key=lambda f: (-f[0], -f[1]))
    return families


def clone_share(copies) -> float:
    """What FRACTION of a name's pairs are near-identical, after normalising.

    This is what decides whether a name is a real clone family or a name collision,
    and so whether adding another copy fails the gate.

    Neither extreme works, and both were measured over the whole tree before this
    was chosen:

    * The BEST pair is nearly free for a large family and says almost nothing --
      `_make_member` has 45 copies and 990 pairs, of which 5 reach 0.90, so its best
      pair is 0.99. Keying on it blocks 45 independently written fixtures.
    * The WORST pair is too blunt in the other direction. `_persist_eur_company` has
      17 copies and 136 pairs, of which **50 reach 0.90 and one is byte-identical**,
      yet its worst pair is 0.13. Keying on the worst pair calls that a name
      collision -- and it is the case this whole gate leads with (#394: two copies
      fixed with a docstring recording why, a third missed, eight in total).

    The share separates them: 0.5% for `_make_member`, 3.8% for `_make_donor`,
    36.8% for `_persist_eur_company`, 100% for the three Mollie fixture helpers.

    CLONE_SHARE is a knob, not a natural boundary. The distribution is strongly
    bimodal -- 342 of 567 families sit at exactly 0% and 110 at 100% -- but the
    middle is a continuum, and lowering the threshold to 0.10 would pull in 38 more
    families (`_ensure_company`, `_make_account`, ...). It is set where it is
    because it clears every motivating case and every complaint case with room on
    both sides, not because there is a gap there.

    A pair whose body failed to unparse counts as NOT near-identical, so a parse
    failure can never be read as a clone -- `SequenceMatcher("", "").ratio()` is 1.0.
    """
    pairs = near = 0
    for i in range(len(copies)):
        for j in range(i + 1, len(copies)):
            a, b = copies[i][2], copies[j][2]
            pairs += 1
            if not a or not b:
                continue
            if a == b or difflib.SequenceMatcher(None, a, b).ratio() >= CLONE_RATIO:
                near += 1
    return near / pairs if pairs else 0.0


def regressions(counts: Dict[str, int], baseline: Dict[str, int]) -> Dict[str, int]:
    """Names that are newly duplicated, or that gained a copy.

    Upward only: consolidating is the entire point of this gate and must never be
    what fails it.
    """
    return {k: v for k, v in counts.items() if v > baseline.get(k, 0)}


def split_regressions(new: Dict[str, int], families: Dict):
    """(blocking, advisory) -- which newly duplicated names actually fail the gate.

    Separate from main() so it can be tested against real source trees rather than
    against similarity numbers a test made up.
    """
    blocking = {n: c for n, c in new.items() if clone_share(families.get(n, [])) >= CLONE_SHARE}
    return blocking, {n: c for n, c in new.items() if n not in blocking}


def load_baseline(path: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        # Strip the inline clone-family marker as well as whole-line comments.
        # A helper name cannot contain '#'.
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, count = line.rpartition("::")
        if name and count.isdigit():
            out[name] = int(count)
    return out


CLONE_MARK = "# clone family"


def write_baseline(path: Path, counts: Dict[str, int], families: Dict) -> None:
    header = [
        "# Private helpers -- module-level functions AND methods -- defined in more",
        "# than one file. The ratchet baseline for",
        "# scripts/validation/duplicate_helper_validator.py. Format:",
        "#     <helper name>::<number of files defining it>",
        "#",
        "# A change fails only if it adds a copy of a name marked `# clone family`",
        "# below -- one whose copies really are near-identical. A new copy of an",
        "# unmarked name is reported and recorded, not blocked: those share a name and",
        "# little else, and the only exit a blocking gate leaves for them is renaming",
        "# the method. Consolidating never fails the gate.",
        "#",
        "# This file should only ever SHRINK. It is a to-do list, not a permission slip:",
        "# each line is a place where a future fix can be applied to one copy and missed",
        "# in the others -- which happened four times on 2026-08-19 alone (#392, #394,",
        "# #399, and a merge collision between two branches fixing the same test).",
        "#",
        "# A high count here does NOT mean the copies are clones; same name, unrelated",
        "# bodies is common (13 `_payment` helpers share 6% similarity) -- which is why",
        "# only the marked lines block. Run with --report for the similarity view",
        "# before consolidating anything, and --drift for the band that matters most:",
        "# near-identical copies with NO exact pair, i.e. a fix that already landed in",
        "# one of them.",
        "",
    ]
    # Mark the clone families. This is what the gate blocks on, and marking it in
    # the file is what lets CI's "baseline did not grow" step tell a new copy of a
    # near-identical helper from a new name collision -- it compares the marked
    # total, not the raw one. Without the mark that step re-imposes the blocking
    # this validator just stopped doing.
    body = []
    for name, count in sorted(counts.items()):
        share = clone_share(families.get(name, []))
        mark = f"  {CLONE_MARK}, {share:.0%} of pairs near-identical" if share >= CLONE_SHARE else ""
        body.append(f"{name}::{count}{mark}")
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
        for pairs, files, _exact, best, name, dirs, worst, _cos in drifted:
            # `best` is rounded to 2dp, so a 0.997 family printed as 1.00 under a
            # header promising "no exact pair". Show 3dp.
            print(f"{pairs:>5} {files:>5} {worst:>6.3f} {best:>6.3f}  {name}")
            for d in dirs[:4]:
                print(f"{'':>26}{d}/")
        cosmetic_only = [f for f in clone_families() if f[2] and f[7] and f[0] == f[2]]
        print(
            f"\n{len(drifted)} families in which EVERY copy is >={CLONE_RATIO:.0%} similar to "
            "every other and none is identical AFTER normalising away docstrings and\n"
            "type annotations -- i.e. the CODE diverged, and an edit landed in one of them."
        )
        print(
            f"{len(cosmetic_only)} further families are identical once normalised and differ "
            "only in docstrings or\nannotations. Not behavioural drift -- but a docstring that "
            "exists in one copy and not\nits sibling is often the explanation of a fix, which "
            "this repo treats as a search query."
        )
        return 0

    if args.report:
        families = clone_families()
        print(f"{'pairs':>5} {'files':>5} {'exact':>5} {'best':>5}  helper")
        for pairs, files, exact, best, name, dirs, _worst, _cos in families:
            print(f"{pairs:>5} {files:>5} {exact:>5} {best:>5}  {name}")
            for d in dirs[:4]:
                print(f"{'':>28}{d}/")
        print(f"\n{len(families)} clone families")
        return 0

    # One scan, reused by the writer and by the blocking decision below. census()
    # would repeat it.
    families = _by_name(str(REPO_ROOT / SCAN_ROOT))
    counts = {name: len(v) for name, v in families.items() if len(v) > 1}

    if args.update_baseline:
        write_baseline(args.baseline, counts, families)
        print(
            f"baseline written: {len(counts)} duplicated helpers, "
            f"{sum(counts.values()) - len(counts)} redundant copies"
        )
        return 0

    baseline = load_baseline(args.baseline)
    new = regressions(counts, baseline)

    # A new copy FAILS the gate only when the name is a real clone family -- at
    # least CLONE_SHARE of its pairs near-identical (see clone_share()). A name
    # collision is reported and does not fail.
    #
    # Replaying the last 400 commits: blocking on the NAME alone fires on 60.5% of
    # the 129 commits that add a Python file, and roughly half of those firings are
    # names whose copies share almost nothing. The only exit a blocking gate leaves
    # for those is renaming the method, and `_make_member_for_this_test` is a worse
    # codebase than the duplicate was. This rule fires on 34.1% of the same
    # commits, and still fails every case the gate was built for.
    blocking, advisory = split_regressions(new, families)

    def _list(names: Dict[str, int]) -> None:
        print("=" * 60)
        for name, count in sorted(names.items()):
            print(f"\n{name}  (now in {count} files, baseline {baseline.get(name, 0)})")
            for path in sorted(_rel(x) for x, _, _ in families[name]):
                print(f"  {path}")

    if advisory:
        print("\n⚪ NEWLY DUPLICATED -- name collision only, NOT blocking:")
        _list(advisory)
        print(
            "\nThese copies are not near-identical, so the shared name is very likely a\n"
            "coincidence rather than a copy-paste. Record them and move on:\n"
            "    python scripts/validation/duplicate_helper_validator.py --update-baseline"
        )

    if blocking:
        print("\n🔴 NEWLY DUPLICATED HELPERS (not in the baseline):")
        _list(blocking)
        print(
            "\nEvery copy of these is near-identical to every other, so this is a\n"
            "copy-paste, and a copy-pasted helper is where a fix goes to die: the next\n"
            "person fixes one of these and the others keep the bug, silently. Import the\n"
            "existing one, or move it to a shared module.\n\n"
            "If the duplication is genuinely intended, record it:\n"
            "    python scripts/validation/duplicate_helper_validator.py --update-baseline"
        )
        return 1

    total = sum(baseline.values()) - len(baseline)
    print(f"✅ No newly duplicated helpers ({len(baseline)} known, {total} redundant copies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
