"""Tests for v2_2.retry_mollie_and_bank_transaction_unique_indexes (#746).

This patch exists to reach sites where the pre-fix Mollie/Bank Transaction index
patches already ran, bailed on duplicates, and got recorded as executed anyway --
fixing the source of those two patches does nothing for a site where Frappe already
believes them done (see module docstring). These tests exercise the aggregation
behaviour (both attempted, failures combined) rather than re-proving the underlying
patches' own duplicate/idempotency logic, which is covered by their own test modules.
"""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.retry_mollie_and_bank_transaction_unique_indexes import execute

MODULE = "verenigingen.patches.v2_2.retry_mollie_and_bank_transaction_unique_indexes"


class TestRetryMollieAndBankTransactionUniqueIndexes(FrappeTestCase):
    def test_succeeds_when_both_underlying_patches_succeed(self):
        with patch(f"{MODULE}.ensure_mollie_payment_entry_index") as mollie:
            with patch(f"{MODULE}.ensure_bank_transaction_index") as bank:
                execute()  # must not raise

        mollie.assert_called_once_with()
        bank.assert_called_once_with()

    def test_attempts_bank_transaction_even_if_mollie_fails(self):
        """A duplicate blocking one table must not hide the report on the other."""
        with patch(f"{MODULE}.ensure_mollie_payment_entry_index", side_effect=Exception("mollie boom")):
            with patch(f"{MODULE}.ensure_bank_transaction_index") as bank:
                with self.assertRaises(Exception):
                    execute()

        bank.assert_called_once_with()

    def test_raises_and_reports_both_failures(self):
        with patch(
            f"{MODULE}.ensure_mollie_payment_entry_index", side_effect=Exception("mollie boom")
        ):
            with patch(
                f"{MODULE}.ensure_bank_transaction_index", side_effect=Exception("bank boom")
            ):
                with self.assertRaises(Exception) as ctx:
                    execute()

        self.assertIn("mollie boom", str(ctx.exception))
        self.assertIn("bank boom", str(ctx.exception))

    def test_logs_a_traceback_for_each_unexpected_failure(self):
        """An unexpected (non-duplicate) failure must not rely on `str(e)` alone.

        The duplicates-found path already logs its own detailed report; this
        aggregator's job is to make sure a DIFFERENT kind of failure -- a real DB
        error, a lock timeout -- isn't left with only a one-line message and no
        traceback. frappe.log_error must be called once per failure.
        """
        with patch(f"{MODULE}.ensure_mollie_payment_entry_index", side_effect=Exception("mollie boom")):
            with patch(f"{MODULE}.ensure_bank_transaction_index", side_effect=Exception("bank boom")):
                with patch(f"{MODULE}.frappe.log_error") as log_error:
                    with self.assertRaises(Exception):
                        execute()

        self.assertEqual(log_error.call_count, 2)
        titles = [call.kwargs.get("title", "") for call in log_error.call_args_list]
        self.assertTrue(any("Mollie" in t for t in titles))
        self.assertTrue(any("Bank Transaction" in t for t in titles))
