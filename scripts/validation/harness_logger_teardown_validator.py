#!/usr/bin/env python3
r"""
Harness-Logger Class-Teardown Census
====================================

Makes the measurement in ``verenigingen/tests/harness_logger.py``'s
``_StderrHandler`` docstring re-runnable.

That docstring justifies a design decision -- the ``>= ERROR`` mirror gate --
with a count: how many ``tearDownClass`` bodies reach the harness logger, at
which levels. The gate sits at ERROR "because that is the level of the two
class-teardown records that must not be lost". If a third class-teardown site
appears at WARNING that must not be lost, that premise is silently false and
nothing says so.

The count has already been wrong twice. It entered the codebase as "nine sites,
all ERROR" -- a review's figure, never measured, merged and propagated for
months (#564). Correcting it produced a second wrong number ("ten sites, five
calls, one ERROR"), because the filter used to tighten an over-approximate walk
excluded a real edge class. See #571.

So the number is not the point. **The rule that produces the number is the
point**, and this script is that rule, executable.

Two resolution modes, because the docstring's central claim is that the answer
depends on which one you use:

``--mode mro`` (default)
    An attribute call's receiver is resolved to its class where possible and
    bound through the MRO. This is the mode the docstring's figures come from.

``--mode name``
    Edges resolved by callee name alone -- every def with that name is a
    candidate. Deliberately an over-approximation: it bounds the true answer
    from ABOVE, which is what refuted "nine, all ERROR" (an over-approximation
    returning fewer than the claim is a refutation). Do not mistake it for the
    answer; ``tearDown`` alone has hundreds of defs in this repo.

Usage
-----
    python scripts/validation/harness_logger_teardown_validator.py            # check vs baseline
    python scripts/validation/harness_logger_teardown_validator.py --report   # human-readable
    python scripts/validation/harness_logger_teardown_validator.py --mode name --report
    python scripts/validation/harness_logger_teardown_validator.py --emit-baseline

Exit codes
----------
    0  census matches the committed baseline
    1  census differs -- a class-teardown logging route was added, removed or
       changed level. Re-read the ``>= ERROR`` gate rationale in
       harness_logger.py BEFORE regenerating the baseline.
    2  usage / IO error, or the self-check failed

Why there is no pre-commit hook
-------------------------------
The sibling validators in this directory (`error_swallow`, `failed_write`,
`duplicate_helper`) are per-file hooks: `pass_filenames: true`, `files: '\.py$'`.
This one cannot be. A call graph is whole-tree by construction -- a teardown in
one file reaches a logging call in another -- so there is no useful "just the
files you touched" mode, and the walk costs ~20s. Paying that on every Python
commit to guard a docstring is the wrong trade.

Enforcement is `scripts/validation/tests/test_harness_logger_teardown_census.py`,
run by the Code Validation workflow alongside the other validator suites. It lives
there rather than in `verenigingen/tests/` for the same two reasons the siblings do:
it is stdlib-only so that job needs no bench or site, and a ~20s whole-tree walk
inside a Frappe shard would perturb every other bin (shards re-pack on runtime).

Self-check
----------
Before reporting any total, the walk asserts it finds the two ERROR sites the
docstring names by hand (``singleton_backup.py`` ``_restore_singleton`` and
``error_log_guard.py`` ``_capture_test_error_logs``). An earlier version of this
instrument silently missed an entire file because it handled the
``logger = get_harness_logger(...)`` alias shape but not the inline
``get_harness_logger(...).error(...)`` shape. A total from a blind instrument
settles nothing, so the control runs first and a failure is exit 2, not a
smaller number.
"""

import argparse
import ast
import os
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = APP_ROOT / "verenigingen"
BASELINE = Path(__file__).resolve().parent / "harness_logger_teardown_baseline.txt"

LOG_LEVELS = ("debug", "info", "warning", "error", "critical", "exception")
LIFECYCLE = ("setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule", "tearDownModule")
FACTORY = "get_harness_logger"

# Sites the walk MUST reach, as (path, level). The first two are the ERROR sites
# harness_logger.py names by hand; the third exists for a different reason.
#
# Both ERROR sites are INLINE form -- `get_harness_logger("x").error(...)` -- which
# is the shape #564 missed. That makes them a perfect control for #564 and a
# useless one for its mirror: blinding only the ALIAS shape
# (`logger = get_harness_logger(...)`) leaves both ERROR sites reachable, so the
# control passed while the census silently fell from 19 sites to 6. Measured.
# The third entry is alias-form, so each binding shape now has a control.
CONTROL_SITES = (
    ("verenigingen/tests/fixtures/singleton_backup.py", "error"),  # inline
    ("verenigingen/tests/utils/error_log_guard.py", "error"),  # inline
    ("verenigingen/tests/fixtures/enhanced_test_factory.py", "warning"),  # alias
)


