"""Typed values in the SEEDED Email Templates are HTML-escaped (#2351, template-side sibling of #2307).

Frappe's ``render_template`` does not autoescape (measured: ``{{ x }}`` of ``<i>x</i>`` stays a live
tag), so every typed value needs ``|e`` in the template source. Each test seeds the template through
the REAL seeder (``create_comprehensive_email_templates`` / ``create_default_email_templates`` /
``create_application_email_templates``) and renders it through the exact two calls
``EmailService.send_templated_email`` makes (``_get_template`` then ``_render_template``).

Declared shortcuts: the render is called directly rather than through a full sender (the senders'
own context building is unchanged); the seeders' ``frappe.db.commit`` is patched out so the rows they
write are rolled back by the harness teardown instead of leaking into the site.

Run:
    bench --site test_site_8 run-tests --app verenigingen --module verenigingen.tests.test_email_template_escaping_2351
"""

from unittest.mock import patch

import frappe

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.tests.utils.base import VereningingenTestCase

RAW = '<i>x</i> & "y"'
ESCAPED = "&lt;i&gt;x&lt;/i&gt; &amp; &#34;y&#34;"


class TestSeededTemplateEscaping(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.set_user, frappe.session.user)
        frappe.set_user("Administrator")

    def _seed(self, seeder, names):
        for name in names:
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True, ignore_permissions=True)
        with patch.object(frappe.db, "commit"):
            seeder()
        for name in names:
            self.assertTrue(frappe.db.exists("Email Template", name), f"{name} was not seeded")

    def _render(self, name, context):
        service = get_email_service()
        service.template_cache.clear() if hasattr(service.template_cache, "clear") else None
        template = service._get_template(name)
        return service._render_template(template, context)["content"]

    def _assert_escaped(self, body, *needles):
        self.assertNotIn("<i>x</i>", body)
        self.assertNotIn('& "y"', body)
        self.assertIn(ESCAPED, body)
        for n in needles:
            self.assertIn(n, body)

    def _seed_comprehensive(self, names):
        from verenigingen.api.email_template_manager import create_comprehensive_email_templates

        self._seed(create_comprehensive_email_templates, names)

    def test_expense_approval_request_escapes_description_and_names(self):
        self._seed_comprehensive(["expense_approval_request"])
        body = self._render(
            "expense_approval_request",
            {
                "doc": frappe._dict(name="EXP-1", description=RAW, organization_type="Chapter"),
                "volunteer_name": RAW, "category_name": RAW, "organization_name": RAW,
                "approver_name": RAW, "company": "Co", "required_level": "Manager",
                "formatted_amount": "10.00", "formatted_date": "2026-01-01",
                "approval_url": "http://x/a?b=1&c=2", "dashboard_url": "http://x/d",
            },
        )
        self._assert_escaped(body)
        self.assertGreaterEqual(body.count(ESCAPED), 5)

    def test_expense_approved_and_rejected_escape_typed_values(self):
        self._seed_comprehensive(["expense_approved", "expense_rejected"])
        ctx = {
            "doc": frappe._dict(name="EXP-1", description=RAW),
            "volunteer_name": RAW, "approved_by_name": RAW, "rejected_by_name": RAW,
            "rejection_reason": RAW, "company": "Co", "formatted_amount": "10.00",
            "approved_on": "2026-01-01",
        }
        approved = self._render("expense_approved", ctx)
        rejected = self._render("expense_rejected", ctx)
        self._assert_escaped(approved)
        self.assertGreaterEqual(approved.count(ESCAPED), 3)
        self._assert_escaped(rejected)
        self.assertGreaterEqual(rejected.count(ESCAPED), 4)

    def test_donation_templates_escape_donor_notes_and_reference(self):
        self._seed_comprehensive(["donation_confirmation", "donation_payment_confirmation"])
        ctx = {
            "donation_id": "D-1", "donation_amount": "1.00", "donation_date": "d",
            "donation_status": "s", "earmarking": RAW, "donation_notes": RAW,
            "donor_name": RAW, "organization_name": "Org", "organization_email": "o@x.nl",
            "payment_date": "d", "payment_method": "m", "payment_reference": RAW,
        }
        confirmation = self._render("donation_confirmation", ctx)
        self._assert_escaped(confirmation)
        self.assertGreaterEqual(confirmation.count(ESCAPED), 3)
        payment = self._render("donation_payment_confirmation", ctx)
        self._assert_escaped(payment)
        self.assertGreaterEqual(payment.count(ESCAPED), 3)

    def test_anbi_receipt_and_contact_request_escape_typed_values(self):
        self._seed_comprehensive(["anbi_tax_receipt", "member_contact_request_received"])
        receipt = self._render(
            "anbi_tax_receipt",
            {"donor_name": RAW, "receipt_number": "R", "anbi_number": "A", "tax_year": 2026,
             "organization_name": "Org", "doc": frappe._dict(amount=1)},
        )
        self._assert_escaped(receipt)
        contact = self._render(
            "member_contact_request_received",
            {"doc": frappe._dict(name="C-1", message=RAW, request_category="c", priority="p"),
             "contact_name": RAW, "submission_date": "d", "organization_name": "Org"},
        )
        self._assert_escaped(contact)
        self.assertGreaterEqual(contact.count(ESCAPED), 2)

    def test_control_system_html_still_renders_as_html(self):
        """request_rows is HTML the sender builds from its own rows; it must stay markup."""
        self._seed_comprehensive(["termination_overdue_notification"])
        body = self._render(
            "termination_overdue_notification",
            {"count": 1, "request_rows": "<tr><td>ROW-MARKER</td></tr>"},
        )
        self.assertIn("<tr><td>ROW-MARKER</td></tr>", body)

    def test_rejection_templates_escape_reason_and_names(self):
        from verenigingen.api.membership_email_templates import create_default_email_templates

        names = [
            "membership_application_rejected", "membership_rejection_incomplete",
            "membership_rejection_ineligible", "membership_rejection_duplicate",
        ]
        self._seed(create_default_email_templates, names)
        for name in names:
            body = self._render(
                name,
                {"reason": RAW, "first_name": RAW, "member_name": RAW, "application_id": "A-1",
                 "company": "Co"},
            )
            with self.subTest(template=name):
                self._assert_escaped(body)
                self.assertGreaterEqual(body.count(ESCAPED), 2)

    def test_setup_templates_escape_typed_values(self):
        from verenigingen.setup import create_application_email_templates

        names = ["volunteer_welcome", "membership_welcome", "membership_payment_failed"]
        self._seed(create_application_email_templates, names)
        volunteer = self._render(
            "volunteer_welcome",
            {"volunteer": frappe._dict(
                volunteer_name=RAW, commitment_level="c", experience_level="e", email=RAW,
                interests=[frappe._dict(interest_area=RAW)])},
        )
        self._assert_escaped(volunteer)
        self.assertGreaterEqual(volunteer.count(ESCAPED), 3)
        member = frappe._dict(first_name=RAW, name="M-1", current_chapter=RAW)
        welcome = self._render(
            "membership_welcome",
            {"member": member, "membership_type": frappe._dict(membership_type_name="T"),
             "membership": frappe._dict(start_date="2026-01-01", renewal_date="2027-01-01"),
             "company": frappe.defaults.get_global_default("company"),
             "member_portal_url": "http://x", "login_url": "http://x"},
        )
        self._assert_escaped(welcome)
        self.assertGreaterEqual(welcome.count(ESCAPED), 2)
        failed = self._render("membership_payment_failed", {"member": member, "retry_url": "http://x"})
        self._assert_escaped(failed)
