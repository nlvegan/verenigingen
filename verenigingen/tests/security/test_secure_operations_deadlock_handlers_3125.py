"""
#3125: three handlers in verenigingen/utils/secure_operations.py turned a MariaDB
1213/1205 (QueryDeadlockError / QueryTimeoutError) into an ordinary failure:

* verify_document_integrity: a deadlock in the link-existence read became an
  "Integrity verification failed" violation string and the operation carried on.
* _execute_document_operation, timestamp-mismatch retry: a deadlock in doc.reload()
  was wrapped into a ValidationError, which the outer handler turns into success=False.
* get_system_user_for_operation: a deadlock in the settings/user reads was wrapped
  into ConfigurationError.

The deadlock is injected at the DB read the handler really makes (frappe.db.exists /
Document.reload / frappe.get_single); a real 1213 cannot be provoked deterministically.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import secure_operations as so

DEADLOCKS_3125 = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)


class _StaleDoc3125:
    """Minimal doc whose save() always reports a stale timestamp and whose reload() raises."""

    doctype = "Bulk Operation Tracker"  # tolerant doctype: takes the retry branch
    name = "TEST-3125"

    def __init__(self, reload_error):
        self.flags = frappe._dict()
        self._reload_error = reload_error

    def save(self):
        raise frappe.TimestampMismatchError("stale")

    def reload(self):
        raise self._reload_error


class TestSecureOperationsDeadlockHandlers3125(EnhancedTestCase):
    def _linked_todo_3125(self, user="Administrator"):
        return frappe.get_doc({"doctype": "ToDo", "description": "x", "allocated_to": user})

    # ---- verify_document_integrity ----
    def test_integrity_read_deadlock_escapes(self):
        doc = self._linked_todo_3125()
        for exc in DEADLOCKS_3125:
            with self.subTest(exc=exc.__name__), patch.object(frappe.db, "exists", side_effect=exc("1213")):
                with self.assertRaises(exc):
                    so.verify_document_integrity(doc, ["link_validation"])

    def test_integrity_ordinary_read_error_still_reported(self):
        """Control: a non-deadlock error keeps the violation-string behaviour."""
        doc = self._linked_todo_3125()
        with patch.object(frappe.db, "exists", side_effect=RuntimeError("boom")):
            violations = so.verify_document_integrity(doc, ["link_validation"])
        self.assertEqual(len(violations), 1)
        self.assertIn("Integrity verification failed", violations[0])

    def test_integrity_real_broken_link_still_reported(self):
        """Control with a real row to find: an unknown user is a broken link, no patching."""
        doc = self._linked_todo_3125(user="no-such-user-3125@example.com")
        violations = so.verify_document_integrity(doc, ["link_validation"])
        self.assertEqual(len(violations), 1)
        self.assertIn("Broken link in allocated_to", violations[0])

    # ---- reload after a timestamp mismatch ----
    def test_reload_deadlock_after_timestamp_mismatch_escapes(self):
        for exc in DEADLOCKS_3125:
            with self.subTest(exc=exc.__name__):
                with self.assertRaises(exc):
                    so._execute_document_operation(_StaleDoc3125(exc("1213")), "save")

    def test_reload_ordinary_error_still_wrapped(self):
        """Control: a non-deadlock reload failure is still the chained ValidationError."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            so._execute_document_operation(_StaleDoc3125(RuntimeError("gone")), "save")
        self.assertIn("could not be reloaded", str(ctx.exception))

    # ---- get_system_user_for_operation ----
    def test_system_user_read_deadlock_escapes(self):
        settings = frappe._dict(creation_user="Administrator")
        for exc in DEADLOCKS_3125:
            with self.subTest(exc=exc.__name__):
                with patch.object(frappe, "get_single", return_value=settings), patch.object(
                    frappe.db, "exists", side_effect=exc("1213")
                ):
                    with self.assertRaises(exc):
                        so.get_system_user_for_operation("t3125")

    def test_system_user_ordinary_read_error_still_configuration_error(self):
        settings = frappe._dict(creation_user="Administrator")
        with patch.object(frappe, "get_single", return_value=settings), patch.object(
            frappe.db, "exists", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(so.ConfigurationError):
                so.get_system_user_for_operation("t3125")
