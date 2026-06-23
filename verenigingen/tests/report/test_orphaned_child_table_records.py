"""
Real-integration tests for the *Orphaned Child Table Records* script report
(``verenigingen/verenigingen/report/orphaned_child_table_records/``).

This report was at 0% coverage. It is a LIVE standard Script Report
(ref_doctype DocType, roles System Manager / Verenigingen Administrator) that
delegates to ``orphaned_child_table_cleanup.detect_orphaned_child_tables`` to
find child rows whose parent document was deleted. It is a data-integrity
diagnostic running real SQL against ``information_schema`` / every child table;
no app-data seeding is required for the happy path.

To exercise the "orphans found" branch we deliberately create a real orphaned
child row (a Has Role row pointing at a non-existent parent) and remove it in
tearDown. We never use DDL, so nothing leaks past rollback.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.orphaned_child_table_records import (
    orphaned_child_table_records as report,
)


class TestOrphanedChildTableRecordsReport(VereningingenTestCase):
    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 5)
        for expected in (
            "child_table",
            "parent_doctype",
            "orphaned_count",
            "sample_parent",
            "module",
        ):
            self.assertIn(expected, fieldnames)

    # --------------------------------------------------------- clean DB branch

    def test_execute_returns_columns_and_list(self):
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(len(columns), 5)
        self.assertIsInstance(data, list)
        # Every returned row must carry the documented keys.
        for row in data:
            self.assertEqual(
                set(row.keys()),
                {"child_table", "parent_doctype", "orphaned_count", "sample_parent", "module"},
            )
            self.assertGreater(row["orphaned_count"], 0)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data = report.execute(None)
        self.assertEqual(len(columns), 5)
        self.assertIsInstance(data, list)

    # --------------------------------------------------------- orphans branch

    def test_seeded_orphan_is_detected(self):
        """Insert a real orphaned Has Role row and assert the report surfaces it.

        ``Has Role`` is a child table (parent=User). We insert a row whose
        parent points at a User that does not exist, creating a genuine
        orphan, then assert the report row shape for it and clean it up.
        """
        orphan_parent = f"nonexistent-user-{frappe.generate_hash(length=8)}@invalid"
        row_name = frappe.generate_hash(length=10)
        self._insert_orphan_has_role(row_name, orphan_parent)
        self.addCleanup(
            lambda: frappe.db.delete("Has Role", {"name": row_name})
        )

        with self.assertNoErrorLog():
            _columns, data = report.execute({})

        has_role_rows = [r for r in data if r["child_table"] == "Has Role"]
        self.assertTrue(
            has_role_rows,
            "the seeded orphaned Has Role row must be detected by the report",
        )
        row = has_role_rows[0]
        self.assertEqual(row["parent_doctype"], "User")
        self.assertGreaterEqual(row["orphaned_count"], 1)
        self.assertTrue(row["sample_parent"], "a sample orphaned parent id must be reported")

    def _insert_orphan_has_role(self, row_name, orphan_parent):
        """Create a genuine orphaned child row (no DML hooks, direct insert)."""
        frappe.db.sql(
            """
            INSERT INTO `tabHas Role`
                (name, parent, parenttype, parentfield, role, creation, modified, owner, modified_by, idx)
            VALUES
                (%(name)s, %(parent)s, 'User', 'roles', 'System Manager',
                 NOW(), NOW(), 'Administrator', 'Administrator', 1)
            """,
            {"name": row_name, "parent": orphan_parent},
        )
