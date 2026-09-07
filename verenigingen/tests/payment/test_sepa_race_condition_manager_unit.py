"""#958: `_lock_invoices_for_processing` must not flatten a non-resumable DB error.

Split out of test_sepa_race_condition_manager.py (Tier 2 / integration) into its
own Tier 1 / unit file -- the enforcer blocks mocking `frappe.db.sql` directly in
an integration test, and this is exactly that: the whole point is to inject a
`frappe.QueryDeadlockError` at the `SELECT ... FOR UPDATE` without a second real
connection to contend for the lock.

`_lock_invoices_for_processing`'s `except Exception as e: raise SEPAError(...)`
flattens a real `frappe.QueryDeadlockError` from that statement into a `SEPAError`
(a `VerenigingenException`). `handle_api_error` (the decorator on the public
`create_sepa_batch_with_race_protection` endpoint) has a dedicated
`except NON_RESUMABLE_DB_ERRORS` clause that re-raises a 1213/1205 instead of
returning it as an ordinary `OperationResult.fail(...)` -- precisely so the
request does not reach its success path and commit half-applied work (#481). A
`SEPAError` is a `VerenigingenException`, so once the type is destroyed here that
guard can never fire and the deadlock is reported as a normal, non-retryable
batch failure.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.non_resumable_errors import deadlock
from verenigingen.verenigingen_payments.utils.sepa_race_condition_manager import (
    SEPABatchRaceConditionManager,
)


class TestLockInvoicesForProcessingPreservesNonResumableErrors(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.manager = SEPABatchRaceConditionManager()

    def _make_unpaid_invoice(self):
        member = self.sepa.create_test_member(first_name="Race")
        customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}")
        member.db_set("customer", customer.name)
        self.sepa.create_test_sepa_mandate(member=member.name)
        membership = self.sepa.create_test_membership(member=member.name)
        invoice = self.sepa.create_test_sales_invoice(
            customer=customer.name,
            member=member.name,
            membership=membership.name,
            submit=True,
        )
        invoice.reload()
        return invoice

    def test_lock_invoices_deadlock_propagates_as_deadlock_not_sepa_error(self):
        invoice = self._make_unpaid_invoice()

        with patch("frappe.db.sql", side_effect=deadlock()):
            with self.assertRaises(frappe.QueryDeadlockError):
                self.manager._lock_invoices_for_processing([invoice.name])


if __name__ == "__main__":
    import unittest

    unittest.main()
