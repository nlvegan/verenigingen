# -*- coding: utf-8 -*-
"""
Unit tests for verenigingen/services/billing/progressive_dues_service.py

ProgressiveDuesService is a pure-calculation service. It only READS attributes
from the schedule doc (via getattr / attribute access), so a frappe._dict stand-in
faithfully exercises the real arithmetic. No business logic is mocked.

Asserts EXACT multipliers / suggested dues and exercises boundary conditions
(invalid config, income below threshold, above reference, validation throws).
"""

import frappe

from verenigingen.services.billing.progressive_dues_service import (
    ProgressiveDuesResult,
    get_progressive_dues_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _schedule(**kwargs):
    """Build an attribute-bearing stand-in for a Membership Dues Schedule.

    The service reads (never writes) these fields, so a _dict is a faithful
    representation of the real document's relevant state.
    """
    defaults = {
        "name": "TEST-PROG-SCHED",
        "contribution_mode": "Income-Based",
        "income_calculation_type": "Progressive",
        "is_template": 0,
        "suggested_amount": 0,
        "progressive_reference_income": None,
        "progressive_lower_threshold": None,
    }
    defaults.update(kwargs)
    return frappe._dict(defaults)


class TestProgressiveDuesCalculation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_progressive_dues_service()

    def test_income_at_reference_is_full_dues(self):
        # reference 3000, threshold 1000, base 100. income==reference -> multiplier 1.0
        sched = _schedule(progressive_reference_income=3000, progressive_lower_threshold=1000)
        result = self.service.calculate_progressive_dues(sched, monthly_income=3000, base_dues=100)
        self.assertIsInstance(result, ProgressiveDuesResult)
        self.assertEqual(result.multiplier, 1.0)
        self.assertEqual(result.percentage, 100.0)
        self.assertEqual(result.suggested_dues, 100.0)
        self.assertEqual(result.base_dues, 100)

    def test_income_at_lower_threshold_is_zero_dues(self):
        # income == lower_threshold -> multiplier 0
        sched = _schedule(progressive_reference_income=3000, progressive_lower_threshold=1000)
        result = self.service.calculate_progressive_dues(sched, monthly_income=1000, base_dues=100)
        self.assertEqual(result.multiplier, 0.0)
        self.assertEqual(result.percentage, 0.0)
        self.assertEqual(result.suggested_dues, 0.0)

    def test_income_midway_is_half_dues(self):
        # range 1000..3000 (width 2000), income 2000 -> (2000-1000)/2000 = 0.5
        sched = _schedule(progressive_reference_income=3000, progressive_lower_threshold=1000)
        result = self.service.calculate_progressive_dues(sched, monthly_income=2000, base_dues=100)
        self.assertEqual(result.multiplier, 0.5)
        self.assertEqual(result.percentage, 50.0)
        self.assertEqual(result.suggested_dues, 50.0)

    def test_income_below_threshold_floors_at_zero(self):
        # income below lower_threshold -> negative raw multiplier floored to 0
        sched = _schedule(progressive_reference_income=3000, progressive_lower_threshold=1000)
        result = self.service.calculate_progressive_dues(sched, monthly_income=500, base_dues=100)
        self.assertEqual(result.multiplier, 0.0)
        self.assertEqual(result.suggested_dues, 0.0)

    def test_income_above_reference_no_ceiling(self):
        # income 5000 -> (5000-1000)/2000 = 2.0 -> dues 200 (solidarity)
        sched = _schedule(progressive_reference_income=3000, progressive_lower_threshold=1000)
        result = self.service.calculate_progressive_dues(sched, monthly_income=5000, base_dues=100)
        self.assertEqual(result.multiplier, 2.0)
        self.assertEqual(result.percentage, 200.0)
        self.assertEqual(result.suggested_dues, 200.0)

    def test_invalid_config_reference_le_threshold_returns_base(self):
        # reference <= threshold -> invalid config -> returns base unchanged at 100%
        # (logged via logger.warning, which is NOT an Error Log row)
        sched = _schedule(progressive_reference_income=1000, progressive_lower_threshold=1000)
        result = self.service.calculate_progressive_dues(sched, monthly_income=5000, base_dues=80)
        self.assertEqual(result.multiplier, 1.0)
        self.assertEqual(result.percentage, 100)
        self.assertEqual(result.suggested_dues, 80)
        self.assertEqual(result.base_dues, 80)

    def test_base_dues_defaults_to_suggested_amount(self):
        # base_dues None -> uses suggested_amount (42)
        sched = _schedule(
            progressive_reference_income=2000,
            progressive_lower_threshold=0,
            suggested_amount=42,
        )
        result = self.service.calculate_progressive_dues(sched, monthly_income=1000)  # 50%
        self.assertEqual(result.base_dues, 42)
        self.assertEqual(result.multiplier, 0.5)
        self.assertEqual(result.suggested_dues, 21.0)

    def test_rounding_to_two_decimals(self):
        # multiplier 1/3, base 100 -> 33.33 (rounded)
        sched = _schedule(progressive_reference_income=3000, progressive_lower_threshold=0)
        result = self.service.calculate_progressive_dues(sched, monthly_income=1000, base_dues=100)
        self.assertEqual(result.multiplier, 0.3333)  # rounded to 4 places
        self.assertEqual(result.suggested_dues, 33.33)


class TestProgressiveValidation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_progressive_dues_service()

    def test_non_income_based_mode_skips_validation(self):
        sched = _schedule(contribution_mode="Fixed", is_template=1)
        # Should NOT raise even though progressive fields are missing
        self.service.validate_progressive_configuration(sched)

    def test_percentage_calc_type_skips_validation(self):
        sched = _schedule(income_calculation_type="Percentage", is_template=1)
        self.service.validate_progressive_configuration(sched)

    def test_non_template_progressive_skips_strict_validation(self):
        # Non-template schedules don't require full config
        sched = _schedule(is_template=0, progressive_reference_income=None)
        self.service.validate_progressive_configuration(sched)

    def test_template_requires_reference_income(self):
        sched = _schedule(is_template=1, progressive_reference_income=0, progressive_lower_threshold=500)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.validate_progressive_configuration(sched)
        self.assertIn("Reference Income", str(ctx.exception))

    def test_template_requires_lower_threshold(self):
        sched = _schedule(is_template=1, progressive_reference_income=3000, progressive_lower_threshold=None)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.validate_progressive_configuration(sched)
        self.assertIn("Lower Income Threshold", str(ctx.exception))

    def test_template_threshold_must_be_below_reference(self):
        sched = _schedule(is_template=1, progressive_reference_income=2000, progressive_lower_threshold=2500)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.validate_progressive_configuration(sched)
        self.assertIn("must be less than", str(ctx.exception))

    def test_valid_template_config_passes(self):
        sched = _schedule(is_template=1, progressive_reference_income=3000, progressive_lower_threshold=1000)
        # Should not raise
        self.service.validate_progressive_configuration(sched)


class TestIncomeBracketDescription(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_progressive_dues_service()
        self.sched = _schedule(progressive_reference_income=2000, progressive_lower_threshold=800)

    def test_below_minimum_threshold(self):
        self.assertEqual(
            self.service.get_income_bracket_description(self.sched, 800),
            "Below minimum threshold - minimum dues apply",
        )

    def test_below_average(self):
        # < reference * 0.75 == 1500
        self.assertEqual(
            self.service.get_income_bracket_description(self.sched, 1200),
            "Below average income - reduced dues",
        )

    def test_around_average(self):
        # between 0.75*ref (1500) and 1.25*ref (2500)
        self.assertEqual(
            self.service.get_income_bracket_description(self.sched, 2000),
            "Around average income - standard dues",
        )

    def test_above_average(self):
        # > 1.25 * reference (2500)
        self.assertEqual(
            self.service.get_income_bracket_description(self.sched, 4000),
            "Above average income - solidarity contribution",
        )


class TestDuesForIncomeRange(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_progressive_dues_service()

    def test_range_generates_steps_and_endpoints(self):
        sched = _schedule(
            progressive_reference_income=2000, progressive_lower_threshold=0, suggested_amount=100
        )
        rows = self.service.calculate_dues_for_income_range(sched, 0, 2000, steps=5)
        self.assertEqual(len(rows), 5)
        # First point income 0 -> 0 dues; last point 2000 -> full 100
        self.assertEqual(rows[0]["income"], 0.0)
        self.assertEqual(rows[0]["suggested_dues"], 0.0)
        self.assertEqual(rows[-1]["income"], 2000.0)
        self.assertEqual(rows[-1]["suggested_dues"], 100.0)
        # Midpoint income 1000 -> 50%
        self.assertEqual(rows[2]["income"], 1000.0)
        self.assertEqual(rows[2]["multiplier"], 0.5)

    def test_single_step_no_division_by_zero(self):
        sched = _schedule(
            progressive_reference_income=2000, progressive_lower_threshold=0, suggested_amount=100
        )
        rows = self.service.calculate_dues_for_income_range(sched, 500, 1500, steps=1)
        self.assertEqual(len(rows), 1)
        # step_size 0 -> income == income_min
        self.assertEqual(rows[0]["income"], 500.0)
