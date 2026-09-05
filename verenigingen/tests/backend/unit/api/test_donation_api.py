"""Tests for verenigingen.api.donation_api.process_campaign_donation (#430).

templates/pages/campaign.html posts to this endpoint, which never existed before
this fix. Uses payment_method="Bank Transfer" throughout to exercise the field
mapping and donation-creation path without touching the Mollie gateway (per
CLAUDE.md's environment-parity warning) -- the Mollie-default behaviour itself is
a single `setdefault` line, verified by test_defaults_payment_method_to_mollie
via the request-required-fields error path, which runs before any gateway call.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.donation_form_data import make_donation_form_data


class TestProcessCampaignDonation(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _make_campaign(self, **overrides):
        data = {
            "doctype": "Donation Campaign",
            "campaign_name": f"TEST Campaign {frappe.generate_hash()[:8]}",
            "campaign_type": "Project Funding",
            "status": "Active",
            "start_date": frappe.utils.today(),
            "is_public": 1,
            "show_on_website": 1,
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        self._track_test_document("Donation Campaign", doc.name)
        return doc

    def _form_data(self, campaign, **overrides):
        data = make_donation_form_data(
            label="Campaign Donor",
            payment_key="payment_method",
            payment_method="Bank Transfer",
            donation_purpose_type="Campaign",
            donation_campaign=campaign.name,
        )
        data.update(overrides)
        return data

    def test_maps_campaign_and_message_fields_and_creates_donation(self):
        """The core #430 regression: the campaign form's own field names
        (donation_campaign, donation_message) must reach the Donation record,
        not be silently dropped because the service expects different names."""
        from verenigingen.api.donation_api import process_campaign_donation

        campaign = self._make_campaign()
        frappe.set_user("Guest")

        result = process_campaign_donation(
            **self._form_data(campaign, donation_message="Keep up the great work!")
        )

        self.assertTrue(result.get("success"), f"Campaign donation should succeed: {result}")
        donation_id = result.get("donation_id")
        self.assertIsNotNone(donation_id)

        frappe.set_user(self._original_user)
        donation = frappe.get_doc("Donation", donation_id)
        self.assertEqual(donation.campaign, campaign.name)
        self.assertEqual(donation.donation_notes, "Keep up the great work!")

    def test_anonymous_checkbox_is_persisted(self):
        """get_top_donors() filters `anonymous = 0` (donation_campaign.py) -- if the
        field is never set, a donor who asked to stay anonymous shows up anyway."""
        from verenigingen.api.donation_api import process_campaign_donation

        campaign = self._make_campaign()
        frappe.set_user("Guest")

        result = process_campaign_donation(**self._form_data(campaign, anonymous=1))

        frappe.set_user(self._original_user)
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.assertEqual(donation.anonymous, 1)

    def test_not_anonymous_by_default(self):
        from verenigingen.api.donation_api import process_campaign_donation

        campaign = self._make_campaign()
        frappe.set_user("Guest")

        result = process_campaign_donation(**self._form_data(campaign))

        frappe.set_user(self._original_user)
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.assertEqual(donation.anonymous, 0)

    def test_defaults_payment_method_to_mollie(self):
        """No payment_method sent (the campaign form has no selector) must not
        surface the service's own "Missing required field: payment_method" error --
        proof the setdefault ran before PublicDonationService.submit()'s own
        required-fields check, without needing a live Mollie call to observe it."""
        from verenigingen.api.donation_api import process_campaign_donation

        campaign = self._make_campaign()
        form_data = self._form_data(campaign)
        del form_data["payment_method"]
        # Force validation to fail on the amount check (runs right after the
        # required-fields check, still before any Mollie network call) so the
        # test stays fast and gateway-free while still proving payment_method
        # was populated.
        form_data["amount"] = "0"
        frappe.set_user("Guest")

        result = process_campaign_donation(**form_data)

        self.assertFalse(result.get("success"))
        self.assertNotIn("payment_method", (result.get("message") or "").lower())
        self.assertIn("greater than zero", (result.get("message") or "").lower())
