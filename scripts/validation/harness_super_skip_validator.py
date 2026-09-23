#!/usr/bin/env python3
"""Blocks a harness-base test class that overrides a lifecycle method
(``setUp``/``tearDown``/``setUpClass``/``tearDownClass``) without calling
``super().<method>(...)`` anywhere in its body.

The defect (#1307): three ``VereningingenTestCase`` subclasses defined
``setUp``/``tearDown`` (two of them also ``setUpClass``/``tearDownClass``) with
no ``super()`` call at all. ``VereningingenTestCase``'s own ``tearDown`` is
where the per-test rollback (``_rollback_once_before_draining``), the Error Log
capture/leak check, and the batch-queue / volunteer-cache isolation resets
live -- none of that runs for a subclass that skips ``super()``, and nothing
about a passing test run announces it. Measured on ``TestSEPAReconciliation``
(test_site_12, 2026-09-23): the per-test Error Log leak check that
``super().tearDown()`` wires in was entirely dark for this class -- 27 Error
Log rows written per run, zero of them ever reported.

WHAT THIS GUARD CHECKS (and why it stops here)
-----------------------------------------------
A class transitively rooted at ``VereningingenTestCase`` or ``EnhancedTestCase``
(the app's two harness bases with real per-test/per-class lifecycle contracts --
a bare ``FrappeTestCase``/``unittest.TestCase`` subclass defines no such
contract, so skipping ``super()`` there is a no-op, not a defect) that DEFINES
one of the four lifecycle methods in its own body with NO ``super().<name>(...)``
call anywhere in that method's AST. It does not evaluate what the override
does with the isolation it skips, or whether the omission is currently
harmless -- only whether the contract is honoured. It also does not flag a
class that never overrides the method at all (normal MRO dispatch already
calls the harness version).

Resolution is by class name across the whole scanned tree (not import-path
aware): every ``class Foo(Bar):`` anywhere under ``SCAN_ROOT`` contributes an
edge ``Foo -> Bar``, and a class is "harness-rooted" if that edge chain reaches
``VereningingenTestCase`` or ``EnhancedTestCase`` (including being one of them
directly). A same-named intermediate base defined in an unrelated module could
in principle create a false edge; none does today (checked via ``--report``).

Usage:
    python scripts/validation/harness_super_skip_validator.py              # check vs baseline
    python scripts/validation/harness_super_skip_validator.py --report     # verbose
    python scripts/validation/harness_super_skip_validator.py --update-baseline <path>

Exit codes:
    0  no violations outside the committed baseline
    1  a NEW violation exists (not in the baseline) -- fix it or, if it is
       genuinely pre-existing debt just discovered, add it to the baseline
       deliberately (see CLAUDE.md's "growing a baseline" rule: state before/
       after counts and justify it, do not do this silently)
    2  usage / IO error
"""

import argparse
import os
import sys
from ast import Attribute, Call, ClassDef, FunctionDef, Name, NodeVisitor, parse, walk
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = REPO_ROOT / "verenigingen"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "validation" / "harness_super_skip_baseline.txt"

HARNESS_ROOTS = {"VereningingenTestCase", "EnhancedTestCase"}
LIFECYCLE_METHODS = ("setUp", "tearDown", "setUpClass", "tearDownClass")

EXCLUDE_DIR_PARTS = {
    "archived_unused",
    "archived_deleted",
    "archived_removal",
    "node_modules",
    ".git",
}


@dataclass
class ClassInfo:
    bases: list = field(default_factory=list)
    # method name -> True if a super().<name>(...) call exists in its body
    methods: dict = field(default_factory=dict)
    file: Path = None
    lineno: int = 0


def _is_scannable(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIR_PARTS:
        return False
    return path.name.startswith("test_") or "tests" in path.parts


def _iter_py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_PARTS]
        for name in filenames:
            if name.endswith(".py"):
                p = Path(dirpath) / name
                if _is_scannable(p.relative_to(root)):
                    yield p


def _base_name(node) -> str:
    """Best-effort textual name of a base-class expression (Name or Attribute)."""
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Attribute):
        return node.attr
    return None


class _SuperCallFinder(NodeVisitor):
    """True if a `super().<method_name>(...)` call appears anywhere in a subtree."""

    def __init__(self, method_name):
        self.method_name = method_name
        self.found = False

    def visit_Call(self, node):
        func = node.func
        if (
            isinstance(func, Attribute)
            and func.attr == self.method_name
            and isinstance(func.value, Call)
            and isinstance(func.value.func, Name)
            and func.value.func.id == "super"
        ):
            self.found = True
        self.generic_visit(node)


