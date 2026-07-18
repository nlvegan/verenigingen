# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Integration tests for the public donation portal page controller
(``verenigingen/templates/pages/donate.py``).

These tests exercise the real ``get_context`` rendering paths, the
``submit_donation`` whitelisted endpoint (guest + logged-in, several payment
methods), the donor/donation creation helpers, payment-method processing,
status lookup, retry and the small pure helpers. No business logic is mocked -
real Donor/Donation/Member documents are created via the ORM.
"""

import frappe

from verenigingen.services.donation.donor_service import get_donation_donor_service
from verenigingen.services.donation.public_donation_service import (
    get_public_donation_service,
)
from verenigingen.templates.pages import donate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonatePage(VereningingenTestCase):
    """Real integration tests for the donate page controller."""

    def setUp(self):
        super().setUp()
        # Always begin each test as Administrator with a clean form_dict.
        frappe.set_user("Administrator")
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.local.form_dict = frappe._dict()
        super().tearDown()

    def _unique_email(self, prefix="donor"):
        return f"{prefix}.{frappe.generate_hash(length=8)}@example.com"

    # ------------------------------------------------------------------
    # get_context
    # ------------------------------------------------------------------

    def test_get_context_guest_basic(self):
        """get_context renders the donation form for a guest user."""
        frappe.set_user("Guest")
        context = frappe._dict()
        donate.get_context(context)

        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)
        self.assertIn("settings", context)
        self.assertIn("company_name", context.settings)
        # Donor types are hard-coded as Individual + Organization.
        self.assertEqual(len(context.donor_types), 2)
        self.assertIn("payment_methods", context)
        # A guest has no pre-filled user info.
        self.assertEqual(context.user_info, {})

    def test_get_context_logged_in_user_without_donor(self):
        """A logged-in user gets user_info but no existing_donor when not a donor."""
        email = self._unique_email("user")
        user = self.create_test_user(email, roles=["Verenigingen Member"])

        frappe.set_user(user.name)
        context = frappe._dict()
        donate.get_context(context)

        self.assertEqual(context.user_info.get("email"), email)
        self.assertNotIn("existing_donor", context)

    def test_get_context_logged_in_user_with_existing_donor(self):
        """A logged-in user who is already a donor gets existing_donor populated."""
        email = self._unique_email("user")
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        donor = self.create_test_donor(donor_email=email)

        frappe.set_user(user.name)
        context = frappe._dict()
        donate.get_context(context)

        self.assertIn("existing_donor", context)
        self.assertEqual(context.existing_donor["name"], donor.name)
        self.assertEqual(context.existing_donor["donor_email"], email)

    def test_get_context_with_paid_donation_return(self):
        """Returning from a successful payment surfaces the donation result."""
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, paid=1)

        frappe.local.form_dict = frappe._dict({"donation_id": donation.name})
        context = frappe._dict()
        donate.get_context(context)

        self.assertEqual(context.payment_status, "success")
        self.assertEqual(context.donation_result.name, donation.name)

    def test_get_context_with_pending_donation_no_payment_id(self):
        """Unpaid donation without a payment_id is reported as pending."""
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, paid=0)

        frappe.local.form_dict = frappe._dict({"donation_id": donation.name})
        context = frappe._dict()
        donate.get_context(context)

        self.assertEqual(context.payment_status, "pending")

    def test_get_context_with_nonexistent_donation(self):
        """A bad donation_id on return is reported as an error, not a crash."""
        frappe.local.form_dict = frappe._dict({"donation_id": "DOES-NOT-EXIST-XYZ"})
        context = frappe._dict()
        donate.get_context(context)

        self.assertEqual(context.payment_status, "error")

    # ------------------------------------------------------------------
    # map_donation_status (pure helper)
    # ------------------------------------------------------------------

    def test_map_donation_status(self):
        svc = get_public_donation_service()
        self.assertEqual(svc.map_donation_status("One-time donation"), "One-time")
        self.assertEqual(svc.map_donation_status("Monthly recurring"), "Recurring")
        self.assertEqual(svc.map_donation_status("Promised donation"), "Promised")
        self.assertEqual(svc.map_donation_status("Recurring"), "Recurring")
        # Unknown value falls back to One-time.
        self.assertEqual(svc.map_donation_status("garbage"), "One-time")

    # ------------------------------------------------------------------
    # submit_donation - validation paths
    # ------------------------------------------------------------------

    def test_submit_donation_missing_required_field(self):
        result = donate.submit_donation(donor_name="No Email", amount="10", payment_method="Bank Transfer")
        self.assertFalse(result["success"])
        self.assertIn("donor_email", result["message"])

    def test_submit_donation_invalid_email(self):
        result = donate.submit_donation(
            donor_name="Bad Email",
            donor_email="not-an-email",
            amount="10",
            payment_method="Bank Transfer",
        )
        self.assertFalse(result["success"])
        self.assertIn("Invalid email", result["message"])

    def test_submit_donation_zero_amount(self):
        result = donate.submit_donation(
            donor_name="Zero",
            donor_email=self._unique_email(),
            amount="0",
            payment_method="Bank Transfer",
        )
        self.assertFalse(result["success"])
        self.assertIn("greater than zero", result["message"])

    # ------------------------------------------------------------------
    # submit_donation - full happy paths (non-Mollie)
    # ------------------------------------------------------------------

    def test_submit_donation_bank_transfer_creates_records(self):
        """A complete bank-transfer donation creates donor + donation records.

        Bank Transfer availability depends on ``company_iban`` being configured in
        Verenigingen Settings. When it is, PaymentHook returns transfer
        instructions; when it isn't, the donation is still created but payment
        setup reports a failure. Either way the donor + donation records must
        exist - that is the contract this test guards.
        """
        email = self._unique_email()
        result = donate.submit_donation(
            donor_name="Bank Donor",
            donor_email=email,
            amount="25.50",
            payment_method="Bank Transfer",
            donation_purpose_type="General",
        )

        # Whether payment setup succeeded or not, the donation record is created.
        self.assertTrue(result.get("donation_created"), msg=result)
        donation_name = result["donation_id"]
        self.track_doc("Donation", donation_name)

        donation = frappe.get_doc("Donation", donation_name)
        self.track_doc("Donor", donation.donor)
        self.assertEqual(donation.amount, 25.50)
        self.assertEqual(donation.mode_of_payment, "Bank Transfer")
        self.assertEqual(donation.paid, 0)

        # A donor record now exists for this email.
        self.assertTrue(frappe.db.exists("Donor", {"donor_email": email}))

    def test_submit_donation_cash_creates_records(self):
        email = self._unique_email()
        result = donate.submit_donation(
            donor_name="Cash Donor",
            donor_email=email,
            amount="5",
            payment_method="Cash",
        )
        self.assertTrue(result["success"], msg=result)
        donation_name = result["donation_id"]
        self.track_doc("Donation", donation_name)
        donor = frappe.db.get_value("Donor", {"donor_email": email})
        self.track_doc("Donor", donor)
        self.assertIn(result["payment_info"]["status"], ("cash_pending", "pending"))

    def test_submit_donation_unknown_payment_method_fails_gracefully(self):
        """An unknown payment method (invalid Mode of Payment link) fails cleanly.

        ``mode_of_payment`` is a Link to Mode of Payment, so a bogus value makes
        donation creation fail with a LinkValidationError. ``submit_donation``
        must catch this and return a structured failure rather than 500.
        """
        email = self._unique_email()
        result = donate.submit_donation(
            donor_name="Weird Donor",
            donor_email=email,
            amount="12",
            payment_method="Carrier Pigeon",
        )
        self.assertFalse(result["success"], msg=result)
        self.assertIn("message", result)
        # The donor may have been created before the donation failed - clean up.
        donor = frappe.db.get_value("Donor", {"donor_email": email})
        if donor:
            self.track_doc("Donor", donor)

    def test_submit_donation_reuses_existing_donor(self):
        """Submitting twice with the same email reuses the donor record."""
        email = self._unique_email()
        first = donate.submit_donation(
            donor_name="Repeat Donor",
            donor_email=email,
            amount="10",
            payment_method="Cash",
        )
        self.track_doc("Donation", first["donation_id"])

        second = donate.submit_donation(
            donor_name="Repeat Donor",
            donor_email=email,
            amount="20",
            payment_method="Cash",
        )
        self.track_doc("Donation", second["donation_id"])

        d1 = frappe.get_doc("Donation", first["donation_id"])
        d2 = frappe.get_doc("Donation", second["donation_id"])
        self.track_doc("Donor", d1.donor)
        self.assertEqual(d1.donor, d2.donor)

    def test_submit_donation_campaign_purpose_unknown_campaign(self):
        """An unknown campaign reference is folded into the donation notes."""
        email = self._unique_email()
        result = donate.submit_donation(
            donor_name="Campaign Donor",
            donor_email=email,
            amount="30",
            payment_method="Cash",
            donation_purpose_type="Campaign",
            campaign_reference="A Campaign That Does Not Exist",
            donation_notes="Keep going!",
        )
        self.assertTrue(result["success"], msg=result)
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.track_doc("Donation", donation.name)
        self.track_doc("Donor", donation.donor)
        # Campaign field stays empty (campaign didn't exist) but notes preserve intent.
        self.assertIn("A Campaign That Does Not Exist", donation.donation_notes)
        self.assertIn("Keep going!", donation.donation_notes)

    def test_submit_donation_chapter_purpose(self):
        """A chapter-earmarked donation stores the chapter_reference link."""
        chapter = self.create_test_chapter()
        email = self._unique_email()
        result = donate.submit_donation(
            donor_name="Chapter Donor",
            donor_email=email,
            amount="40",
            payment_method="Cash",
            donation_purpose_type="Chapter",
            chapter_reference=chapter.name,
        )
        self.assertTrue(result["success"], msg=result)
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.track_doc("Donation", donation.name)
        self.track_doc("Donor", donation.donor)
        self.assertEqual(donation.chapter_reference, chapter.name)

    # ------------------------------------------------------------------
    # get_or_create_donor / create_donation_record helpers
    # ------------------------------------------------------------------

    def test_get_or_create_donor_creates_new(self):
        email = self._unique_email()
        form_data = frappe._dict(
            {
                "donor_name": "Helper Donor",
                "donor_email": email,
                "donor_type": "Individual",
            }
        )
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
        self.assertIsNotNone(donor)
        self.track_doc("Donor", donor.name)
        self.assertEqual(donor.donor_email, email)
        self.assertEqual(donor.donor_category, "Regular Donor")

    def test_get_or_create_donor_default_type_fallback(self):
        """When no donor_type is given, the settings default (Individual) is used."""
        email = self._unique_email()
        form_data = frappe._dict({"donor_name": "Fallback Donor", "donor_email": email})
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
        self.track_doc("Donor", donor.name)
        self.assertIn(donor.donor_type, ("Individual", "Organization"))

    def test_create_donation_record_specific_goal(self):
        donor = self.create_test_donor()
        form_data = frappe._dict(
            {
                "amount": "55",
                "payment_method": "Cash",
                "donation_purpose_type": "Specific Goal",
                "specific_goal_description": "New shelter roof",
                "donation_notes": "urgent",
            }
        )
        donation = donate.create_donation_record(donor, form_data)
        self.track_doc("Donation", donation.name)
        self.assertEqual(donation.specific_goal_description, "New shelter roof")
        self.assertEqual(donation.donation_notes, "urgent")

    # ------------------------------------------------------------------
    # payment-method processing helpers (real PaymentHook delegation)
    # ------------------------------------------------------------------

    def test_process_bank_transfer_returns_instructions(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, mode_of_payment="Bank Transfer")
        result = donate.process_bank_transfer(donation, frappe._dict())
        self.assertEqual(result["status"], "awaiting_transfer")
        self.assertIn("bank_details", result)
        self.assertEqual(result["bank_details"]["amount"], donation.amount)

    def test_process_cash_payment_returns_pending(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, mode_of_payment="Cash")
        result = donate.process_cash_payment(donation, frappe._dict())
        self.assertEqual(result["status"], "cash_pending")

    def test_process_sepa_direct_debit_returns_mandate_required(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, mode_of_payment="Bank Transfer")
        result = donate.process_sepa_direct_debit(donation, frappe._dict())
        self.assertEqual(result["status"], "mandate_required")
        self.assertEqual(result["next_step"], "sepa_mandate_form")

    def test_process_payment_method_cash_available(self):
        """process_payment_method delegates to PaymentHook for an always-available method.

        Cash is always offered by PaymentHook, so this exercises the real
        PaymentHook -> SHOW_INSTRUCTIONS -> cash_pending conversion path end to end.
        (Bank Transfer is intentionally not covered here: its availability is
        gated on a ``company_iban`` field that does not exist on Verenigingen
        Settings, so it is never available via PaymentHook - see test report.)
        """
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, mode_of_payment="Cash")
        form_data = frappe._dict(
            {
                "payment_method": "Cash",
                "donor_email": donor.donor_email,
                "donor_name": donor.donor_name,
            }
        )
        result = donate.process_payment_method(donation, form_data)
        # Cash is always available; result carries a status (cash_pending or pending).
        self.assertIn("status", result)
        self.assertNotEqual(result["status"], "error")

    def test_process_payment_method_unimplemented(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name)
        form_data = frappe._dict({"payment_method": "Telepathy"})
        result = donate.process_payment_method(donation, form_data)
        self.assertEqual(result["status"], "pending")

    # ------------------------------------------------------------------
    # _convert_payment_hook_response (pure mapping helper)
    # ------------------------------------------------------------------

    def test_convert_payment_hook_response_redirect(self):
        result = donate._convert_payment_hook_response(
            {
                "success": True,
                "action": "redirect",
                "data": {"url": "https://pay.example/abc", "expires_at": "2099-01-01"},
                "payment_id": "tr_123",
                "message": "go",
            }
        )
        self.assertEqual(result["status"], "redirect_required")
        self.assertEqual(result["payment_url"], "https://pay.example/abc")
        self.assertEqual(result["payment_id"], "tr_123")

    def test_convert_payment_hook_response_failure(self):
        result = donate._convert_payment_hook_response({"success": False, "message": "nope"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "nope")

    def test_convert_payment_hook_response_mandate_form(self):
        result = donate._convert_payment_hook_response(
            {
                "success": True,
                "action": "mandate_form",
                "data": {"mandate_id": "MND-1", "collection_date": "2099-01-01"},
                "message": "ok",
            }
        )
        self.assertEqual(result["status"], "mandate_required")
        self.assertEqual(result["mandate_id"], "MND-1")

    def test_convert_payment_hook_response_instructions_bank(self):
        result = donate._convert_payment_hook_response(
            {
                "success": True,
                "action": "show_instructions",
                "data": {"bank_details": {"iban": "NL00"}, "payment_reference": "REF1"},
                "message": "ok",
            }
        )
        self.assertEqual(result["status"], "awaiting_transfer")

    def test_convert_payment_hook_response_instructions_cash(self):
        result = donate._convert_payment_hook_response(
            {
                "success": True,
                "action": "show_instructions",
                "data": {"reference": "CASH-1"},
                "message": "ok",
            }
        )
        self.assertEqual(result["status"], "cash_pending")

    # ------------------------------------------------------------------
    # get_donation_status (whitelisted) + mark_donation_paid
    # ------------------------------------------------------------------

    def test_get_donation_status_missing_id(self):
        result = donate.get_donation_status(None)
        self.assertIn("error", result)

    def test_get_donation_status_returns_data(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, paid=0)
        result = donate.get_donation_status(donation.name)
        self.assertEqual(result["donation_id"], donation.name)
        self.assertEqual(result["status"], "Pending")
        self.assertEqual(result["amount"], donation.amount)
        # Regression guard: this used to crash with AttributeError because the
        # endpoint read donation.date (the field is donation_date).
        self.assertEqual(str(result["date"]), str(donation.donation_date))

    def test_mark_donation_paid(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, paid=0)
        result = donate.mark_donation_paid(donation.name, payment_reference="REF-TEST-1")
        self.assertTrue(result.get("success"), msg=result)
        donation.reload()
        self.assertEqual(donation.paid, 1)
        self.assertEqual(donation.payment_id, "REF-TEST-1")

    # ------------------------------------------------------------------
    # retry_payment (whitelisted, guest-allowed)
    # ------------------------------------------------------------------

    def test_retry_payment_already_paid_raises(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, paid=1, mode_of_payment="Cash")
        with self.assertRaises(frappe.exceptions.ValidationError):
            donate.retry_payment(donation.name)

    def test_retry_payment_non_mollie_raises(self):
        donor = self.create_test_donor()
        donation = self.create_test_donation(donor=donor.name, paid=0, mode_of_payment="Cash")
        with self.assertRaises(frappe.exceptions.ValidationError):
            donate.retry_payment(donation.name)
