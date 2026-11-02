"""
#1876: with no Administrator fallback the Mollie webhook runs as the minimal webhook user
(Verenigingen Webhook User + Accounts User + Sales User), and its compensating cleanup
(`_withdraw_bank_transaction`: a refund/chargeback Journal Entry did not post, so the Bank
Transaction must be withdrawn) needs `cancel` on Bank Transaction. The maintainer ruled the
role gets it (CORE_GRANTS in setup/custom_docperm_setup.py).

Usage:
    scripts/testing/run_without_credentials.sh test_site_3 \
        verenigingen.tests.payment.test_webhook_user_bank_transaction_cancel_1876
"""

import functools
import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment import test_mollie_reversal_single_booking as base
from verenigingen.verenigingen_payments.mollie.services import webhook_wrapper_service_unified as wrapper

SETTINGS = "Verenigingen Payments Settings"


def _webhook_user():
    return frappe.db.get_single_value(SETTINGS, "webhook_user")


class TestWebhookUserCancelPermissions(EnhancedTestCase):
    def test_the_webhook_user_can_cancel_a_bank_transaction(self):
        user = _webhook_user()
        self.assertTrue(user, "control: a webhook user is configured")
        self.assertTrue(frappe.has_permission("Bank Transaction", "cancel", user=user))

    def test_the_grant_did_not_truncate_the_set_for_other_roles(self):
        """Frappe ignores stock DocPerm rows once any Custom DocPerm row exists, so a grant that
        dropped the stock rows would strip these. Compared with the stock (JSON) rows."""
        rows = {
            r.role: r
            for r in frappe.get_all(
                "Custom DocPerm",
                filters={"parent": "Bank Transaction", "permlevel": 0},
                fields=["role", "read", "write", "create", "submit", "cancel"],
            )
        }
        for role, ptypes in (
            ("Accounts Manager", ("read", "write", "create", "submit", "cancel")),
            ("Accounts User", ("read", "write", "create", "submit")),
            ("System Manager", ("read", "write", "create", "submit", "cancel")),
            ("Verenigingen Webhook User", ("read", "write", "create", "submit", "cancel")),
        ):
            with self.subTest(role=role):
                self.assertIn(role, rows)
                for ptype in ptypes:
                    self.assertTrue(rows[role][ptype], f"{role} lost {ptype}")
        self.assertFalse(rows["Accounts User"]["cancel"], "control: Accounts User never had cancel")

    def test_the_webhook_user_still_cannot_cancel_a_sales_invoice(self):
        """Control: the grant is Bank Transaction only."""
        self.assertFalse(frappe.has_permission("Sales Invoice", "cancel", user=_webhook_user()))


class TestReversalCleanupRunsAsTheWebhookUser(base.TestReversalMirrorsTheForwardArtefact):
    """Every test of the reversal booking, with the webhook entry running as the webhook user.
    `test_a_reversal_whose_journal_entry_did_not_post_is_not_reported_as_success` is the one that
    needs the cancel. The user is switched with frappe.set_user around the service call only (a
    stand-in for the real entry points, which set it in authenticate_*_webhook)."""

    def setUp(self):
        super().setUp()
        original = wrapper.UnifiedWebhookWrapperService.process_reversal_webhook

        @functools.wraps(original)
        def as_webhook_user(*args, **kwargs):
            previous = frappe.session.user
            frappe.set_user(_webhook_user())
            try:
                return original(*args, **kwargs)
            finally:
                frappe.set_user(previous)

        # Identity switch only (the service body runs unmodified); undone in cleanup.
        service = wrapper.UnifiedWebhookWrapperService
        service.process_reversal_webhook = as_webhook_user
        self.addCleanup(setattr, service, "process_reversal_webhook", original)
