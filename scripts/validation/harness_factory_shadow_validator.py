#!/usr/bin/env python3
"""Blocks a harness-base test class that builds a class-level fixture in
``setUpClass`` (e.g. ``cls.factory = CoreTestDataFactory(...)``), reads it via
``self.<name>`` in a test body, and never re-points ``self.<name>`` back to
the class-level object after the harness's own ``setUp()`` runs.

The defect (#1344, #1347 -- same mechanism as the ``TestPerformanceEdgeCases``
fix in #1307/#1345): ``VereningingenTestCase.setUp()`` and
``EnhancedTestCase.setUp()`` each unconditionally assign their OWN
``self.factory = <fresh, untracked factory>``. Calling ``super().setUp()`` (or
simply never overriding ``setUp()`` at all, so the harness version runs via
normal MRO dispatch) therefore SHADOWS a subclass's class-level ``cls.factory``
for the rest of that test method's ``self`` -- any record created through
``self.factory`` in a test body is tracked by the shadow instance, which
nothing ever cleans up, while ``tearDownClass``'s ``cls.factory.cleanup()``
walks a completely different (empty) object. A passing -- or even skipping --
test announces none of this; the row is simply still in the database once the
process exits.

``harness_super_skip_validator.py`` (#1307) does NOT catch this shape: both
#1344's and #1347's classes call ``super().setUp()`` correctly (or don't
override ``setUp()`` at all, which is not a "skip" in that validator's sense
either -- see its own docstring: "It also does not flag a class that never
overrides the method at all"). The bug here is not a skipped contract, it is
an HONOURED one whose side effect the subclass never accounts for. Hence a
second, narrower guard rather than widening the first one's definition of
"violation".

WHAT THIS GUARD CHECKS (and why it stops here)
-----------------------------------------------
1. Derives the set of "shadow-risk" attribute names by reading the harness
   roots' (``VereningingenTestCase``, ``EnhancedTestCase``) OWN ``setUp()``
   bodies for any ``self.<name> = ...`` assignment. Today that set is just
   ``{"factory"}``, but this is derived from the source, not hardcoded, so a
   future harness change that starts shadowing another attribute is picked up
   automatically.
2. For every OTHER harness-rooted class (transitively, same resolution as
   ``harness_super_skip_validator``): does its own ``setUpClass`` assign
   ``cls.<name>`` for one of those shadow-risk names?
3. If so, is ``self.<name>`` ever READ (anywhere in the class's own method
   bodies -- test methods, helpers, its own ``setUp``/``tearDown``)? A
   ``cls.<name>`` that nothing reads via ``self.<name>`` is not exposed to the
   shadow (matches #1347's own scope note: a class that builds ``cls.factory``
   but never reads ``self.factory`` in a test body has "no exposure").
4. If exposed: does the class's OWN ``setUp()`` -- assuming it calls
   ``super().setUp()`` at all; if it does not, ``harness_super_skip_validator``
   already owns that defect and this guard stays out of its way -- contain a
   re-pointing assignment to ``self.<name>`` (``type(self).<name>``,
   ``self.__class__.<name>``, or any other ``self.<name> = ...``) in a
   statement AFTER the one that calls ``super().setUp()``? A class with NO
   ``setUp()`` override at all is exposed unconditionally (normal MRO dispatch
   runs the harness version, which shadows).

This is mechanical, like its sibling: it does not evaluate whether the
re-pointing assignment's right-hand side is actually correct (points at the
right class, etc.), only whether the shape is present. It also only looks at
module-level classes and top-level statements inside the lifecycle methods it
inspects -- same trade-off as ``harness_super_skip_validator``.

KNOWN LIMITATION: ``_setupclass_attrs`` only reads ``cls.<attr> = ...``
assignments in the LEAF class's OWN ``setUpClass`` -- it does not walk up the
MRO the way ``_is_harness_rooted`` does for base resolution. So a class-level
fixture built in an INTERMEDIATE ancestor's ``setUpClass`` (inherited, not
reassigned, by a leaf that reads ``self.<attr>`` and never overrides
``setUp()``) is exposed to the exact same shadow but produces 0 findings
here. Zero real instances of this shape exist in the tree today (every
current ``cls.factory`` assignment lives in the same class that reads
``self.factory``) -- see
``scripts/validation/tests/test_harness_factory_shadow_validator.py``'s
``KnownLimitationTest`` for a reproduction and a note on what fixing it would
take.

Usage:
    python scripts/validation/harness_factory_shadow_validator.py              # check vs baseline
    python scripts/validation/harness_factory_shadow_validator.py --report     # verbose
    python scripts/validation/harness_factory_shadow_validator.py --update-baseline <path>

Exit codes:
    0  no violations outside the committed baseline
    1  a NEW violation exists (not in the baseline) -- fix it or, if it is
       genuinely pre-existing debt just discovered, add it to the baseline
       deliberately (state before/after counts and justify it, do not do this
       silently -- see CLAUDE.md's "growing a baseline" rule)
    2  usage / IO error
"""

