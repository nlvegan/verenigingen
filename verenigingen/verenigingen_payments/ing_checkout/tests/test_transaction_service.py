# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for ING Checkout TransactionService.

Exercises ``create_payment_entry_for_transaction`` across its guard branches
(missing inputs, unsupported reference type, missing reference document, missing
/ invalid bank account, non-positive amount, already-paid invoice) and the
happy path that creates and submits a real ERPNext Payment Entry against a real
submitted Sales Invoice in ``_Test Company``. The alert-delegation methods are
verified by capturing the call on a real PaymentAlertService double.

These use real Frappe docs (Sales Invoice, Payment Entry, Account). The only
stubbing is the lazily-loaded ``settings`` (a plain dict configuring the bank
account) and ``alert_service`` (to capture delegated calls without sending real
email) -- both are infrastructure seams the service exposes for exactly this.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from verenigingen.verenigingen_payments.ing_checkout.services.transaction_service import (
    TransactionService,
    get_transaction_service,
)

TEST_COMPANY = "_Test Company"
TEST_BANK_ACCOUNT = "_Test Bank - _TC"


class _RecordingAlertService:
    """Captures alert calls so we can assert delegation without sending email."""

    def __init__(self):
        self.overpayment_calls = []
        self.failure_calls = []

    def send_overpayment_alert(self, **kwargs):
        self.overpayment_calls.append(kwargs)

    def send_payment_entry_failure_alert(self, **kwargs):
        self.failure_calls.append(kwargs)


class TestValidatePaymentEntryInputs(FrappeTestCase):
    """Pure-logic validation guard (no DB)."""

    def setUp(self):
        super().setUp()
        self.service = TransactionService()

    def test_missing_transaction_name(self):
        self.assertEqual(
            self.service._validate_payment_entry_inputs("", "Sales Invoice", "SI-1", 10),
            "Transaction name is required",
        )

    def test_missing_reference(self):
        err = self.service._validate_payment_entry_inputs("TXN-1", None, None, 10)
        self.assertIn("no reference document", err)

    def test_invalid_amount_none(self):
        err = self.service._validate_payment_entry_inputs("TXN-1", "Sales Invoice", "SI-1", None)
        self.assertIn("Invalid amount", err)

    def test_invalid_amount_zero(self):
        err = self.service._validate_payment_entry_inputs("TXN-1", "Sales Invoice", "SI-1", 0)
        self.assertIn("Invalid amount", err)

    def test_valid_returns_none(self):
        self.assertIsNone(self.service._validate_payment_entry_inputs("TXN-1", "Sales Invoice", "SI-1", 10))


class TestCreatePaymentEntryGuards(FrappeTestCase):
    """Branches that return an error result before any Payment Entry work."""

    def setUp(self):
        super().setUp()
        self.service = TransactionService()
        # Default to a configured, existing bank account so guards that come
        # *after* the bank-account check can be reached; individual tests
        # override as needed.
        self.service._settings = {"ing_checkout_bank_account": TEST_BANK_ACCOUNT}

    def test_validation_error_bubbles_up(self):
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="",
            transaction_id="EX-1",
            reference_doctype="Sales Invoice",
            reference_name="SI-1",
            amount=10,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Transaction name is required")

    def test_unsupported_reference_type(self):
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-1",
            transaction_id="EX-1",
            reference_doctype="Purchase Invoice",
            reference_name="PI-1",
            amount=10,
        )
        self.assertFalse(result["success"])
        self.assertIn("Unsupported reference type", result["error"])

    def test_reference_document_not_found(self):
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-1",
            transaction_id="EX-1",
            reference_doctype="Sales Invoice",
            reference_name="ACC-SINV-DOES-NOT-EXIST-9999",
            amount=10,
        )
        self.assertFalse(result["success"])
        self.assertIn("Reference document not found", result["error"])


