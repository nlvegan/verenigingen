# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for application/membership_application_service.py.

Drives the MembershipApplicationService against REAL Membership Type +
dues-schedule-template documents to verify:
- template contribution-value resolution (and empty-dict on bad input)
- listing active types with contribution options
- dues-schedule formatting for the frontend (+ fallback path)
- contribution validation against min/max constraints
- income-based contribution calculation across intervals
- private contribution-settings builder for Fixed/Income-Based/Flexible modes
- billing-frequency display mapping
"""

from verenigingen.services.member.application.membership_application_service import (
    MembershipApplicationService,
    get_membership_application_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipApplicationService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MembershipApplicationService()
        self.mt = self.create_test_membership_type(membership_type_name="AppSvcType", amount=20.0)

    # --- get_template_contribution_values -------------------------------

    def test_template_values_resolved(self):
        values = self.service.get_template_contribution_values(self.mt.name)
        self.assertEqual(values["billing_frequency"], "Annual")
        self.assertGreater(values["suggested_contribution"], 0)
        self.assertIn("allow_custom_amounts", values)
        self.assertIn("invoice_days_before", values)

    def test_template_values_empty_on_bad_type(self):
        """Unknown membership type yields empty dict (caught internally)."""
        values = self.service.get_template_contribution_values("Nonexistent-Type-999999")
        self.assertEqual(values, {})

    # --- get_membership_types_with_contributions ------------------------

    def test_lists_active_type_with_contribution_options(self):
        types = self.service.get_membership_types_with_contributions()
        names = [t["name"] for t in types]
        self.assertIn(self.mt.name, names)
        mine = next(t for t in types if t["name"] == self.mt.name)
        self.assertIn("contribution_options", mine)
        self.assertGreater(mine["amount"], 0)
        self.assertEqual(mine["billing_frequency"], "Annual")

    # --- get_dues_schedules ---------------------------------------------

    def test_dues_schedules_returns_formatted_template(self):
        result = self.service.get_dues_schedules(self.mt.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["membership_type"], self.mt.name)
        self.assertGreaterEqual(len(result["schedules"]), 1)
        sched = result["schedules"][0]
        self.assertIn("billing_display", sched)
        self.assertIn("contribution_settings", sched)
        # currency falls back to the schedule's value (site default), never empty
        self.assertTrue(sched["currency"])

    # --- validate_contribution ------------------------------------------

    def test_validate_contribution_within_range(self):
        # suggested amount comes from the template (== type amount, 20)
        result = self.service.validate_contribution(self.mt.name, 20.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["amount"], 20.0)
        self.assertIn("min_amount", result)
        self.assertIn("max_amount", result)

    def test_validate_contribution_below_minimum(self):
        result = self.service.validate_contribution(self.mt.name, 0.01)
        self.assertFalse(result["valid"])
        self.assertIn("minimum", result["error"].lower())

    def test_validate_contribution_above_maximum(self):
        # max defaults to suggested * 10, so a huge number must fail
        result = self.service.validate_contribution(self.mt.name, 999999.0)
        self.assertFalse(result["valid"])
        self.assertIn("maximum", result["error"].lower())

    def test_validate_contribution_nonexistent_type(self):
        result = self.service.validate_contribution("Nonexistent-Type-999999", 20.0)
        self.assertFalse(result["valid"])
        self.assertIn("not found", result["error"])

    # --- calculate_income_contribution ----------------------------------

    def test_income_calculation_monthly(self):
        result = self.service.calculate_income_contribution(self.mt.name, 2000, interval="monthly")
        self.assertTrue(result["success"])
        self.assertEqual(result["payment_interval"], "monthly")
        self.assertEqual(result["monthly_income"], 2000)
        self.assertGreaterEqual(result["calculated_amount"], result["minimum_amount"])

    def test_income_calculation_quarterly_multiplies(self):
        monthly = self.service.calculate_income_contribution(self.mt.name, 3000, interval="monthly")
        quarterly = self.service.calculate_income_contribution(self.mt.name, 3000, interval="quarterly")
        # quarterly base = monthly base * 3 (before the minimum floor kicks in)
        self.assertAlmostEqual(quarterly["base_monthly_amount"], monthly["base_monthly_amount"], places=2)
        self.assertGreaterEqual(quarterly["calculated_amount"], monthly["calculated_amount"])

    def test_income_calculation_floor_for_zero_income(self):
        """Zero income still yields at least the minimum amount."""
        result = self.service.calculate_income_contribution(self.mt.name, 0, interval="monthly")
        self.assertTrue(result["success"])
        self.assertEqual(result["calculated_amount"], result["minimum_amount"])

    # --- _build_contribution_settings -----------------------------------

    def test_build_settings_fixed(self):
        settings = self.service._build_contribution_settings(
            "Fixed", {"dues_rate": 50, "minimum_amount": 25, "suggested_amount": 50}
        )
        self.assertEqual(settings["mode"], "Fixed")
        self.assertEqual(settings["minimum"], 25)
        self.assertEqual(settings["suggested"], 50)

    def test_build_settings_income_based_percentage(self):
        settings = self.service._build_contribution_settings(
            "Income-Based",
            {"dues_rate": 50, "income_calculation_type": "Percentage", "income_percentage": 0.6},
        )
        self.assertEqual(settings["calculation_type"], "Percentage")
        self.assertEqual(settings["percentage"], 0.6)

    def test_build_settings_income_based_progressive(self):
        settings = self.service._build_contribution_settings(
            "Income-Based",
            {
                "dues_rate": 50,
                "income_calculation_type": "Progressive",
                "progressive_reference_income": 4000,
                "progressive_lower_threshold": 2500,
            },
        )
        self.assertEqual(settings["calculation_type"], "Progressive")
        self.assertEqual(settings["progressive"]["reference_income"], 4000)
        self.assertEqual(settings["progressive"]["lower_threshold"], 2500)

    def test_build_settings_flexible_builds_suggestions(self):
        settings = self.service._build_contribution_settings(
            "Flexible",
            {"dues_rate": 10, "suggestion_multipliers": "1,2,3", "default_multiplier": 2},
        )
        self.assertEqual(len(settings["suggestions"]), 3)
        amounts = [s["amount"] for s in settings["suggestions"]]
        self.assertEqual(amounts, [10, 20, 30])
        default = next(s for s in settings["suggestions"] if s["is_default"])
        self.assertEqual(default["multiplier"], 2)

    def test_build_settings_flexible_handles_bad_multipliers(self):
        """Non-numeric multipliers fall back to the default tier set."""
        settings = self.service._build_contribution_settings(
            "Flexible", {"dues_rate": 10, "suggestion_multipliers": "abc,def"}
        )
        # falls back to [1, 1.25, 1.5, 2]
        self.assertEqual(len(settings["suggestions"]), 4)

    # --- _get_billing_display -------------------------------------------

    def test_billing_display_mapping(self):
        self.assertEqual(self.service._get_billing_display("Monthly"), "per month")
        self.assertEqual(self.service._get_billing_display("Annual"), "per year")
        self.assertEqual(self.service._get_billing_display("Quarterly"), "per quarter")
        # Unknown values pass through unchanged
        self.assertEqual(self.service._get_billing_display("Weird"), "Weird")

    # --- singleton accessor ---------------------------------------------

    def test_singleton_accessor_returns_same_instance(self):
        a = get_membership_application_service()
        b = get_membership_application_service()
        self.assertIs(a, b)
        self.assertIsInstance(a, MembershipApplicationService)
