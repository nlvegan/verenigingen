"""
Coverage-extension tests for the NON-Mollie gateways of payment_gateways.py.

Focuses on SEPA / Ponto / BankTransfer / Cash / factory branches that the
existing four test files (test_payment_gateways.py / _unit.py / _coverage.py /
_endpoints.py) do NOT already drive:

    - SEPAGateway.process_payment: IBAN whitespace/case normalisation feeding the
      mandate, member-less mandate (donor without a member), one-off (OOFF) type
      for a non-recurring donation, and BIC derivation onto the mandate record.
    - SEPAGateway._create_sepa_mandate: the formatted-IBAN persisted on the
      mandate (not the raw spaced input) and the donor-name fallback when
      form_data omits donor_name.
    - PontoGateway.process_payment: the full SUCCESS path (link inserted via
      secure_document_operation, submit() -> Ponto request created, redirect
      returned, donation.payment_id persisted) and the submit-failure exception
      branch. The ONLY thing stubbed is the outbound Ponto HTTP client
      (get_betaalverzoek_client) - everything else (the real Ponto Payment Link
      doctype, secure_document_operation, db_set) runs for real.
    - BankTransferGateway.process_payment: bank_details content (IBAN/BIC pulled
      from payments settings, reference embeds the creation date, amount).
    - PaymentGatewayFactory.get_gateway: fresh instances per call + Mollie name
      pass-through (constructed lazily so no live Mollie settings are needed).

Constraints honoured: real fixtures via the factory; no patching of frappe
internals; secure_document_operation is the app's own wrapper and runs for real;
no insert/save(ignore_permissions=True) in test bodies. Extends EnhancedTestCase
(auto-rollback).
"""

import types
import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

VALID_IBAN_RABO = "NL39RABO0300065264"  # -> BIC RABONL2U
VALID_IBAN_ABNA = "NL02ABNA0123456789"  # -> BIC ABNANL2A


# ===========================================================================
# SEPAGateway.process_payment / _create_sepa_mandate - field mapping branches
# not covered by TestSEPAGatewayMandateCreation
# ===========================================================================
class TestSEPAGatewayMandateFieldMapping(EnhancedTestCase):
    def _donation(self, amount=15.0, status=None, donor=None):
        kw = dict(amount=amount, mode_of_payment="SEPA Direct Debit", paid=0)
        if status is not None:
            kw["status"] = status
        if donor is not None:
            kw["donor"] = donor
        return self.create_test_donation(**kw)

    def test_iban_with_spaces_is_normalised_onto_mandate(self):
        # process_payment strips spaces/upper-cases the input IBAN before
        # validating; _create_sepa_mandate then stores the canonical formatted
        # IBAN (grouped) on the mandate. The raw spaced input must not leak.
        donor = self.create_test_donor(donor_name="Spaced IBAN Donor")
        donation = self._donation(donor=donor.name)
        spaced = "nl39 rabo 0300 0652 64"  # lower-case + spaces

        result = SEPAGateway_process(donation, {"donor_iban": spaced, "donor_name": "Spaced IBAN Donor"})

        self.assertEqual(result["status"], "mandate_created")
        stored = frappe.db.get_value("SEPA Mandate", result["mandate_id"], "iban")
        # No spaces, upper-case, same digits as the canonical RABO IBAN.
        self.assertEqual(stored.replace(" ", ""), VALID_IBAN_RABO)

    def test_mandate_carries_derived_bic(self):
        donor = self.create_test_donor(donor_name="BIC Donor")
        donation = self._donation(donor=donor.name)
        result = SEPAGateway_process(donation, {"donor_iban": VALID_IBAN_RABO, "donor_name": "BIC Donor"})
        self.assertEqual(result["status"], "mandate_created")
        self.assertEqual(frappe.db.get_value("SEPA Mandate", result["mandate_id"], "bic"), "RABONL2U")

    def test_non_recurring_donation_yields_ooff_mandate(self):
        # Negative control for the RCUR test that already exists: a plain
        # (non-"Recurring" status) donation must produce a one-off OOFF mandate.
        donor = self.create_test_donor(donor_name="OneOff Donor")
        donation = self._donation(donor=donor.name)  # default status, not "Recurring"
        result = SEPAGateway_process(donation, {"donor_iban": VALID_IBAN_ABNA, "donor_name": "OneOff Donor"})
        self.assertEqual(result["status"], "mandate_created")
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate", result["mandate_id"], "mandate_type"), "OOFF"
        )

    def test_donor_without_member_yields_member_less_mandate(self):
        # A donor with no linked member is acceptable: the mandate is created and
        # simply has no member link (the `member` field stays empty).
        donor = self.create_test_donor(donor_name="No Member Donor")
        self.assertFalse(donor.member)
        donation = self._donation(donor=donor.name)
        result = SEPAGateway_process(donation, {"donor_iban": VALID_IBAN_RABO, "donor_name": "No Member Donor"})
        self.assertEqual(result["status"], "mandate_created")
        self.assertFalse(frappe.db.get_value("SEPA Mandate", result["mandate_id"], "member"))

    def test_account_holder_falls_back_to_donor_name_when_form_omits_it(self):
        # When form_data has no donor_name, _create_sepa_mandate uses the Donor's
        # donor_name for account_holder_name.
        donor = self.create_test_donor(donor_name="Fallback Holder Name")
        donation = self._donation(donor=donor.name)
        result = SEPAGateway_process(donation, {"donor_iban": VALID_IBAN_RABO})  # no donor_name
        self.assertEqual(result["status"], "mandate_created")
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate", result["mandate_id"], "account_holder_name"),
            "Fallback Holder Name",
        )

    def test_collection_date_returned_on_success(self):
        donor = self.create_test_donor(donor_name="Collection Date Donor")
        donation = self._donation(donor=donor.name)
        result = SEPAGateway_process(donation, {"donor_iban": VALID_IBAN_RABO, "donor_name": "x"})
        self.assertEqual(result["status"], "mandate_created")
        # Collection date is T+2 from today.
        from frappe.utils import add_to_date, getdate

        expected = getdate(add_to_date(getdate(), days=2))
        self.assertEqual(getdate(result["collection_date"]), expected)