class FunctionInfo:
    """One `def`, plus what it calls and what it logs."""

    __slots__ = ("path", "name", "cls", "lineno", "logs", "calls")

    def __init__(self, path, name, cls, lineno):
        self.path = path
        self.name = name
        self.cls = cls  # owning class name, or None for module-level
        self.lineno = lineno
        self.logs = []  # [(lineno, level)]
        self.calls = []  # [(callee, recv_kind, recv_attr, is_super)]

    @property
    def key(self):
        return (self.path, self.cls, self.name, self.lineno)

    @property
    def qualname(self):
        return f"{self.cls}.{self.name}" if self.cls else self.name


def _is_factory_call(node):
    """True for `get_harness_logger(...)`, however it was imported."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == FACTORY) or (
        isinstance(f, ast.Attribute) and f.attr == FACTORY
    )


def _own_nodes(fn):
    """Nodes belonging to `fn` itself, not to any nested def.

    A nested `def` is walked separately as its own FunctionInfo; without this,
    `ast.walk` attributes the inner body to the outer function AND to the inner
    one, double-counting every call it makes.
    """
    out = []
    stack = [fn]
    while stack:
        node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not fn:
                continue
            out.append(child)
            stack.append(child)
    return out


class ModuleScanner(ast.NodeVisitor):
    """Collect classes, functions, call edges and harness-logger call sites."""

    def __init__(self, path):
        self.path = path
        self.functions = []
        self.bases = {}  # class name -> [base names]
        self.attr_types = defaultdict(dict)  # class name -> {attr: class name}
        self._class_stack = []
        self._alias = set()  # names bound to get_harness_logger(...)

    # -- binding shapes -------------------------------------------------

    def visit_Assign(self, node):
        # logger = get_harness_logger("...")   (module- or function-level alias)
        if _is_factory_call(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self._alias.add(t.id)
        # cls.factory = SomeClass(...) / self.x = SomeClass() / cls._inst = cls()
        if self._class_stack and isinstance(node.value, ast.Call):
            owner = self._class_stack[-1]
            vf = node.value.func
            rhs = None
            if isinstance(vf, ast.Name):
                rhs = owner if vf.id in ("cls", "self") else vf.id
            elif isinstance(vf, ast.Attribute) and vf.attr == "__class__":
                rhs = owner
            if rhs:
                for t in node.targets:
                    if (
                        isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id in ("cls", "self")
                    ):
                        self.attr_types[owner][t.attr] = rhs
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.bases[node.name] = [
            b.id if isinstance(b, ast.Name) else b.attr for b in node.bases if isinstance(b, (ast.Name, ast.Attribute))
        ]
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node):
        self._function(node)

    def visit_AsyncFunctionDef(self, node):
        self._function(node)

    def _function(self, node):
        cls = self._class_stack[-1] if self._class_stack else None
        info = FunctionInfo(self.path, node.name, cls, node.lineno)
        for child in _own_nodes(node):
            if not isinstance(child, ast.Call):
                continue
            f = child.func
            if not isinstance(f, ast.Attribute):
                if isinstance(f, ast.Name):
                    info.calls.append((f.id, "plain", None, False))
                continue

            # A harness-logger logging call, in either binding shape.
            if f.attr in LOG_LEVELS:
                recv = f.value
                if _is_factory_call(recv) or (isinstance(recv, ast.Name) and recv.id in self._alias):
                    info.logs.append((child.lineno, f.attr))
                    continue

            recv = f.value
            is_super = isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name) and recv.func.id == "super"
            if isinstance(recv, ast.Name) and recv.id in ("self", "cls"):
                info.calls.append((f.attr, "selfcls", None, is_super))
            elif is_super:
                info.calls.append((f.attr, "super", None, True))
            elif (
                isinstance(recv, ast.Attribute)
                and isinstance(recv.value, ast.Name)
                and recv.value.id in ("self", "cls")
            ):
                # cls.<attr>.<method>() -- the shape that makes route 3 real
                info.calls.append((f.attr, "attr", recv.attr, False))
            else:
                info.calls.append((f.attr, "other", None, False))
        self.functions.append(info)
        # Still descend: a nested `def` must be registered as its own
        # FunctionInfo (its body was excluded from `info` by _own_nodes).
        self.generic_visit(node)


_SCAN_CACHE = {}


def scan(package: Path):
    """Parse the package once. Cached: the walk costs ~20s over ~3k files, and
    the test module calls census() five times. Without this the module adds two
    minutes to whichever CI shard it lands in -- and shards re-pack on measured
    runtime, so a slow module perturbs every other bin too."""
    if package in _SCAN_CACHE:
        return _SCAN_CACHE[package]
    functions, bases, attr_types = [], {}, defaultdict(dict)
    for root, dirs, names in os.walk(package):
        # Sorted, not just filtered: os.walk yields directories in arbitrary
        # order. The census is stable across shuffled orders (measured), but
        # that should be structural rather than incidental.
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "node_modules"))
        for n in sorted(names):
            if not n.endswith(".py"):
                continue
            p = Path(root) / n
            try:
                # Some modules in this tree carry invalid escape sequences in
                # non-raw strings; ast.parse emits a SyntaxWarning per file and
                # it is not this script's business to report them.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = str(p.relative_to(APP_ROOT))
            sc = ModuleScanner(rel)
            sc.visit(tree)
            functions.extend(sc.functions)
            bases.update(sc.bases)
            for k, v in sc.attr_types.items():
                attr_types[k].update(v)
    _SCAN_CACHE[package] = (functions, bases, attr_types)
    return functions, bases, attr_types


def mro(cls, bases, seen=None):
    """Depth-first base linearization over classes we can actually see."""
    if seen is None:
        seen = []
    if cls is None or cls in seen:
        return seen
    seen.append(cls)
    for b in bases.get(cls, []):
        mro(b, bases, seen)
    return seen


def build_index(functions):
    by_name = defaultdict(list)
    by_cls_name = {}
    for fn in functions:
        by_name[fn.name].append(fn)
        if fn.cls:
            by_cls_name.setdefault((fn.cls, fn.name), fn)
    return by_name, by_cls_name


def resolve(fn, call, mode, by_name, by_cls_name, bases, attr_types):
    """Return the candidate callees for one call edge."""
    callee, kind, recv_attr, is_super = call

    # Lifecycle methods are invoked by unittest, not by helpers -- EXCEPT on a
    # non-super() receiver. Dropping that exception unconditionally is what made
    # an earlier revision say "ten" and "exactly one ERROR": it hid
    # `cls._test_instance.tearDown()`, the only place in the repo where a class
    # teardown invokes a per-test tearDown on a stashed instance.
    if callee in LIFECYCLE and kind != "attr":
        return []

    if mode == "name":
        return by_name.get(callee, [])

    # -- mro mode --
    if kind in ("selfcls", "super") and fn.cls:
        chain = mro(fn.cls, bases)
        if is_super:
            chain = chain[1:]
        for c in chain:
            if (c, callee) in by_cls_name:
                return [by_cls_name[(c, callee)]]
        return []

    if kind == "attr" and fn.cls:
        # resolve cls.<attr> to a class via recorded attribute types
        owner_chain = mro(fn.cls, bases)
        recv_cls = None
        for c in owner_chain:
            if recv_attr in attr_types.get(c, {}):
                recv_cls = attr_types[c][recv_attr]
                break
        if recv_cls:
            for c in mro(recv_cls, bases):
                if (c, callee) in by_cls_name:
                    return [by_cls_name[(c, callee)]]
            return []
        return []  # unresolvable receiver -> no edge in mro mode

    if kind == "plain":
        return [f for f in by_name.get(callee, []) if f.cls is None]

    return []


def census(mode="mro"):
    functions, bases, attr_types = scan(PACKAGE)
    by_name, by_cls_name = build_index(functions)
    roots = [f for f in functions if f.name == "tearDownClass"]

    routes = {}  # root.key -> {(path, lineno, level)}
    for root in roots:
        reached, stack, hits = set(), [root], set()
        while stack:
            cur = stack.pop()
            if cur.key in reached:
                continue
            reached.add(cur.key)
            for ln, lvl in cur.logs:
                hits.add((cur.path, ln, lvl))
            for call in cur.calls:
                for nxt in resolve(cur, call, mode, by_name, by_cls_name, bases, attr_types):
                    if nxt.key not in reached:
                        stack.append(nxt)
        if hits:
            routes[root] = hits

    sites = set()
    for hits in routes.values():
        sites |= hits
    return routes, sites, functions


def self_check(sites):
    """The control: the two ERROR sites the docstring names must be REACHED.

    This deliberately inspects `sites` (what the walk arrived at) and not the
    parsed functions. Checking the parsed functions only controls the MATCHER --
    whether `get_harness_logger(...).error(...)` was recognised -- which is
    #564's failure. #571's failure was different and worse: a resolution filter
    that dropped a real edge class, so the matcher worked fine and the WALK went
    nowhere. A control that inspects functions returns "all present" for a call
    graph that resolves to nothing at all.
    """
    reached = {(path, lvl) for path, _ln, lvl in sites}
    return [f"{path} [{lvl}]" for path, lvl in CONTROL_SITES if (path, lvl) not in reached]


def format_baseline(routes, sites):
    levels = defaultdict(int)
    for _, _, lvl in sites:
        levels[lvl] += 1
    lines = [
        f"teardowns {len(routes)}",
        f"calls {len(sites)}",
    ]
    for lvl in sorted(levels):
        lines.append(f"level {lvl} {levels[lvl]}")
    for path, cls, name, _ in sorted(r.key for r in routes):
        lines.append(f"teardown {path}::{cls}.{name}")
    # Sites are keyed by path + enclosing-function-free level only; line numbers
    # rot on any edit above them (see error_swallow_baseline.txt's header).
    per_file = defaultdict(lambda: defaultdict(int))
    for path, _, lvl in sites:
        per_file[path][lvl] += 1
    for path in sorted(per_file):
        for lvl in sorted(per_file[path]):
            lines.append(f"site {path} {lvl} {per_file[path][lvl]}")
    return "\n".join(lines) + "\n"


def read_baseline():
    if not BASELINE.exists():
        return None
    return "\n".join(
        l for l in BASELINE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")
    ) + "\n"


BASELINE_HEADER = """\
# Census of harness-logger logging calls reachable from a `tearDownClass` body.
# Produced by scripts/validation/harness_logger_teardown_validator.py (--mode mro).
#
# This exists because verenigingen/tests/harness_logger.py's `_StderrHandler`
# docstring justifies its `>= ERROR` mirror gate with these numbers, and that
# figure has been wrong twice (#564, #571) precisely because nobody could re-run
# it. Regenerate with --emit-baseline.
#
# If this file changes, DO NOT just regenerate. A new class-teardown logging
# route means re-reading the gate rationale: the gate mirrors only `>= ERROR`,
# so a new WARNING site from class teardown is LOST. Decide whether that is
# acceptable, then regenerate in the same commit.
#
# Line numbers are deliberately absent -- they rot on any edit above them.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Census of harness-logger calls reachable from a tearDownClass body."
    )
    ap.add_argument("--mode", choices=("mro", "name"), default="mro")
    ap.add_argument("--report", action="store_true", help="human-readable breakdown")
    ap.add_argument("--emit-baseline", action="store_true")
    args = ap.parse_args(argv)

    routes, sites, functions = census(args.mode)

    missing = self_check(sites)
    if missing:
        print("SELF-CHECK FAILED -- the walk did not find sites the docstring names:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print("Any total from this run is meaningless. Fix the instrument.", file=sys.stderr)
        return 2

    levels = defaultdict(int)
    for _, _, lvl in sites:
        levels[lvl] += 1

    if args.report:
        print(f"mode: {args.mode}")
        print(f"tearDownClass bodies reaching the harness logger: {len(routes)}")
        print(f"logging calls reached: {len(sites)}")
        print("by level: " + ", ".join(f"{k}={v}" for k, v in sorted(levels.items())))
        print()
        print("routes:")
        for root in sorted(routes, key=lambda r: r.key):
            print(f"  {root.path}::{root.cls}.{root.name}  -> {len(routes[root])} call(s)")
        print()
        print("sites at ERROR (what the >= ERROR mirror gate exists to keep):")
        for path, ln, lvl in sorted(sites):
            if lvl in ("error", "critical", "exception"):
                print(f"  {path}:{ln} [{lvl}]")
        print()
        print("sites NOT covered by that gate (these are LOST):")
        for path, ln, lvl in sorted(sites):
            if lvl not in ("error", "critical", "exception"):
                print(f"  {path}:{ln} [{lvl}]")
        print()
        # The docstring cites these to explain why name-only resolution is
        # useless for `tearDown`. Emitted so that figure is regenerable too.
        counts = Counter(f.name for f in functions)
        print(
            "def counts (why name-only resolution over-approximates): "
            + ", ".join(f"{n}={counts[n]}" for n in ("tearDown", "cleanup", "restore"))
        )
        return 0

    current = format_baseline(routes, sites)
    if args.emit_baseline:
        sys.stdout.write(BASELINE_HEADER + current)
        return 0

    expected = read_baseline()
    if expected is None:
        print(f"No baseline at {BASELINE}. Create it with --emit-baseline.", file=sys.stderr)
        return 2
    if current != expected:
        print("Class-teardown harness-logger census CHANGED.", file=sys.stderr)
        print("", file=sys.stderr)
        exp, cur = expected.splitlines(), current.splitlines()
        for line in sorted(set(exp) - set(cur)):
            print(f"  - {line}", file=sys.stderr)
        for line in sorted(set(cur) - set(exp)):
            print(f"  + {line}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "The `>= ERROR` mirror gate in verenigingen/tests/harness_logger.py rests on\n"
            "this census: anything below ERROR from class teardown is LOST. Re-read that\n"
            "rationale before regenerating with --emit-baseline.",
            file=sys.stderr,
        )
        return 1
    print(f"Class-teardown harness-logger census unchanged ({len(routes)} teardowns, {len(sites)} calls). OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
