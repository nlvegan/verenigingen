"""Real-integration tests for the *Mollie Subscription Audit* script report
(``verenigingen/verenigingen/report/mollie_subscription_audit/``).

This report was at 0% coverage. It is LIVE (linked from the Verenigingen
workspace and the admin portal), but its ``get_data`` delegates to
``SubscriptionAudit.run_full_audit()``, which makes live calls to the Mollie
subscriptions API via ``MollieBaseClient``. That path strictly requires a
configured Mollie Live API key, so the data-bearing branches are OUT OF SCOPE
in the test environment (no live token).

What these tests DO cover with real wiring:
  * the column structure of ``get_columns``;
  * that ``get_data`` fails fast (rather than silently returning bad data) when
    the Mollie API key is not configured -- the realistic test-env state.

OUT OF SCOPE (documented for the caller): the issue-classification rows
(no-member-match / status-mismatch / deleted-member / etc.) and the summary
row, all of which require a live Mollie subscription dataset.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.mollie_subscription_audit import (
    mollie_subscription_audit as report,
)


class TestMollieSubscriptionAuditReport(VereningingenTestCase):
    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        self.assertEqual(len(columns), 12)
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(fieldnames[0], "issue_type")
        self.assertIn("subscription_id", fieldnames)
        self.assertIn("member_id", fieldnames)
        # member_id renders as a Member link.
        member_col = next(c for c in columns if c["fieldname"] == "member_id")
        self.assertEqual(member_col["fieldtype"], "Link")
        self.assertEqual(member_col["options"], "Member")

    def test_columns_include_amount_and_interval(self):
        columns = report.get_columns()
        amount_col = next(c for c in columns if c["fieldname"] == "amount")
        self.assertEqual(amount_col["fieldtype"], "Currency")
        self.assertIn("interval", [c["fieldname"] for c in columns])
        self.assertIn("details", [c["fieldname"] for c in columns])

    # ----------------------------------------- data path needs a live token

    def _live_secret_key(self):
        settings = frappe.get_single("Mollie Settings")
        return settings.get_password("live_secret_key", raise_exception=False)

    def test_get_data_without_valid_mollie_credentials_raises(self):
        # The audit must fail fast rather than returning silently wrong data when
        # Mollie credentials are absent/invalid. Depending on the environment this
        # is either a ValidationError ("Mollie Live API Key not configured") or an
        # HTTP error surfaced from the live subscriptions endpoint -- both are
        # frappe exceptions and both legitimately log to the Error Log, which we
        # mark expected so the tearDown guard does not flag them.
        self.expectErrorLog(
            "Subscription Audit",
            "Mollie api_connection",
            "HTTP Request Failed",
            "Mollie Live API Key not configured",
        )
        with self.assertRaises(Exception):
            report.get_data({})

    def test_execute_without_valid_mollie_credentials_raises(self):
        self.expectErrorLog(
            "Subscription Audit",
            "Mollie api_connection",
            "HTTP Request Failed",
            "Mollie Live API Key not configured",
        )
        with self.assertRaises(Exception):
            report.execute({})
