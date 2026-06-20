# -*- coding: utf-8 -*-
"""
Coverage tests for services/member/application/membership_application_service.py

Most methods are pure business logic operating on dicts/strings (contribution
settings building, billing display, income calculation, validation). These are
exercised directly. DB-backed methods (validate_contribution,
calculate_income_contribution) are exercised against a real Membership Type.
"""

import frappe

from verenigingen.services.member.application.membership_application_service import (
    MembershipApplicationService,
    get_membership_application_service,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestBuildContributionSettings(VereningingenTestCase):
    """_build_contribution_settings() — pure dict transformation per mode."""

    def setUp(self):
        super().setUp()
        self.service = MembershipApplicationService()

    def test_fixed_mode_uses_dues_rate_fallback(self):
        """Fixed mode: minimum/suggested fall back to dues_rate when not set."""
        settings = self.service._build_contribution_settings(
            "Fixed", {"dues_rate": 20, "minimum_amount": None, "suggested_amount": None}
        )
        self.assertEqual(settings["mode"], "Fixed")
        self.assertEqual(settings["minimum"], 20)
        self.assertEqual(settings["suggested"], 20)

    def test_fixed_mode_prefers_explicit_amounts(self):
        settings = self.service._build_contribution_settings(
            "Fixed", {"dues_rate": 20, "minimum_amount": 5, "suggested_amount": 15}
        )
        self.assertEqual(settings["minimum"], 5)
        self.assertEqual(settings["suggested"], 15)

    def test_income_based_percentage(self):
        settings = self.service._build_contribution_settings(
            "Income-Based",
            {
                "dues_rate": 0,
                "income_calculation_type": "Percentage",
                "income_percentage": 0.6,
                "progressive_formula_description": "desc",
            },
        )
        self.assertEqual(settings["calculation_type"], "Percentage")
        self.assertEqual(settings["percentage"], 0.6)
        self.assertEqual(settings["description"], "desc")

    def test_income_based_percentage_default(self):
        """Missing income_percentage falls back to 0.75."""
        settings = self.service._build_contribution_settings(
            "Income-Based", {"income_calculation_type": "Percentage", "income_percentage": None}
        )
        self.assertEqual(settings["percentage"], 0.75)

    def test_income_based_progressive(self):
        settings = self.service._build_contribution_settings(
            "Income-Based",
            {
                "income_calculation_type": "Progressive",
                "progressive_reference_income": 4000,
                "progressive_lower_threshold": 2000,
            },
        )
        self.assertEqual(settings["calculation_type"], "Progressive")
        self.assertEqual(settings["progressive"]["reference_income"], 4000)
        self.assertEqual(settings["progressive"]["lower_threshold"], 2000)

    def test_income_based_progressive_defaults(self):
        settings = self.service._build_contribution_settings(
            "Income-Based",
            {"income_calculation_type": "Progressive"},
        )
        self.assertEqual(settings["progressive"]["reference_income"], 3500)
        self.assertEqual(settings["progressive"]["lower_threshold"], 2200)

    def test_flexible_builds_suggestions(self):
        settings = self.service._build_contribution_settings(
            "Flexible",
            {
                "dues_rate": 10,
                "suggestion_multipliers": "1,1.5,2",
                "default_multiplier": 1.5,
                "allow_custom_amount": 1,
            },
        )
        suggestions = settings["suggestions"]
        self.assertEqual(len(suggestions), 3)
        # base 10 * multipliers
        self.assertEqual([s["amount"] for s in suggestions], [10, 15, 20])
        # multiplier 1 -> "Minimum", others -> percentage
        self.assertEqual(suggestions[0]["label"], "Minimum")
        self.assertEqual(suggestions[1]["label"], "150%")
        # default flagged correctly
        self.assertTrue(suggestions[1]["is_default"])
        self.assertFalse(suggestions[0]["is_default"])
        self.assertTrue(settings["allow_custom"])
        self.assertEqual(settings["default_multiplier"], 1.5)

    def test_flexible_malformed_multipliers_fall_back(self):
        """A non-numeric multiplier string falls back to the default list."""
        settings = self.service._build_contribution_settings(
            "Flexible",
            {"dues_rate": 4, "suggestion_multipliers": "abc,def", "default_multiplier": 1},
        )
        # Fallback list is [1, 1.25, 1.5, 2]
        self.assertEqual([s["multiplier"] for s in settings["suggestions"]], [1, 1.25, 1.5, 2])


class TestGetBillingDisplay(VereningingenTestCase):
    """_get_billing_display() — frequency to human string."""

    def setUp(self):
        super().setUp()
        self.service = MembershipApplicationService()

    def test_known_frequencies(self):
        self.assertEqual(self.service._get_billing_display("Monthly"), "per month")
        self.assertEqual(self.service._get_billing_display("Quarterly"), "per quarter")
        self.assertEqual(self.service._get_billing_display("Semi-Annual"), "every 6 months")
        self.assertEqual(self.service._get_billing_display("Annual"), "per year")

    def test_unknown_frequency_passthrough(self):
        """Unknown frequencies are returned verbatim."""
        self.assertEqual(self.service._get_billing_display("Weekly"), "Weekly")


class TestValidateContribution(VereningingenTestCase):
    """validate_contribution() — constraint checks against a real type."""

    def setUp(self):
        super().setUp()
        self.service = MembershipApplicationService()
        self.mt = self.create_test_membership_type(minimum_amount=20.0)

    def test_amount_below_minimum_rejected(self):
        result = self.service.validate_contribution(self.mt.name, 0.01)
        self.assertFalse(result["valid"])
        self.assertIn("minimum", result["error"].lower())

    def test_amount_above_maximum_rejected(self):
        """An absurdly large amount exceeds the computed maximum."""
        result = self.service.validate_contribution(self.mt.name, 9_999_999)
        self.assertFalse(result["valid"])
        self.assertIn("maximum", result["error"].lower())

    def test_reasonable_amount_valid(self):
        result = self.service.validate_contribution(self.mt.name, 25.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["amount"], 25.0)
        self.assertIn("min_amount", result)
        self.assertIn("max_amount", result)

    def test_nonexistent_type_returns_error(self):
        result = self.service.validate_contribution("No Such Type XYZ", 10)
        self.assertFalse(result["valid"])
        self.assertIn("not found", result["error"].lower())


class TestCalculateIncomeContribution(VereningingenTestCase):
    """calculate_income_contribution() — income-based suggestion math."""

    def setUp(self):
        super().setUp()
        self.service = MembershipApplicationService()
        self.mt = self.create_test_membership_type(minimum_amount=20.0)

    def test_monthly_calculation(self):
        result = self.service.calculate_income_contribution(self.mt.name, 2000, interval="monthly")
        self.assertTrue(result["success"])
        self.assertEqual(result["payment_interval"], "monthly")
        self.assertEqual(result["monthly_income"], 2000)
        # base = income * (rate/100); final >= minimum
        self.assertGreaterEqual(result["calculated_amount"], result["minimum_amount"])

    def test_annual_interval_multiplies(self):
        """Annual interval multiplies the monthly base by 12."""
        monthly = self.service.calculate_income_contribution(self.mt.name, 3000, interval="monthly")
        annual = self.service.calculate_income_contribution(self.mt.name, 3000, interval="annually")
        self.assertTrue(annual["success"])
        # base monthly amount is identical; annual calculated should be ~12x the base
        self.assertAlmostEqual(
            annual["base_monthly_amount"], monthly["base_monthly_amount"], places=4
        )
        self.assertGreater(annual["calculated_amount"], monthly["calculated_amount"])

    def test_quarterly_minimum_scaled(self):
        result = self.service.calculate_income_contribution(self.mt.name, 100, interval="quarterly")
        self.assertTrue(result["success"])
        # With tiny income, final equals the (scaled) minimum.
        self.assertEqual(result["calculated_amount"], result["minimum_amount"])

    def test_nonexistent_type_returns_error_dict(self):
        # The except-branch logs the failure before returning the error dict.
        self.expectErrorLog("Error calculating suggested contribution")
        result = self.service.calculate_income_contribution("No Such Type XYZ", 1000)
        self.assertIn("error", result)


class TestGetDuesSchedulesFormatting(VereningingenTestCase):
    """get_dues_schedules() formats templates / falls back to default template."""

    def setUp(self):
        super().setUp()
        self.service = MembershipApplicationService()

    def test_returns_schedules_for_type_with_template(self):
        mt = self.create_test_membership_type()
        result = self.service.get_dues_schedules(mt.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["membership_type"], mt.name)
        self.assertIsInstance(result["schedules"], list)
        # The auto-created Active template should surface as a formatted schedule.
        self.assertTrue(result["schedules"])
        first = result["schedules"][0]
        for key in ("name", "billing_frequency", "billing_display", "amount", "currency"):
            self.assertIn(key, first)

    def test_nonexistent_type_handled(self):
        """A nonexistent membership type yields a failure result, not a raise."""
        result = self.service.get_dues_schedules("No Such Membership Type XYZ")
        self.assertFalse(result["success"])
        self.assertIn("error", result)


class TestServiceSingleton(VereningingenTestCase):
    """get_membership_application_service() returns a stable singleton."""

    def test_singleton_identity(self):
        a = get_membership_application_service()
        b = get_membership_application_service()
        self.assertIs(a, b)
        self.assertIsInstance(a, MembershipApplicationService)
