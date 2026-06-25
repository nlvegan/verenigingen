"""
DB-backed integration tests for shared db_helpers utilities.

Tests ``ensure_table_exists``, ``insert_audit_row``, and ``update_row_status``
against a real MariaDB table that is created in setUp and dropped in tearDown.
No business-logic mocks; every assertion reads back from the DB.
"""

import hashlib
import time
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.shared.db_helpers import (
    ensure_table_exists,
    insert_audit_row,
    update_row_status,
)

# Use a deterministic suffix so the table name is the same within a test run
# but unique enough to avoid collision with other runs/sites.
_SUFFIX = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
# Full MariaDB table name (with "tab" prefix, matching Frappe convention).
# All characters match ^[A-Za-z0-9_]+$ so the identifier validator accepts it.
_TABLE = f"tabZZ_Test_DRY_{_SUFFIX}"

_CREATE_SQL = f"""
    CREATE TABLE IF NOT EXISTS `{_TABLE}` (
        `name`          varchar(255) NOT NULL PRIMARY KEY,
        `status`        varchar(50)  DEFAULT 'pending',
        `error_message` text         DEFAULT NULL,
        `completed_at`  datetime(6)  DEFAULT NULL,
        `payload`       text         DEFAULT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class TestDbHelpers(EnhancedTestCase):
    """Integration tests for db_helpers using a throwaway temp table."""

    # ------------------------------------------------------------------
    # Life-cycle
    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()
        # Step 1 (TDD): create the temp table via the helper under test.
        # Pass the full table name (including "tab" prefix) — it satisfies the
        # ^[A-Za-z0-9_]+$ identifier guard and matches the backtick-quoted SQL.
        ensure_table_exists(_CREATE_SQL, table_name=_TABLE)

    def tearDown(self):
        frappe.db.sql(f"DROP TABLE IF EXISTS `{_TABLE}`")  # noqa: S608
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _make_row(self, suffix: str = "") -> dict:
        """Return a minimal valid row dict."""
        name = f"TEST-ROW-{_SUFFIX}{suffix}"
        return {
            "name": name,
            "status": "pending",
            "payload": "hello",
        }

    def _read_row(self, name: str) -> dict | None:
        rows = frappe.db.sql(
            f"SELECT name, status, error_message, completed_at, payload FROM `{_TABLE}` WHERE name = %s",  # noqa: S608
            (name,),
            as_dict=True,
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # ensure_table_exists
    # ------------------------------------------------------------------

    def test_ensure_table_exists_creates_table(self):
        """Table created in setUp should be queryable."""
        # If the table does not exist, the INSERT below raises OperationalError.
        row = self._make_row("-create")
        insert_audit_row(_TABLE, row)
        result = self._read_row(row["name"])
        self.assertIsNotNone(result)

    def test_ensure_table_exists_idempotent(self):
        """Calling ensure_table_exists twice must not raise, and the table must exist."""
        tname = _TABLE
        # First call already done in setUp; second call must also succeed.
        ensure_table_exists(_CREATE_SQL, table_name=tname)
        # Assert the table actually exists — meaningful even when errors are swallowed.
        count = frappe.db.sql(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
            (frappe.conf.db_name, tname),
        )[0][0]
        self.assertEqual(
            count, 1, f"Table {tname!r} not found in information_schema after ensure_table_exists"
        )

    def test_ensure_table_exists_invalid_name_raises(self):
        """An identifier with forbidden characters must raise ValueError."""
        with self.assertRaises(ValueError):
            ensure_table_exists(_CREATE_SQL, table_name="bad-name!")

    # ------------------------------------------------------------------
    # insert_audit_row
    # ------------------------------------------------------------------

    def test_insert_audit_row_returns_name(self):
        """insert_audit_row must return the inserted name."""
        row = self._make_row("-ins-name")
        tname = _TABLE
        returned = insert_audit_row(tname, row)
        self.assertEqual(returned, row["name"])

    def test_insert_audit_row_values_persisted(self):
        """Values in the row dict must be readable back from the DB."""
        row = self._make_row("-ins-vals")
        tname = _TABLE
        insert_audit_row(tname, row)
        result = self._read_row(row["name"])
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["payload"], "hello")

    def test_insert_audit_row_invalid_table_raises(self):
        """A table name with forbidden chars must raise ValueError before any SQL."""
        with self.assertRaises(ValueError):
            insert_audit_row("bad-table!", {"name": "x"})

    def test_insert_audit_row_invalid_column_raises(self):
        """A column name with forbidden chars must raise ValueError before any SQL."""
        tname = _TABLE
        with self.assertRaises(ValueError):
            insert_audit_row(tname, {"name": "x", "bad-col!": "v"})

    # ------------------------------------------------------------------
    # update_row_status
    # ------------------------------------------------------------------

    def test_update_row_status_basic(self):
        """Status field must be updated correctly."""
        row = self._make_row("-upd-basic")
        tname = _TABLE
        insert_audit_row(tname, row)

        update_row_status(tname, row["name"], "completed")

        result = self._read_row(row["name"])
        self.assertEqual(result["status"], "completed")

    def test_update_row_status_with_error_message(self):
        """error_message field must be updated when supplied."""
        row = self._make_row("-upd-err")
        tname = _TABLE
        insert_audit_row(tname, row)

        update_row_status(tname, row["name"], "failed", error_message="something broke")

        result = self._read_row(row["name"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_message"], "something broke")

    def test_update_row_status_with_completed_at(self):
        """completed_at field must be updated when supplied."""
        row = self._make_row("-upd-ts")
        tname = _TABLE
        insert_audit_row(tname, row)

        ts = frappe.utils.now()
        update_row_status(tname, row["name"], "completed", completed_at=ts)

        result = self._read_row(row["name"])
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["completed_at"])

    def test_update_row_status_invalid_table_raises(self):
        """A table name with forbidden chars must raise ValueError."""
        with self.assertRaises(ValueError):
            update_row_status("bad-table!", "pk", "done")

    def test_update_row_status_invalid_pk_column_raises(self):
        """A pk_column with forbidden chars must raise ValueError."""
        tname = _TABLE
        with self.assertRaises(ValueError):
            update_row_status(tname, "pk", "done", pk_column="bad-col!")


if __name__ == "__main__":
    unittest.main()
