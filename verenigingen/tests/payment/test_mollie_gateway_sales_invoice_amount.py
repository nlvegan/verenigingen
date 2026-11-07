# Copyright (c) 2026, Verenigingen
# License: MIT

"""
A Sales Invoice paid through guest ``mollie_checkout.make_payment`` charges its
``outstanding_amount`` (#2225).

``MollieGateway.process_payment`` built the Mollie amount from ``doc.amount``, which a Sales
Invoice lacks, so every invoice payment ended in the generic "Could not create payment" error.
Maintainer ruling (2026-11-07): charge ``outstanding_amount``; REFUSE when it is 0 (settled).
Never ``grand_total`` of a partly paid invoice, never the client-sent amount.

Only Mollie's HTTP client is stubbed (``MollieSettings.get_mollie_client``); the request goes
through the real ``make_payment`` -> ``load_owned_reference`` -> ``MollieGateway`` chain, and the
assertions read the amount that actually reached ``client.payments.create``.

Caller identity (stated): the amount tests run as Administrator, NOT Guest. As a Guest,
``MollieGateway.__init__`` is refused before ``process_payment`` is reached, because
``get_mollie_settings`` is ``@high_security_api`` (measured on test_site_fresh; filed as its own
issue). That is a separate blocker; these tests prove the amount ``process_payment`` sends once the
gateway exists. The existence-oracle test below does run as Guest: it refuses at ownership.

Probe shortcut (stated, per the dispatch brief): ``contact_email``, ``currency`` (EUR) and ``outstanding_amount`` are
set directly with ``db_set`` after submit (the factory does this; a real partly paid invoice would
come from a Payment Entry). Tests of the amount therefore prove the gateway's reading of the
field, not that a Payment Entry produces it.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_GET_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
    "MollieSettings.get_mollie_client"
)
_GET_WEBHOOK_URL = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
    "MollieSettings.get_webhook_url"
)


def _fake_mollie_client():
    client = MagicMock()
    client.payments.create.return_value = SimpleNamespace(
        id="tr_fake2225",
        status="open",
        expires_at=datetime.now() + timedelta(days=1),
        checkout_url="https://pay.mollie.test/checkout/2225",
    )
    return client


class TestMollieGatewaySalesInvoiceAmount(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_user = frappe.session.user

    def tearDown(self):
        frappe.set_user(self._original_user)
        super().tearDown()

    def _mollie_invoice(self, *, grand_total=100.0, outstanding_amount=None, draft=False):
        member = self.create_test_member(first_name="Mollie", last_name=f"Inv{frappe.generate_hash()[:6]}")
        kwargs = {"grand_total": grand_total}
        if outstanding_amount is not None:
            kwargs["outstanding_amount"] = outstanding_amount
        if draft:
            kwargs["status"] = "Draft"
        invoice = self.create_test_sales_invoice(customer=member.name, **kwargs)
        email = f"inv-owner-{frappe.generate_hash()[:8]}@example.com"
        invoice.db_set("contact_email", email)
        # The harness company's currency is site-dependent (INR on some test sites) and Mollie
        # refuses INR; this association bills in EUR. Pinned directly, like contact_email.
        invoice.db_set("currency", "EUR")
        invoice.reload()
        return invoice, email

    def _pay_via_checkout(self, name, email, *, client_amount=1.23, doctype="Sales Invoice", user="Administrator"):
        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        data = json.dumps(
            {
                "amount": client_amount,
                "title": "Invoice",
                "description": "Invoice",
                "payer_name": "Someone",
                "payer_email": email,
                "order_id": "ORD-2225",
                "currency": "EUR",
            }
        )
        client = _fake_mollie_client()
        # Webhook URL construction needs a configured API key, which CI's sites lack; it is
        # URL building, not Mollie's HTTP boundary, so it is stubbed alongside the client.
        with (
            self.as_user(user),
            patch(_GET_CLIENT, return_value=client),
            patch(_GET_WEBHOOK_URL, return_value="https://example.test/webhook"),
        ):
            result = make_payment(
                data=data, reference_doctype=doctype, reference_docname=name, gateway_name="Default"
            )
        return result, client

    def _sent_amount(self, client):
        client.payments.create.assert_called_once()
        return client.payments.create.call_args.args[0]["amount"]

    def test_partly_paid_invoice_charges_outstanding_not_grand_total_or_client_amount(self):
        invoice, email = self._mollie_invoice(grand_total=100.0, outstanding_amount=40.0)
        outstanding = flt(invoice.outstanding_amount)
        self.assertNotEqual(outstanding, flt(invoice.grand_total), "fixture must be partly paid")

        result, client = self._pay_via_checkout(invoice.name, email, client_amount=1.23)

        self.assertEqual(result["status"], "Open", result)
        sent = self._sent_amount(client)
        self.assertEqual(sent["value"], f"{outstanding:.2f}")
        self.assertEqual(sent["currency"], invoice.currency)
        metadata = client.payments.create.call_args.args[0]["metadata"]
        self.assertEqual(metadata["reference_doctype"], "Sales Invoice")
        self.assertEqual(metadata["reference_docname"], invoice.name)

    def test_unpaid_invoice_charges_its_outstanding(self):
        invoice, email = self._mollie_invoice(grand_total=75.0)
        result, client = self._pay_via_checkout(invoice.name, email)
        self.assertEqual(result["status"], "Open", result)
        self.assertEqual(self._sent_amount(client)["value"], f"{flt(invoice.outstanding_amount):.2f}")

    def _assert_refused_without_charge(self, invoice, email):
        result, client = self._pay_via_checkout(invoice.name, email)
        self.assertEqual(result["status"], "Error", result)
        self.assertEqual(result["message"], "There is nothing left to pay on this document.")
        self.assertIsNone(result["paymentUrl"])
        client.payments.create.assert_not_called()

    def test_settled_invoice_is_refused_with_no_mollie_call(self):
        invoice, email = self._mollie_invoice(grand_total=100.0, outstanding_amount=0.0)
        self.assertEqual(flt(invoice.outstanding_amount), 0.0)
        self.assertEqual(invoice.docstatus, 1)
        self._assert_refused_without_charge(invoice, email)

    def test_overcredited_invoice_is_refused_with_no_mollie_call(self):
        invoice, email = self._mollie_invoice(grand_total=100.0, outstanding_amount=-20.0)
        self._assert_refused_without_charge(invoice, email)

    def test_draft_invoice_is_refused_with_no_mollie_call(self):
        """A draft's outstanding mirrors grand_total (#209/#856), so docstatus must gate it."""
        invoice, email = self._mollie_invoice(grand_total=100.0, draft=True)
        self.assertEqual(invoice.docstatus, 0)
        self.assertGreater(flt(invoice.outstanding_amount), 0)
        self._assert_refused_without_charge(invoice, email)

    def test_donation_still_charges_its_amount(self):
        """Control: the Donation path is unchanged."""
        email = f"donor-{frappe.generate_hash()[:8]}@example.com"
        donor = self.create_test_donor(donor_email=email)
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": today(),
                "amount": 20.0,
                "mode_of_payment": "Mollie",
                "status": "One-time",
                "donation_purpose_type": "General",
                "paid": 0,
            }
        ).insert()
        result, client = self._pay_via_checkout(donation.name, email, client_amount=1.23, doctype="Donation")
        self.assertEqual(result["status"], "Open", result)
        self.assertEqual(self._sent_amount(client)["value"], f"{flt(donation.amount):.2f}")

    def test_settled_invoice_refusal_to_a_stranger_matches_an_unknown_invoice(self):
        """Existence oracle: ownership is decided BEFORE the amount, so a stranger who names a
        real settled invoice sees exactly what they see for a name that does not exist."""
        self.expectErrorLog("Mollie Payment Error")  # the ownership refusal, both probes
        invoice, _owner = self._mollie_invoice(grand_total=100.0, outstanding_amount=0.0)
        stranger = f"stranger-{frappe.generate_hash()[:8]}@example.com"

        def probe(name):
            before_log = len(frappe.local.message_log)
            result, client = self._pay_via_checkout(name, stranger, user="Guest")
            client.payments.create.assert_not_called()
            return result, list(frappe.local.message_log[before_log:])

        known = probe(invoice.name)
        unknown = probe("ACC-SINV-DOES-NOT-EXIST-2225")
        self.assertEqual(known, unknown)
