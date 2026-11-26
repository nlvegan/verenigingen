# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
`MandateService.execute_debit_for_invoice` must refuse a mandate/invoice mismatch
for EVERY caller (#2819, maintainer ruling 2026-11-20).

Before the fix the service checked mandate status, invoice docstatus and outstanding
amount but never that the mandate owner's Customer (`Member.customer`) is the
invoice's customer. #1089 added that pairing only in the whitelisted API and only for
non-staff, so a staff caller (or any internal caller) could debit member A's mandate
for member B's invoice. A mandate with no member is refused as well.

Real Member / Customer / Sales Invoice / ING Checkout Mandate documents; only the
Pay.nl HTTP client is stubbed (at `get_client()`), and every refusal test asserts that
the stub was never called and no ING Checkout Transaction was booked.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ing_checkout.api import mandate as mandate_api
from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

GET_CLIENT = "verenigingen.verenigingen_payments.ing_checkout.client.get_client"


class TestExecuteDebitInvoicePairing(MemberOwnershipProbeMixin, EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.member_a = self.create_test_member(first_name="Pairing2819A")
        self.member_b = self.create_test_member(first_name="Pairing2819B")
        self.customer_a = self._pairing_2819_give_customer(self.member_a)
        self.customer_b = self._pairing_2819_give_customer(self.member_b)
        self.mandate_a = self._pairing_2819_mandate(self.member_a.name)
        self.invoice_a = self._pairing_2819_invoice(self.customer_a)
        self.invoice_b = self._pairing_2819_invoice(self.customer_b)
        self.service = MandateService()
        self.client = MagicMock()
        self.client.create_direct_debit.return_value = {"referenceId": "DD-PAIRING-2819"}
        # Mock justified: external Pay.nl HTTP boundary, not business logic.
        patcher = patch(GET_CLIENT, return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pairing_2819_give_customer(self, member):
        customer = self.sepa.create_test_customer(customer_name=f"Cust {member.name}").name
        frappe.db.set_value("Member", member.name, "customer", customer)
        return customer

    def _pairing_2819_mandate(self, member_name):
        mandate = frappe.get_doc(
            {
                "doctype": "ING Checkout Mandate",
                "mandate_id": f"MD-{frappe.generate_hash(length=10)}",
                "mandate_type": "flexible",
                "status": "Active",
                "debtor_name": "Pairing Probe",
                "debtor_iban": "NL91ABNA0417164300",
                "member": member_name,
            }
        )
        mandate.insert()
        self.track_doc("ING Checkout Mandate", mandate.name)
        return mandate

    def _pairing_2819_invoice(self, customer):
        invoice = self.sepa.create_test_sales_invoice(
            customer=customer,
            grand_total=42.0,
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
        )
        invoice.submit()
        return invoice

    def _assert_nothing_sent_or_booked(self, invoice):
        self.client.create_direct_debit.assert_not_called()
        self.assertFalse(
            frappe.db.exists(
                "ING Checkout Transaction",
                {"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
            ),
            "a refused pairing must not book a transaction",
        )

    def test_service_refuses_other_members_invoice(self):
        result = self.service.execute_debit_for_invoice(self.mandate_a.name, self.invoice_b.name)
        self.assertFalse(result["success"], result)
        self.assertIn("does not belong", result["error"])
        self._assert_nothing_sent_or_booked(self.invoice_b)

    def test_staff_through_the_api_is_refused_too(self):
        staff = self._staff_user()
        with self.set_user(staff):
            result = mandate_api.execute_debit_for_invoice(self.mandate_a.name, self.invoice_b.name)
        self.assertFalse(result["success"], result)
        self.assertIn("does not belong", result["error"])
        self._assert_nothing_sent_or_booked(self.invoice_b)

    def test_pairing_is_refused_before_status_and_docstatus_checks(self):
        """A mispaired call reports the pairing error whatever else is wrong.

        Probe shortcut: the mandate status is set with `db.set_value` rather than
        driven through a real cancellation; the invoice is a real never-submitted
        draft. Pins that the guard runs BEFORE the status/docstatus/outstanding
        checks, so a mispair is never masked by (or reported as) another refusal.
        """
        frappe.db.set_value("ING Checkout Mandate", self.mandate_a.name, "status", "Cancelled")
        result = self.service.execute_debit_for_invoice(self.mandate_a.name, self.invoice_b.name)
        self.assertIn("does not belong", result.get("error", ""), result)
        frappe.db.set_value("ING Checkout Mandate", self.mandate_a.name, "status", "Active")
        draft_b = self.sepa.create_test_sales_invoice(
            customer=self.customer_b,
            grand_total=42.0,
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
        )
        self.assertEqual(draft_b.docstatus, 0)
        result = self.service.execute_debit_for_invoice(self.mandate_a.name, draft_b.name)
        self.assertIn("does not belong", result.get("error", ""), result)
        self._assert_nothing_sent_or_booked(draft_b)

    def test_mandate_without_member_is_refused(self):
        orphan = self._pairing_2819_mandate(None)
        result = self.service.execute_debit_for_invoice(orphan.name, self.invoice_a.name)
        self.assertFalse(result["success"], result)
        self.assertIn("does not belong", result["error"])
        self._assert_nothing_sent_or_booked(self.invoice_a)

    def test_member_without_customer_is_refused(self):
        member_c = self.create_test_member(first_name="Pairing2819C")
        frappe.db.set_value("Member", member_c.name, "customer", None)
        mandate_c = self._pairing_2819_mandate(member_c.name)
        result = self.service.execute_debit_for_invoice(mandate_c.name, self.invoice_a.name)
        self.assertFalse(result["success"], result)
        self._assert_nothing_sent_or_booked(self.invoice_a)

    def test_matching_pair_still_debits(self):
        """Control: the guard must not block the legitimate pairing."""
        result = self.service.execute_debit_for_invoice(self.mandate_a.name, self.invoice_a.name)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["reference_id"], "DD-PAIRING-2819")
        self.client.create_direct_debit.assert_called_once()
        self.assertTrue(
            frappe.db.exists(
                "ING Checkout Transaction",
                {"reference_doctype": "Sales Invoice", "reference_name": self.invoice_a.name},
            )
        )

    def test_staff_through_the_api_may_debit_the_matching_pair(self):
        staff = self._staff_user()
        with self.set_user(staff):
            result = mandate_api.execute_debit_for_invoice(self.mandate_a.name, self.invoice_a.name)
        self.assertTrue(result["success"], result)