class TestCreatePaymentEntryWithInvoice(FrappeTestCase):
    """Branches and happy path that need a real submitted Sales Invoice."""

    def setUp(self):
        super().setUp()
        self.service = TransactionService()
        # This class submits a Sales Invoice in _Test Company dated today. On a
        # fresh CI runner _Test Company has no Fiscal Year covering today() (and
        # erpnext's bootstrap FY can be restricted to a single company), so submit
        # fails with "Date <today> is not in any active Fiscal Year". This is a
        # FrappeTestCase (not EnhancedTestCase), so seed the FY explicitly. The
        # helper is idempotent and date-driven (self-heals each calendar year).
        from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

        ensure_test_fiscal_year_for_all_companies()
        self._ensure_mode_of_payment()
        self.invoice = self._make_submitted_invoice(rate=25.00)

    # ---- helpers (privileged data creation lives here, not in test bodies) ----

    def _ensure_mode_of_payment(self):
        # The service stamps mode_of_payment="iDEAL" on the Payment Entry; the
        # link must resolve. Production sites ship this Mode of Payment.
        if not frappe.db.exists("Mode of Payment", "iDEAL"):
            frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "iDEAL", "type": "Bank"}).insert(
                ignore_permissions=True
            )

    def _make_submitted_invoice(self, rate):
        customer = self._ensure_customer()
        item = self._ensure_item()
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "company": TEST_COMPANY,
                "customer": customer,
                "currency": "INR",
                "debit_to": "Debtors - _TC",
                "items": [{"item_code": item, "qty": 1, "rate": rate, "income_account": "Sales - _TC"}],
            }
        )
        si.insert(ignore_permissions=True)
        # Strip any auto-applied taxes so the fixture's total == rate. A sibling
        # test in the same shard can leave a committed default Sales Taxes template
        # (or tax rule) flagged for _Test Company; ERPNext then auto-applies it to
        # this no-taxes fixture invoice (see accounts_controller.set_taxes),
        # inflating grand_total above `rate` and breaking the exact allocation /
        # overpayment math the assertions below depend on. set_taxes() only fires
        # while the doc is_new(), so emptying the taxes table (and the master link)
        # after insert is stable across the submit revalidation, regardless of how
        # the tax leaked in. (FrappeTestCase rolls everything back at tearDown.)
        if si.get("taxes") or si.get("taxes_and_charges"):
            si.set("taxes", [])
            si.taxes_and_charges = ""
            si.save(ignore_permissions=True)
        si.submit()
        return si

    def _ensure_customer(self):
        name = "ING-TxnSvc-Test-Customer"
        if not frappe.db.exists("Customer", name):
            frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": name,
                    "customer_type": "Individual",
                    "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
                    "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
                }
            ).insert(ignore_permissions=True)
        return name

    def _ensure_item(self):
        name = "ING-TxnSvc-Test-Item"
        if not frappe.db.exists("Item", name):
            frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": name,
                    "item_name": name,
                    "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
                    "is_stock_item": 0,
                }
            ).insert(ignore_permissions=True)
        return name

    # ---------------------------- tests ----------------------------------

    def test_bank_account_not_configured(self):
        self.service._settings = {}  # no ing_checkout_bank_account
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-1",
            transaction_id="EX-1",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=25.00,
        )
        self.assertFalse(result["success"])
        self.assertIn("Bank account not configured", result["error"])

    def test_bank_account_does_not_exist(self):
        self.service._settings = {"ing_checkout_bank_account": "No Such Account - _TC"}
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-1",
            transaction_id="EX-1",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=25.00,
        )
        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"])

    def test_invoice_already_paid(self):
        # Pay it off first by creating the Payment Entry, then call again.
        # Pay the invoice's ACTUAL outstanding (not a hardcoded 25): a sibling
        # test in the same shard can leak a default/item tax onto _Test Company,
        # inflating grand_total above `rate`, so the amount that fully settles the
        # invoice is only knowable at runtime.
        self.service._settings = {"ing_checkout_bank_account": TEST_BANK_ACCOUNT}
        self.invoice.reload()
        outstanding = flt(self.invoice.outstanding_amount)
        first = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-1",
            transaction_id="EX-1",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=outstanding,
        )
        self.assertTrue(first["success"], msg=first["error"])

        second = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-2",
            transaction_id="EX-2",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=25.00,
        )
        self.assertFalse(second["success"])
        self.assertEqual(second["error"], "Invoice already paid")

    def test_happy_path_creates_and_submits_payment_entry(self):
        self.service._settings = {"ing_checkout_bank_account": TEST_BANK_ACCOUNT}
        # Pay the actual outstanding so the invoice fully settles regardless of
        # any tax leaked onto the fixture by a sibling test (see the
        # already-paid test for the rationale).
        self.invoice.reload()
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-OK",
            transaction_id="EX-OK-123",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=flt(self.invoice.outstanding_amount),
        )
        self.assertTrue(result["success"], msg=result["error"])
        self.assertTrue(result["payment_entry"])
        self.assertIsNone(result["overpayment"])

        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        self.assertEqual(pe.docstatus, 1)  # submitted
        self.assertEqual(pe.reference_no, "EX-OK-123")
        self.assertEqual(pe.mode_of_payment, "iDEAL")
        # Invoice fully settled.
        self.invoice.reload()
        self.assertEqual(flt(self.invoice.outstanding_amount), 0.0)

    def test_overpayment_detected_and_allocation_capped(self):
        self.service._settings = {"ing_checkout_bank_account": TEST_BANK_ACCOUNT}
        # Pay (outstanding + 15) -> 15 overpayment, allocation capped at the
        # outstanding. Derive from the actual outstanding rather than a hardcoded
        # 25 so a sibling test's leaked tax can't break the exact math.
        self.invoice.reload()
        outstanding = flt(self.invoice.outstanding_amount)
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-OVER",
            transaction_id="EX-OVER",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=outstanding + 15.00,
        )
        self.assertTrue(result["success"], msg=result["error"])
        self.assertEqual(flt(result["overpayment"]), 15.00)

        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        # Allocation against the invoice is capped at the outstanding, not the
        # full paid amount.
        allocated = sum(flt(r.allocated_amount) for r in pe.references)
        self.assertEqual(allocated, outstanding)

        # ...but the ENTRY records the full cash Pay.nl settled, with the excess held
        # as an unallocated credit on the customer. Previously the excess was dropped:
        # the entry posted only the capped figure, so the ING clearing account was
        # debited less than the settlement actually moved and could not be reconciled.
        # Asserting `allocated` alone cannot see that difference - the reference row is
        # identical either way - which is why these three assertions exist.
        self.assertEqual(flt(pe.paid_amount, 2), flt(outstanding + 15.00, 2))
        self.assertEqual(flt(pe.unallocated_amount, 2), 15.00)
        self.assertEqual(flt(pe.difference_amount, 2), 0.00)

    def test_remarks_wording_reaches_the_saved_document(self):
        """The gateway's own wording must survive validate().

        Payment Entry.validate() calls set_remarks(), which rebuilds the field and
        returns early only when custom_remarks is truthy. This path used to assign
        remarks alone, so its text was discarded on save - the in-memory document
        looked correct and the stored one did not.

        Assert on the PHRASING, not on the transaction id: ERPNext's generated text
        appends "Transaction reference no {reference_no} dated {date}"
        (payment_entry.py:1250-1252), so the id is present either way and asserting
        on it would pass against the broken behaviour. "ING Checkout payment" is what
        tells an operator which gateway produced the entry, and only the custom text
        carries it. Read back from the database rather than trusting the returned doc.
        """
        self.service._settings = {"ing_checkout_bank_account": TEST_BANK_ACCOUNT}
        self.invoice.reload()
        result = self.service.create_payment_entry_for_transaction(
            transaction_name="TXN-REMARKS",
            transaction_id="EX-REMARKS-9",
            reference_doctype="Sales Invoice",
            reference_name=self.invoice.name,
            amount=flt(self.invoice.outstanding_amount),
        )
        self.assertTrue(result["success"], msg=result["error"])

        stored = frappe.db.get_value(
            "Payment Entry", result["payment_entry"], ["remarks", "custom_remarks"], as_dict=True
        )
        self.assertIn("ING Checkout payment", stored.remarks or "")
        self.assertIn("EX-REMARKS-9", stored.remarks or "")
        self.assertEqual(
            stored.custom_remarks, 1, "custom_remarks must be set or validate() overwrites remarks"
        )