import argparse
import sys
from ast import (
    Assign,
    Attribute,
    Call,
    ClassDef,
    FunctionDef,
    Load,
    Name,
    NodeVisitor,
    parse,
    walk,
)
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.validation.harness_super_skip_validator import (  # noqa: E402
    HARNESS_ROOTS,
    SCAN_ROOT,
    _base_name,
    _collect_classes,
    _is_harness_rooted,
    _iter_py_files,
)

DEFAULT_BASELINE = REPO_ROOT / "scripts" / "validation" / "harness_factory_shadow_baseline.txt"


def _is_super_setup_call(node) -> bool:
    return (
        isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "setUp"
        and isinstance(node.func.value, Call)
        and isinstance(node.func.value.func, Name)
        and node.func.value.func.id == "super"
    )


def _stmt_calls_super_setup(stmt) -> bool:
    return any(_is_super_setup_call(n) for n in walk(stmt))


def _self_attr_assign_targets(assign_node):
    """Names X such that `self.X = ...` is one of this Assign's targets."""
    names = []
    for t in assign_node.targets:
        if isinstance(t, Attribute) and isinstance(t.value, Name) and t.value.id == "self":
            names.append(t.attr)
    return names


def _cls_attr_assign_targets(assign_node):
    """Names X such that `cls.X = ...` is one of this Assign's targets."""
    names = []
    for t in assign_node.targets:
        if isinstance(t, Attribute) and isinstance(t.value, Name) and t.value.id == "cls":
            names.append(t.attr)
    return names


class _SelfAttrReadFinder(NodeVisitor):
    """Names X such that `self.X` is read (Load context) anywhere in a subtree."""

    def __init__(self):
        self.found = set()

    def visit_Attribute(self, node):
        if (
            isinstance(node.ctx, Load)
            and isinstance(node.value, Name)
            and node.value.id == "self"
        ):
            self.found.add(node.attr)
        self.generic_visit(node)


def _find_method(class_node: ClassDef, name: str):
    for item in class_node.body:
        if isinstance(item, FunctionDef) and item.name == name:
            return item
    return None


def _setupclass_attrs(class_node: ClassDef) -> set:
    """Names assigned as `cls.X = ...` anywhere in this class's own setUpClass."""
    method = _find_method(class_node, "setUpClass")
    if method is None:
        return set()
    names = set()
    for node in walk(method):
        if isinstance(node, Assign):
            names.update(_cls_attr_assign_targets(node))
    return names


def _self_attr_reads(class_node: ClassDef) -> set:
    """Names read as `self.X` anywhere in this class's own body (all methods)."""
    finder = _SelfAttrReadFinder()
    for item in class_node.body:
        finder.visit(item)
    return finder.found


def _repointed_after_super(class_node: ClassDef) -> tuple:
    """Returns (has_setup, calls_super, names repointed via self.X = ... in a
    statement AFTER the one calling super().setUp())."""
    method = _find_method(class_node, "setUp")
    if method is None:
        return False, False, set()

    super_idx = None
    for i, stmt in enumerate(method.body):
        if _stmt_calls_super_setup(stmt):
            super_idx = i
            break

    if super_idx is None:
        return True, False, set()

    repointed = set()
    for stmt in method.body[super_idx + 1 :]:
        for node in walk(stmt):
            if isinstance(node, Assign):
                repointed.update(_self_attr_assign_targets(node))
    return True, True, repointed


