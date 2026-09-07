#!/usr/bin/env python3
"""Advisory census of DIVERGED duplicate PUBLIC functions in production code (#991).

`duplicate_helper_validator.py` restricts itself to single-underscore-prefixed
helpers on purpose (`duplicate_helper_validator.py:161`) -- that is what keeps its
census to real test-fixture duplication instead of 273 names that are framework
contract (`execute`, `get_context`, ...). The tradeoff is that PUBLIC production
functions are invisible to it. #495 is the seed instance already in the tracker:
four (now measured as six, see below) independent implementations of
`calculate_next_invoice_date`, agreeing today, reachable from different callers,
and a change to one is invisible to the others. #206 was the damage: one of those
paths computed a period boundary by hand and produced a 366-day invoice for months.

This module covers exactly that gap: PRODUCTION files (tests/ and test_*.py
excluded -- those already belong to the sibling gate), PUBLIC names (leading
underscore excluded -- ditto), reusing the sibling's normalisation/similarity
machinery so "diverged" means the same thing in both places.

## Why divergence, not a general clone census

A raw census of every name in >1 production file is NOT what this reports --
measured at 611 duplicated names / 1341 redundant copies, and legitimate
production near-duplication (per-gateway handlers, adapters, interface
implementations) makes a plain-count gate noisy. #949 documents what a noisy gate
earns: it gets disarmed by more copy-pasting, because the standing response to a
gate that cries wolf is to mute it. So this reports only families where at least
one pair has ACTUALLY diverged from a common origin -- near-identical after
normalising away docstrings/annotations, but not byte-identical -- while every
other pair may be (and usually is) unrelated. Measured: this band holds 17
families, not 611.

## Why "at least one near pair", not "every pair near" (`--drift`'s rule)

`--drift` requires EVERY pair in the family to be >=CLONE_RATIO similar, which is
right for test-fixture families that really were one copy-pasted N times. It is
the wrong rule for production "same responsibility, independently reimplemented"
families: #495's own flagship case fails it. Measured directly against the six
current `calculate_next_invoice_date` copies -- two of which are thin delegating
wrapper methods that happen to be 0.911 similar to each other, the rest
independent reimplementations with real behavioural differences (which
frequencies they handle, which fallback they use) -- the WORST pair is 0.094,
so `exact == 0 and worst >= CLONE_RATIO` (the --drift selector) reports NOTHING for
this family. Only ONE of its 10 pairs is near-identical. Requiring every pair to
be near would make the flagship case of this very issue invisible to the check
built to catch it. So the selector here is: exact == 0 (excludes plain,
un-diverged duplication) AND at least one pair >= CLONE_RATIO (excludes name
collisions where nothing is actually alike).

## A known, deliberate gap: this does not see data-literal duplication

#495's OTHER family -- the `Biannual` -> `Semi-Annual` vocabulary map duplicated
between `contribution_amendment_approval_service.py` and
`application_payments.py` -- is a dict LITERAL, not a function, and is invisible
to this scanner by construction (it only walks `FunctionDef`/`AsyncFunctionDef`).
It is also, as of this writing, byte-identical between the two copies -- i.e. not
diverged, just duplicated (a human already caught it: application_payments.py
carries a comment cross-referencing the other copy). Building a literal-duplication
detector would mean walking every `Assign` to a dict/list literal, at ANY nesting
level (this map lives inside a method body, not at module scope) -- and unlike
function names, local variable names are not distinctive, so that scan is very
likely far noisier than the 611-name function census this module avoided turning
into a gate. Not built here; if divergent literal maps turn out to be a recurring
class rather than this one instance, that is a separate, differently-shaped
follow-up, not a widening of this one.

Usage:
    python scripts/validation/production_divergence_scanner.py            # report
    python scripts/validation/production_divergence_scanner.py --report   # same

Advisory only. Always exits 0 -- see #401 and #985 for what a large pre-existing
baseline does to a gate's credibility on day one. This ships as a report first;
whether any of it becomes a blocking gate is a separate decision, made after
someone has read the census below.
"""
import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_DHV_PATH = _THIS_DIR / "duplicate_helper_validator.py"


