#!/usr/bin/env python3
"""Pick the test modules a pull request should run BEFORE it reaches the merge queue.

#2184 moved the full suite into the merge queue, so a PR reads green on `Test Summary`
without having run a single test, and a defect that a few seconds of census would have
caught costs a ~50 minute queue build instead. The PR-side job (server-tests.yml,
`pr-tests`) runs the modules this script prints, on the merged tree.

Selection (union, de-duplicated, sorted):

  a. OWN     every test module the PR adds or changes. Deleted modules and modules with no
             test method are skipped (a module with nothing to collect prints no OK line, a
             false red: the same two rules as dispatch/rule24_hook.sh).
  b. DERIVED test modules for changed NON-test .py files, bounded by --derived-cap: first
             a test named after the file (test_<stem>*.py), then test files that mention
             the file's dotted module path. Cheap and heuristic on purpose.
  c. CENSUS  the fixed list in pr_census_modules.txt: modules that scan the whole tree and
             redden on a change ELSEWHERE (the guest-endpoint floor, the fixture-isolation
             AST invariants, ...). A census entry that no longer exists or has no test
             class is an ERROR, never silently dropped: a shrinking census must be loud.

Exit codes: 0 selection printed; 2 the selection is unusable (empty, bad census, git failed).
It never prints an empty selection with exit 0: an empty set would let the job pass having
run nothing.

Every printed module is checked against a strict dotted-identifier pattern, so a hostile
file name in a PR cannot reach the workflow's shell loop.

Stdlib only. Usage:
    select_pr_test_modules.py --base <sha> [--head HEAD] [--github-output $GITHUB_OUTPUT]
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CENSUS_FILE = Path(__file__).with_name("pr_census_modules.txt")
APP_DIR = "verenigingen"
# The committed per-module CI runtimes (seconds) that the shard balancer reads; reused here.
TIMINGS_FILE = REPO_ROOT / APP_DIR / "tests" / "test_timings.json"

# Time budget for the modules a PR adds on top of the census. pr-tests has a 45 minute
# timeout and the census alone is ~10 minutes locally (budget ~15 on a slower runner); the
# rest of the budget is 20 minutes of estimated runtime, so worst case is ~35 of 45 with
# slack for setup drift. Each module also pays ~10s of `bench run-tests` start-up, and a
# module with no recorded timing is assumed to take 60s (the table's p90 is 24s, its
# maximum 612s): conservative, so an unknown module is not mistaken for a free one.
DEFAULT_BUDGET_SECONDS = 1200
MODULE_OVERHEAD_SECONDS = 10
UNKNOWN_MODULE_SECONDS = 60

# The census is never trimmed. A PR editing more than OWN_CAP test modules is a sweep: the
# job's time budget cannot hold it, and the merge queue runs the rest.
DEFAULT_OWN_CAP = 25
DEFAULT_DERIVED_CAP = 10

_TEST_FILE = re.compile(r"(^|/)test_[^/]*\.py$")
# A path that can be turned into an importable dotted module. Anything else (spaces,
# quotes, `$(...)`, hyphens, leading digits) is refused rather than escaped.
_SAFE_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*\.py$")
_SAFE_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


class SelectionError(Exception):
    pass


def git(*args, cwd=REPO_ROOT) -> bytes:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if res.returncode != 0:
        raise SelectionError(f"git {' '.join(args)} failed: {res.stderr.decode(errors='replace').strip()}")
    return res.stdout


def changed_paths(base: str, head: str, cwd=REPO_ROOT) -> dict:
    """{path: status letter}. --no-renames: a rename is a delete plus an add, so the old
    name is skipped as deleted and the new one is picked up as added. NUL-separated so a
    path with a newline or quote cannot split into two entries."""
    out = git("diff", "--name-status", "--no-renames", "-z", base, head, cwd=cwd)
    parts = out.decode("utf-8", errors="surrogateescape").split("\0")
    paths = {}
    for i in range(0, len(parts) - 1, 2):
        paths[parts[i + 1]] = parts[i][:1]
    return paths


def path_to_module(path: str) -> str:
    return path[: -len(".py")].replace("/", ".")


def module_to_path(module: str) -> str:
    return module.replace(".", "/") + ".py"


def is_test_path(path: str) -> bool:
    return bool(_TEST_FILE.search(path))


# Framework roots: a class deriving ONLY from these brings no tests of its own.
_ROOT_BASES = {"TestCase", "FrappeTestCase", "IntegrationTestCase", "UnitTestCase", "EnhancedTestCase"}


def has_tests(source: str) -> bool:
    """True when the module defines something unittest can collect: a class with a test*
    method, or a class that may INHERIT tests (it derives from a *TestCase/*Test base that is
    imported, so its tests cannot be seen here, or from a local class that itself has tests).
    Deriving from a bare framework root (unittest.TestCase, EnhancedTestCase, ...) or from a
    local class with no tests does NOT count: tests/utils/test_base_framework.py is only
    `class VerenigingenTestCase(unittest.TestCase)` with a setUp, so `bench run-tests` prints no
    OK line and the job reads it as RED (#2352). rule24_hook.sh's rule counted any *TestCase base,
    which is how that module got through; a plain `class TestDataContext:` helper ran 0 tests too
    (#2211)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Unparseable: let the run report the real error rather than hide it.
        return True

    def base(b):
        return getattr(b, "id", None) or getattr(b, "attr", "")

    def has_test_method(c):
        return any(
            isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test")
            for m in c.body
        )

    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}

    def may_have_tests(c, seen=()):
        if has_test_method(c):
            return True
        for b in map(base, c.bases):
            local = classes.get(b)
            if local is not None:
                if local.name not in seen and may_have_tests(local, seen + (c.name,)):
                    return True
            elif b.endswith(("TestCase", "Test")) and b not in _ROOT_BASES:
                return True
        return False

    return any(may_have_tests(c) for c in classes.values())


def runnable(root: Path, path: str) -> bool:
    """The file exists in the tree under test, has a safe name and a collectable test class."""
    if not _SAFE_PATH.fullmatch(path) or not path.startswith(APP_DIR + "/"):
        return False
    f = root / path
    return f.is_file() and has_tests(f.read_text(encoding="utf-8", errors="replace"))


def own_modules(root: Path, changed: dict, log) -> list:
    picked = []
    for path, status in sorted(changed.items()):
        if not is_test_path(path) or not path.startswith(APP_DIR + "/"):
            continue
        if runnable(root, path):
            picked.append(path_to_module(path))
        else:
            reason = "deleted" if status == "D" or not (root / path).is_file() else "unsafe name or no test method"
            log(f"  skip own {path}: {reason}")
    return picked


def all_test_files(root: Path) -> list:
    return sorted(
        p.relative_to(root).as_posix()
        for p in (root / APP_DIR).rglob("test_*.py")
        if _SAFE_PATH.fullmatch(p.relative_to(root).as_posix())
    )


def derived_modules(root: Path, changed: dict, own: set, cap: int, log) -> list:
    """Name matches first, then importers; stops at `cap`."""
    sources = [
        p for p, s in changed.items()
        if s != "D" and p.startswith(APP_DIR + "/") and p.endswith(".py")
        and not is_test_path(p) and not p.endswith("/__init__.py")
    ]
    if not sources or cap <= 0:
        return []
    tests = all_test_files(root)
    named, importing = [], []
    for src in sorted(sources):
        stem = Path(src).stem
        dotted = path_to_module(src)
        for t in tests:
            tstem = Path(t).stem
            if tstem == f"test_{stem}" or tstem.startswith(f"test_{stem}_"):
                named.append(t)
        if len(stem) >= 4:
            for t in tests:
                try:
                    if dotted in (root / t).read_text(encoding="utf-8", errors="replace"):
                        importing.append(t)
                except OSError:
                    continue
    out = []
    for t in dict.fromkeys(named + importing):
        m = path_to_module(t)
        if m in own or m in out:
            continue
        if not runnable(root, t):
            log(f"  skip derived {t}: no test method")
            continue
        out.append(m)
    if len(out) > cap:
        for m in out[cap:]:
            log(f"::warning::{m} NOT run on the PR (derived-module cap {cap}); the merge queue runs it")
    return out[:cap]


def load_timings(path: Path = TIMINGS_FILE) -> dict:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, (int, float))}


def estimate(module: str, timings: dict) -> float:
    return timings.get(module, UNKNOWN_MODULE_SECONDS) + MODULE_OVERHEAD_SECONDS


def within_budget(candidates: list, timings: dict, budget: float, warn) -> list:
    """Keep candidates in priority order while their summed estimate fits `budget`.
    A module that does not fit is dropped and the next, smaller one is still tried. Every
    drop is a ::warning:: so it shows on the PR's checks page, not only in the log."""
    kept, spent = [], 0.0
    for m in candidates:
        cost = estimate(m, timings)
        if spent + cost <= budget:
            kept.append(m)
            spent += cost
        else:
            warn(f"::warning::{m} NOT run on the PR (estimated {cost:.0f}s, time budget "
                 f"{budget:.0f}s used {spent:.0f}s); the merge queue runs it")
    return kept


def census_modules(root: Path, census_file: Path = CENSUS_FILE) -> list:
    if not census_file.is_file():
        raise SelectionError(f"census list {census_file} is missing")
    mods = []
    for raw in census_file.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            mods.append(line)
    if not mods:
        raise SelectionError(f"census list {census_file} is empty")
    for m in mods:
        if not _SAFE_MODULE.fullmatch(m) or not runnable(root, module_to_path(m)):
            raise SelectionError(
                f"census module {m!r} does not exist, has no test class or is not a safe module name; "
                "fix scripts/testing/pr_census_modules.txt (a census entry must never be dropped silently)"
            )
    return mods


def select(root: Path, changed: dict, derived_cap=DEFAULT_DERIVED_CAP, own_cap=DEFAULT_OWN_CAP,
           census_file: Path = CENSUS_FILE, log=lambda _m: None, timings=None,
           budget=DEFAULT_BUDGET_SECONDS) -> list:
    timings = load_timings() if timings is None else timings
    census = census_modules(root, census_file)
    own = own_modules(root, changed, log)
    if len(own) > own_cap:
        for m in own[own_cap:]:
            log(f"::warning::{m} NOT run on the PR (own-module cap {own_cap}); the merge queue runs it")
        own = own[:own_cap]
    derived = derived_modules(root, changed, set(own) | set(census), derived_cap, log)
    extras = within_budget(own + derived, timings, budget, log)
    ordered = list(dict.fromkeys(census + extras))
    if not ordered:
        raise SelectionError("empty selection")
    return sorted(ordered)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="the PR's base commit (diff is base..head)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--github-output", help="append `modules=<space separated>` to this file")
    ap.add_argument("--derived-cap", type=int, default=DEFAULT_DERIVED_CAP)
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET_SECONDS,
                    help="estimated seconds allowed for own+derived modules (census is never dropped)")
    ap.add_argument("--own-cap", type=int, default=DEFAULT_OWN_CAP)
    args = ap.parse_args(argv)

    def log(msg):
        print(msg, file=sys.stderr)

    try:
        changed = changed_paths(args.base, args.head)
        log(f"{len(changed)} changed paths in {args.base[:9]}..{args.head[:9]}")
        mods = select(REPO_ROOT, changed, args.derived_cap, args.own_cap, log=log, budget=args.budget)
    except SelectionError as exc:
        log(f"select_pr_test_modules: {exc}")
        return 2
    for m in mods:
        print(m)
    if args.github_output:
        with open(args.github_output, "a") as fh:
            fh.write(f"modules={' '.join(mods)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