def _root_shadowed_attrs(root: Path) -> set:
    """Names X such that `self.X = ...` appears anywhere in a harness ROOT
    class's (VereningingenTestCase / EnhancedTestCase) own setUp() body --
    i.e. attributes the harness itself unconditionally (re)assigns per test,
    derived from the source rather than hardcoded."""
    shadowed = set()
    for path in sorted(_iter_py_files(root)):
        try:
            source = path.read_text(encoding="utf-8")
            tree = parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ClassDef) and node.name in HARNESS_ROOTS:
                setup = _find_method(node, "setUp")
                if setup is None:
                    continue
                for sub in walk(setup):
                    if isinstance(sub, Assign):
                        shadowed.update(_self_attr_assign_targets(sub))
    return shadowed


@dataclass
class _ClassRecord:
    node: ClassDef = None
    bases: list = field(default_factory=list)
    file: Path = None


def _collect(root: Path) -> dict:
    """class_name -> _ClassRecord across every scannable file (last write
    wins on a duplicate name -- same name-resolution trade-off as
    harness_super_skip_validator; see its docstring)."""
    registry = {}
    for path in sorted(_iter_py_files(root)):
        try:
            source = path.read_text(encoding="utf-8")
            tree = parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if not isinstance(node, ClassDef):
                continue
            bases = [b for b in (_base_name(n) for n in node.bases) if b]
            registry[node.name] = _ClassRecord(
                node=node, bases=bases, file=path.relative_to(root)
            )
    return registry


@dataclass
class Violation:
    file: str
    class_name: str
    attr: str
    lineno: int

    def key(self) -> str:
        return f"{self.file}::{self.class_name}::{self.attr}"


def find_violations(root: Path = SCAN_ROOT) -> list:
    shadowed_attrs = _root_shadowed_attrs(root)
    # ClassInfo registry (name -> .bases) for harness-rootedness resolution --
    # reuse the sibling validator's own collector so both tools agree on what
    # "harness-rooted" means.
    registry = _collect_classes(root)
    records = _collect(root)

    violations = []
    for name, rec in records.items():
        if name in HARNESS_ROOTS:
            continue
        if not _is_harness_rooted(name, registry):
            continue

        class_attrs = _setupclass_attrs(rec.node)
        candidates = class_attrs & shadowed_attrs
        if not candidates:
            continue

        reads = _self_attr_reads(rec.node)
        has_setup, calls_super, repointed = _repointed_after_super(rec.node)

        for attr in sorted(candidates):
            if attr not in reads:
                continue  # cls.<attr> built, but never read via self.<attr> -- no exposure
            if has_setup and not calls_super:
                continue  # harness_super_skip_validator's territory, not ours
            if attr in repointed:
                continue  # re-pointed after super().setUp() (or has_setup managed it)
            violations.append(
                Violation(file=str(rec.file), class_name=name, attr=attr, lineno=rec.node.lineno)
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
        "# Harness-base classes that build a class-level fixture (cls.<attr>) in",
        "# setUpClass, read it via self.<attr> in a test body, and never re-point",
        "# self.<attr> back to it after the harness's own setUp() shadows it -- see",
        "# #1344 / #1347 (same mechanism as #1307's TestPerformanceEdgeCases fix).",
        "# Upward-only: a NEW entry here must be a deliberate, justified addition",
        "# (state before/after counts in the PR), not a silent widening. Regenerate:",
        "#   python scripts/validation/harness_factory_shadow_validator.py --update-baseline <this file>",
    ]
    for v in violations:
        lines.append(f"{v.key()}  # harness-factory-shadow")
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
        print(f"Total harness-factory-shadow findings: {len(violations)}")
        for v in violations:
            marker = "NEW" if v.key() not in baseline else "baselined"
            print(f"  [{marker}] {v.file}:{v.lineno} {v.class_name}.{v.attr}")
        if stale_baseline:
            print(f"\n{len(stale_baseline)} baseline entries no longer found (fixed -- shrink the baseline):")
            for k in sorted(stale_baseline):
                print(f"  {k}")

    if new_violations:
        print(f"FAIL: {len(new_violations)} NEW harness-factory-shadow violation(s):")
        for v in new_violations:
            print(
                f"  {v.file}:{v.lineno} {v.class_name}.{v.attr} -- re-point self.{v.attr} "
                f"after super().setUp(), e.g. `self.{v.attr} = type(self).{v.attr}`"
            )
        return 1

    print(f"OK: {len(violations)} harness-factory-shadow finding(s), all baselined ({len(baseline)} total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