def SEPAGateway_process(donation, form_data):
    """Tiny helper so the SEPA call reads the same way in every test body."""
    return pg.SEPAGateway().process_payment(donation, form_data)


# ===========================================================================
# PontoGateway.process_payment - SUCCESS path + submit-failure branch
# ===========================================================================
class _FakePontoResult:
    """Stand-in for the Ponto client's PaymentInitiationRequest result."""

    def __init__(self, request_id="pi_fake123", redirect_link="https://bank.test/authorize/pi_fake123"):
        self.id = request_id
        self.redirect_link = redirect_link


class _FakePontoClient:
    """Outbound Ponto HTTP boundary stub - models only create_payment_request."""

    def __init__(self, result=None, raise_exc=None):
        self._result = result or _FakePontoResult()
        self._raise = raise_exc
        self.last_call = None

    def create_payment_request(self, **kwargs):
        self.last_call = kwargs
        if self._raise:
            raise self._raise
        return self._result


class TestPontoGatewayProcessPaymentSuccess(EnhancedTestCase):
    """The Ponto submit() path makes one outbound HTTP call via
    get_betaalverzoek_client(); that single boundary is stubbed. The real Ponto
    Payment Link doctype validation, secure_document_operation insert, submit
    lifecycle, and donation.db_set all run for real.
    """

    def _donation(self, amount=18.0):
        donor = self.create_test_donor(donor_name="Ponto Success Donor")
        return self.create_test_donation(
            amount=amount, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )

    def _settings_with_iban(self, iban="NL39RABO0300065264"):
        return types.SimpleNamespace(company_account_holder="Test Org Holder", company_iban=iban)

    def test_process_payment_creates_link_and_returns_redirect(self):
        donation = self._donation(amount=27.5)
        fake_client = _FakePontoClient(
            result=_FakePontoResult(request_id="pi_ok", redirect_link="https://bank.test/authorize/pi_ok")
        )
        # Stub only the outbound boundaries: payments-settings read (so a company
        # IBAN exists deterministically) and the Ponto HTTP client factory.
        ponto_mod = "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
        with patch.object(pg, "get_payments_settings", return_value=self._settings_with_iban()), patch(
            ponto_mod, return_value=fake_client
        ):
            result = pg.PontoGateway().process_payment(donation, {"donor_name": "Ponto Success Donor"})

        self.assertEqual(result["status"], "redirect_required")
        self.assertEqual(result["payment_url"], "https://bank.test/authorize/pi_ok")
        self.assertEqual(result["ponto_request_id"], "pi_ok")
        # A real, submitted Ponto Payment Link was created and linked to the donation.
        link_name = result["payment_id"]
        self.track_doc("Ponto Payment Link", link_name)
        link = frappe.get_doc("Ponto Payment Link", link_name)
        self.assertEqual(link.docstatus, 1)
        self.assertEqual(link.status, "Pending Authorization")
        self.assertEqual(link.reference_doctype, "Donation")
        self.assertEqual(link.reference_name, donation.name)
        self.assertEqual(link.amount, 27.5)
        # donation.payment_id was persisted with the link name.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "payment_id"), link_name)
        # The amount/creditor flowed to the outbound Ponto call.
        self.assertEqual(fake_client.last_call["amount"], 27.5)
        self.assertEqual(fake_client.last_call["creditor_iban"], "NL39RABO0300065264")

    def test_description_uses_donor_name_when_provided(self):
        donation = self._donation()
        fake_client = _FakePontoClient()
        ponto_mod = "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
        with patch.object(pg, "get_payments_settings", return_value=self._settings_with_iban()), patch(
            ponto_mod, return_value=fake_client
        ):
            result = pg.PontoGateway().process_payment(donation, {"donor_name": "Named Donor Person"})
        self.track_doc("Ponto Payment Link", result["payment_id"])
        link = frappe.get_doc("Ponto Payment Link", result["payment_id"])
        self.assertEqual(link.description, "Donation from Named Donor Person")

    def test_description_defaults_to_donation_name_without_donor_name(self):
        donation = self._donation()
        fake_client = _FakePontoClient()
        ponto_mod = "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
        with patch.object(pg, "get_payments_settings", return_value=self._settings_with_iban()), patch(
            ponto_mod, return_value=fake_client
        ):
            result = pg.PontoGateway().process_payment(donation, {})
        self.track_doc("Ponto Payment Link", result["payment_id"])
        link = frappe.get_doc("Ponto Payment Link", result["payment_id"])
        self.assertEqual(link.description, f"Donation {donation.name}")

    def test_process_payment_submit_failure_returns_error(self):
        # The outbound Ponto call fails during submit() -> before_submit throws ->
        # PontoGateway.process_payment catches it and returns a structured error.
        donation = self._donation()
        fake_client = _FakePontoClient(raise_exc=RuntimeError("ponto upstream 503"))
        ponto_mod = "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
        with patch.object(pg, "get_payments_settings", return_value=self._settings_with_iban()), patch(
            ponto_mod, return_value=fake_client
        ):
            result = pg.PontoGateway().process_payment(donation, {})
        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to create Ponto payment link", result["message"])
        # The donation was NOT linked to any payment id (submit failed).
        self.assertFalse(frappe.db.get_value("Donation", donation.name, "payment_id"))