class TestAlertDelegation(FrappeTestCase):
    """The alert methods delegate to the shared PaymentAlertService."""

    def setUp(self):
        super().setUp()
        self.service = TransactionService()
        self.recorder = _RecordingAlertService()
        self.service._alert_service = self.recorder

    def test_handle_overpayment_delegates(self):
        self.service.handle_overpayment(
            transaction_name="TXN-1",
            reference_name="SI-1",
            transaction_amount=40.0,
            outstanding_amount=25.0,
        )
        self.assertEqual(len(self.recorder.overpayment_calls), 1)
        call = self.recorder.overpayment_calls[0]
        self.assertEqual(call["source"], "ING Checkout")
        self.assertEqual(call["amount_paid"], 40.0)
        self.assertEqual(call["amount_due"], 25.0)
        self.assertEqual(call["transaction_doctype"], "ING Checkout Transaction")

    def test_failure_alert_delegates(self):
        self.service.send_payment_entry_failure_alert(
            transaction_name="TXN-1",
            reference_name="SI-1",
            amount=25.0,
            error_message="boom",
        )
        self.assertEqual(len(self.recorder.failure_calls), 1)
        call = self.recorder.failure_calls[0]
        self.assertEqual(call["source"], "ING Checkout")
        self.assertEqual(call["error_message"], "boom")


class TestFactory(FrappeTestCase):
    def test_get_transaction_service_returns_instance(self):
        self.assertIsInstance(get_transaction_service(), TransactionService)
