"""Shipped Email Templates render with the context their REAL senders build (#2018, #2020).

Each test drives a real sender (``send_payment_reminder_email``, the Mollie payment-failure
notifier, the Mollie subscription-status notifier) with the stock row from
``fixtures/email_template.json`` and reads the mail handed to ``frappe.sendmail`` (the harness
captures it; EnhancedTestCase writes no Email Queue row). Only the mail transport is replaced.

Setup never rewrites an existing Email Template row, but Frappe's fixture sync on migrate DOES
overwrite these rows (reproduced, regardless of ``modified``), which is how existing sites
receive this fix.

What this does NOT prove: that the page a link points at works (only that the route is served,
as in ``test_shipped_links_resolve``), nor anything about a site whose Email Template rows pre-date
the fix (#1984: setup never rewrites an existing row).
"""

import re
import types

import frappe
from frappe.utils import getdate

from verenigingen.api.payment_processing import send_payment_reminder_email
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment import test_payment_reminder_outcomes as _outcomes
from verenigingen.tests.utils.notification_state import own_notification_keys
from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import _notify_member_of_payment_failure
from verenigingen.verenigingen_payments.mollie.api.sync import _notify_subscription_status_change

REMINDERS = ["payment_reminder_friendly", "payment_reminder_urgent"]
FAILURES = ["payment_failure_first", "payment_failure_second", "payment_failure_final"]
STATUS = ["subscription_suspended", "subscription_cancelled"]
STOCK = REMINDERS + FAILURES + STATUS

HREF = re.compile(r"""href=["']([^"']*)["']""")


def _failed_mollie_payment_stub(amount="25.00"):
    return types.SimpleNamespace(
        id=f"tr_ctx_{frappe.generate_hash(length=8)}",
        status="failed",
        amount={"value": amount, "currency": "EUR"},
    )


class TestShippedTemplateContext(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _cleanup_stock_email_templates(STOCK)  # the stock rows, whatever this site holds

    @classmethod
    def tearDownClass(cls):
        _cleanup_stock_email_templates(STOCK)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._own_default_outgoing_account()
        own_notification_keys(self, *(STOCK))
        self.member = self.create_test_member(
            first_name="Context",
            last_name=frappe.generate_hash(length=6),
            email=f"context.{frappe.generate_hash(length=8)}@example.com",
        )
        # Distinctive values: none equals a template default or the fixture member's data.
        self.info = {"total_overdue": 187.5, "overdue_count": 4, "days_overdue": 43}

    def _own_default_outgoing_account(self):
        """A site with no default outgoing Email Account (CI, test_site_11) refuses every send.

        Reuses the outcomes module's creator (called unbound: it reads no instance state; the
        module, not the class, is imported so the runner does not collect that class here).
        The account is removed afterwards, and only if this test created it: a leaked default
        outgoing account masks mail failures shard-wide (#2044).
        """
        had_one = frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1})
        _outcomes.TestPaymentReminderOutcomes._ensure_outgoing_account(self)
        if not had_one:
            self.addCleanup(self._remove_outgoing_account, "Test Outgoing")

    @staticmethod
    def _remove_outgoing_account(name):
        if frappe.db.exists("Email Account", name):
            frappe.delete_doc("Email Account", name, force=True, ignore_permissions=True)
        frappe.db.commit()  # the account was committed by nothing; but a rollback must not resurrect it

    def _one_mail(self):
        mails = self.get_sent_emails(to=self.member.email)
        self.assertEqual(len(mails), 1, "control: the real sender queued exactly one mail")
        return mails[0]["message"] if isinstance(mails[0], dict) else mails[0].message

    def _assert_links_are_absolute_and_served(self, message):
        from frappe.website.path_resolver import PathResolver

        links = [h for h in HREF.findall(message) if not h.startswith("mailto:")]
        self.assertTrue(links, "control: the mail carries at least one link")
        site = frappe.utils.get_url()
        for link in links:
            self.assertTrue(link.startswith(("http://", "https://")), f"relative link in mail: {link!r}")
            self.assertTrue(link.startswith(site), f"link not on this site: {link!r}")
            route = link[len(site) :].split("?", 1)[0].strip("/")
            with self.as_user("Guest"):
                _, renderer = PathResolver(route).resolve()
            self.assertNotEqual(type(renderer).__name__, "NotFoundPage", f"dead route in mail: {link!r}")

    # ---- #2018: the member reminder reads payment_info ------------------

    def _assert_reminder_renders_figures(self, reminder_type):
        send_payment_reminder_email(
            member_name=self.member.name, reminder_type=reminder_type, payment_info=self.info
        )
        message = self._one_mail()
        self.assertNotIn("{{", message)
        self.assertIn(str(self.info["total_overdue"]), message)
        self.assertIn(f'{self.info["days_overdue"]} days', message)
        self.assertRegex(message, rf'Number of Invoices:</strong>\s*{self.info["overdue_count"]}\b')

    def test_friendly_reminder_shows_amount_days_and_count(self):
        self._assert_reminder_renders_figures("Friendly Reminder")

    def test_urgent_reminder_shows_amount_days_and_count(self):
        self._assert_reminder_renders_figures("Urgent Notice")

    # ---- #2020: dunning / subscription links ----------------------------

    def test_payment_failure_mails_link_to_a_served_absolute_route(self):
        for count, template in ((1, "payment_failure_first"), (2, "payment_failure_second"),
                                (3, "payment_failure_final")):
            with self.subTest(template=template):
                self.captured_emails.clear()
                _notify_member_of_payment_failure(self.member, _failed_mollie_payment_stub(), count)
                message = self._one_mail()
                self.assertNotIn("{{", message)
                self._assert_links_are_absolute_and_served(message)

    def test_subscription_status_mails_link_to_a_served_absolute_route(self):
        for new_status in ("suspended", "canceled"):
            with self.subTest(new_status=new_status):
                self.captured_emails.clear()
                _notify_subscription_status_change(
                    self.member, "active", new_status, {"id": "sub_ctx", "next_payment_date": None}
                )
                message = self._one_mail()
                self.assertNotIn("{{", message)
                self._assert_links_are_absolute_and_served(message)

    def test_control_the_dead_route_check_can_fail(self):
        """Control: the resolver really calls the pre-fix link dead, so the tests above can fail."""
        from frappe.website.path_resolver import PathResolver

        for dead in ("members/bank-details", "members/membership-renewal"):
            with self.as_user("Guest"):
                _, renderer = PathResolver(dead).resolve()
            self.assertEqual(type(renderer).__name__, "NotFoundPage", dead)
