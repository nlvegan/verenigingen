"""
Regression tests for guest donation flow.

Verifies that guest users (unauthenticated) can complete the full donation flow
via the /donate page. This is a regression test for the bug where
secure_document_operation(allow_system_user=True) failed for guests because
they lack roles in ESCALATION_ALLOWED_ROLES.

The fix replaced all secure_document_operation calls in the guest donation path
with secure_user_context() via the _save_donation_as_system_user() helper.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.donation_form_data import make_donation_form_data


class TestGuestDonationFlow(EnhancedTestCase):
    """Test that guest users can complete the donation flow end-to-end."""

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _make_form_data(self, **overrides):
        """Build minimal valid form data for submit_donation."""
        return make_donation_form_data(label="Guest Donor", payment_key="payment_method", **overrides)

    def _create_guest_donation(self, payment_method="Bank Transfer"):
        """Create a donor and donation as Guest, returning (donor, donation)."""
        from verenigingen.services.donation.donor_service import get_donation_donor_service
        from verenigingen.services.donation.public_donation_service import (
            get_public_donation_service,
        )

        form_data = frappe._dict(self._make_form_data(payment_method=payment_method))
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
        donation = get_public_donation_service().create_donation(donor, form_data, draft=False)
        return donor, donation, form_data

    # ------------------------------------------------------------------
    # Core regression: guest donation creation via submit_donation
    # ------------------------------------------------------------------

    def test_guest_can_create_donation_via_submit(self):
        """REGRESSION: Guest user can submit a donation without PermissionError.

        Before the fix, secure_document_operation(allow_system_user=True) raised
        'You do not have permission to request elevated system operations' for guests.
        """
        from verenigingen.templates.pages.donate import submit_donation

        frappe.set_user("Guest")

        form_data = self._make_form_data(payment_method="Bank Transfer")
        result = submit_donation(**form_data)

        self.assertTrue(result.get("success"), f"Guest donation should succeed: {result}")
        self.assertTrue(result.get("donation_created"))
        self.assertIsNotNone(result.get("donation_id"))

        # Verify donation persisted correctly
        frappe.set_user(self._original_user)
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.assertEqual(donation.mode_of_payment, "Bank Transfer")
        self.assertEqual(float(donation.amount), 25.0)

    def test_guest_can_create_donation_cash(self):
        """REGRESSION: Guest user can submit a cash donation."""
        from verenigingen.templates.pages.donate import submit_donation

        frappe.set_user("Guest")

        form_data = self._make_form_data(payment_method="Cash")
        result = submit_donation(**form_data)

        self.assertTrue(result.get("success"), f"Guest cash donation should succeed: {result}")
        self.assertIsNotNone(result.get("donation_id"))
        self.assertEqual(result.get("payment_info", {}).get("status"), "cash_pending")

    # ------------------------------------------------------------------
    # Individual function tests: document creation as Guest
    # ------------------------------------------------------------------

    def test_guest_create_donation_record(self):
        """REGRESSION: create_donation_record works for guest user."""
        frappe.set_user("Guest")
        _donor, donation, _form_data = self._create_guest_donation()

        self.assertIsNotNone(donation)
        self.assertIsNotNone(donation.name)
        self.assertEqual(float(donation.amount), 25.0)

    def test_guest_create_draft_donation_for_mollie(self):
        """REGRESSION: create_draft_donation_for_payment works for guest user."""
        from verenigingen.services.donation.donor_service import get_donation_donor_service
        from verenigingen.services.donation.public_donation_service import (
            get_public_donation_service,
        )

        frappe.set_user("Guest")

        form_data = frappe._dict(self._make_form_data(payment_method="Mollie"))
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
        donation = get_public_donation_service().create_donation(donor, form_data, draft=True)

        self.assertIsNotNone(donation)
        self.assertIsNotNone(donation.name)
        self.assertEqual(donation.status, "Promised")

    # ------------------------------------------------------------------
    # Payment method saves as Guest
    # ------------------------------------------------------------------

    def test_guest_process_mollie_saves_payment_method(self):
        """REGRESSION: process_mollie_payment can save donation as guest.

        Tests only the payment method save, not the Mollie API call.
        If Mollie is not configured, the save should still succeed and the
        function returns an error from the Mollie API, not a permission error.
        """
        from verenigingen.services.donation.donor_service import get_donation_donor_service
        from verenigingen.services.donation.public_donation_service import (
            get_public_donation_service,
        )

        frappe.set_user("Guest")

        form_data = frappe._dict(self._make_form_data(payment_method="Mollie"))
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
        service = get_public_donation_service()
        donation = service.create_donation(donor, form_data, draft=True)

        result = service.process_mollie_payment(donation, form_data)

        # The save must succeed. If we get an error, it must be from the
        # Mollie API, not a permission/escalation error from secure_operations.
        if result.get("status") == "error":
            msg = result.get("message", "").lower()
            self.assertNotIn("permission", msg, f"Should not get permission error: {result}")
            self.assertNotIn("elevated system operations", msg, f"Should not get escalation error: {result}")

        # Verify the payment method was persisted
        frappe.set_user(self._original_user)
        donation.reload()
        self.assertEqual(donation.mode_of_payment, "Mollie")

    # ------------------------------------------------------------------
    # Donor creation/reuse as Guest
    # ------------------------------------------------------------------

    def test_guest_get_or_create_donor_new(self):
        """Guest user can create a new donor."""
        from verenigingen.services.donation.donor_service import get_donation_donor_service

        frappe.set_user("Guest")

        form_data = frappe._dict(self._make_form_data())
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)

        self.assertIsNotNone(donor)
        self.assertEqual(donor.donor_name, form_data.donor_name)
        self.assertEqual(donor.donor_email, form_data.donor_email)

    def test_guest_get_or_create_donor_existing(self):
        """Guest user reuses existing donor by email."""
        from verenigingen.services.donation.donor_service import get_donation_donor_service

        form_data = frappe._dict(self._make_form_data())

        frappe.set_user("Guest")
        service = get_donation_donor_service(None)
        donor1 = service.get_or_create_from_public_form(form_data)
        donor2 = service.get_or_create_from_public_form(form_data)

        self.assertEqual(donor1.name, donor2.name)

    # ------------------------------------------------------------------
    # Edge case: authenticated user should also still work
    # ------------------------------------------------------------------

    def test_authenticated_user_can_still_donate(self):
        """Authenticated users should still be able to donate after the fix."""
        from verenigingen.templates.pages.donate import submit_donation

        admin = self.ensure_test_admin_user()
        frappe.set_user(admin.email)

        form_data = self._make_form_data(payment_method="Bank Transfer")
        result = submit_donation(**form_data)

        self.assertTrue(result.get("success"), f"Authenticated donation should succeed: {result}")
        self.assertIsNotNone(result.get("donation_id"))
