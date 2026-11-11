# Copyright (c) 2026, Verenigingen
# License: MIT

"""
BankTransfer, Ponto and SEPA refuse a Sales Invoice reference (#2238).

These gateways were written for a Donation (``amount``, ``donor``, ``payment_id``,
``sepa_mandate``). A Sales Invoice has none of those, so a guest-reachable
``initiate_payment`` call for a member invoice failed by accident and mid-way: Ponto forwarded
an internal ``AttributeError`` text to the caller. Maintainer ruling (2026-11-10): refuse
BEFORE any side effect, with the #2225 wording, until #2244 is settled.

Driven through the real ``PaymentHook.initiate_payment`` with a real submitted Sales Invoice.
Only method AVAILABILITY (settings reads) and Ponto's HTTP client are stubbed.

Probe shortcut (stated): the invoice's ``contact_email`` is set with ``db_set`` after submit,
as the Mollie gate tests do, so the guest endpoint's ownership check can resolve it.

SEPA caveat: through the hook SEPA is currently refused with "IBAN is required" for EVERY
reference because the hook sends ``iban`` while the gateway reads ``donor_iban`` (#2423, not
fixed here). So the SEPA Donation control calls the gateway directly with ``donor_iban``.
"""

import types
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

GATE_MESSAGE = "Paying an invoice through this page is not available yet."
IBAN = "NL39RABO0300065264"
_HOOK = "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook"
_PONTO_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)


class _FakePontoClient:
    def __init__(self):
        self.calls = 0

    def create_payment_request(self, **kwargs):
        self.calls += 1
        return types.SimpleNamespace(id="pi_2238", redirect_link="https://bank.test/authorize/pi_2238")


class TestGatewaysRefuseSalesInvoice(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._user = frappe.session.user
        self.settings = types.SimpleNamespace(
            company_account_holder="Test Org", company_iban=IBAN, company_bic="RABONL2U"
        )
        for name in ("_get_ponto_config", "_get_sepa_config", "_get_bank_transfer_config"):
            p = patch(f"{_HOOK}.{name}", return_value={"available": True})
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(pg, "get_payments_settings", return_value=self.settings)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        frappe.set_user(self._user)
        super().tearDown()

    def _invoice(self):
        member = self.create_test_member(first_name="Gate", last_name=f"Inv{frappe.generate_hash()[:6]}")
        invoice = self.create_test_sales_invoice(customer=member.name, grand_total=100.0)
        email = f"gate-owner-{frappe.generate_hash()[:8]}@example.com"
        invoice.db_set("contact_email", email)
        invoice.reload()
        self.assertEqual(invoice.docstatus, 1)
        return invoice, email

    def _donation(self):
        donor = self.create_test_donor(donor_name="Gate Control Donor")
        return self.create_test_donation(
            amount=18.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )

    def _counts(self):
        return {
            "mandates": frappe.db.count("SEPA Mandate"),
            "ponto": frappe.db.count("Ponto Payment Link"),
            "errors": frappe.db.count("Error Log"),
        }

    def _pay(self, method, doctype, name, email="x@example.com"):
        return PaymentHook.initiate_payment(
            method=method,
            amount=10.0,
            reference_doctype=doctype,
            reference_name=name,
            payer_info={"email": email, "name": "Payer", "iban": IBAN},
        )

    def _assert_refused_cleanly(self, method):
        invoice, email = self._invoice()
        before = self._counts()
        client = _FakePontoClient()
        with patch.object(
            frappe.model.document.Document, "db_set", side_effect=AssertionError("db_set attempted")
        ), patch(_PONTO_CLIENT, return_value=client):
            result = self._pay(method, "Sales Invoice", invoice.name, email)
        self.assertFalse(result["success"], result)
        self.assertEqual(result["message"], GATE_MESSAGE, result)
        self.assertNotIn("AttributeError", str(result))
        self.assertNotIn("SalesInvoice", str(result))
        self.assertEqual(self._counts(), before, "refusal must not create rows or log errors")
        self.assertEqual(client.calls, 0)

    def test_bank_transfer_refuses_sales_invoice(self):
        self._assert_refused_cleanly("bank_transfer")

    def test_ponto_refuses_sales_invoice_without_leaking_internal_error(self):
        self._assert_refused_cleanly("ponto")

    def test_sepa_refuses_sales_invoice(self):
        self._assert_refused_cleanly("sepa")

    def test_sepa_gateway_refuses_sales_invoice_even_with_a_valid_iban(self):
        """Direct call with the key the gateway reads (the hook never sends it, #2423): the
        refusal comes before IBAN handling and before any mandate."""
        invoice, _email = self._invoice()
        before = self._counts()
        result = pg.SEPAGateway().process_payment(invoice, {"donor_iban": IBAN, "donor_name": "X"})
        self.assertEqual(result, {"status": "error", "message": GATE_MESSAGE})
        self.assertEqual(self._counts(), before)

    def test_guest_endpoint_surfaces_the_refusal(self):
        from verenigingen.verenigingen_payments.hooks.api import initiate_payment

        invoice, email = self._invoice()
        result = initiate_payment(
            method="ponto",
            amount=1.0,
            reference_doctype="Sales Invoice",
            reference_name=invoice.name,
            payer_email=email,
            payer_name="Payer",
        )
        self.assertFalse(result["success"], result)
        self.assertEqual(result["message"], GATE_MESSAGE)

    # --- controls: a Donation still works through each gateway -----------------------------

    def test_control_bank_transfer_still_serves_a_donation(self):
        donation = self._donation()
        result = self._pay("bank_transfer", "Donation", donation.name)
        self.assertTrue(result["success"], result)
        self.assertTrue(frappe.db.get_value("Donation", donation.name, "payment_id"))

    def test_control_ponto_still_serves_a_donation(self):
        donation = self._donation()
        client = _FakePontoClient()
        with patch(_PONTO_CLIENT, return_value=client):
            result = self._pay("ponto", "Donation", donation.name)
        self.assertTrue(result["success"], result)
        self.assertEqual(client.calls, 1)
        link = frappe.db.get_value("Donation", donation.name, "payment_id")
        self.track_doc("Ponto Payment Link", link)
        self.assertEqual(frappe.db.get_value("Ponto Payment Link", link, "reference_name"), donation.name)

    def test_control_sepa_still_creates_a_mandate_for_a_donation(self):
        donation = self._donation()
        result = pg.SEPAGateway().process_payment(donation, {"donor_iban": IBAN, "donor_name": "X"})
        self.assertEqual(result["status"], "mandate_created", result)
