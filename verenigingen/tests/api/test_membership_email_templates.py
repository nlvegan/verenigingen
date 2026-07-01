# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Real integration tests for verenigingen/api/membership_email_templates.py

Covers the single whitelisted endpoint:
  - create_default_email_templates()  [@frappe.whitelist + @critical_api]

The function creates the five default Email Templates used by the membership
application review workflow (four rejection variants + one approval). It checks
existence per-template before creating, so it is idempotent.

Observed real return shape (developer_mode on, direct call): a FLAT dict
    {"success": True, "message": "...", "templates": [<created names>]}
(NOT the nested {"success","data",...} OperationResult envelope.)

Every managed Email Template is force-deleted in tearDown so the suite is
self-cleaning and idempotent across runs.
"""

import frappe

from verenigingen.api.membership_email_templates import create_default_email_templates
from verenigingen.tests.utils.base import VereningingenTestCase

# The exact set of templates the module manages, with their expected subjects.
# Kept in sync with membership_email_templates.py so cleanup + assertions are exhaustive.
MANAGED_TEMPLATES = {
    "membership_application_rejected": "Membership Application Update - {{ member_name }}",
    "membership_rejection_incomplete": (
        "Membership Application - Additional Information Required - {{ member_name }}"
    ),
    "membership_rejection_ineligible": "Membership Application Update - {{ member_name }}",
    "membership_rejection_duplicate": "Membership Application - Duplicate Detected - {{ member_name }}",
    "membership_application_approved": (
        "Membership Application Approved - Payment Required - {{ member_name }}"
    ),
}


class TestMembershipEmailTemplates(VereningingenTestCase):
    """Behaviour-level tests for the default membership email template creator."""

    def setUp(self):
        super().setUp()
        # Start every test from a known-clean slate so the "create" branch runs.
        self._delete_managed_templates()

    def tearDown(self):
        # Force-delete every managed template (created here or pre-existing) so the
        # suite leaves no duplicate/garbage template docs on the test site.
        self._delete_managed_templates()
        super().tearDown()

    def _delete_managed_templates(self):
        """Remove all managed Email Templates (helper, not a test-body operation)."""
        for name in MANAGED_TEMPLATES:
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True)
        frappe.db.commit()

    def _track_all_created(self):
        """Track every managed template that now exists for teardown cleanup."""
        for name in MANAGED_TEMPLATES:
            if frappe.db.exists("Email Template", name):
                self.track_doc("Email Template", name)

    # ------------------------------------------------------------------
    # Happy path: creation + real effect
    # ------------------------------------------------------------------
    def test_creates_all_five_templates(self):
        """From a clean slate, all five named Email Templates are created and the
        function reports each one in a flat success dict."""
        result = create_default_email_templates()
        self._track_all_created()

        # Real return shape is a flat dict (not the nested OperationResult envelope).
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], f"creation failed: {result}")
        self.assertEqual(result["message"], "Created 5 email templates")
        self.assertEqual(set(result["templates"]), set(MANAGED_TEMPLATES.keys()))

        # Assert the ACTUAL effect: each named template now exists with the right subject.
        for name, expected_subject in MANAGED_TEMPLATES.items():
            self.assertTrue(
                frappe.db.exists("Email Template", name),
                f"Email Template '{name}' should have been created",
            )
            doc = frappe.get_doc("Email Template", name)
            self.assertEqual(doc.subject, expected_subject, f"wrong subject for {name}")
            self.assertTrue(doc.response and doc.response.strip(), f"{name} response is empty")

    def test_template_bodies_have_distinctive_content(self):
        """Spot-check distinctive content per template so a swapped/blanked body or
        a broken merge field would be caught (not just 'a template exists')."""
        create_default_email_templates()
        self._track_all_created()

        rejected = frappe.get_doc("Email Template", "membership_application_rejected")
        self.assertIn("{{ application_id }}", rejected.response)
        self.assertIn("{{ reason }}", rejected.response)
        self.assertIn("regret to inform", rejected.response)

        incomplete = frappe.get_doc("Email Template", "membership_rejection_incomplete")
        self.assertIn("Additional Information Required", incomplete.response)
        self.assertIn("Missing Information", incomplete.response)

        ineligible = frappe.get_doc("Email Template", "membership_rejection_ineligible")
        self.assertIn("eligibility requirements", ineligible.response)

        duplicate = frappe.get_doc("Email Template", "membership_rejection_duplicate")
        self.assertIn("Duplicate Application", duplicate.response)
        self.assertIn("already submitted", duplicate.response)

        approved = frappe.get_doc("Email Template", "membership_application_approved")
        self.assertIn("{{ payment_url }}", approved.response)
        self.assertIn("{{ membership_type.membership_type_name }}", approved.response)
        self.assertIn("{{ payment_amount }}", approved.response)
        self.assertIn("Congratulations", approved.response)

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------
    def test_second_call_is_idempotent_no_duplicates(self):
        """Running the creator twice must not error or duplicate: the second call
        creates zero templates and every managed name still resolves to exactly one
        (single-name) doc with the original content."""
        first = create_default_email_templates()
        self._track_all_created()
        self.assertEqual(len(first["templates"]), 5)

        # Capture the original response of one template to confirm it is untouched.
        original_body = frappe.get_doc("Email Template", "membership_application_approved").response

        second = create_default_email_templates()
        self.assertTrue(second["success"])
        self.assertEqual(second["message"], "Created 0 email templates")
        self.assertEqual(second["templates"], [])

        # Named docs cannot duplicate, but assert existence + unchanged content anyway.
        for name in MANAGED_TEMPLATES:
            self.assertTrue(frappe.db.exists("Email Template", name))
        self.assertEqual(
            frappe.get_doc("Email Template", "membership_application_approved").response,
            original_body,
            "idempotent re-run must not alter an existing template body",
        )

    def test_partial_existence_creates_only_missing(self):
        """When some templates already exist, the creator only creates the missing
        ones and reports exactly those (covers the per-template existence branch)."""
        create_default_email_templates()
        self._track_all_created()

        # Remove two templates, leaving three in place.
        missing = ["membership_rejection_ineligible", "membership_application_approved"]
        for name in missing:
            frappe.delete_doc("Email Template", name, force=True)
        frappe.db.commit()

        result = create_default_email_templates()
        self._track_all_created()

        self.assertTrue(result["success"])
        self.assertEqual(set(result["templates"]), set(missing))
        self.assertEqual(result["message"], "Created 2 email templates")

        # All five exist again after the top-up run.
        for name in MANAGED_TEMPLATES:
            self.assertTrue(
                frappe.db.exists("Email Template", name),
                f"'{name}' should exist after the top-up create",
            )
