"""Reminder mails' payment link opens a served page for the OLDEST overdue invoice (#2109).

The link a real ``send_payment_reminder_email`` produces must resolve (not NotFoundPage) and carry
``member`` and the member's oldest overdue invoice, for every reminder type, whatever the order the
invoices were created in. The /payment_retry page sends a logged-out visitor to login and back to the same URL.
"""

import re
from urllib.parse import parse_qs, quote, urlparse

import frappe
from frappe.utils import add_days, today
from frappe.website.path_resolver import PathResolver

from verenigingen.api.payment_processing import send_payment_reminder_email
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.templates.pages import payment_retry
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)
from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates, _load_fixture_rows

REMINDER_TYPES = ["Friendly Reminder", "Urgent Notice", "Final Notice", "Bulk Reminder"]
TEMPLATES = [
    "payment_reminder_friendly",
    "payment_reminder_urgent",
    "payment_reminder_final",
    "payment_reminder_bulk",
]
KEYS = ["payment_reminder_friendly", "payment_reminder_urgent"]


class TestReminderPaymentLink(PortalSelfServiceTestMixin, EnhancedTestCase):
    @classmethod
    def tearDownClass(cls):
        _cleanup_stock_email_templates(TEMPLATES)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        fixture = _load_fixture_rows()
        for name in TEMPLATES:
            if name in fixture and not frappe.db.exists("Email Template", name):
                row = {k: v for k, v in fixture[name].items() if k != "modified"}
                doc = frappe.get_doc(row)
                doc.flags.ignore_links = True
                doc.insert()
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = 1
        config.respect_user_preferences = 1
        config.save()
        for key in KEYS:
            configure_notification_key(key, 1, 0)
        clear_email_cooldowns()
        self._original_user = frappe.session.user
        self._original_form_dict = frappe.local.form_dict

        self.member = self.create_test_member(
            first_name="Link",
            last_name=frappe.generate_hash(length=6),
            email=f"link.{frappe.generate_hash(length=8)}@example.com",
            birth_date="1990-01-01",
        )
        # Created NEWEST first, so "oldest" is neither first-created nor lowest-named.
        self.newer = self._overdue_invoice(posting_offset=-40, due_offset=-10, amount=30.0)
        self.oldest = self._overdue_invoice(posting_offset=-90, due_offset=-60, amount=20.0)
        self.middle = self._overdue_invoice(posting_offset=-70, due_offset=-30, amount=25.0)
        self.info = {"total_overdue": 75.0, "overdue_count": 3, "days_overdue": 60, "membership_type": "Regular"}

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    # ---- helpers -------------------------------------------------------

    def _overdue_invoice(self, posting_offset, due_offset, amount):
        invoice = self.create_test_sales_invoice(
            customer=self.member.name,
            grand_total=amount,
            posting_date=add_days(today(), posting_offset),
            due_date=add_days(today(), due_offset),
        )
        frappe.db.set_value("Sales Invoice", invoice.name, "member", self.member.name)
        return invoice.name

    def _links_in_mail(self, reminder_type):
        clear_email_cooldowns()
        send_payment_reminder_email(
            member_name=self.member.name, reminder_type=reminder_type, payment_info=self.info
        )
        mails = [
            e["kwargs"].get("message") or ""
            for e in self.captured_emails
            if e["kwargs"].get("reference_name") == self.member.name
        ]
        self.assertTrue(mails, f"{reminder_type}: no mail was handed to sendmail")
        return re.findall(r'href="([^"]*payment[^"]*)"', mails[-1])

    # ---- the link --------------------------------------------------------

    def test_every_reminder_links_a_served_page_for_the_oldest_overdue_invoice(self):
        for reminder_type in REMINDER_TYPES:
            links = self._links_in_mail(reminder_type)
            self.assertEqual(len(links), 1, (reminder_type, links))
            parsed = urlparse(links[0])
            self.assertEqual(parsed.path, "/payment_retry", reminder_type)
            query = parse_qs(parsed.query)
            self.assertEqual(query["member"], [self.member.name], reminder_type)
            self.assertEqual(query["invoice"], [self.oldest], reminder_type)

            frappe.set_user("Guest")
            _, renderer = PathResolver(parsed.path.lstrip("/")).resolve()
            frappe.set_user(self._original_user)
            self.assertNotEqual(type(renderer).__name__, "NotFoundPage", reminder_type)

    def test_a_paid_older_invoice_is_not_the_one_linked(self):
        """Control: only OVERDUE invoices count, so the pick is not simply 'earliest posting date'."""
        paid_old = self._overdue_invoice(posting_offset=-200, due_offset=-170, amount=10.0)
        frappe.db.set_value("Sales Invoice", paid_old, {"outstanding_amount": 0, "status": "Paid"})
        query = parse_qs(urlparse(self._links_in_mail("Final Notice")[0]).query)
        self.assertEqual(query["invoice"], [self.oldest])

    def test_a_member_with_no_overdue_invoice_gets_no_link(self):
        for name in (self.newer, self.oldest, self.middle):
            frappe.db.set_value("Sales Invoice", name, {"outstanding_amount": 0, "status": "Paid"})
        self.assertEqual(self._links_in_mail("Friendly Reminder"), [])

    # ---- the page ----------------------------------------------------------

    def test_logged_out_visitor_is_sent_to_login_and_back_to_the_same_url(self):
        frappe.set_user("Guest")
        frappe.local.form_dict = frappe._dict({"member": self.member.name, "invoice": self.oldest})
        with self.assertRaises(frappe.Redirect) as raised:
            payment_retry.get_context(frappe._dict())
        self.assertEqual(raised.exception.args, (302,))
        back = f"/payment_retry?member={self.member.name}&invoice={self.oldest}"
        self.assertEqual(
            frappe.local.flags.redirect_location, f"/login?redirect-to={quote(back, safe='')}"
        )

    def test_logged_in_stranger_is_still_refused_not_redirected(self):
        """The #1052 guard stays: a logged-in non-owner discloses nothing."""
        stranger = self.create_test_member(birth_date="1991-01-01")
        user = self._link_member_to_user(stranger)
        frappe.set_user(user.name)
        frappe.local.form_dict = frappe._dict({"member": self.member.name, "invoice": self.oldest})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.invoice)

    def test_owner_sees_the_linked_invoice(self):
        user = self._link_member_to_user(self.member)
        frappe.set_user(user.name)
        frappe.local.form_dict = frappe._dict({"member": self.member.name, "invoice": self.oldest})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertEqual(context.invoice.name, self.oldest)

    def test_owner_sees_an_invoice_that_carries_only_the_members_customer(self):
        """Real invoices mostly leave Sales Invoice.member blank; they are still the member's own."""
        frappe.db.set_value("Sales Invoice", self.oldest, "member", None)
        user = self._link_member_to_user(self.member)
        frappe.set_user(user.name)
        frappe.local.form_dict = frappe._dict({"member": self.member.name, "invoice": self.oldest})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertEqual(context.invoice.name, self.oldest)

    def test_invoice_naming_another_member_is_not_shown_even_on_the_members_customer(self):
        """Control: a Customer shared by two Members must not open the other Member's invoice."""
        other = self.create_test_member(birth_date="1994-01-01")
        shared = self.create_test_sales_invoice(customer=self.member.name)  # on THIS member's customer
        frappe.db.set_value("Sales Invoice", shared.name, "member", other.name)  # ...but naming another
        user = self._link_member_to_user(self.member)
        frappe.set_user(user.name)
        frappe.local.form_dict = frappe._dict({"member": self.member.name, "invoice": shared.name})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.invoice)

    def test_blank_member_invoice_of_another_customer_is_not_shown(self):
        """Control for the test above: a blank `member` does not make any invoice the member's."""
        other = self.create_test_member(birth_date="1992-01-01")
        foreign = self.create_test_sales_invoice(customer=other.name)
        frappe.db.set_value("Sales Invoice", foreign.name, "member", None)
        user = self._link_member_to_user(self.member)
        frappe.set_user(user.name)
        frappe.local.form_dict = frappe._dict({"member": self.member.name, "invoice": foreign.name})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.invoice)
