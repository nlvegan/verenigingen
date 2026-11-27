"""#822: a DRAFT Bank Transaction must not read as "already processed" in the bulk-run
retry queue or the admin payment dashboard.

A draft is what an earlier caller without submit permission leaves behind (#383). Rows are
seeded raw (docstatus 0/1) on the Mollie account; the "submit refused / submit succeeds"
outcome of ``_try_submit_existing_draft`` is the only seam replaced, because a raw-SQL row
cannot be genuinely submitted (that real path is #383's own test).

Run:
    scripts/testing/run_without_credentials.sh test_site_8 \\
        verenigingen.tests.payment.test_mollie_draft_bank_transaction_retry_822
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.payment.test_mollie_bt_lookup_account_scope_2620 import (
    MOLLIE_ACCOUNT,
    OTHER_ACCOUNT,
    BankTransactionScopeCase,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator


class TestDraftBankTransactionRetry822(BankTransactionScopeCase):
    def run_bulk_row(self, row, submit_outcome):
        """Run one row through the real _process_rows; ``submit_outcome(creator, name)`` is the
        stand-in for the resubmit attempt (None leaves the draft a draft)."""
        from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc

        run = MagicMock(status="Processing", payments=[row], last_processed_index=0)
        run.total_succeeded = run.total_skipped = run.total_failed = 0
        orchestrator = MagicMock()
        orchestrator.process_payment.side_effect = RuntimeError("stop-822")

        def attempt(creator, name, reference):
            if submit_outcome:
                submit_outcome(name)

        with patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator.get_payment_orchestrator",
            return_value=orchestrator,
        ), patch.object(
            # Mock justified: a raw-SQL seeded row cannot really submit; the real resubmit is #383's test.
            BankTransactionCreator,
            "_try_submit_existing_draft",
            autospec=True,
            side_effect=attempt,
        ) as submit, patch.object(svc, "_checkpoint"), patch.object(
            svc, "_cancel_requested", return_value=False
        ):
            svc._process_rows(run)
        return orchestrator, submit

    def pending_row(self, reference=None):
        return SimpleNamespace(payment_id=reference or self.ref, attempts=0, row_status="Pending")

    def test_a_still_draft_row_is_not_skipped_and_stays_retryable(self):
        draft = self.seed_bt("DRAFT", MOLLIE_ACCOUNT, docstatus=0)
        row = self.pending_row()
        self.run_bulk_row(row, submit_outcome=None)
        self.assertEqual(row.row_status, "Failed", "Skipped would hide the unfinished import for good")
        self.assertEqual(row.bank_transaction, draft)
        self.assertIn("still a draft", row.message)
        self.assertIn("submit failed", row.message, "Administrator may submit, so this is a failure, not a refusal")
        self.assertEqual(row.attempts, 1, "Failed rows below the attempt cap are retried on resume")

    def test_a_draft_that_submits_on_retry_is_skipped_as_imported(self):
        draft = self.seed_bt("DRAFT", MOLLIE_ACCOUNT, docstatus=0)
        row = self.pending_row()

        def submit(name):
            frappe.db.sql("UPDATE `tabBank Transaction` SET docstatus = 1 WHERE name = %s", name)

        _, attempt = self.run_bulk_row(row, submit_outcome=submit)
        self.assertEqual(attempt.call_count, 1)
        self.assertEqual(row.row_status, "Skipped")
        self.assertEqual(row.bank_transaction, draft)

    def test_a_submitted_row_is_skipped_without_a_resubmit_attempt(self):
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT, docstatus=1)
        row = self.pending_row()
        _, attempt = self.run_bulk_row(row, submit_outcome=None)
        self.assertEqual(row.row_status, "Skipped")
        self.assertEqual(row.bank_transaction, own)
        attempt.assert_not_called()

    def test_another_accounts_draft_is_neither_resubmitted_nor_skips_the_payment(self):
        self.seed_bt("OTHER", OTHER_ACCOUNT, docstatus=0)
        row = self.pending_row()
        orchestrator, attempt = self.run_bulk_row(row, submit_outcome=None)
        attempt.assert_not_called()
        orchestrator.process_payment.assert_called_once()
        self.assertIn("stop-822", row.message)

    def admin_rows(self, references):
        from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service as svc

        def payment(pid):
            return SimpleNamespace(
                id=pid, status="paid", amount={"currency": "EUR", "value": "10.00"}, created_at=None,
                paid_at=None, description="x", customer_id=None, subscription_id=None,
            )

        payment_list = MagicMock()
        payment_list.__iter__.return_value = iter([payment(r) for r in references])
        payment_list.has_next.return_value = False
        client = MagicMock()
        client.sdk_client.payments.list.return_value = payment_list
        client.list_resource_page.side_effect = lambda name, **kw: getattr(client.sdk_client, name).list(**kw)
        matcher = MagicMock()
        matcher.find_member_for_payment.return_value = None
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient", return_value=client
        ), patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher",
            return_value=matcher,
        ):
            result = svc._retrieve_global_payments_with_orphans(
                days_back=3650, max_payments=10, payment_status_filter="all"
            )
        self.assertNotIn("error", result)
        return {r["payment_id"]: r for r in result["orphaned_transactions"]}

    def test_admin_map_does_not_report_a_draft_as_processed(self):
        draft_ref, mixed_ref, submitted_ref, foreign_ref = (f"{self.ref}{s}" for s in "dmsf")
        self.seed_bt("DRAFT", MOLLIE_ACCOUNT, docstatus=0, reference=draft_ref)
        self.seed_bt("MIXED-D", MOLLIE_ACCOUNT, docstatus=0, reference=mixed_ref)
        mixed_sub = self.seed_bt("MIXED-S", MOLLIE_ACCOUNT, docstatus=1, reference=mixed_ref, transaction_id="t2")
        submitted = self.seed_bt("SUB", MOLLIE_ACCOUNT, docstatus=1, reference=submitted_ref)
        self.seed_bt("OTHER", OTHER_ACCOUNT, docstatus=1, reference=foreign_ref)
        other_company_ref = f"{self.ref}c"
        other_company_bt = self.seed_bt("OTHERCO", MOLLIE_ACCOUNT, docstatus=1, reference=other_company_ref)
        frappe.db.sql(
            "UPDATE `tabBank Transaction` SET company = 'TEST-822-Other Company' WHERE name = %s",
            other_company_bt,
        )
        rows = self.admin_rows([draft_ref, mixed_ref, submitted_ref, foreign_ref, other_company_ref])
        self.assertFalse(rows[other_company_ref]["already_processed"], "another company's row is not ours")
        self.assertFalse(rows[draft_ref]["already_processed"])
        self.assertTrue(rows[draft_ref]["processable"])
        self.assertTrue(rows[mixed_ref]["already_processed"], "a submitted row beside a draft is processed")
        self.assertEqual(rows[mixed_ref]["bank_transaction"], mixed_sub)
        self.assertTrue(rows[submitted_ref]["already_processed"])
        self.assertEqual(rows[submitted_ref]["bank_transaction"], submitted)
        self.assertFalse(rows[foreign_ref]["already_processed"])
