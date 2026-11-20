# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
create_ideal_payment charges a Sales Invoice's outstanding amount, never the caller's (#3023).

Mirrors the Mollie ruling (#2225, ``MollieGateway._amount_to_charge``): a Sales Invoice
charges its ``outstanding_amount``; a client-sent figure is ignored; a draft or settled
invoice is refused with "There is nothing left to pay on this document.".

Harm, measured by driving the real flow (fake Pay.nl client, real submitted Sales Invoice,
real ``_process_payment_webhook`` and Payment Entry): the webhook books the amount stored on
the ING Checkout Transaction, which is the CALLER's amount, not the invoice's outstanding. An
underpayment therefore leaves the invoice "Partly Paid" and an overpayment books an unallocated
credit. Pay.nl's own paid amount is not consulted by the booking.

Fixture helpers are borrowed from test_transaction_service (plain functions, so the loader does
not re-collect the donor TestCase). Pay.nl is faked at ``payment.get_client`` and settings.
"""

import types
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.ing_checkout.api import payment as payment_api
from verenigingen.verenigingen_payments.ing_checkout.api import webhook as webhook_api
from verenigingen.verenigingen_payments.ing_checkout.tests import test_payment_api_ownership as ownership
from verenigingen.verenigingen_payments.ing_checkout.tests import test_transaction_service as _txn_tests

NOTHING_LEFT = "There is nothing left to pay on this document."
_SETTINGS_PATH = (
    "verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings."
    "get_ing_checkout_settings"
)


class _Fake3023Mixin:
    """Fake Pay.nl + settings, shared by the E2E and the ownership-ordering classes."""

    def _ing3023_fake_pay_nl(self):
        self.ing3023_client = MagicMock()
        self.ing3023_client.create_order.side_effect = lambda order_data: {
            "id": f"EX-3023-{frappe.generate_hash(length=8)}",
            "links": {"redirect": "https://pay.example.test/checkout"},
        }
        settings = types.SimpleNamespace(service_id="SL-TEST", default_return_url="https://example.test/ok")
        for p in (
            patch.object(payment_api, "get_client", return_value=self.ing3023_client),
            patch(_SETTINGS_PATH, return_value=settings),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _ing3023_charged_cents(self):
        order_data = self.ing3023_client.create_order.call_args[0][0]
        return order_data["amount"]["value"]


class TestIdealAmountComesFromTheInvoice(_Fake3023Mixin, EnhancedTestCase):
    _ensure_mode_of_payment = _txn_tests.TestCreatePaymentEntryWithInvoice._ensure_mode_of_payment
    _make_submitted_invoice = _txn_tests.TestCreatePaymentEntryWithInvoice._make_submitted_invoice
    _make_draft_invoice = _txn_tests.TestCreatePaymentEntryWithInvoice._make_draft_invoice
    _ensure_customer = _txn_tests.TestCreatePaymentEntryWithInvoice._ensure_customer
    _ensure_item = _txn_tests.TestCreatePaymentEntryWithInvoice._ensure_item

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

        ensure_test_fiscal_year_for_all_companies()
        self._ensure_mode_of_payment()
        self._ing3023_fake_pay_nl()
        self.invoice = self._make_submitted_invoice(rate=25.00)
        self.invoice.reload()
        self.outstanding = flt(self.invoice.outstanding_amount)

    def _ing3023_create(self, invoice, amount):
        return payment_api.create_ideal_payment("Sales Invoice", invoice.name, amount, "probe")

    def _ing3023_pay_via_webhook(self, invoice, order_id):
        """The real webhook path; Pay.nl reports exactly what the order asked it to charge."""
        payload = {
            "id": order_id,
            "object": {
                "reference": f"SINV:{invoice.name}",
                "amount": {"value": self._ing3023_charged_cents(), "currency": "EUR"},
                "status": {"code": 100},
                "payments": [],
            },
        }
        settings = {"ing_checkout_bank_account": _txn_tests.TEST_BANK_ACCOUNT}
        with patch("verenigingen.utils.settings_utils.get_payments_settings", return_value=settings):
            return webhook_api._process_payment_webhook(order_id, payload)

    def _ing3023_pe_amounts(self, payment_entry):
        pe = frappe.get_doc("Payment Entry", payment_entry)
        return flt(pe.paid_amount), sum(flt(r.allocated_amount) for r in pe.references)

    def test_underpaying_caller_amount_is_ignored_and_invoice_settles(self):
        result = self._ing3023_create(self.invoice, self.outstanding - 10.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._ing3023_charged_cents(), round(self.outstanding * 100))
        self._ing3023_pay_via_webhook(self.invoice, result["transaction_id"])
        self.invoice.reload()
        self.assertEqual(flt(self.invoice.outstanding_amount), 0.0)

    def test_overpaying_caller_amount_is_ignored_and_no_credit_is_booked(self):
        result = self._ing3023_create(self.invoice, self.outstanding + 15.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._ing3023_charged_cents(), round(self.outstanding * 100))
        txn = self._ing3023_pay_via_webhook(self.invoice, result["transaction_id"])
        paid, allocated = self._ing3023_pe_amounts(txn["payment_entry"])
        self.assertEqual((paid, allocated), (self.outstanding, self.outstanding))

    def test_transaction_row_records_the_outstanding_not_the_caller_amount(self):
        result = self._ing3023_create(self.invoice, 0.01)

        stored = frappe.db.get_value(
            "ING Checkout Transaction", {"transaction_id": result["transaction_id"]}, "amount"
        )
        self.assertEqual(flt(stored), self.outstanding)

    def test_partly_paid_invoice_charges_the_remaining_outstanding(self):
        """Control: outstanding differs from grand_total, so charging grand_total is detectable."""
        first = self._ing3023_create(self.invoice, self.outstanding)
        # Pay.nl settles only part of it: book a partial Payment Entry through the real service.
        service_settings = {"ing_checkout_bank_account": _txn_tests.TEST_BANK_ACCOUNT}
        with patch("verenigingen.utils.settings_utils.get_payments_settings", return_value=service_settings):
            from verenigingen.verenigingen_payments.ing_checkout.services import get_transaction_service

            partial = get_transaction_service().create_payment_entry_for_transaction(
                transaction_name="TXN-3023",
                transaction_id=first["transaction_id"],
                reference_doctype="Sales Invoice",
                reference_name=self.invoice.name,
                amount=10.0,
            )
        self.assertTrue(partial["success"], partial)
        self.invoice.reload()
        remaining = flt(self.invoice.outstanding_amount)
        self.assertNotEqual(remaining, flt(self.invoice.grand_total), "premise: partly paid")

        self.ing3023_client.create_order.reset_mock()
        self._ing3023_create(self.invoice, self.outstanding)

        self.assertEqual(self._ing3023_charged_cents(), round(remaining * 100))

    def test_settled_invoice_is_refused_and_pay_nl_not_called(self):
        self.invoice.db_set("outstanding_amount", 0)
        before = frappe.db.count("ING Checkout Transaction")

        result = self._ing3023_create(self.invoice, 25.0)

        self.assertEqual(result, {"success": False, "message": NOTHING_LEFT})
        self.ing3023_client.create_order.assert_not_called()
        self.assertEqual(frappe.db.count("ING Checkout Transaction"), before)

    def test_draft_invoice_is_refused_and_pay_nl_not_called(self):
        draft = self._make_draft_invoice(rate=25.00)
        self.assertGreater(flt(draft.outstanding_amount), 0, "premise: a draft mirrors grand_total")

        result = self._ing3023_create(draft, flt(draft.outstanding_amount))

        self.assertEqual(result, {"success": False, "message": NOTHING_LEFT})
        self.ing3023_client.create_order.assert_not_called()

    def test_desk_button_case_full_outstanding_still_works(self):
        """sales_invoice_ing_checkout.js sends frm.doc.outstanding_amount."""
        result = self._ing3023_create(self.invoice, self.outstanding)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._ing3023_charged_cents(), round(self.outstanding * 100))

    def test_member_reference_keeps_its_caller_amount(self):
        """Unchanged on purpose: a Member has no amount source, so no server-side figure exists."""
        member = self.create_test_member(first_name="Ing3023", last_name="Amount")

        result = payment_api.create_ideal_payment("Member", member.name, 12.34, "probe")

        self.assertTrue(result["success"], result)
        self.assertEqual(self._ing3023_charged_cents(), 1234)


class TestAmountCheckRunsAfterTheOwnershipRefusal(_Fake3023Mixin, ownership._Pay2814Base):
    """A forbidden invoice's settled state must not be observable through the amount refusal.

    Scope: the protection is the WRAPPER's #2814 ownership gate. `create_ideal_order` called
    directly does not hide it (its `check_permission("read")` passes for a board member;
    measured), so the amount check's position inside it is not pinned and not claimed.
    """

    def setUp(self):
        super().setUp()
        self._ing3023_fake_pay_nl()
        with self.set_user("Administrator"):
            self.victim_invoice.reload()
            self.victim_invoice.submit()
        frappe.db.set_value("Sales Invoice", self.victim_invoice.name, "outstanding_amount", 0)

    def _create(self, name):
        return payment_api.create_ideal_payment("Sales Invoice", name, 42.0, "probe")

    def test_settled_foreign_invoice_is_indistinguishable_from_unknown(self):
        with self.set_user(self.attacker):
            unknown = self._observe(self._create, ownership.UNKNOWN_INVOICE)
            forbidden = self._observe(self._create, self.victim_invoice.name)

        self.assertEqual(forbidden["outcome"][0], "raised", forbidden)
        self.assertIs(forbidden["outcome"][1], frappe.PermissionError)
        self.assertEqual(unknown, forbidden)
        self.ing3023_client.create_order.assert_not_called()

    def test_own_settled_invoice_gets_the_nothing_left_refusal(self):
        self._ing3023_submit_own_invoice()
        frappe.db.set_value("Sales Invoice", self.own_invoice.name, "outstanding_amount", 0)
        with self.set_user(self.attacker):
            result = self._create(self.own_invoice.name)

        self.assertEqual(result, {"success": False, "message": NOTHING_LEFT})

    def _ing3023_submit_own_invoice(self):
        """The base fixture invoice is a draft (refused by design); submit it as a real invoice."""
        with self.set_user("Administrator"):
            self.own_invoice.reload()
            self.own_invoice.submit()
        self.assertEqual(self.own_invoice.docstatus, 1)

    def test_own_draft_invoice_is_refused(self):
        self.assertEqual(frappe.db.get_value("Sales Invoice", self.own_invoice.name, "docstatus"), 0)
        with self.set_user(self.attacker):
            result = self._create(self.own_invoice.name)

        self.assertEqual(result, {"success": False, "message": NOTHING_LEFT})

    def test_own_invoice_charges_outstanding_not_caller_amount(self):
        self._ing3023_submit_own_invoice()
        outstanding = flt(frappe.db.get_value("Sales Invoice", self.own_invoice.name, "outstanding_amount"))
        with self.set_user(self.attacker):
            result = payment_api.create_ideal_payment("Sales Invoice", self.own_invoice.name, 1.0, "probe")

        self.assertTrue(result["success"], result)
        self.assertEqual(self._ing3023_charged_cents(), round(outstanding * 100))
