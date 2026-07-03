"""
Regression tests for audit #10 coverage additions.

Two previously-undecorated guest-accessible endpoints were brought under the
@public_api security decorator (adds rate limiting + input validation without
changing who may call them). These tests verify guest access still works and
returns the expected dict shapes.
"""

import frappe

from verenigingen.templates.pages.membership_application import (
    get_dues_schedules_for_membership_type,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member.member_utils import find_chapter_by_postal_code


class TestPublicApiCoverageAdditions(VereningingenTestCase):
    """@public_api must not break guest access to these read-only endpoints."""

    def setUp(self):
        super().setUp()
        # find_chapter_by_postal_code short-circuits when chapter management is
        # disabled; enable it so the tests deterministically exercise the real
        # lookup path (and the fixed internal-call behaviour) rather than the
        # "disabled" early return.
        self._orig_ccm = frappe.db.get_single_value(
            "Verenigingen Settings", "enable_chapter_management"
        )
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
        self.addCleanup(
            frappe.db.set_single_value,
            "Verenigingen Settings",
            "enable_chapter_management",
            self._orig_ccm,
        )

    def test_find_chapter_by_postal_code_guest_accessible(self):
        # Guest access must succeed (not raise) and return the success shape with
        # a chapter list - the whole point of audit #10's fix + the internal-call
        # bug fix (it previously hit a MEDIUM auth check via is_chapter_management_enabled).
        with self.as_user("Guest"):
            result = find_chapter_by_postal_code("1011AB")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIn("matching_chapters", result)
        self.assertIsInstance(result["matching_chapters"], list)

    def test_find_chapter_by_postal_code_missing_arg(self):
        with self.as_user("Guest"):
            result = find_chapter_by_postal_code("")
        self.assertFalse(result["success"])
        self.assertIn("required", result["message"].lower())

    def test_get_dues_schedules_guest_accessible(self):
        # Empty arg is rejected by the endpoint's own validation, but the call
        # must reach that logic as a Guest (not be blocked by the auth layer).
        with self.as_user("Guest"):
            result = get_dues_schedules_for_membership_type("")
        self.assertFalse(result["success"])
        self.assertIn("error", result)
