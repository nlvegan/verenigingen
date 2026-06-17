"""
Tests for the member contact-request portal page
(verenigingen.templates.pages.contact_request).

get_context requires login, resolves the caller's Member, exposes dropdown
options + recent requests (or a graceful no-member error). submit_contact_request
validates required fields and creates a Member Contact Request via the internal
helper, writing the result into frappe.response.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageContactRequest(EnhancedTestCase):
    """Real-data tests for the contact request page + submission endpoint."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        self._original_response = frappe.local.response

        self.email = f"contact-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Contact",
            last_name="Tester",
            email=self.email,
            birth_date="1990-01-01",
        )
        self.user = self._ensure_member_user(self.email)
        self.member.db_set("user", self.user)
        # Contact requests are only allowed for members whose membership_status
        # is "Active" (see member_contact_request.validate).
        self.member.db_set("membership_status", "Active")

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        frappe.local.response = self._original_response
        super().tearDown()

    def _ensure_member_user(self, email):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Contact",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
        return email

    # ----- get_context -------------------------------------------------

    def test_context_for_member_populates_dropdowns(self):
        from verenigingen.templates.pages.contact_request import get_context

        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertFalse(ctx.no_member_record)
        self.assertEqual(ctx.member.name, self.member.name)
        self.assertIn("General Inquiry", ctx.request_types)
        self.assertEqual(len(ctx.urgency_levels), 4)
        self.assertIn("Email", ctx.contact_methods)
        self.assertIsInstance(ctx.recent_requests, list)

    def test_context_for_user_without_member_is_graceful(self):
        """A logged-in user with no Member record gets a friendly error context."""
        from verenigingen.templates.pages.contact_request import get_context

        orphan_email = f"orphan-{frappe.generate_hash()[:8]}@example.com"
        if not frappe.db.exists("User", orphan_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": orphan_email,
                    "first_name": "Orphan",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.as_user(orphan_email):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertTrue(ctx.no_member_record)
        self.assertTrue(ctx.error_title)
        # support_email is always resolved (from settings or fallback); it may be
        # an empty string on a site with no support contact configured.
        self.assertIn("support_email", ctx)

    # ----- submit_contact_request --------------------------------------

    def test_submit_creates_contact_request(self):
        from verenigingen.templates.pages.contact_request import submit_contact_request

        with self.as_user(self.user):
            frappe.form_dict = frappe._dict(
                {
                    "subject": "Need help with membership",
                    "message": "Please call me about my dues.",
                    "request_type": "Membership Question",
                    "urgency": "High",
                }
            )
            try:
                submit_contact_request()
                response_message = frappe.response.get("message")
            finally:
                frappe.form_dict = frappe._dict()

        self.assertTrue(response_message["success"])

        # Side effect: a Member Contact Request now exists for this member.
        created = frappe.get_all(
            "Member Contact Request",
            filters={"member": self.member.name, "subject": "Need help with membership"},
            fields=["name", "request_type", "urgency"],
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].request_type, "Membership Question")
        self.assertEqual(created[0].urgency, "High")

    def test_submit_missing_required_field_throws(self):
        from verenigingen.templates.pages.contact_request import submit_contact_request

        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"subject": "No message here", "request_type": "General Inquiry"})
            try:
                with self.assertRaises(frappe.ValidationError):
                    submit_contact_request()
            finally:
                frappe.form_dict = frappe._dict()

        # No record should have been created.
        self.assertEqual(
            frappe.db.count(
                "Member Contact Request",
                {"member": self.member.name, "subject": "No message here"},
            ),
            0,
        )

    def test_submit_without_member_throws(self):
        from verenigingen.templates.pages.contact_request import submit_contact_request

        orphan_email = f"orphan2-{frappe.generate_hash()[:8]}@example.com"
        if not frappe.db.exists("User", orphan_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": orphan_email,
                    "first_name": "Orphan",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.as_user(orphan_email):
            frappe.form_dict = frappe._dict(
                {
                    "subject": "Hi",
                    "message": "Hello",
                    "request_type": "General Inquiry",
                }
            )
            try:
                with self.assertRaises(frappe.ValidationError):
                    submit_contact_request()
            finally:
                frappe.form_dict = frappe._dict()

    def test_has_website_permission_guest_denied(self):
        from verenigingen.templates.pages.contact_request import has_website_permission

        self.assertFalse(has_website_permission(None, "read", "Guest"))
