from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import build_eur_membership_invoice


class TestPaymentEntryHookDefers(EnhancedTestCase):
    def test_drain_fn_lands_history_row(self):
        """End-to-end proof that the drain worker function lands a
        payment_history row for the member — the enqueue path (per-handler)
        is already unit-tested; this proves the drain itself works.
        """
        from verenigingen.utils.background_jobs import drain_member_payment_history

        member = self.create_test_member(
            first_name="Drain",
            last_name="Lands",
            email="drain.lands@test.invalid",
        )
        self.assertTrue(member.customer, "test member must have a customer for invoicing")

        invoice = build_eur_membership_invoice(self, member.customer)

        drain_member_payment_history(member.name, member.customer)

        member.reload()
        self.assertIn(
            invoice.name,
            [e.invoice for e in member.payment_history],
            "drain_member_payment_history should have landed the submitted invoice "
            "into the member's payment_history",
        )

    def test_handler_enqueues_per_member_and_does_not_process_inline(self):
        from verenigingen.utils import background_jobs

        member = self.create_test_member(
            first_name="HookDefer",
            last_name="Payment",
            email="hookdefer.payment@test.invalid",
        )
        doc = frappe._dict(
            doctype="Payment Entry", name="PE-TEST", party_type="Customer", party=member.customer
        )

        calls = []
        with patch(
            "verenigingen.utils.background_jobs.frappe.enqueue", side_effect=lambda *a, **k: calls.append(k)
        ):
            with patch(
                "verenigingen.utils.financial_history_batch_processor."
                "FinancialHistoryBatchProcessor._process_member_payment_batch"
            ) as proc:
                background_jobs.queue_member_payment_history_update_handler(doc)

        self.assertTrue(calls, "handler must enqueue a drain job")
        k = calls[0]
        self.assertEqual(k.get("member"), member.name)
        self.assertTrue(k.get("enqueue_after_commit"))
        self.assertTrue(k.get("deduplicate"))
        self.assertEqual(k.get("job_id"), f"fin_history_payment_{member.name}")
        proc.assert_not_called()  # no inline processing in the hook