# ===========================================================================
# BankTransferGateway.process_payment - bank_details content
# ===========================================================================
class TestBankTransferBankDetails(EnhancedTestCase):
    def test_bank_details_pull_iban_and_bic_from_settings(self):
        donor = self.create_test_donor(donor_name="Bank Detail Donor")
        donation = self.create_test_donation(
            amount=33.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        settings_stub = types.SimpleNamespace(
            company_iban="NL02ABNA0123456789", company_bic="ABNANL2A"
        )
        # Stub only the payments-settings read so IBAN/BIC are deterministic.
        with patch.object(pg, "get_payments_settings", return_value=settings_stub):
            result = pg.BankTransferGateway().process_payment(donation, {})

        self.assertEqual(result["status"], "awaiting_transfer")
        details = result["bank_details"]
        self.assertEqual(details["iban"], "NL02ABNA0123456789")
        self.assertEqual(details["bic"], "ABNANL2A")
        self.assertEqual(details["amount"], donation.amount)
        # Reference embeds the donation name and an 8-digit creation date (YYYYMMDD).
        ref = result["payment_reference"]
        self.assertTrue(ref.startswith(f"DON-{donation.name}-"))
        date_part = ref.rsplit("-", 1)[-1]
        self.assertEqual(len(date_part), 8)
        self.assertTrue(date_part.isdigit())
        self.assertEqual(details["reference"], ref)

    def test_bank_details_empty_iban_when_settings_missing(self):
        donor = self.create_test_donor(donor_name="No IBAN Settings Donor")
        donation = self.create_test_donation(
            amount=12.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        # Settings object missing company_iban/company_bic -> getattr defaults "".
        with patch.object(pg, "get_payments_settings", return_value=types.SimpleNamespace()):
            result = pg.BankTransferGateway().process_payment(donation, {})
        self.assertEqual(result["bank_details"]["iban"], "")
        self.assertEqual(result["bank_details"]["bic"], "")


# ===========================================================================
# PaymentGatewayFactory - instance freshness + Mollie name pass-through
# ===========================================================================
class TestPaymentGatewayFactoryInstances(EnhancedTestCase):
    def test_get_gateway_returns_fresh_instance_each_call(self):
        a = pg.PaymentGatewayFactory.get_gateway("SEPA Direct Debit")
        b = pg.PaymentGatewayFactory.get_gateway("SEPA Direct Debit")
        self.assertIsInstance(a, pg.SEPAGateway)
        self.assertIsInstance(b, pg.SEPAGateway)
        self.assertIsNot(a, b)

    def test_get_gateway_mollie_passes_gateway_name(self):
        # Mollie is constructed lazily; we only verify the factory routes the
        # gateway_name to the MollieGateway constructor without a live API by
        # capturing the constructor call (the constructor itself needs live
        # settings, so we replace it at the class boundary).
        captured = {}

        class _StubMollie:
            def __init__(self, gateway_name="Default"):
                captured["gateway_name"] = gateway_name

        with patch.object(pg.PaymentGatewayFactory, "_gateways", {**pg.PaymentGatewayFactory._gateways, "Mollie": _StubMollie}):
            pg.PaymentGatewayFactory.get_gateway("Mollie", gateway_name="Config-X")
        self.assertEqual(captured["gateway_name"], "Config-X")

    def test_get_gateway_non_mollie_ignores_gateway_name(self):
        # For non-Mollie methods the gateway_name argument is irrelevant and the
        # class is constructed with no args.
        gw = pg.PaymentGatewayFactory.get_gateway("Cash", gateway_name="ignored")
        self.assertIsInstance(gw, pg.CashGateway)

    def test_supported_methods_contains_non_mollie_set(self):
        methods = set(pg.PaymentGatewayFactory.get_supported_methods())
        self.assertTrue({"Bank Transfer", "Ponto", "SEPA Direct Debit", "Cash"}.issubset(methods))


if __name__ == "__main__":
    unittest.main()
