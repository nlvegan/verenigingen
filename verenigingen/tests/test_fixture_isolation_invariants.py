"""Invariants for test fixtures that must not depend on their neighbours.

Every defect these guard was found in CI on 2026-08-20, each as several instances
of one shape: a fixture assuming it was alone on the database. They are written as
invariants rather than per-instance assertions because in every case the instance
CI reported was not the only one -- the seeding bug had seven sites, the drain
priority eight, the region code six.

Source-level where the property is about how tests are WRITTEN (a behavioural test
cannot see a site that has not gone wrong yet), behavioural where it is about what
the framework DOES.
"""

import ast
import os
import re

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_ROOT = os.path.join(APP_ROOT, "tests")


def _iter_test_sources(root=None):
    """(path, source) for every test module in the app."""
    for base in {root or APP_ROOT}:
        for dirpath, _dirnames, filenames in os.walk(base):
            for fn in filenames:
                if not fn.startswith("test_") or not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, encoding="utf-8") as handle:
                        yield path, handle.read()
                except (OSError, UnicodeDecodeError):  # pragma: no cover
                    continue


def _rel(path):
    return os.path.relpath(path, APP_ROOT)


class TestSeededRowsLeaveTheNamingSeriesAlone(VereningingenTestCase):
    """A row inserted with db_insert() must preset its own name.

    ``db_insert`` autonames only ``if not self.name``, so a seeded row otherwise
    draws from the shared naming series. A submitted document's GL / Payment Ledger
    Entries can outlive it while the series counter rolls back with the test
    transaction, so a later row drawing the same name inherits the orphans and can
    no longer be deleted -- CI: "is linked with Payment Ledger Entry". Seven sites
    had this; the series number varies per shard, so a narrower fix just moves it.
    """

    def _series_named(self, doctype):
        try:
            autoname = frappe.get_meta(doctype).autoname or ""
        except Exception:
            return False
        autoname = autoname.lower()
        # Not just `naming_series:` -- `format:...{####}` (Member) and old-style
        # expression autonames (`ACC-GLE-.YYYY.-.#####`, GL Entry) also draw from
        # tabSeries, and an earlier version of this check missed both.
        return "naming_series" in autoname or "#" in autoname

    def test_db_insert_on_a_series_named_doctype_presets_the_name(self):
        offenders = []
        for path, source in _iter_test_sources():
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                created, named, inserted = {}, set(), {}
                for node in ast.walk(fn):
                    # var = frappe.new_doc("DocType")
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "new_doc"
                        and node.value.args
                        and isinstance(node.value.args[0], ast.Constant)
                    ):
                        created[node.targets[0].id] = node.value.args[0].value
                    # var.name = ...
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Attribute)
                        and node.targets[0].attr == "name"
                        and isinstance(node.targets[0].value, ast.Name)
                    ):
                        named.add(node.targets[0].value.id)
                    # var.db_insert()
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "db_insert"
                        and isinstance(node.func.value, ast.Name)
                    ):
                        inserted[node.func.value.id] = node.lineno

                for var, lineno in inserted.items():
                    doctype = created.get(var)
                    if not doctype or var in named:
                        continue
                    if self._series_named(doctype):
                        offenders.append(f"{_rel(path)}:{lineno} {var}=new_doc({doctype!r}).db_insert()")
            # `source` stays bound as a local otherwise, and Frappe's traceback
            # renderer dumps every local -- 12KB of an unrelated file per failure.
            del tree, source

        self.assertEqual(
            sorted(offenders),
            [],
            "these seeded rows draw a name from the shared naming series and can "
            "inherit another document's orphaned ledger rows; preset a unique name "
            f"(EnhancedTestCase.unique_seed_name) before db_insert():\n  " + "\n  ".join(sorted(offenders)),
        )


