from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentEntryHookDefers(EnhancedTestCase):
    def _build_test_invoice(self, customer, rate=42.0):
        """Build + submit a v16-valid EUR Sales Invoice for `customer`.

        Field set mirrors
        ``test_integrated_security_payment_system.py::_build_secured_invoice``
        so the invoice passes v16 mandatory-field validation.
        """
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        company = get_eur_test_company()
        self._ensure_test_item("TEST-MEMBERSHIP")

        debit_to = frappe.db.get_value(
            "Company", company, "default_receivable_account"
        ) or frappe.db.get_value(
            "Account", {"account_type": "Receivable", "company": company, "is_group": 0}, "name"
        )
        income_account = frappe.db.get_value(
            "Account", {"account_type": "Income Account", "company": company, "is_group": 0}, "name"
        )
        cost_center = frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )
        price_list = frappe.db.get_value("Price List", {"selling": 1}, "name") or "Standard Selling"

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer
        invoice.company = company
        invoice.currency = "EUR"
        invoice.conversion_rate = 1.0
        invoice.debit_to = debit_to
        invoice.selling_price_list = price_list
        invoice.price_list_currency = "EUR"
        invoice.plc_conversion_rate = 1.0
        invoice.ignore_pricing_rule = 1
        invoice.posting_date = today()
        invoice.set_posting_time = 1
        invoice.due_date = add_days(invoice.posting_date, 30)
        invoice.is_membership_invoice = 1
        invoice.append(
            "items",
            {
                "item_code": "TEST-MEMBERSHIP",
                "qty": 1,
                "rate": rate,
                "income_account": income_account,
                "cost_center": cost_center,
            },
        )
        invoice.save()
        invoice.submit()
        return invoice

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

        invoice = self._build_test_invoice(member.customer)

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