def _method_calls_super(func_node) -> bool:
    finder = _SuperCallFinder(func_node.name)
    finder.visit(func_node)
    return finder.found


def _collect_classes(root: Path) -> dict:
    """file-order-stable class_name -> ClassInfo across every scannable file.

    A duplicate class name across files overwrites the earlier entry, same
    trade-off harness_method_shadow_validator.py accepts (see its own
    docstring) -- name resolution here is a heuristic, not an import graph.
    """
    registry = {}
    for path in sorted(_iter_py_files(root)):
        try:
            source = path.read_text(encoding="utf-8")
            tree = parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            _visit_top_level_classes(node, path, root, registry)
    return registry


def _visit_top_level_classes(node, path, root, registry):
    """Record a module-level class def; ignores anything that is not one."""
    if not isinstance(node, ClassDef):
        return
    bases = [b for b in (_base_name(n) for n in node.bases) if b]
    methods = {}
    for item in node.body:
        if isinstance(item, FunctionDef) and item.name in LIFECYCLE_METHODS:
            methods[item.name] = _method_calls_super(item)
    registry[node.name] = ClassInfo(
        bases=bases, methods=methods, file=path.relative_to(root), lineno=node.lineno
    )


def _is_harness_rooted(name: str, registry: dict, _seen=None) -> bool:
    if name in HARNESS_ROOTS:
        return True
    if _seen is None:
        _seen = set()
    if name in _seen or name not in registry:
        return False
    _seen.add(name)
    return any(_is_harness_rooted(base, registry, _seen) for base in registry[name].bases)


@dataclass
class Violation:
    file: str
    class_name: str
    method: str
    lineno: int

    def key(self) -> str:
        return f"{self.file}::{self.class_name}::{self.method}"


def find_violations(root: Path = SCAN_ROOT) -> list:
    registry = _collect_classes(root)
    violations = []
    for name, info in registry.items():
        if name in HARNESS_ROOTS:
            continue  # the roots themselves correctly call super() up to FrappeTestCase
        if not _is_harness_rooted(name, registry):
            continue
        for method, has_super in info.methods.items():
            if not has_super:
                violations.append(
                    Violation(
                        file=str(info.file),
                        class_name=name,
                        method=method,
                        lineno=info.lineno,
                    )
                )
    violations.sort(key=lambda v: v.key())
    return violations


def _load_baseline(path: Path) -> set:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(line.split("  #", 1)[0].strip())
    return keys


def _write_baseline(path: Path, violations: list) -> None:
    lines = [
        "# Harness-base classes that override a lifecycle method without calling",
        "# super() -- see #1307. Upward-only: a NEW entry here must be a deliberate,",
        "# justified addition (state before/after counts in the PR), not a silent",
        "# widening. Regenerate with:",
        "#   python scripts/validation/harness_super_skip_validator.py --update-baseline <this file>",
    ]
    for v in violations:
        lines.append(f"{v.key()}  # harness-super-skip")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update-baseline", type=Path, default=None)
    args = parser.parse_args()

    violations = find_violations()

    if args.update_baseline is not None:
        _write_baseline(args.update_baseline, violations)
        print(f"Wrote {len(violations)} entries to {args.update_baseline}")
        return 0

    baseline = _load_baseline(args.baseline)
    found_keys = {v.key() for v in violations}
    new_violations = [v for v in violations if v.key() not in baseline]
    stale_baseline = baseline - found_keys

    if args.report:
        print(f"Total harness-rooted lifecycle overrides skipping super(): {len(violations)}")
        for v in violations:
            marker = "NEW" if v.key() not in baseline else "baselined"
            print(f"  [{marker}] {v.file}:{v.lineno} {v.class_name}.{v.method}")
        if stale_baseline:
            print(f"\n{len(stale_baseline)} baseline entries no longer found (fixed -- shrink the baseline):")
            for k in sorted(stale_baseline):
                print(f"  {k}")

    if new_violations:
        print(f"FAIL: {len(new_violations)} NEW harness-super-skip violation(s):")
        for v in new_violations:
            print(f"  {v.file}:{v.lineno} {v.class_name}.{v.method} -- add super().{v.method}(...)")
        return 1

    print(f"OK: {len(violations)} harness-super-skip finding(s), all baselined ({len(baseline)} total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
