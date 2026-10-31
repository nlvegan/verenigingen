# -*- coding: utf-8 -*-
"""#1860 (maintainer ruling 2026-10-31): an approval that names a chapter that does not exist is
REFUSED before anything is written. It used to approve the member with no chapter row.

Real flow: Guest submit_application, then approve_membership_application as Administrator.
"""

import json

import frappe

from verenigingen.api.membership_application import submit_application
from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.tests.backend.unit.api.test_membership_application_coverage import (
    _ensure_test_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestApprovalRefusesUnknownChapter(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        self.membership_type = _ensure_test_membership_type()

    def _apply_as_guest(self):
        data = {
            "first_name": "Unknown",
            "last_name": f"Chapter{frappe.generate_hash(length=6)}",
            "email": f"uc-{frappe.generate_hash(length=8)}@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "1 Test Street",
            # No chapter may be suggested at submit (suggestion also matches on city).
            "city": f"Nergenshuizen-{frappe.generate_hash(length=6)}",
            "postal_code": "9999ZZ",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type,
        }
        frappe.set_user("Guest")
        self.addCleanup(frappe.set_user, "Administrator")
        result = submit_application(**data)
        frappe.set_user("Administrator")
        self.assertTrue(result["success"], msg=json.dumps(result, default=str))
        member = result["data"]["member_record"]
        self.track_doc("Member", member)
        return member

    def test_an_unknown_chapter_is_refused_before_anything_is_written(self):
        ghost = f"No Such Chapter {frappe.generate_hash(length=6)}"
        member = self._apply_as_guest()

        with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
            approve_membership_application(
                member_name=member, membership_type=self.membership_type, chapter=ghost
            )

        self.assertEqual(
            frappe.db.get_value("Member", member, ["status", "application_status"]), ("Pending", "Pending")
        )
        self.assertFalse(frappe.db.exists("Membership", {"member": member}))
        self.assertFalse(frappe.db.exists("Chapter Member", {"member": member}))

    def test_an_existing_chapter_still_approves(self):
        """Control: the refusal must not catch a real chapter."""
        chapter = self.create_test_chapter(published=1)
        member = self._apply_as_guest()

        approve_membership_application(
            member_name=member, membership_type=self.membership_type, chapter=chapter.name
        )

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_an_unpublished_existing_chapter_is_not_refused(self):
        """Control for the ruling's boundary: only a chapter that does not EXIST is refused."""
        chapter = self.create_test_chapter(published=0)
        member = self._apply_as_guest()

        approve_membership_application(
            member_name=member, membership_type=self.membership_type, chapter=chapter.name
        )

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_no_chapter_still_approves(self):
        """Control: an approval naming no chapter is not refused."""
        member = self._apply_as_guest()

        approve_membership_application(member_name=member, membership_type=self.membership_type, chapter=None)

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")