class TestExpenseClaimDrainsBeforeItsEmployee(VereningingenTestCase):
    """Cancelling a submitted Expense Claim reads its employee as the GL party, and
    the drain deletes highest-priority first. A claim tracked below the Employee it
    points at therefore cannot be cancelled -- CI: "Could not find Party".
    Eight files had the pair inverted.

    Read with AST, not a regex: `track_document(doctype, name)` takes `priority=0`
    by default, so a claim tracked WITHOUT an explicit priority sits below an
    Employee tracked at 2 -- and a regex keyed on `priority=` cannot see it.
    """

    # ONLY the priority-ordered trackers. VereningingenTestCase.track_doc (and the
    # secure factory's) take `depends_on`, not `priority`, and their cleanup walks
    # `reversed(self._test_docs)` -- LIFO, so registration order already deletes a
    # claim before the employee registered ahead of it. Judging those by priority
    # reports a false positive (test_document_links.py was one).
    TRACKERS = {"track_document", "_track_test_document"}

    @staticmethod
    def _literal(node):
        return node.value if isinstance(node, ast.Constant) else None

    def _tracked_priorities(self, tree):
        """{doctype: [priority, ...]} for every tracking call in the tree."""
        found = {}
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in self.TRACKERS or not call.args:
                continue
            doctype = self._literal(call.args[0])
            if doctype not in ("Expense Claim", "Employee"):
                continue
            priority = 0  # the signature default
            for kw in call.keywords:
                if kw.arg == "priority":
                    value = self._literal(kw.value)
                    if not isinstance(value, int):
                        priority = None  # computed; cannot judge, do not guess
                        break
                    priority = value
            if priority is not None:
                found.setdefault(doctype, []).append(priority)
        return found

    def test_no_test_tracks_an_expense_claim_below_its_employee(self):
        offenders = []
        for path, source in _iter_test_sources():
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover
                continue
            found = self._tracked_priorities(tree)
            claims, employees = found.get("Expense Claim"), found.get("Employee")
            if claims and employees and min(claims) <= max(employees):
                offenders.append(f"{_rel(path)} (Expense Claim={min(claims)} <= Employee={max(employees)})")
            del tree, source

        self.assertEqual(
            sorted(offenders),
            [],
            "an Expense Claim must drain BEFORE the Employee it names as GL party "
            "(higher priority drains first):\n  " + "\n  ".join(sorted(offenders)),
        )


class TestRegionCodesAreNotDrawnFromANarrowSpace(VereningingenTestCase):
    """region_code is UNIQUE and capped at 5 chars, so a code DERIVED from a counter
    has a tiny space -- "R" + 4 digits is 10,000 values, "TR" + 3 is 1,000, and one
    site used 10. CI: "Region Code R7655 already exists", which cost a 12-shard run.

    The rule is not "never compute a code" -- it is "either allocate one that was
    verified free, or verify it yourself". A literal is fine (deliberate, and the
    format-validation tests need specific values); a computed code is fine if the
    same function checks `frappe.db.exists("Region", ...)`. Anything else is a
    collision waiting for a warm site.

    An earlier regex version of this check matched exactly the one shape that had
    already been fixed and missed `f"TR{seq}"[:5]`, `base + str(n)[-4:]`,
    `generate_hash(4).upper()[:4]` and the kwarg form.
    """

    ALLOCATORS = {"allocate_free_region_code", "unique_region_code"}

    def _region_code_values(self, tree):
        """(lineno, value_node) for every region_code assignment in the tree."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "region_code":
                        yield value.lineno, value
            elif isinstance(node, ast.keyword) and node.arg == "region_code":
                yield node.value.lineno, node.value
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    name = getattr(target, "attr", None) or getattr(target, "id", None)
                    if name == "region_code":
                        yield node.value.lineno, node.value

    def _allocated_names(self, fn_node):
        """Locals bound to an allocator result: `code = self.unique_region_code()`."""
        names = set()
        for node in ast.walk(fn_node):
            if isinstance(node, ast.Assign) and self._calls_allocator(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    def _calls_allocator(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                name = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if name in self.ALLOCATORS:
                    return True
        return False

    def _is_allocated(self, node, allocated_names):
        if self._calls_allocator(node):
            return True
        # `code` and derivations of it, e.g. `code.lower()` for the
        # case-insensitivity test, are as safe as the allocation that produced them.
        return any(isinstance(sub, ast.Name) and sub.id in allocated_names for sub in ast.walk(node))

    @staticmethod
    def _checks_existence(fn_node):
        for sub in ast.walk(fn_node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                if sub.func.attr in ("exists", "get_value", "get_all"):
                    for arg in sub.args:
                        if isinstance(arg, ast.Constant) and arg.value == "Region":
                            return True
        return False

    def test_a_computed_region_code_is_either_allocated_or_checked(self):
        offenders = []
        for path, source in _iter_test_sources():
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                checked = self._checks_existence(fn)
                allocated = self._allocated_names(fn)
                for lineno, value in self._region_code_values(fn):
                    if isinstance(value, ast.Constant):
                        continue  # a deliberate literal
                    if self._is_allocated(value, allocated) or checked:
                        continue
                    offenders.append(f"{_rel(path)}:{lineno}")
            del tree, source

        self.assertEqual(
            sorted(set(offenders)),
            [],
            "a computed region_code must either come from a checked allocator "
            "(unique_region_code / allocate_free_region_code) or be verified free in "
            "the same function:\n  " + "\n  ".join(sorted(set(offenders))),
        )
