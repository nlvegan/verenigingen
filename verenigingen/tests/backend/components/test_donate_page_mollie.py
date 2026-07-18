# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Integration tests for the Mollie (online payment) branch of the public donation
portal page controller (``verenigingen/templates/pages/donate.py``).

The non-Mollie payment paths (bank transfer, cash, SEPA), the validation
branches, ``get_or_create_donor``, ``create_donation_record``,
``get_donation_status``, ``mark_donation_paid``, ``retry_payment`` and the pure
helpers are already exercised by
``tests/backend/components/test_donate_page.py`` and
``tests/backend/portal/test_guest_donation_flow.py``. This module deliberately
covers the *complement*: the payment-first Mollie flow that those suites leave
uncovered, because it requires stubbing the Mollie API boundary.

Only the external Mollie boundary is stubbed:
    * ``CompletePaymentService`` (used by ``process_mollie_payment``)
    * ``MollieClient`` (used by ``get_context`` to re-check a returning payment)

Everything else - Donor creation, draft Donation creation, the draft-then-submit
state machine, the form-data plumbing - runs for real against the ORM, and the
tests assert the real persisted documents and their field values.
"""

from unittest.mock import patch

import frappe

from verenigingen.services.donation.donor_service import get_donation_donor_service
from verenigingen.services.donation.public_donation_service import (
    get_public_donation_service,
)
from verenigingen.templates.pages import donate
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _FakeCompletePaymentService:
    """Stand-in for CompletePaymentService that records calls and never hits the network.

    Captures the donation document and form data passed to it so tests can
    assert the real donation was created and the correct metadata reached the
    Mollie boundary. Returns a redirect-style result, exactly like the real
    service does on success.
    """

    # Class-level capture so the test can inspect after submit_donation returns.
    last_donation = None
    last_form_data = None
    last_method = None

    def __init__(self, client=None):
        self.client = client

    def create_donation_payment(self, donation_doc, form_data):
        _FakeCompletePaymentService.last_donation = donation_doc
        _FakeCompletePaymentService.last_form_data = form_data
        _FakeCompletePaymentService.last_method = "single"
        return {
            "status": "redirect_required",
            "payment_id": "tr_fake_single",
            "payment_url": "https://pay.mollie.test/checkout/single",
            "checkout_url": "https://pay.mollie.test/checkout/single",
            "message": "Payment created successfully",
            "info": "You will be redirected",
        }

    def create_recurring_donation_payment(self, donation_doc, form_data):
        _FakeCompletePaymentService.last_donation = donation_doc
        _FakeCompletePaymentService.last_form_data = form_data
        _FakeCompletePaymentService.last_method = "recurring"
        return {
            "status": "subscription_redirect_required",
            "payment_id": "tr_fake_recurring",
            "payment_url": "https://pay.mollie.test/checkout/recurring",
            "checkout_url": "https://pay.mollie.test/checkout/recurring",
            "message": "Subscription payment created",
        }


class _RaisingCompletePaymentService:
    """CompletePaymentService stand-in whose payment creation raises (provider down)."""

    def __init__(self, client=None):
        self.client = client

    def create_donation_payment(self, donation_doc, form_data):
        raise RuntimeError("Mollie API unreachable")

    def create_recurring_donation_payment(self, donation_doc, form_data):
        raise RuntimeError("Mollie API unreachable")


# Path where process_mollie_payment imports CompletePaymentService (local import).
_CPS_PATH = (
    "verenigingen.verenigingen_payments.mollie.services." "complete_payment_service.CompletePaymentService"
)
# Path where get_context imports MollieClient (local import).
_MOLLIE_CLIENT_PATH = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"


class TestDonatePageMollie(EnhancedTestCase):
    """Mollie-branch integration tests for the donate page controller."""

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        frappe.local.form_dict = frappe._dict()
        _FakeCompletePaymentService.last_donation = None
        _FakeCompletePaymentService.last_form_data = None
        _FakeCompletePaymentService.last_method = None

    def tearDown(self):
        frappe.local.form_dict = frappe._dict()
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _unique_email(self, prefix="mollie.donor"):
        return f"{prefix}.{frappe.generate_hash(length=8)}@example.com"

    # ------------------------------------------------------------------
    # submit_donation - Mollie payment-first flow (guest)
    # ------------------------------------------------------------------

    def test_submit_donation_mollie_guest_creates_draft_and_redirects(self):
        """A guest Mollie donation creates a real draft Donation and returns a redirect.

        Asserts the payment-first contract:
          * a real Donor is created/matched for the email,
          * a real *draft* Donation (status Promised, paid 0, docstatus 0) exists,
          * the correct amount + mode_of_payment are persisted,
          * the API response carries the donation id and the Mollie redirect info.
        """
        email = self._unique_email()
        frappe.set_user("Guest")

        with patch(_CPS_PATH, _FakeCompletePaymentService):
            result = donate.submit_donation(
                donor_name="Mollie Guest",
                donor_email=email,
                amount="42.50",
                payment_method="Mollie",
                donation_purpose_type="General",
            )

        frappe.set_user(self._original_user)

        self.assertTrue(result.get("success"), msg=result)
        donation_name = result["donation_id"]
        self.track_doc("Donation", donation_name)

        donation = frappe.get_doc("Donation", donation_name)
        self.track_doc("Donor", donation.donor)

        # Real persisted draft donation.
        self.assertEqual(float(donation.amount), 42.50)
        self.assertEqual(donation.mode_of_payment, "Mollie")
        self.assertEqual(donation.status, "Promised")
        self.assertEqual(donation.paid, 0)
        self.assertEqual(donation.docstatus, 0)  # draft until webhook submits it

        # Real donor matched on the submitted email.
        self.assertEqual(frappe.db.get_value("Donor", donation.donor, "donor_email"), email)

        # Redirect metadata surfaced to the frontend.
        payment_info = result["payment_info"]
        self.assertEqual(payment_info["status"], "redirect_required")
        self.assertEqual(payment_info["payment_url"], "https://pay.mollie.test/checkout/single")

        # The real draft donation (not a copy) reached the payment boundary.
        self.assertEqual(_FakeCompletePaymentService.last_donation.name, donation_name)
        self.assertEqual(_FakeCompletePaymentService.last_method, "single")

    def test_submit_donation_mollie_recurring_uses_subscription_path(self):
        """A recurring Mollie donation routes through the subscription service method."""
        email = self._unique_email()
        frappe.set_user("Guest")

        with patch(_CPS_PATH, _FakeCompletePaymentService):
            result = donate.submit_donation(
                donor_name="Recurring Donor",
                donor_email=email,
                amount="15",
                payment_method="Mollie",
                donation_status="Recurring",
                recurring_interval="1 month",
            )

        frappe.set_user(self._original_user)

        self.assertTrue(result.get("success"), msg=result)
        self.track_doc("Donation", result["donation_id"])
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.track_doc("Donor", donation.donor)

        self.assertEqual(_FakeCompletePaymentService.last_method, "recurring")
        self.assertEqual(result["payment_info"]["status"], "subscription_redirect_required")

    def test_submit_donation_mollie_reuses_existing_donor(self):
        """Mollie submission for a known email reuses the existing Donor record."""
        email = self._unique_email()
        existing = self.create_test_donor(donor_email=email, donor_name="Known Donor")

        frappe.set_user("Guest")
        with patch(_CPS_PATH, _FakeCompletePaymentService):
            result = donate.submit_donation(
                donor_name="Known Donor",
                donor_email=email,
                amount="20",
                payment_method="Mollie",
            )
        frappe.set_user(self._original_user)

        self.assertTrue(result.get("success"), msg=result)
        self.track_doc("Donation", result["donation_id"])
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.assertEqual(donation.donor, existing.name)

    def test_submit_donation_mollie_provider_error_returns_structured_failure(self):
        """When Mollie setup raises, submit_donation returns a structured failure, not a 500.

        The draft donation has already been created at this point; the endpoint
        must surface a user-facing failure message rather than propagating the
        exception.
        """
        email = self._unique_email()
        frappe.set_user("Guest")

        with patch(_CPS_PATH, _RaisingCompletePaymentService):
            result = donate.submit_donation(
                donor_name="Unlucky Donor",
                donor_email=email,
                amount="33",
                payment_method="Mollie",
            )

        frappe.set_user(self._original_user)

        self.assertFalse(result.get("success"), msg=result)
        self.assertIn("message", result)
        # A draft donation was created before the failure - clean it up.
        donor = frappe.db.get_value("Donor", {"donor_email": email})
        if donor:
            self.track_doc("Donor", donor)
            for d in frappe.get_all("Donation", filters={"donor": donor}, pluck="name"):
                self.track_doc("Donation", d)

    def test_submit_donation_mollie_non_redirect_result_is_failure(self):
        """A Mollie result without a redirect status is reported as a failure.

        process_mollie_payment can return an error dict (e.g. provider returned a
        non-redirect status). submit_donation only treats redirect_required /
        subscription_redirect_required as success; anything else is surfaced as a
        failure carrying the provider message.
        """

        class _ErrorService:
            def __init__(self, client=None):
                pass

            def create_donation_payment(self, donation_doc, form_data):
                return {"status": "error", "message": "card declined", "info": "try another card"}

        email = self._unique_email()
        frappe.set_user("Guest")
        with patch(_CPS_PATH, _ErrorService):
            result = donate.submit_donation(
                donor_name="Declined Donor",
                donor_email=email,
                amount="10",
                payment_method="Mollie",
            )
        frappe.set_user(self._original_user)

        self.assertFalse(result.get("success"), msg=result)
        self.assertEqual(result.get("message"), "card declined")
        donor = frappe.db.get_value("Donor", {"donor_email": email})
        if donor:
            self.track_doc("Donor", donor)
            for d in frappe.get_all("Donation", filters={"donor": donor}, pluck="name"):
                self.track_doc("Donation", d)

    # ------------------------------------------------------------------
    # process_mollie_payment - direct, success path
    # ------------------------------------------------------------------

    def _make_draft_mollie_donation(self):
        """Create a real *draft* (unsubmitted) donation via the prod helper.

        process_mollie_payment calls donation.save(); the factory's
        create_test_donation submits the donation (docstatus=1), which can't be
        re-saved. The real Mollie flow always operates on a draft created by
        create_draft_donation_for_payment, so we mirror that here.
        """
        email = self._unique_email()
        form_data = frappe._dict(
            {
                "donor_name": "Direct Mollie Donor",
                "donor_email": email,
                "donor_type": "Individual",
                "amount": "27.00",
                "payment_method": "Mollie",
                "donation_purpose_type": "General",
            }
        )
        donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
        donation = get_public_donation_service().create_donation(donor, form_data, draft=True)
        self.track_doc("Donation", donation.name)
        self.track_doc("Donor", donor.name)
        return donor, donation

    def test_process_mollie_payment_success_persists_method_and_returns_redirect(self):
        """process_mollie_payment saves mode_of_payment=Mollie and returns the service result."""
        donor, donation = self._make_draft_mollie_donation()

        form_data = frappe._dict({"donor_email": donor.donor_email, "donor_name": donor.donor_name})

        with patch(_CPS_PATH, _FakeCompletePaymentService):
            result = donate.process_mollie_payment(donation, form_data)

        self.assertEqual(result["status"], "redirect_required")
        self.assertEqual(result["payment_id"], "tr_fake_single")
        # The donation's payment method was persisted before the service call.
        donation.reload()
        self.assertEqual(donation.mode_of_payment, "Mollie")

    def test_process_mollie_payment_recurring_branch(self):
        """donation_status=Recurring routes process_mollie_payment to the recurring method."""
        donor, donation = self._make_draft_mollie_donation()

        form_data = frappe._dict(
            {
                "donor_email": donor.donor_email,
                "donor_name": donor.donor_name,
                "donation_status": "Recurring",
                "recurring_interval": "1 month",
            }
        )
        with patch(_CPS_PATH, _FakeCompletePaymentService):
            result = donate.process_mollie_payment(donation, form_data)

        self.assertEqual(result["status"], "subscription_redirect_required")
        self.assertEqual(_FakeCompletePaymentService.last_method, "recurring")

    def test_process_mollie_payment_service_exception_returns_error_dict(self):
        """A raising service is caught and converted to a user-facing error dict."""
        donor, donation = self._make_draft_mollie_donation()

        with patch(_CPS_PATH, _RaisingCompletePaymentService):
            result = donate.process_mollie_payment(donation, frappe._dict())

        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)
        # Even on provider failure, the method was still persisted on the donation.
        donation.reload()
        self.assertEqual(donation.mode_of_payment, "Mollie")

    # ------------------------------------------------------------------
    # get_context - returning from a Mollie payment (payment_id re-check)
    # ------------------------------------------------------------------

    def _make_unpaid_mollie_donation(self):
        donor = self.create_test_donor(donor_email=self._unique_email())
        donation = self.create_test_donation(
            donor=donor.name, mode_of_payment="Bank Transfer", paid=0, payment_id="tr_return_test"
        )
        return donation

    def test_get_context_mollie_return_paid_status(self):
        """Returning with a payment_id that Mollie reports 'paid' shows success + webhook flag."""
        donation = self._make_unpaid_mollie_donation()
        frappe.local.form_dict = frappe._dict({"donation_id": donation.name})

        fake_client = _FakeMollieClient(status="paid")
        with patch(_MOLLIE_CLIENT_PATH, return_value=fake_client):
            context = frappe._dict()
            donate.get_context(context)

        self.assertEqual(context.payment_status, "success")
        self.assertTrue(context.get("payment_pending_webhook"))
        self.assertEqual(context.donation_result.name, donation.name)

    def test_get_context_mollie_return_open_status_pending(self):
        """A Mollie 'open' status on return is reported as pending."""
        donation = self._make_unpaid_mollie_donation()
        frappe.local.form_dict = frappe._dict({"donation_id": donation.name})

        fake_client = _FakeMollieClient(status="open")
        with patch(_MOLLIE_CLIENT_PATH, return_value=fake_client):
            context = frappe._dict()
            donate.get_context(context)

        self.assertEqual(context.payment_status, "pending")

    def test_get_context_mollie_return_failed_status(self):
        """A Mollie 'failed' status on return is reported as failed."""
        donation = self._make_unpaid_mollie_donation()
        frappe.local.form_dict = frappe._dict({"donation_id": donation.name})

        fake_client = _FakeMollieClient(status="failed")
        with patch(_MOLLIE_CLIENT_PATH, return_value=fake_client):
            context = frappe._dict()
            donate.get_context(context)

        self.assertEqual(context.payment_status, "failed")

    def test_get_context_mollie_status_check_error_falls_back_to_pending(self):
        """If the Mollie status check itself raises, get_context falls back to pending."""
        donation = self._make_unpaid_mollie_donation()
        frappe.local.form_dict = frappe._dict({"donation_id": donation.name})

        with patch(_MOLLIE_CLIENT_PATH, side_effect=RuntimeError("mollie down")):
            context = frappe._dict()
            donate.get_context(context)

        self.assertEqual(context.payment_status, "pending")


class _FakeMollieClient:
    """Minimal MollieClient stand-in returning a payment object with a status attr."""

    def __init__(self, status):
        self._status = status

    def get_payment(self, payment_id):
        return frappe._dict({"status": self._status})
