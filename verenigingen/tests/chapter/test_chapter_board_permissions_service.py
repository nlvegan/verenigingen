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

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, suspend_insert_capture

TARGET_ROLE = "Verenigingen Chapter Board Member"


def _board_perm_exists(doctype):
    return bool(frappe.db.exists("DocPerm", {"parent": doctype, "role": TARGET_ROLE}))


class TestChapterBoardPermissionsService(EnhancedTestCase):
    """Cover reset + skip + idempotency branches of the permission service."""

    def _cleanup_restore_canonical_board_perms(self):
        """Restore + commit the canonical Chapter Board Member DocPerm rows.

        Shared by every test/tearDown in this class that needs the restore --
        #1579: this mutates real, site-wide DocType permissions that must
        outlive whichever test calls it, not per-test throwaway data.
        Membership Termination Request has no pre-existing duplicate-DocPerm
        defect blocking its removal/recreation (Membership does -- that
        defect is the ONLY reason Membership's row survived this bug by
        accident), so a plain setup_chapter_board_permissions() call can
        create a BRAND NEW DocPerm row. EnhancedTestCase's captured-insert
        drain (running right after, inside tearDown) would otherwise
        force-delete any row inserted during the calling test, silently
        stripping board access on MTR for the rest of the shard.
        suspend_insert_capture() is this repo's established fix for exactly
        this shape (see enhanced_test_factory.py's shared-fixture guidance /
        the `@shared_fixture` decorator it backs).
        """
        from verenigingen.services.chapter.chapter_board_permissions import (
            setup_chapter_board_permissions,
        )

        with suspend_insert_capture():
            result = setup_chapter_board_permissions()
            frappe.db.commit()
        return result

    def tearDown(self):
        # Leave the canonical Chapter Board Member DocPerms in place for the
        # rest of the suite regardless of which branch a test exercised.
        self._cleanup_restore_canonical_board_perms()
        super().tearDown()

        # Fail loud (#1579) instead of silently leaving the rest of the shard
        # without board access: assert the canonical rows are still present
        # AFTER the harness's own cleanup (the drains above) has run, for
        # every DocType actually shipped on this site.
        live_doctypes = ["Membership", "Membership Termination Request"]
        if frappe.db.exists("DocType", "Volunteer Expense"):
            live_doctypes.append("Volunteer Expense")
        for live_doctype in live_doctypes:
            self.assertTrue(
                _board_perm_exists(live_doctype),
                f"Chapter Board Member permission missing on {live_doctype} "
                "after tearDown restore + harness cleanup",
            )

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

        # #1579: this can INSERT a brand new DocPerm row (if a prior test in
        # the shard already stripped it) that must survive this test's own
        # teardown -- see suspend_insert_capture()'s docstring.
        with suspend_insert_capture():
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

        # #1579: see suspend_insert_capture()'s docstring -- this DocPerm row
        # must outlive this test, so a fresh insert here (if a prior test
        # already stripped it) must not be claimed by the captured-insert
        # drain.
        with suspend_insert_capture():
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
        )

        # Ensure perms are present first.
        self._cleanup_restore_canonical_board_perms()
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
            self._cleanup_restore_canonical_board_perms()
        # Round-trip: the restore must have re-added the rows.
        self.assertTrue(_board_perm_exists("Membership"))
        self.assertTrue(_board_perm_exists("Membership Termination Request"))

    def test_restored_termination_request_permission_survives_the_insert_drain(self):
        """Regression for #1579.

        PR #1575's CI shard 3 hit ``PermissionError: Insufficient Permission for
        Membership Termination Request`` in an unrelated later test
        (``test_board_identity_resolution_1546``). The suspected mechanism was
        that ``setup_chapter_board_permissions()`` silently failed to restore the
        permission (it is ``@critical_api``-wrapped and swallows exceptions into
        ``{"success": False}``).

        That was NOT what happened. Reproduced empirically on test_site_4
        (developer_mode=0, matching CI): the restore SUCCEEDS -- no Error Log,
        no ``success: False``. The actual mechanism is this harness's OWN
        captured-insert drain (``EnhancedTestCase._drain_captured_inserts``,
        called from ``tearDown``): ``reset_chapter_board_permissions()`` deletes
        the DocPerm row, then ``setup_chapter_board_permissions()`` creates a
        BRAND NEW child row (a fresh ``db_insert``, not an update, because the
        old row is gone). That insert is captured like any other test-created
        row and force-deleted again at teardown -- silently stripping board
        access on MTR for the rest of the shard, even though the restore itself
        never failed.

        (Membership's own board-perm row happens to survive this exact bug by
        accident: its DocType JSON ships two "Verenigingen Staff" permission
        rows at permlevel 0, a pre-existing, unrelated defect that makes
        validate_permissions() reject ANY save of the Membership DocType -- so
        reset_chapter_board_permissions() can never actually remove Membership's
        row in the first place, and it is therefore never re-inserted or
        captured. MTR carries no such defect, so it round-trips cleanly and
        gets caught by the drain. That Membership-side defect is reported
        separately, not fixed here.)

        This test drives the exact round-trip a real test in this class
        performs, then calls the harness's OWN drain directly (the same method
        ``tearDown`` calls) to prove the restored row survives it -- without
        depending on cross-test ordering.
        """
        from verenigingen.services.chapter.chapter_board_permissions import (
            reset_chapter_board_permissions,
        )

        doctype = "Membership Termination Request"
        if not frappe.db.exists("DocType", doctype):
            self.skipTest(f"{doctype} not present on this site")

        self._cleanup_restore_canonical_board_perms()
        self.assertTrue(_board_perm_exists(doctype), "fixture setup: perm not present before the test")

        # No intermediate commit needed: the restore below runs in the same
        # transaction and sees this delete via ordinary read-your-own-writes
        # visibility, and it is the restore's INSERT -- not this delete --
        # that the drain below is being tested against.
        #
        # Same guard as test_reset_result_is_consistent_with_row_removal: a
        # failed per-DocType save logs a "Failed to reset ..." / "Secure
        # Operation Failed" Error Log for Membership (the shipped duplicate-
        # DocPerm defect -- see #1589), which this reset call also triggers.
        self.expectErrorLog("reset Chapter Board Member", "Secure Operation Failed", "Membership")
        reset_chapter_board_permissions()
        self.assertFalse(_board_perm_exists(doctype), "fixture setup: reset did not remove the row")

        restore_result = self._cleanup_restore_canonical_board_perms()
        self.assertTrue(
            _board_perm_exists(doctype),
            f"restore failed outright: {restore_result}",
        )

        # This is what a bare tearDown() does next, every time: drain whatever
        # this test body inserted. Call it directly so the assertion below does
        # not depend on which test runs after this one.
        self._drain_captured_inserts()

        self.assertTrue(
            _board_perm_exists(doctype),
            "the just-restored Chapter Board Member permission on "
            f"{doctype} must survive the harness's own captured-insert drain "
            "(suspend_insert_capture() must wrap the restore above)",
        )

    def test_validate_permission_security_passes_after_setup(self):
        """Security validation: no delete/cancel/amend/submit granted to board role."""
        from verenigingen.services.chapter.chapter_board_permissions import (
            validate_permission_security,
        )

        self._cleanup_restore_canonical_board_perms()
        is_valid, issues = validate_permission_security()
        self.assertTrue(is_valid, f"Security validation should pass: {issues}")
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
