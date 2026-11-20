# Copyright (c) 2026, Verenigingen
# License: MIT

"""
A Sales Invoice is NOT payable through Mollie yet (#2225, #2244).

#2225 taught ``MollieGateway`` to charge a Sales Invoice's ``outstanding_amount`` (maintainer
ruling 2026-11-07). Review then showed that a live payment for an invoice cannot be linked back
(no ``payment_id``: a repeat call creates a second payment; the webhook resolver cannot map the
payment to the invoice: the money is never booked), so the maintainer ruled (2026-11-08) that
``process_payment`` REFUSES every Sales Invoice, before any Mollie call, until #2244 is fixed.

* The gate is tested end to end through ``make_payment`` and directly on ``process_payment``
  (the gate lives in the gateway so it covers every caller).
* ``_amount_to_charge`` stays as the reviewed logic for when the gate is lifted; it is exercised
  directly here (partly paid -> outstanding, never grand_total; settled/over-credited/draft ->
  refuse). It takes only the document, so a client-sent amount cannot reach it.

Only Mollie's HTTP client (``MollieSettings.get_mollie_client``) is stubbed. Amount tests run no
gateway at all. The end-to-end tests run as Administrator because a Guest cannot construct
``MollieGateway`` (#2237); the existence-oracle test runs as Guest and refuses at ownership.

Probe shortcut (stated): ``contact_email`` and ``outstanding_amount`` are set with ``db_set``
after submit (the factory does the latter), so the amount tests prove the logic's reading of the
field, not that a Payment Entry produces it. ``currency`` is pinned to EUR the same way (see
``_mollie_invoice``). An EUR company fixture was not used: building one is a shared-fixture
build the harness guards against.
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


GATE_MESSAGE = "Paying an invoice through this page is not available yet."


def _fake_mollie_client():
    client = MagicMock()
    client.payments.create.return_value = SimpleNamespace(
        id="tr_fake2225",
        status="open",
        expires_at=datetime.now() + timedelta(days=1),
        checkout_url="https://pay.mollie.test/checkout/2225",
    )
    return client


class TestMollieGatewaySalesInvoiceGate(EnhancedTestCase):
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
        # refuses INR. Pinned to EUR so that WITHOUT the gate this invoice WOULD reach
        # payments.create; with INR a missing gate would be hidden by the currency refusal.
        invoice.db_set("currency", "EUR")
        invoice.reload()
        return invoice, email

    def _mollie_stubs(self, client):
        # Webhook URL construction needs a configured API key, which CI's sites lack; it is
        # URL building, not Mollie's HTTP boundary, so it is stubbed alongside the client.
        return (
            patch(_GET_CLIENT, return_value=client),
            patch(_GET_WEBHOOK_URL, return_value="https://example.test/webhook"),
        )

    def _pay_via_checkout(self, name, email, *, doctype="Sales Invoice", user="Administrator"):
        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        data = json.dumps(
            {
                "amount": 1.23,
                "title": "Invoice",
                "description": "Invoice",
                "payer_name": "Someone",
                "payer_email": email,
                "order_id": "ORD-2225",
                "currency": "EUR",
            }
        )
        client = _fake_mollie_client()
        stub_client, stub_url = self._mollie_stubs(client)
        with self.as_user(user), stub_client, stub_url:
            result = make_payment(
                data=data, reference_doctype=doctype, reference_docname=name, gateway_name="Default"
            )
        return result, client

    def _mollie_error_logs(self):
        return frappe.db.count("Error Log", {"method": ["like", "Mollie Payment%"]})

    # --- the gate -------------------------------------------------------------------------

    def test_owned_invoice_through_make_payment_is_refused_before_mollie(self):
        invoice, email = self._mollie_invoice(grand_total=100.0, outstanding_amount=40.0)
        logs_before = self._mollie_error_logs()

        result, client = self._pay_via_checkout(invoice.name, email)

        client.payments.create.assert_not_called()
        self.assertEqual(result["status"], "Error", result)
        self.assertEqual(result["message"], GATE_MESSAGE)
        self.assertIsNone(result["paymentUrl"])
        self.assertEqual(self._mollie_error_logs(), logs_before, "the gate is not an error")

    def test_process_payment_refuses_an_invoice_for_a_direct_caller(self):
        """The gate lives in the gateway, not in make_payment: PaymentHook and
        process_donation_payment call process_payment directly."""
        from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

        invoice, _email = self._mollie_invoice(grand_total=100.0, outstanding_amount=40.0)
        client = _fake_mollie_client()
        stub_client, stub_url = self._mollie_stubs(client)
        with self.as_user("Administrator"), stub_client, stub_url:
            result = MollieGateway("Default").process_payment(invoice, {})

        client.payments.create.assert_not_called()
        self.assertEqual(result, {"status": "error", "message": GATE_MESSAGE})

    def test_donation_still_reaches_mollie(self):
        """Control: the gate is keyed on Sales Invoice only."""
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
        result, client = self._pay_via_checkout(donation.name, email, doctype="Donation")
        self.assertEqual(result["status"], "Open", result)
        client.payments.create.assert_called_once()
        self.assertEqual(
            client.payments.create.call_args.args[0]["amount"]["value"], f"{flt(donation.amount):.2f}"
        )

    def test_gate_message_is_only_reachable_after_ownership_passes(self):
        """Existence oracle: a stranger naming a real invoice gets exactly what an unknown name
        gets (the ownership refusal), never the gate message; only the owner sees the gate."""
        self.expectErrorLog("Mollie Payment Error")  # the ownership refusal, both probes
        invoice, owner_email = self._mollie_invoice(grand_total=100.0, outstanding_amount=40.0)
        stranger = f"stranger-{frappe.generate_hash()[:8]}@example.com"

        def probe(name, email, user):
            before_log = len(frappe.local.message_log)
            result, client = self._pay_via_checkout(name, email, user=user)
            client.payments.create.assert_not_called()
            return result, list(frappe.local.message_log[before_log:])

        known = probe(invoice.name, stranger, "Guest")
        unknown = probe("ACC-SINV-DOES-NOT-EXIST-2225", stranger, "Guest")
        self.assertEqual(known, unknown)
        self.assertNotEqual(known[0]["message"], GATE_MESSAGE)
        owner = probe(invoice.name, owner_email, "Administrator")
        self.assertEqual(owner[0]["message"], GATE_MESSAGE)

    # --- _amount_to_charge: the logic kept for when #2244 lifts the gate ---------------------

    def test_amount_to_charge_partly_paid_is_outstanding_not_grand_total(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

        invoice, _email = self._mollie_invoice(grand_total=100.0, outstanding_amount=40.0)
        self.assertNotEqual(flt(invoice.outstanding_amount), flt(invoice.grand_total))
        self.assertEqual(MollieGateway._amount_to_charge(invoice), flt(invoice.outstanding_amount))

    def test_amount_to_charge_refuses_settled_overcredited_and_draft(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

        settled, _e = self._mollie_invoice(grand_total=100.0, outstanding_amount=0.0)
        over, _e = self._mollie_invoice(grand_total=100.0, outstanding_amount=-20.0)
        draft, _e = self._mollie_invoice(grand_total=100.0, draft=True)
        self.assertEqual(settled.docstatus, 1)
        self.assertEqual(draft.docstatus, 0)
        self.assertGreater(flt(draft.outstanding_amount), 0, "a draft's outstanding mirrors grand_total")
        for invoice in (settled, over, draft):
            self.assertIsNone(MollieGateway._amount_to_charge(invoice), invoice.name)

    def test_amount_to_charge_leaves_a_donation_amount_alone(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

        self.assertEqual(MollieGateway._amount_to_charge(SimpleNamespace(doctype="Donation", amount=20.0)), 20.0)
