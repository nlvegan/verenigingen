# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
`MandateService.execute_debit_for_invoice` against a REAL Sales Invoice (#856).

`test_mandate_service_unit.py` covers this method's success/inactive/zero-outstanding
branches with `MagicMock` invoices - fine for the Pay.nl payload shape, but a
`docstatus` guard is exactly the kind of check a mock can accidentally satisfy for
the wrong reason (the same shape that hid #623 for `Member`). This uses a real,
never-submitted Sales Invoice instead, and a real "ING Checkout Mandate" document -
only the Pay.nl HTTP client is mocked, at `get_client()`, the module's own external
boundary (mandate resolution against real documents is separately covered by
`test_ing_checkout_mandate_resolution.py`).

The bug: `execute_debit_for_invoice` read `invoice.outstanding_amount` and refused
only when it was `<= 0` ("no outstanding amount"), with no `docstatus` check. A draft
Sales Invoice does NOT carry `outstanding_amount == 0` - `calculate_outstanding_amount`
runs on every save that is not cancelled, so a draft carries its full `grand_total`.
So the old code let a draft through as a normal payable invoice, called
`mandate.execute_debit(amount=invoice.outstanding_amount, ...)`, and recorded an ING
Checkout Transaction referencing it - a debit initiated, and a ledger row created,
against a document that does not exist yet as far as ERPNext's own accounting is
concerned (a Payment Entry against it is refused at submit: "... must be submitted").
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ing_checkout.services import MandateService


class TestExecuteDebitForInvoiceDocstatusGuard(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.member = self.sepa.create_test_member(first_name="INGDebitDraft")
        if not self.member.customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {self.member.full_name}").name
            self.member.db_set("customer", customer)
            self.member.reload()

        self.mandate = self._make_active_mandate()
        self.service = MandateService()

    def _make_active_mandate(self):
        """A real, Active ING Checkout Mandate document."""
        mandate = frappe.get_doc(
            {
                "doctype": "ING Checkout Mandate",
                "mandate_id": f"MD-{frappe.generate_hash(length=10)}",
                "mandate_type": "flexible",
                "status": "Active",
                "debtor_name": self.member.full_name,
                "debtor_iban": "NL91ABNA0417164300",
                "member": self.member.name,
            }
        )
        mandate.insert(ignore_permissions=True)
        return mandate

    def _draft_invoice(self, amount=42.0):
        """A never-submitted Sales Invoice - docstatus 0."""
        return self.sepa.create_test_sales_invoice(
            customer=self.member.customer,
            grand_total=amount,
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
            # submit defaults to False
        )

    def test_draft_invoice_carries_nonzero_outstanding(self):
        """Premise: a draft's outstanding_amount is its grand_total, not 0."""
        invoice = self._draft_invoice(amount=42.0)
        self.assertEqual(invoice.docstatus, 0)
        self.assertGreater(flt(invoice.outstanding_amount), 0)

    def test_draft_invoice_is_refused_not_debited(self):
        """The fix: a draft must be refused before any debit is attempted.

        No Pay.nl mock is needed here: the guard must fire BEFORE
        `mandate.execute_debit` is ever reached, so nothing here can call out.
        """
        invoice = self._draft_invoice(amount=42.0)

        result = self.service.execute_debit_for_invoice(self.mandate.name, invoice.name)

        self.assertFalse(result["success"])
        self.assertIn("not submitted", result["error"].lower())
        self.assertFalse(
            frappe.db.exists(
                "ING Checkout Transaction",
                {"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
            ),
            "no transaction may be recorded against a draft invoice",
        )

    def test_submitted_invoice_still_proceeds_to_debit(self):
        """Control: the guard must not block a real, submitted, unpaid invoice."""
        invoice = self._draft_invoice(amount=42.0)
        invoice.submit()

        mock_client = MagicMock()
        mock_client.create_direct_debit.return_value = {"referenceId": "DD-DRAFT-TEST"}

        # Mock justified: external Pay.nl HTTP boundary, not business logic.
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.client.get_client",
            return_value=mock_client,
        ):
            result = self.service.execute_debit_for_invoice(self.mandate.name, invoice.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["reference_id"], "DD-DRAFT-TEST")
        mock_client.create_direct_debit.assert_called_once()
        self.assertTrue(
            frappe.db.exists(
                "ING Checkout Transaction",
                {"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
            ),
            "a submitted invoice must still record its transaction",
        )
