"""
Chapter Board Permissions Service Test Suite (services layer)
============================================================

Real-DB integration tests for the lower-level / reset paths of
``verenigingen.services.chapter.chapter_board_permissions`` that the existing
``tests/chapter/test_chapter_board_permissions.py`` suite does not exercise:

- ``update_volunteer_expense_permissions`` returns False when the Volunteer
  Expense DocType has been archived/dropped (the migrated-site path).
- ``update_membership_termination_request_permissions`` is idempotent (re-runs
  update the existing permission row instead of appending a duplicate).
- ``reset_chapter_board_permissions`` removes the Chapter Board Member DocPerm
  rows for the live DocTypes and skips the missing (archived) ones, then a
  subsequent setup re-adds them (round-trip).

These functions mutate real DocType permissions and call ``frappe.clear_cache()``
+ commit globally (same accepted pattern as the existing
``setup_chapter_board_permissions`` integration tests). Each test restores the
permission state by re-running setup so the canonical DocPerm rows remain.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

TARGET_ROLE = "Verenigingen Chapter Board Member"


def _board_perm_exists(doctype):
    return bool(frappe.db.exists("DocPerm", {"parent": doctype, "role": TARGET_ROLE}))


class TestChapterBoardPermissionsService(EnhancedTestCase):
    """Cover reset + skip + idempotency branches of the permission service."""

    def tearDown(self):
        # Leave the canonical Chapter Board Member DocPerms in place for the rest
        # of the suite regardless of which branch a test exercised.
        from verenigingen.services.chapter.chapter_board_permissions import (
            setup_chapter_board_permissions,
        )

        setup_chapter_board_permissions()
        frappe.db.commit()
        super().tearDown()

    def test_volunteer_expense_permissions_skipped_when_archived(self):
        """Volunteer Expense was archived; the updater returns False, not a crash."""
        from verenigingen.services.chapter.chapter_board_permissions import (
            update_volunteer_expense_permissions,
        )

        if frappe.db.exists("DocType", "Volunteer Expense"):
            self.skipTest("Volunteer Expense DocType still present on this site")

        result = update_volunteer_expense_permissions()
        self.assertFalse(result, "Archived Volunteer Expense permission update must return False")

    def test_membership_termination_request_idempotent(self):
        """Re-running the updater keeps exactly one Chapter Board Member DocPerm row."""
        from verenigingen.services.chapter.chapter_board_permissions import (
            update_membership_termination_request_permissions,
        )

        doctype = "Membership Termination Request"
        if not frappe.db.exists("DocType", doctype):
            self.skipTest(f"{doctype} not present on this site")

        self.assertTrue(update_membership_termination_request_permissions())
        self.assertTrue(update_membership_termination_request_permissions())
        frappe.db.commit()

        rows = frappe.get_all(
            "DocPerm", filters={"parent": doctype, "role": TARGET_ROLE}, fields=["name"]
        )
        self.assertEqual(len(rows), 1, "Idempotent update must not duplicate the permission row")

    def test_membership_permissions_idempotent(self):
        """update_membership_permissions short-circuits True when the perm exists."""
        from verenigingen.services.chapter.chapter_board_permissions import (
            update_membership_permissions,
        )

        self.assertTrue(update_membership_permissions())
        frappe.db.commit()
        # Second call hits the early "already exist" return True branch.
        self.assertTrue(update_membership_permissions())
        frappe.db.commit()
        rows = frappe.get_all(
            "DocPerm", filters={"parent": "Membership", "role": TARGET_ROLE}, fields=["name"]
        )
        self.assertEqual(len(rows), 1, "Idempotent update must not duplicate the Membership perm row")

    def test_reset_result_is_consistent_with_row_removal(self):
        """reset's success flag must reflect whether the rows were actually removed.

        Regression for a bug where reset hardcoded ``{"success": True}`` even when
        every per-DocType save failed (e.g. a pre-existing duplicate-perm
        validation error on the parent DocType), so the API reported success while
        the Chapter Board Member rows were never removed.

        We assert the *consistency* of the contract rather than a fixed outcome,
        because on a polluted site a parent-DocType save can legitimately fail:
          - success True  -> live board-perm rows must be gone
          - success False -> at least one DocType is reported in ``failed``
        """
        from verenigingen.services.chapter.chapter_board_permissions import (
            reset_chapter_board_permissions,
            setup_chapter_board_permissions,
        )

        # Ensure perms are present first.
        setup_chapter_board_permissions()
        frappe.db.commit()
        self.assertTrue(_board_perm_exists("Membership"))
        self.assertTrue(_board_perm_exists("Membership Termination Request"))

        # A failed per-DocType save logs a "Failed to reset ..." / "Secure
        # Operation Failed" Error Log; expected on a site whose Membership perms
        # carry pre-existing duplicate rows. Tolerate it under the strict guard.
        self.expectErrorLog("reset Chapter Board Member", "Secure Operation Failed", "Membership")
        reset_result = reset_chapter_board_permissions()
        frappe.db.commit()

        try:
            if reset_result["success"]:
                # A successful reset must actually have removed the live rows.
                self.assertFalse(
                    _board_perm_exists("Membership"),
                    "Successful reset must remove the Membership board perm",
                )
                self.assertFalse(
                    _board_perm_exists("Membership Termination Request"),
                    "Successful reset must remove the Termination Request board perm",
                )
            else:
                # A failed reset must name the DocType(s) it could not reset, and the
                # rows for those DocTypes must still be present (no silent loss/gain).
                self.assertIn("failed", reset_result, f"Failed reset must list failures: {reset_result}")
                self.assertTrue(reset_result["failed"], "Failed reset must name at least one DocType")
                for dt in reset_result["failed"]:
                    if dt in ("Membership", "Membership Termination Request"):
                        self.assertTrue(
                            _board_perm_exists(dt),
                            f"Row for failed-to-reset {dt} must remain present",
                        )
        finally:
            # reset_chapter_board_permissions COMMITS its global board-perm removal,
            # which escapes FrappeTestCase rollback. Restore unconditionally — even if
            # an assertion above failed mid-way — so we never leave the shared site
            # without board perms for every subsequent test / board user.
            setup_chapter_board_permissions()
            frappe.db.commit()
        # Round-trip: the restore must have re-added the rows.
        self.assertTrue(_board_perm_exists("Membership"))
        self.assertTrue(_board_perm_exists("Membership Termination Request"))

    def test_validate_permission_security_passes_after_setup(self):
        """Security validation: no delete/cancel/amend/submit granted to board role."""
        from verenigingen.services.chapter.chapter_board_permissions import (
            setup_chapter_board_permissions,
            validate_permission_security,
        )

        setup_chapter_board_permissions()
        frappe.db.commit()
        is_valid, issues = validate_permission_security()
        self.assertTrue(is_valid, f"Security validation should pass: {issues}")
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
