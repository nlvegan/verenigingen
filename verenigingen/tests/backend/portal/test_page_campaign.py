"""
Tests for the public campaign page controller
(verenigingen.templates.pages.campaign).

get_context resolves a Donation Campaign from form_dict (campaign or name),
enforces public/active gating, and assembles display context (progress
percentages, suggested amounts, optional recent-donations / top-donor lists).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageCampaign(EnhancedTestCase):
    """Real-data tests for the campaign page context handler."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        super().tearDown()

    def _make_campaign(self, **overrides):
        """Insert a Donation Campaign with sensible public/active defaults."""
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

    def test_no_campaign_specified_raises(self):
        from verenigingen.templates.pages.campaign import get_context

        frappe.form_dict = frappe._dict()
        with self.assertRaises(frappe.DoesNotExistError):
            get_context(frappe._dict())

    def test_public_active_campaign_happy_path(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(
            monetary_goal=1000,
            suggested_donation_amounts="10, 20, 30",
        )
        frappe.form_dict = frappe._dict({"campaign": campaign.name})

        ctx = frappe._dict()
        get_context(ctx)

        self.assertEqual(ctx.campaign.name, campaign.name)
        self.assertEqual(ctx.title, campaign.campaign_name)
        # Suggested amounts parsed from CSV string into floats.
        self.assertEqual(ctx.suggested_amounts, [10.0, 20.0, 30.0])
        # Progress percentages are clamped to <= 100.
        self.assertLessEqual(ctx.progress_percentage, 100)
        self.assertLessEqual(ctx.donor_progress_percentage, 100)
        self.assertEqual(ctx.no_cache, 1)

    def test_default_suggested_amounts_when_unset(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(suggested_donation_amounts="")
        frappe.form_dict = frappe._dict({"name": campaign.name})

        ctx = frappe._dict()
        get_context(ctx)
        self.assertEqual(ctx.suggested_amounts, [25, 50, 100, 250])

    def test_progress_percentage_clamped_to_100(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign()
        # Force an over-100 progress value directly in the DB column.
        frappe.db.set_value("Donation Campaign", campaign.name, "monetary_progress", 150)
        frappe.form_dict = frappe._dict({"campaign": campaign.name})

        ctx = frappe._dict()
        get_context(ctx)
        self.assertEqual(ctx.progress_percentage, 100)

    def test_non_public_campaign_denied(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(is_public=0, show_on_website=0)
        frappe.form_dict = frappe._dict({"campaign": campaign.name})
        with self.assertRaises(frappe.PermissionError):
            get_context(frappe._dict())

    def test_show_on_website_off_denied(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(is_public=1, show_on_website=0)
        frappe.form_dict = frappe._dict({"campaign": campaign.name})
        with self.assertRaises(frappe.PermissionError):
            get_context(frappe._dict())

    def test_draft_campaign_not_active(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(status="Draft")
        frappe.form_dict = frappe._dict({"campaign": campaign.name})
        with self.assertRaises(frappe.ValidationError):
            get_context(frappe._dict())

    def test_completed_campaign_allowed(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(status="Completed")
        frappe.form_dict = frappe._dict({"campaign": campaign.name})

        ctx = frappe._dict()
        get_context(ctx)
        self.assertEqual(ctx.campaign.name, campaign.name)

    def test_recent_donations_and_top_donors_lists_populated(self):
        from verenigingen.templates.pages.campaign import get_context

        campaign = self._make_campaign(
            show_recent_donations=1,
            show_donor_list=1,
        )
        frappe.form_dict = frappe._dict({"campaign": campaign.name})

        ctx = frappe._dict()
        get_context(ctx)
        # These come straight from campaign methods; just assert the keys exist
        # and are list-shaped (real query executed, no exception).
        self.assertIsInstance(ctx.recent_donations, list)
        self.assertIsInstance(ctx.top_donors, list)
