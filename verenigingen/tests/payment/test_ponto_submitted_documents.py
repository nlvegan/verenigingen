# Copyright (c) 2026, Verenigingen
"""Ponto Payment Request / Payment Link on a REALLY SUBMITTED document -- #1907.

Both doctypes are submittable and production submits them (``before_submit`` calls
Ponto and moves the row to Pending / Pending Authorization). Every earlier Ponto test
inserted at docstatus 0 and set the status by hand, so none of them saw that Frappe
refuses to change a non-``allow_on_submit`` field on a docstatus-1 row
(``UpdateAfterSubmitError``). These tests drive ``Document.submit()`` for real; only the
Ponto HTTP client is stubbed (the call ``before_submit`` makes), and every later step --
the webhook/refresh status write, debtor details, the Payment Entry and its back-link --
runs unmocked.

Usage:
    bench --site test_site_7 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_submitted_documents
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.payment.test_ponto_payment_entry_creation import _ensure_ponto_clearing_account
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    PAY_CLIENT_PATH,
    _PontoPaymentRequestFixtures,
)
from verenigingen.tests.support.sepa_test_company import get_eur_test_company

LINK_CLIENT_PATH = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)


def _create_client(ponto_id):
    """Stand-in for the Ponto client ``before_submit`` calls: ONLY the HTTP boundary."""
    created = SimpleNamespace(id=ponto_id, redirect_link=f"https://ponto.example/sign/{ponto_id}")
    return SimpleNamespace(create_payment=lambda **kw: created, create_payment_request=lambda **kw: created)


def _read_client(status, **extra):
    """Stand-in for the Ponto client a refresh reads the current state from."""
    state = SimpleNamespace(status=status, **extra)
    return SimpleNamespace(get_payment=lambda **kw: state, get_payment_request=lambda *a, **kw: state)


class TestSubmittedPontoPaymentRequest(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """A Request that went through the real submit() lifecycle."""

    def _make_really_submitted_request(self, supplier, amount=42.0):
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = self.TEST_PONTO_ACCOUNT_ID
        req.amount = amount
        req.currency = "EUR"
        req.creditor_name = supplier.supplier_name
        req.creditor_iban = "NL91ABNA0417164300"
        req.remittance_info = "Test payment #1907"
        req.reference_doctype = "Supplier"
        req.reference_name = supplier.name
        req.insert(ignore_permissions=True)
        self.factory.track_document("Ponto Payment Request", req.name, priority=6)
        with patch(
            PAY_CLIENT_PATH, return_value=_create_client(f"ponto_pay_{frappe.generate_hash(length=8)}")
        ):
            req.submit()
        self.assertEqual(
            (req.docstatus, req.status), (1, "Pending"), "fixture must be a really submitted row"
        )
        return req

    def _entries_for(self, req):
        return frappe.get_all("Payment Entry", filters={"reference_no": req.name, "docstatus": 1})

    def test_webhook_moves_a_really_submitted_request_pending_signed_executed(self):
        req = self._make_really_submitted_request(self._create_supplier("Hook"))

        req.update_status_from_webhook("Signed")
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Signed")

        req.update_status_from_webhook("Executed")
        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Executed")
        self.assertTrue(row.payment_entry, "the Payment Entry must be written back on the submitted row")
        self.assertEqual([e.name for e in self._entries_for(req)], [row.payment_entry], "exactly one PE")

    def test_refresh_status_moves_a_really_submitted_request_pending_signed_executed(self):
        req = self._make_really_submitted_request(self._create_supplier("Poll"))

        with patch(PAY_CLIENT_PATH, return_value=_read_client("signed")):
            self.assertEqual(req.refresh_status()["status"], "Signed")
        with patch(PAY_CLIENT_PATH, return_value=_read_client("executed")):
            self.assertEqual(req.refresh_status()["status"], "Executed")

        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Executed")
        self.assertEqual([e.name for e in self._entries_for(req)], [row.payment_entry], "exactly one PE")

    def test_fields_that_are_not_allowed_on_submit_stay_refused(self):
        """Control: the change is not 'everything is editable after submit'."""
        req = self._make_really_submitted_request(self._create_supplier("Ctl"))
        req.amount = 1.0
        with self.assertRaises(frappe.UpdateAfterSubmitError) as ctx:
            req.save()
        self.assertIn("Amount", str(ctx.exception))
        self.assertEqual(flt(frappe.db.get_value("Ponto Payment Request", req.name, "amount")), 42.0)

    def test_cancelling_a_really_submitted_request_still_works(self):
        """Cancel is not an update-after-submit and must keep working.

        Not asserted: ``status == "Cancelled"`` afterwards. ``on_cancel`` sets it in memory
        only, after docstatus 2 was written, so the row keeps "Pending" -- measured on
        develop and unchanged here; filed separately.
        """
        req = self._make_really_submitted_request(self._create_supplier("Cxl"))
        with patch(PAY_CLIENT_PATH, return_value=SimpleNamespace(delete_payment=lambda **kw: None)):
            req.cancel()
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "docstatus"), 2)


class TestSubmittedPontoPaymentLink(EnhancedTestCase):
    """A Link that went through the real submit() lifecycle."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.ponto_account = _ensure_ponto_clearing_account(cls.company)  # commits itself

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )

    def _member_and_invoice(self, amount=30.0):
        member = self.sepa.create_test_member(first_name="Ponto1907")
        if not member.customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
            member.reload()
        invoice = self.sepa.create_test_sales_invoice(
            customer=member.customer,
            grand_total=amount,
            status="Unpaid",
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
            submit=True,
        )
        return member, invoice

    def _make_submitted_link(self, member, invoice=None, amount=30.0):
        link = frappe.new_doc("Ponto Payment Link")
        link.payment_type = "One-Time"
        link.amount = amount
        link.currency = "EUR"
        link.description = "Contributie 2026"
        link.creditor_name = "Vereniging Test"
        link.creditor_iban = "NL91ABNA0417164300"
        link.member = member.name
        if invoice:
            link.sales_invoice = invoice.name
        link.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Link", link.name)
        with patch(
            LINK_CLIENT_PATH, return_value=_create_client(f"ponto_req_{frappe.generate_hash(length=8)}")
        ):
            link.submit()
        self.assertEqual((link.docstatus, link.status), (1, "Pending Authorization"))
        return link

    def _read_link(self, link, *fields):
        return frappe.db.get_value("Ponto Payment Link", link.name, list(fields), as_dict=True)

    def test_webhook_authorizes_with_debtor_then_executes_with_invoice_and_payment_entry(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        debtor = {"name": "Jan Jansen", "iban": "NL02ABNA0123456789", "bank": "ABN AMRO"}

        link.update_status_from_webhook("Authorized", debtor)
        row = self._read_link(link, "status", "debtor_name", "debtor_iban", "debtor_bank")
        self.assertEqual(row.status, "Authorized")
        self.assertEqual((row.debtor_name, row.debtor_iban, row.debtor_bank), tuple(debtor.values()))

        link.update_status_from_webhook("Executed")
        row = self._read_link(link, "status", "sales_invoice", "payment_entry")
        self.assertEqual(row.status, "Executed")
        self.assertEqual(row.sales_invoice, invoice.name)
        self.assertTrue(row.payment_entry, "the Payment Entry must be written back on the submitted row")
        entries = frappe.get_all(
            "Payment Entry", filters={"reference_no": link.ponto_request_id, "docstatus": 1}
        )
        self.assertEqual([e.name for e in entries], [row.payment_entry], "exactly one PE")

    def test_refresh_status_writes_debtor_details_on_a_make_submitted_link(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        state = dict(debtor_name="Jan Jansen", debtor_iban="NL02ABNA0123456789", debtor_bank="ABN AMRO")

        with patch(LINK_CLIENT_PATH, return_value=_read_client("signed", **state)):
            self.assertEqual(link.refresh_status()["status"], "Authorized")

        row = self._read_link(link, "status", "debtor_name", "debtor_iban", "debtor_bank")
        self.assertEqual(
            (row.status, row.debtor_name, row.debtor_iban, row.debtor_bank),
            ("Authorized", *state.values()),
        )

    def test_refresh_status_executes_and_links_the_payment_entry(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)

        with patch(LINK_CLIENT_PATH, return_value=_read_client("executed")):
            self.assertEqual(link.refresh_status()["status"], "Executed")

        row = self._read_link(link, "status", "payment_entry")
        self.assertEqual(row.status, "Executed")
        self.assertTrue(row.payment_entry)

    def test_executed_job_matches_the_invoice_and_writes_both_links(self):
        """The webhook's async path: the invoice matcher writes ``sales_invoice`` AFTER submit."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import _process_executed_payment

        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member)  # no sales_invoice yet
        link.update_status_from_webhook("Executed")

        result = _process_executed_payment(frappe.get_doc("Ponto Payment Link", link.name))

        row = self._read_link(link, "sales_invoice", "payment_entry")
        self.assertEqual(result["sales_invoice"], invoice.name)
        self.assertEqual(row.sales_invoice, invoice.name)
        self.assertTrue(row.payment_entry)

    def test_fields_that_are_not_allowed_on_submit_stay_refused(self):
        """Control: amount is not marked, and neither is the creditor."""
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        link.amount = 1.0
        with self.assertRaises(frappe.UpdateAfterSubmitError) as ctx:
            link.save()
        self.assertIn("Amount", str(ctx.exception))
        self.assertEqual(flt(self._read_link(link, "amount").amount), 30.0)