def _load_duplicate_helper_validator():
    """Load the sibling module by path, not by import, so this works regardless
    of sys.path / cwd -- and so nothing here needs `scripts/validation` to be a
    package. Read-only reuse: this module is owned by #990's fix, not by us."""
    spec = importlib.util.spec_from_file_location("duplicate_helper_validator", _DHV_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dhv = _load_duplicate_helper_validator()

REPO_ROOT = dhv.REPO_ROOT
SCAN_ROOT = dhv.SCAN_ROOT
CLONE_RATIO = dhv.CLONE_RATIO


def is_test_path(path: str) -> bool:
    """True for anything the sibling private-helper gate already owns.

    A `tests/` directory anywhere in the path, or a `test_*.py` / `*_test.py`
    filename -- the latter catches per-doctype test files that sit next to their
    controller rather than under a `tests/` directory (measured: 146 of them).
    """
    rel = Path(dhv._rel(path))
    if "tests" in rel.parts:
        return True
    name = rel.name
    return name.startswith("test_") or name.endswith("_test.py")


def public_definitions_in_source(source: str) -> List[Tuple[str, str, str]]:
    """(name, source, normalised) for each PUBLIC function/method in `source`.

    Same shape as `duplicate_helper_validator.helpers_in_source`, same nesting
    rule (module-level, or one level inside a class), but the opposite name
    filter: skip anything starting with "_" (private helpers AND dunders are the
    sibling gate's job), keep everything else.
    """
    import ast
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    out: List[Tuple[str, str, str]] = []

    def _emit(node):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        if node.name.startswith("_"):
            return
        try:
            out.append((node.name, ast.unparse(node), dhv._normalised(node)))
        except Exception:
            out.append((node.name, "", ""))

    for node in tree.body:
        _emit(node)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                _emit(child)
    return out


def _by_name(root: str = None) -> Dict[str, List[Tuple[str, str, str]]]:
    """name -> [(path, body, normalised), ...] across production files only."""
    root = root or str(REPO_ROOT / SCAN_ROOT)
    found: Dict[str, List[Tuple[str, str, str]]] = {}
    for path in dhv._iter_python_files(root):
        if is_test_path(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                source = handle.read()
        except OSError:
            continue
        seen_here = set()
        for name, body, norm in public_definitions_in_source(source):
            if name in seen_here:
                continue
            seen_here.add(name)
            found.setdefault(name, []).append((path, body, norm))
    return found


def census(root: str = None) -> Dict[str, int]:
    """name -> number of production files defining it, for names in more than one."""
    return {name: len(v) for name, v in _by_name(root).items() if len(v) > 1}


def _pair_stats(copies: List[Tuple[str, str, str]]):
    """(exact, near, best, worst, cosmetic, near_pairs) over every pair in a family.

    Mirrors `duplicate_helper_validator.clone_families`'s per-family loop exactly,
    so "near", "exact" and "cosmetic" mean the same thing in both tools. `near`
    counts only ratio-based near pairs, NOT exact ones -- an exact pair is plain
    duplication, not a diverged pair, and is tracked separately in `exact`.

    `near_pairs` is the actual evidence for the verdict: the (path, path, ratio)
    of every pair that reached CLONE_RATIO, absolute paths. #1008: a report that
    names only the family and a truncated, alphabetically-sorted directory list
    gives a human no way back to the pair that produced it -- for a family with
    more than ~4 directories, alphabetical truncation can drop the pair entirely.
    """
    exact = near = cosmetic = 0
    best = 0.0
    worst = 1.0
    near_pairs: List[Tuple[str, str, float]] = []
    for i in range(len(copies)):
        for j in range(i + 1, len(copies)):
            a, b = copies[i][2], copies[j][2]
            raw_a, raw_b = copies[i][1], copies[j][1]
            if not a or not b:
                worst = 0.0
                continue
            if a == b:
                exact += 1
                best = 1.0
                if raw_a != raw_b:
                    cosmetic += 1
                continue
            ratio = dhv._ratio(a, b)
            best = max(best, ratio)
            worst = min(worst, ratio)
            if ratio >= CLONE_RATIO:
                near += 1
                near_pairs.append((copies[i][0], copies[j][0], ratio))
    return exact, near, best, worst, cosmetic, near_pairs


def divergent_families(root: str = None):
    """Families with at least one diverged (near, not exact) pair.

    Selector: exact == 0 (nothing in the family is a plain, un-diverged copy) AND
    near >= 1 (at least one pair actually did diverge from a shared origin, rather
    than merely sharing a name). See the module docstring for why this is a wider
    band than `--drift`'s "every pair near" rule, and why that widening is
    necessary rather than optional.

    Returns a list of (near, files, best, worst, name, dirs, near_pairs),
    most-diverged first, most-copied as tiebreak. `near_pairs` is a sorted list
    of (rel_path, rel_path, ratio) for every pair that reached CLONE_RATIO --
    the actual evidence for the verdict (#1008), not just the directories the
    family's copies happen to live in.
    """
    out = []
    for name, copies in _by_name(root).items():
        if len(copies) < 2:
            continue
        exact, near, best, worst, _cosmetic, raw_near_pairs = _pair_stats(copies)
        if exact == 0 and near >= 1:
            dirs = sorted({os.path.dirname(dhv._rel(p)) for p, _, _ in copies})
            near_pairs = sorted(
                (dhv._rel(a), dhv._rel(b), round(ratio, 3)) for a, b, ratio in raw_near_pairs
            )
            out.append((near, len(copies), round(best, 3), round(worst, 3), name, dirs, near_pairs))
    out.sort(key=lambda f: (-f[0], -f[1]))
    return out


def _print_report(root: str = None) -> None:
    resolved_root = root or str(REPO_ROOT / SCAN_ROOT)
    # Repo-relative for the header, so the label matches whatever --root
    # scanned instead of always claiming SCAN_ROOT ("verenigingen") even
    # when a different directory was actually walked (#1044).
    root_label = dhv._rel(resolved_root)
    total = 0
    excluded = 0
    for path in dhv._iter_python_files(resolved_root):
        total += 1
        if is_test_path(path):
            excluded += 1
    print(
        f"{total} .py files under {root_label}/, {excluded} excluded as test code "
        f"(tests/ dir or test_*.py/*_test.py) -- {total - excluded} scanned as production."
    )

    counts = census(root)
    redundant = sum(counts.values()) - len(counts)
    print(
        f"\nRAW CENSUS -- public names defined in more than one production file: "
        f"{len(counts)} names, {redundant} redundant copies.\n"
        "This is NOT the finding -- most of it is legitimate structure (per-gateway\n"
        "handlers, interface implementations, ...). See DIVERGED below."
    )

    families = divergent_families(root)
    print(
        f"\nDIVERGED -- at least one pair near-identical (>= {CLONE_RATIO:.0%}) after "
        f"normalising away\ndocstrings/annotations, none byte-identical: {len(families)} families.\n"
    )
    print(f"{'near':>5} {'files':>5} {'best':>6} {'worst':>6}  name")
    for near, files, best, worst, name, dirs, near_pairs in families:
        print(f"{near:>5} {files:>5} {best:>6.3f} {worst:>6.3f}  {name}")
        # #1008: name the actual near-identical pair(s) that produced this
        # verdict, not a truncated, alphabetically-sorted directory list --
        # for a family with more than ~4 directories that truncation can drop
        # the pair a human is meant to triage entirely.
        for a, b, ratio in near_pairs:
            print(f"{'':>26}{a}")
            print(f"{'':>28}<-> {b}   ratio {ratio:.3f}")

    print(
        "\nAdvisory only -- this does not fail CI. Read the flagged pairs; if one "
        "copy carries a fix\nthe others do not, that is the #206 shape. If the "
        "copies are just independently written\nand happen to share a name, "
        "nothing here needs to change."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--report", action="store_true", help="print the census and diverged families (default)"
    )
    parser.add_argument(
        "--root",
        default=SCAN_ROOT,
        help=(
            "repo-relative directory to scan (default: %(default)s). #1044: this "
            "scanner shares its sibling duplicate_helper_validator.py's SCAN_ROOT, "
            "which never covered scripts/. Advisory-only report, so widening it "
            "here changes nothing blocking -- pass --root scripts to see the "
            "PUBLIC-name divergence census for scripts/ itself."
        ),
    )
    args = parser.parse_args()
    _print_report(str(REPO_ROOT / args.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
