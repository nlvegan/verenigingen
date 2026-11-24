"""
#3172: a failed secondary field sync (Member -> User and friends) must leave an
Error Log row instead of vanishing into a stdlib logger, while still not
blocking the source document's own save.
"""

import frappe

from verenigingen.services.field_sync_service import sync_fields
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFieldSyncFailureVisibility(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.fs_start = frappe.utils.now_datetime()
        self.fs_email = f"fieldsync3172.{frappe.generate_hash(length=6)}@test.local"
        self.fs_member = self.create_test_member(
            first_name="Fieldsync",
            last_name="Visible",
            email=self.fs_email,
            birth_date="1990-01-01",
        )
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": self.fs_email,
                "first_name": "Fieldsync",
                "send_welcome_email": 0,
            }
        ).insert(ignore_permissions=True)
        self.fs_member.user = user.name
        self.fs_member.save(ignore_permissions=True)

    def _fs_error_rows(self):
        # Error Log is MyISAM (non-transactional): scope by creation time and title.
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", self.fs_start], "method": ["like", "%Field sync%"]},
            fields=["name", "method", "error"],
        )

    def _fs_change_first_name(self, value):
        member = frappe.get_doc("Member", self.fs_member.name)
        member.load_doc_before_save()
        member.first_name = value
        return member

    def test_failed_target_save_writes_error_log_and_does_not_raise(self):
        # 141 chars exceeds User.first_name's 140 limit: a real validation failure
        # on the TARGET save (the source is never saved here, so only the sync fails).
        member = self._fs_change_first_name("x" * 141)

        sync_fields(member)  # must not raise

        rows = self._fs_error_rows()
        self.assertTrue(rows, "a failed sync must leave an Error Log row")
        self.assertTrue(
            any(self.fs_member.name in r["method"] and "User" in r["method"] for r in rows),
            f"title must name source and target; got {[r['method'] for r in rows]}",
        )
        # Keyword form: title in `method`, diagnostics in `error`. A swapped
        # (message, title) call would put the label in `error` instead.
        row = next(r for r in rows if self.fs_member.name in r["method"])
        self.assertIn("Field sync failed", row["method"])
        self.assertIn("max characters allowed is 140", row["error"])
        self.assertIn("Traceback", row["error"])

    def test_successful_sync_writes_no_error_log(self):
        member = self._fs_change_first_name("Renamed")

        sync_fields(member)

        self.assertEqual(frappe.db.get_value("User", self.fs_email, "first_name"), "Renamed")
        self.assertEqual(self._fs_error_rows(), [])
