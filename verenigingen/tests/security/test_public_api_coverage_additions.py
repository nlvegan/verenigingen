"""
Regression tests for audit #10 coverage additions.

Two previously-undecorated guest-accessible endpoints were brought under the
@public_api security decorator (adds rate limiting + input validation without
changing who may call them). These tests verify guest access still works and
returns the expected dict shapes.
"""

from verenigingen.templates.pages.membership_application import (
    get_dues_schedules_for_membership_type,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member.member_utils import find_chapter_by_postal_code


class TestPublicApiCoverageAdditions(VereningingenTestCase):
    """@public_api must not break guest access to these read-only endpoints."""

    def test_find_chapter_by_postal_code_guest_accessible(self):
        with self.as_user("Guest"):
            result = find_chapter_by_postal_code("1011AB")
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_find_chapter_by_postal_code_missing_arg(self):
        with self.as_user("Guest"):
            result = find_chapter_by_postal_code("")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])

    def test_get_dues_schedules_guest_accessible(self):
        with self.as_user("Guest"):
            result = get_dues_schedules_for_membership_type("")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
