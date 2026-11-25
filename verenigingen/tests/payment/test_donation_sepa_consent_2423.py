"""SEPA mandate consent on the donation path (#2423, ruling (a) of 2026-11-25).

Driven through the real ``PaymentHook.initiate_payment`` and the real ``SEPAGateway`` with a
real Donor/Donation and a real non-staff session user. Stand-in, stated: only
``PaymentHook._get_sepa_config`` is replaced (availability depends on site payment settings
this test does not own); everything after it is real.
"""

from unittest.mock import patch

import frappe

from verenigingen.services.payment import sepa_mandate_consent as consent_module
from verenigingen.services.payment.sepa_mandate_consent import consent_refusal, hash_consent_text
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.validation.iban_validator import generate_test_iban
from verenigingen.verenigingen_payments.hooks import PaymentHook
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


class TestDonationSepaConsent2423(PortalSelfServiceTestMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(birth_date="1990-01-01")
        self.user = self._link_member_to_user(self.member)
        patcher = patch.object(PaymentHook, "_get_sepa_config", return_value={"available": True})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.iban = generate_test_iban("TEST")
        self.holder = f"Consent Donor {frappe.generate_hash(length=6)}"
        donor = self.create_test_donor(donor_name=self.holder)
        self.donation = self.create_test_donation(
            donor=donor.name, amount=15.0, mode_of_payment="SEPA Direct Debit", paid=0
        )

    def _initiate_2423(self, user=None, **payer_extra):
        payer_info = {"email": "donor2423@example.com", "name": self.holder, "iban": self.iban}
        payer_info.update(payer_extra)
        with self._as_user(user or self.user.name):
            return PaymentHook.initiate_payment(
                method=PaymentHook.SEPA,
                amount=15.0,
                reference_doctype="Donation",
                reference_name=self.donation.name,
                payer_info=payer_info,
            )

    def _consent_2423(self):
        return {
            "sepa_consent": True,
            "sepa_consent_text_hash": hash_consent_text(consent_module.get_mandate_consent_text()),
        }

    def _mandates_2423(self):
        return frappe.get_all("SEPA Mandate", filters={"account_holder_name": self.holder}, pluck="name")

    def test_consent_through_the_hook_creates_a_mandate_with_the_consent_record(self):
        result = self._initiate_2423(**self._consent_2423())
        self.assertTrue(result["success"], result)
        mandates = self._mandates_2423()
        self.assertEqual(len(mandates), 1)
        row = frappe.db.get_value(
            "SEPA Mandate", mandates[0], ["consent_source", "consent_text", "iban"], as_dict=True
        )
        self.assertEqual(row.consent_source, "Member consent")
        self.assertEqual(row.consent_text, consent_module.get_mandate_consent_text())
        self.assertEqual(row.iban.replace(" ", ""), self.iban.replace(" ", ""))
        self.assertEqual(frappe.db.get_value("Donation", self.donation.name, "sepa_mandate"), mandates[0])

    def test_no_consent_is_refused_and_creates_nothing(self):
        result = self._initiate_2423()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], consent_refusal()["error"])
        self.assertEqual(self._mandates_2423(), [])

    def test_a_false_or_zero_consent_is_refused(self):
        for value in (False, 0, "0", "false", "", None):
            with self.subTest(consent=value):
                result = self._initiate_2423(
                    sepa_consent=value, sepa_consent_text_hash=self._consent_2423()["sepa_consent_text_hash"]
                )
                self.assertFalse(result["success"])
        self.assertEqual(self._mandates_2423(), [])

    def test_consent_to_a_stale_text_is_refused(self):
        result = self._initiate_2423(sepa_consent=True, sepa_consent_text_hash=hash_consent_text("old text"))
        self.assertFalse(result["success"])
        self.assertEqual(self._mandates_2423(), [])

    def test_the_gateway_itself_refuses_without_consent(self):
        """Server-side, not only the hook: a direct gateway call with a valid IBAN and no consent."""
        with self._as_user(self.user.name):
            result = pg.SEPAGateway().process_payment(
                self.donation, frappe._dict({"donor_iban": self.iban, "donor_name": self.holder})
            )
        self.assertEqual(result.get("status"), "error")
        self.assertEqual(result.get("message"), consent_refusal()["error"])
        self.assertEqual(self._mandates_2423(), [])

    def test_a_guest_donor_with_consent_gets_a_mandate(self):
        result = self._initiate_2423(user="Guest", **self._consent_2423())
        self.assertTrue(result["success"], result)
        self.assertEqual(len(self._mandates_2423()), 1)

    def test_the_donation_service_forwards_the_form_consent(self):
        from verenigingen.services.donation.public_donation_service import get_public_donation_service

        # Shortcut, stated: the fixture force-submits (docstatus=1 via set_value); the public form
        # saves a donation it has just created as a draft, so put it back to that state.
        frappe.db.set_value("Donation", self.donation.name, "docstatus", 0)
        self.donation.reload()
        form_data = frappe._dict(
            {
                "payment_method": "SEPA Direct Debit",
                "donor_email": "donor2423@example.com",
                "donor_name": self.holder,
                "donor_iban": self.iban,
                **self._consent_2423(),
            }
        )
        with self._as_user(self.user.name):
            result = get_public_donation_service().process_payment_method(self.donation, form_data)
        self.assertEqual(result.get("status"), "mandate_required", result)
        self.assertEqual(len(self._mandates_2423()), 1)
        refused = frappe._dict({**form_data, "sepa_consent": False})
        with self._as_user(self.user.name):
            result = get_public_donation_service().process_payment_method(self.donation, refused)
        self.assertEqual(result.get("status"), "error", result)
        self.assertEqual(len(self._mandates_2423()), 1)

    def test_the_donate_page_context_carries_the_mandate_text_and_its_hash(self):
        from verenigingen.templates.pages import donate

        context = frappe._dict()
        donate.get_context(context)
        text = consent_module.get_mandate_consent_text()
        self.assertEqual(context.mandate_consent_text, text)
        self.assertEqual(context.mandate_consent_text_hash, hash_consent_text(text))
