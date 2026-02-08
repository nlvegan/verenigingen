# -*- coding: utf-8 -*-
"""
Integration tests for all three contribution modes (Fixed, Income-Based, Flexible).

Tests the template configuration service, dues schedule creation, fee calculation,
and membership approval flow for each mode - including the case where
suggested_amount is not configured on the template (the bug fixed in 2026-02-08).
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestContributionModeTemplateIntegration(VereningingenTestCase):
    """Integration tests for template configuration across all contribution modes."""

    # ──────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────

    def _setup_type_and_template(self, mode, name_suffix, **fields):
        """Create a Membership Type and configure its auto-created template.

        MembershipType.after_insert() auto-creates a template with defaults.
        This helper modifies that template with the test-specific values.

        Returns (membership_type, template) tuple.
        """
        import time

        ts = str(int(time.time() * 1000))[-6:]
        unique_name = f"ContribTest-{name_suffix}-{ts}"

        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")

        minimum_amount = fields.pop("minimum_amount", 0)
        suggested_amount = fields.pop("suggested_amount", None)
        dues_rate = fields.pop("dues_rate", None)

        # Step 1: Create Membership Type (after_insert auto-creates a template)
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = unique_name
        mt.is_active = 1
        mt.minimum_amount = minimum_amount
        if role_profile:
            mt.role_profile = role_profile
        mt.insert()
        self.track_doc("Membership Type", mt.name)

        # Step 2: Get the auto-created template and update with test values
        mt.reload()
        template = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
        self.track_doc("Membership Dues Schedule", template.name)

        template.contribution_mode = mode
        template.billing_frequency = "Annual"
        template.minimum_amount = minimum_amount
        template.invoice_days_before = 30
        template.billing_day = 1
        template.auto_generate = 1

        # Set test-specific amounts (use db_set to avoid re-validation overwriting)
        template.suggested_amount = suggested_amount
        template.dues_rate = dues_rate

        for k, v in fields.items():
            setattr(template, k, v)

        # Use _skip_template_validation to prevent get_template_values self-reference
        # from re-applying defaults during save
        template._skip_template_validation = True
        template.save()

        # Reload to get final DB state
        template.reload()
        return mt, template

    def _make_member(self, suffix=""):
        """Create a minimal test member."""
        member = frappe.new_doc("Member")
        member.first_name = f"Contrib{suffix}"
        member.last_name = f"Tester{frappe.generate_hash(length=4)}"
        member.email = f"contrib.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.address_line1 = "Teststraat 42"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.insert()
        self.track_doc("Member", member.name)
        return member

    def _make_membership(self, member, membership_type):
        """Create and submit a Membership.

        Skips auto dues schedule creation so tests can control schedule setup.
        """
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.flags.skip_dues_schedule_creation = True
        membership.save()
        membership.submit()
        self.track_doc("Membership", membership.name)
        return membership

    def _make_member_schedule(self, member, membership, template, dues_rate=None):
        """Create an individual (non-template) dues schedule for a member."""
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.is_template = 0
        schedule.schedule_name = f"Sched-{member.name}-{frappe.generate_hash(length=4)}"
        schedule.member = member.name
        schedule.membership = membership.name
        schedule.membership_type = template.membership_type
        schedule.template_reference = template.name
        schedule.contribution_mode = template.contribution_mode
        schedule.billing_frequency = template.billing_frequency or "Annual"
        schedule.minimum_amount = template.minimum_amount or 0
        schedule.suggested_amount = template.suggested_amount or 0
        schedule.status = "Active"
        schedule.auto_generate = 0
        if dues_rate is not None:
            schedule.dues_rate = dues_rate
        schedule.save()
        self.track_doc("Membership Dues Schedule", schedule.name)
        return schedule

    def _get_template_values(self, schedule, membership_type_name, **kw):
        from verenigingen.services.billing.template_configuration_service import (
            TemplateConfigurationService,
        )

        return TemplateConfigurationService().get_template_values(
            schedule, membership_type_name, **kw
        )

    # ══════════════════════════════════════════════════
    #  FIXED MODE
    # ══════════════════════════════════════════════════

    def test_fixed_template_with_suggested_amount(self):
        """Fixed mode with suggested_amount configured returns correct values."""
        mt, template = self._setup_type_and_template(
            "Fixed", "Fix1", suggested_amount=50.0, minimum_amount=10.0,
        )

        values = self._get_template_values(
            frappe.new_doc("Membership Dues Schedule"), mt.name
        )
        self.assertEqual(values["suggested_amount"], 50.0)
        self.assertEqual(values["minimum_amount"], 10.0)
        self.assertEqual(values["billing_frequency"], "Annual")

    def test_fixed_template_schedule_creation(self):
        """Fixed template creates a member schedule with the correct dues_rate."""
        mt, template = self._setup_type_and_template(
            "Fixed", "FixSch", suggested_amount=30.0, minimum_amount=5.0,
        )
        member = self._make_member("Fix2")
        membership = self._make_membership(member, mt)

        schedule = self._make_member_schedule(member, membership, template, dues_rate=30.0)
        self.assertEqual(schedule.contribution_mode, "Fixed")
        self.assertEqual(schedule.dues_rate, 30.0)

    def test_fixed_fee_calculation_returns_template_amount(self):
        """Fee calculation for Fixed mode returns the template amount."""
        mt, template = self._setup_type_and_template(
            "Fixed", "FixFee", suggested_amount=45.0,
        )
        member = self._make_member("Fix3")
        membership = self._make_membership(member, mt)

        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        result = MemberFeeCalculationService().get_current_membership_fee(member)
        self.assertEqual(result["source"], "template")
        self.assertEqual(result["amount"], 45.0)

    # ══════════════════════════════════════════════════
    #  INCOME-BASED MODE
    # ══════════════════════════════════════════════════

    def test_income_based_template_with_suggested_amount(self):
        """Income-Based template with suggested_amount works normally."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "Inc1", suggested_amount=25.0, minimum_amount=5.0,
        )

        values = self._get_template_values(
            frappe.new_doc("Membership Dues Schedule"), mt.name
        )
        self.assertEqual(values["suggested_amount"], 25.0)
        self.assertEqual(values["minimum_amount"], 5.0)

    def test_income_based_template_without_suggested_amount(self):
        """Income-Based template WITHOUT suggested_amount should not throw.

        Core regression test for the 2026-02-08 fix.
        Members declare their own rate; suggested_amount is optional.
        """
        mt, template = self._setup_type_and_template(
            "Income-Based", "Inc2", suggested_amount=None, minimum_amount=10.0,
        )

        # Must not throw
        values = self._get_template_values(
            frappe.new_doc("Membership Dues Schedule"), mt.name
        )
        self.assertEqual(values["suggested_amount"], 0)
        self.assertEqual(values["minimum_amount"], 10.0)

    def test_income_based_template_zero_suggested_amount(self):
        """Income-Based with explicit suggested_amount=0 is treated as absent."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "Inc3", suggested_amount=0, minimum_amount=15.0,
        )

        values = self._get_template_values(
            frappe.new_doc("Membership Dues Schedule"), mt.name
        )
        self.assertEqual(values["suggested_amount"], 0)
        self.assertEqual(values["minimum_amount"], 15.0)

    def test_income_based_schedule_with_member_dues_rate(self):
        """Member's declared dues_rate is preserved when creating an Income-Based schedule."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "Inc4", suggested_amount=None, minimum_amount=5.0,
        )
        member = self._make_member("Inc4")
        membership = self._make_membership(member, mt)

        # Member declared EUR 35/year via the application form
        schedule = self._make_member_schedule(member, membership, template, dues_rate=35.0)
        self.assertEqual(schedule.dues_rate, 35.0)
        self.assertEqual(schedule.contribution_mode, "Income-Based")

    def test_income_based_fee_calculation_uses_fallback(self):
        """Fee calculation falls back to dues_rate when suggested_amount is absent."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "IncFee",
            suggested_amount=None, dues_rate=20.0, minimum_amount=5.0,
        )
        member = self._make_member("Inc5")
        membership = self._make_membership(member, mt)

        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        result = MemberFeeCalculationService().get_current_membership_fee(member)
        self.assertEqual(result["source"], "template")
        self.assertEqual(result["amount"], 20.0)

    def test_income_based_fee_calculation_minimum_fallback(self):
        """Fee calculation falls back to minimum_amount when both suggested and dues_rate are absent."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "IncMin",
            suggested_amount=None, dues_rate=None, minimum_amount=12.0,
        )
        member = self._make_member("Inc6")
        membership = self._make_membership(member, mt)

        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        result = MemberFeeCalculationService().get_current_membership_fee(member)
        self.assertEqual(result["source"], "template")
        self.assertEqual(result["amount"], 12.0)

    def test_income_based_dues_rate_validation_uses_minimum_fallback(self):
        """Dues rate validation calculates dues_rate from minimum_amount when suggested_amount absent."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "IncVal", suggested_amount=None, minimum_amount=8.0,
        )
        member = self._make_member("Inc7")
        membership = self._make_membership(member, mt)

        # Create schedule without explicit dues_rate - validation should calculate it
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.is_template = 0
        schedule.schedule_name = f"ValTest-{frappe.generate_hash(length=6)}"
        schedule.member = member.name
        schedule.membership = membership.name
        schedule.membership_type = mt.name
        schedule.template_reference = template.name
        schedule.contribution_mode = "Income-Based"
        schedule.billing_frequency = "Annual"
        schedule.minimum_amount = 8.0
        schedule.status = "Active"
        schedule.auto_generate = 0
        # dues_rate intentionally left as None
        schedule.save()
        self.track_doc("Membership Dues Schedule", schedule.name)

        # Should have calculated dues_rate from minimum_amount fallback (8.0 * 1.0 multiplier)
        self.assertIsNotNone(schedule.dues_rate)
        self.assertEqual(schedule.dues_rate, 8.0)

    def test_income_based_progressive_with_suggested_amount(self):
        """Progressive Income-Based mode works with suggested_amount as base."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "IncProg",
            suggested_amount=30.0, minimum_amount=5.0,
            income_calculation_type="Progressive",
            progressive_reference_income=3500,
            progressive_lower_threshold=2200,
        )

        from verenigingen.services.billing.progressive_dues_service import (
            get_progressive_dues_service,
        )

        result = get_progressive_dues_service().calculate_progressive_dues(
            template, monthly_income=3500
        )
        self.assertAlmostEqual(result.multiplier, 1.0, places=2)
        self.assertAlmostEqual(result.suggested_dues, 30.0, places=2)

    def test_income_based_progressive_without_suggested_amount(self):
        """Progressive mode with no suggested_amount uses 0 as base, producing 0 dues."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "IncProg0",
            suggested_amount=None, minimum_amount=5.0,
            income_calculation_type="Progressive",
            progressive_reference_income=3500,
            progressive_lower_threshold=2200,
        )

        from verenigingen.services.billing.progressive_dues_service import (
            get_progressive_dues_service,
        )

        result = get_progressive_dues_service().calculate_progressive_dues(
            template, monthly_income=3500
        )
        # No base -> 0 dues; caller should use minimum or member-declared rate
        self.assertEqual(result.suggested_dues, 0)

    # ══════════════════════════════════════════════════
    #  FLEXIBLE MODE
    # ══════════════════════════════════════════════════

    def test_flexible_template_with_suggested_amount(self):
        """Flexible mode with suggested_amount works normally."""
        mt, template = self._setup_type_and_template(
            "Flexible", "Flex1",
            suggested_amount=20.0, minimum_amount=5.0,
            suggestion_multipliers="1,1.25,1.5,2,3",
            default_multiplier=1.0,
            allow_custom_amount=1,
        )

        values = self._get_template_values(
            frappe.new_doc("Membership Dues Schedule"), mt.name
        )
        self.assertEqual(values["suggested_amount"], 20.0)
        self.assertEqual(values["minimum_amount"], 5.0)

    def test_flexible_template_without_suggested_amount(self):
        """Flexible mode without suggested_amount does not throw."""
        mt, template = self._setup_type_and_template(
            "Flexible", "Flex2",
            suggested_amount=None, minimum_amount=10.0,
            suggestion_multipliers="1,1.5,2",
            default_multiplier=1.0,
            allow_custom_amount=1,
        )

        values = self._get_template_values(
            frappe.new_doc("Membership Dues Schedule"), mt.name
        )
        self.assertEqual(values["suggested_amount"], 0)
        self.assertEqual(values["minimum_amount"], 10.0)

    def test_flexible_schedule_with_custom_amount(self):
        """Flexible schedule preserves a member's custom-selected amount."""
        mt, template = self._setup_type_and_template(
            "Flexible", "Flex3", suggested_amount=20.0, minimum_amount=5.0,
        )
        member = self._make_member("Flex3")
        membership = self._make_membership(member, mt)

        schedule = self._make_member_schedule(member, membership, template, dues_rate=40.0)
        self.assertEqual(schedule.dues_rate, 40.0)
        self.assertEqual(schedule.contribution_mode, "Flexible")

    def test_flexible_fee_calculation_returns_template_amount(self):
        """Fee calculation for Flexible returns suggested_amount from template."""
        mt, template = self._setup_type_and_template(
            "Flexible", "FlexFee", suggested_amount=22.0, minimum_amount=5.0,
        )
        member = self._make_member("Flex4")
        membership = self._make_membership(member, mt)

        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        result = MemberFeeCalculationService().get_current_membership_fee(member)
        self.assertEqual(result["source"], "template")
        self.assertEqual(result["amount"], 22.0)

    def test_flexible_dues_rate_fallback_to_minimum(self):
        """Flexible schedule without suggested_amount falls back to minimum for dues_rate."""
        mt, template = self._setup_type_and_template(
            "Flexible", "FlexMin", suggested_amount=None, minimum_amount=7.0,
        )
        member = self._make_member("Flex5")
        membership = self._make_membership(member, mt)

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.is_template = 0
        schedule.schedule_name = f"FlexVal-{frappe.generate_hash(length=6)}"
        schedule.member = member.name
        schedule.membership = membership.name
        schedule.membership_type = mt.name
        schedule.template_reference = template.name
        schedule.contribution_mode = "Flexible"
        schedule.billing_frequency = "Annual"
        schedule.minimum_amount = 7.0
        schedule.status = "Active"
        schedule.auto_generate = 0
        # dues_rate intentionally left as None
        schedule.save()
        self.track_doc("Membership Dues Schedule", schedule.name)

        self.assertIsNotNone(schedule.dues_rate)
        self.assertEqual(schedule.dues_rate, 7.0)

    # ══════════════════════════════════════════════════
    #  CROSS-MODE: application_payments amount resolution
    # ══════════════════════════════════════════════════

    def test_calculate_amount_fixed_with_suggested(self):
        """calculate_membership_amount_with_discounts works for Fixed mode."""
        mt, template = self._setup_type_and_template(
            "Fixed", "CalcFix", suggested_amount=50.0,
        )

        from verenigingen.utils.application_payments import (
            calculate_membership_amount_with_discounts,
        )

        result = calculate_membership_amount_with_discounts(mt, {})
        self.assertEqual(result["base_amount"], 50.0)

    def test_calculate_amount_income_based_no_suggested(self):
        """calculate_membership_amount_with_discounts handles Income-Based without suggested_amount."""
        mt, template = self._setup_type_and_template(
            "Income-Based", "CalcInc",
            suggested_amount=None, dues_rate=None, minimum_amount=15.0,
        )

        from verenigingen.utils.application_payments import (
            calculate_membership_amount_with_discounts,
        )

        result = calculate_membership_amount_with_discounts(mt, {})
        # Falls back to minimum_amount
        self.assertEqual(result["base_amount"], 15.0)

    def test_calculate_amount_flexible_with_dues_rate_fallback(self):
        """calculate_membership_amount_with_discounts falls back to dues_rate."""
        mt, template = self._setup_type_and_template(
            "Flexible", "CalcFlex",
            suggested_amount=None, dues_rate=18.0, minimum_amount=5.0,
        )

        from verenigingen.utils.application_payments import (
            calculate_membership_amount_with_discounts,
        )

        result = calculate_membership_amount_with_discounts(mt, {})
        self.assertEqual(result["base_amount"], 18.0)

    # ══════════════════════════════════════════════════
    #  CROSS-MODE: member custom override takes priority
    # ══════════════════════════════════════════════════

    def test_member_custom_override_trumps_template(self):
        """Member's dues_rate override always takes priority over any template value."""
        mt, template = self._setup_type_and_template(
            "Fixed", "Override", suggested_amount=50.0,
        )
        member = self._make_member("Over")
        member.dues_rate = 75.0
        member.save()
        membership = self._make_membership(member, mt)

        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        result = MemberFeeCalculationService().get_current_membership_fee(member)
        self.assertEqual(result["source"], "custom_override")
        self.assertEqual(result["amount"], 75.0)
