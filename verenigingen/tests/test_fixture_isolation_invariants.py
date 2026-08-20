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
        return autoname.lower().startswith("naming_series")

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
    """

    TRACK = re.compile(
        r"""track(?:_test)?_document\(\s*["'](Expense Claim|Employee)["'][^)]*?priority\s*=\s*(-?\d+)""",
        re.S,
    )

    def test_no_test_tracks_an_expense_claim_below_its_employee(self):
        offenders = []
        for path, source in _iter_test_sources():
            found = self.TRACK.findall(source)
            if not found:
                continue
            claims = [int(p) for dt, p in found if dt == "Expense Claim"]
            employees = [int(p) for dt, p in found if dt == "Employee"]
            if claims and employees and min(claims) <= max(employees):
                offenders.append(f"{_rel(path)} (Expense Claim={min(claims)} <= Employee={max(employees)})")

        self.assertEqual(
            sorted(offenders),
            [],
            "an Expense Claim must drain BEFORE the Employee it names as GL party "
            "(higher priority drains first):\n  " + "\n  ".join(sorted(offenders)),
        )


class TestRegionCodesAreNotDrawnFromANarrowSpace(VereningingenTestCase):
    """region_code is UNIQUE and capped at 5 chars, so a code sliced off a counter
    has a tiny space -- "R" + 4 digits is 10,000 values, "TR" + 3 is 1,000, and one
    site used 10. CI: "Region Code R7655 already exists", which cost a whole
    12-shard run. Use EnhancedTestCase.unique_region_code(), which checks.
    """

    SLICED = re.compile(r"""["']region_code["']\s*:\s*f["'][^"']*\{[^}]*\[\s*:\s*\d+\s*\]""")

    def test_no_test_slices_a_region_code_out_of_a_counter(self):
        offenders = []
        for path, source in _iter_test_sources():
            for lineno, line in enumerate(source.splitlines(), start=1):
                if self.SLICED.search(line):
                    offenders.append(f"{_rel(path)}:{lineno} {line.strip()}")

        self.assertEqual(
            sorted(offenders),
            [],
            "region_code sliced from a counter collides; allocate one that is "
            "verified free:\n  " + "\n  ".join(sorted(offenders)),
        )


class TestDeletingInsideATestTransactionDoesNotStick(VereningingenTestCase):
    """The premise a test-setup purge cannot rely on.

    `_purge_orphan_claims` deleted stale rows in setUp so they could not pollute a
    fixture's aggregates. It could never work: the delete ran inside the test
    transaction, and tearDown's rollback restored every row -- after which the drain
    tried to cancel rows whose employee had never existed, reported them as leaks and
    re-committed them, so one orphan made the module leak on that site forever (#407).

    This pins the mechanism so the next author reaches for a clean name instead of
    cleaning a dirty one.
    """

    def test_a_row_deleted_without_commit_returns_after_rollback(self):
        note = frappe.get_doc(
            {"doctype": "Note", "title": f"purge-premise-{frappe.generate_hash(length=10)}"}
        ).insert()
        frappe.db.commit()  # the row exists independently of this test's transaction
        name = note.name
        try:
            self.assertTrue(frappe.db.exists("Note", name))

            frappe.delete_doc("Note", name, force=True)
            self.assertFalse(
                frappe.db.exists("Note", name), "delete should be visible inside the transaction"
            )

            frappe.db.rollback()  # what tearDown does

            self.assertTrue(
                frappe.db.exists("Note", name),
                "a delete issued inside the test transaction must be understood to be "
                "UNDONE by rollback -- setup code cannot purge rows and expect them gone",
            )
        finally:
            if frappe.db.exists("Note", name):
                frappe.delete_doc("Note", name, force=True)
                frappe.db.commit()
