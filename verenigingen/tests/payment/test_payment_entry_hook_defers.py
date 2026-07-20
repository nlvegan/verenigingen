from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentEntryHookDefers(EnhancedTestCase):
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
