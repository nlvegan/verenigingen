# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ProgressiveDuesService.

Tests income-based progressive dues calculation including:
- Linear sliding scale formula
- Edge cases (below threshold, at reference, above reference)
- Configuration validation
- Income bracket descriptions
"""

from unittest.mock import MagicMock

import frappe

from verenigingen.services.billing.progressive_dues_service import (
    ProgressiveDuesResult,
    ProgressiveDuesService,
    get_progressive_dues_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestProgressiveDuesService(EnhancedTestCase):
    """Test suite for ProgressiveDuesService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_progressive_dues_service()

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = ProgressiveDuesService()
        self.assertEqual(service.service_name, "ProgressiveDuesService")
        self.assertIsNotNone(service.logger)

    def test_get_progressive_dues_service_returns_instance(self):
        """Test that factory function returns service instance."""
        service = get_progressive_dues_service()
        self.assertIsInstance(service, ProgressiveDuesService)


class TestProgressiveDuesCalculation(EnhancedTestCase):
    """Test suite for progressive dues calculation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_progressive_dues_service()

        # Standard test configuration:
        # - Lower threshold: €1000 (0% multiplier)
        # - Reference income: €3000 (100% multiplier)
        # - Base dues: €30
        self.mock_schedule = MagicMock()
        self.mock_schedule.name = "Test-Schedule"
        self.mock_schedule.progressive_reference_income = 3000
        self.mock_schedule.progressive_lower_threshold = 1000
        self.mock_schedule.suggested_amount = 30

    def test_calculate_at_reference_income(self):
        """Test calculation when income equals reference income (100% multiplier)."""
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=3000
        )

        self.assertIsInstance(result, ProgressiveDuesResult)
        self.assertEqual(result.multiplier, 1.0)
        self.assertEqual(result.percentage, 100.0)
        self.assertEqual(result.suggested_dues, 30.0)
        self.assertEqual(result.base_dues, 30.0)

    def test_calculate_at_lower_threshold(self):
        """Test calculation when income equals lower threshold (0% multiplier)."""
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=1000
        )

        self.assertEqual(result.multiplier, 0.0)
        self.assertEqual(result.percentage, 0.0)
        self.assertEqual(result.suggested_dues, 0.0)

    def test_calculate_below_lower_threshold(self):
        """Test calculation when income is below lower threshold (floored at 0)."""
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=500
        )

        # Should be floored at 0, not negative
        self.assertEqual(result.multiplier, 0.0)
        self.assertEqual(result.suggested_dues, 0.0)

    def test_calculate_midpoint_income(self):
        """Test calculation at midpoint between threshold and reference."""
        # Midpoint is (1000 + 3000) / 2 = 2000, which gives 50% multiplier
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=2000
        )

        self.assertEqual(result.multiplier, 0.5)
        self.assertEqual(result.percentage, 50.0)
        self.assertEqual(result.suggested_dues, 15.0)  # 30 * 0.5

    def test_calculate_above_reference_income(self):
        """Test calculation when income exceeds reference (solidarity contribution)."""
        # Income of 5000 with range 1000-3000:
        # multiplier = (5000 - 1000) / (3000 - 1000) = 4000 / 2000 = 2.0
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=5000
        )

        self.assertEqual(result.multiplier, 2.0)
        self.assertEqual(result.percentage, 200.0)
        self.assertEqual(result.suggested_dues, 60.0)  # 30 * 2.0

    def test_calculate_with_custom_base_dues(self):
        """Test calculation with explicit base_dues parameter."""
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=3000, base_dues=50
        )

        self.assertEqual(result.multiplier, 1.0)
        self.assertEqual(result.suggested_dues, 50.0)
        self.assertEqual(result.base_dues, 50.0)

    def test_calculate_with_invalid_configuration(self):
        """Test calculation with invalid config (reference <= threshold)."""
        invalid_schedule = MagicMock()
        invalid_schedule.name = "Invalid-Schedule"
        invalid_schedule.progressive_reference_income = 1000
        invalid_schedule.progressive_lower_threshold = 1000  # Equal to reference
        invalid_schedule.suggested_amount = 30

        result = self.service.calculate_progressive_dues(
            invalid_schedule, monthly_income=2000
        )

        # Should return 1.0 multiplier (fallback)
        self.assertEqual(result.multiplier, 1.0)
        self.assertEqual(result.suggested_dues, 30.0)

    def test_calculate_rounding(self):
        """Test that results are properly rounded."""
        # Use income that produces non-round multiplier
        # (1500 - 1000) / (3000 - 1000) = 500 / 2000 = 0.25
        result = self.service.calculate_progressive_dues(
            self.mock_schedule, monthly_income=1500
        )

        self.assertEqual(result.multiplier, 0.25)
        self.assertEqual(result.suggested_dues, 7.5)  # 30 * 0.25


class TestProgressiveDuesValidation(EnhancedTestCase):
    """Test suite for progressive configuration validation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_progressive_dues_service()

    def test_validate_skips_non_progressive_mode(self):
        """Test that validation is skipped for non-progressive contribution modes."""
        mock_schedule = MagicMock()
        mock_schedule.contribution_mode = "Fixed"

        # Should not raise
        self.service.validate_progressive_configuration(mock_schedule)

    def test_validate_requires_reference_income_for_templates(self):
        """Test that templates require reference income."""
        mock_schedule = MagicMock()
        mock_schedule.contribution_mode = "Income-Based"
        mock_schedule.income_calculation_type = "Progressive"
        mock_schedule.is_template = True
        mock_schedule.progressive_reference_income = None
        mock_schedule.progressive_lower_threshold = 1000

        with self.assertRaises(frappe.ValidationError):
            self.service.validate_progressive_configuration(mock_schedule)

    def test_validate_requires_lower_threshold_for_templates(self):
        """Test that templates require lower threshold."""
        mock_schedule = MagicMock()
        mock_schedule.contribution_mode = "Income-Based"
        mock_schedule.income_calculation_type = "Progressive"
        mock_schedule.is_template = True
        mock_schedule.progressive_reference_income = 3000
        mock_schedule.progressive_lower_threshold = None

        with self.assertRaises(frappe.ValidationError):
            self.service.validate_progressive_configuration(mock_schedule)

    def test_validate_threshold_less_than_reference(self):
        """Test that lower threshold must be less than reference income."""
        mock_schedule = MagicMock()
        mock_schedule.contribution_mode = "Income-Based"
        mock_schedule.income_calculation_type = "Progressive"
        mock_schedule.is_template = True
        mock_schedule.progressive_reference_income = 2000
        mock_schedule.progressive_lower_threshold = 3000  # Greater than reference

        with self.assertRaises(frappe.ValidationError):
            self.service.validate_progressive_configuration(mock_schedule)


class TestIncomeBracketDescription(EnhancedTestCase):
    """Test suite for income bracket descriptions."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_progressive_dues_service()

        self.mock_schedule = MagicMock()
        self.mock_schedule.progressive_reference_income = 3000
        self.mock_schedule.progressive_lower_threshold = 1000

    def test_description_below_threshold(self):
        """Test description for income below threshold."""
        description = self.service.get_income_bracket_description(
            self.mock_schedule, monthly_income=500
        )

        self.assertIn("minimum", description.lower())

    def test_description_below_average(self):
        """Test description for income below average but above threshold."""
        # Below 75% of reference (3000 * 0.75 = 2250)
        description = self.service.get_income_bracket_description(
            self.mock_schedule, monthly_income=1500
        )

        self.assertIn("below", description.lower())
        self.assertIn("reduced", description.lower())

    def test_description_around_average(self):
        """Test description for income around average."""
        # Between 75% and 125% of reference
        description = self.service.get_income_bracket_description(
            self.mock_schedule, monthly_income=3000
        )

        self.assertIn("average", description.lower())
        self.assertIn("standard", description.lower())

    def test_description_above_average(self):
        """Test description for income above average."""
        # Above 125% of reference (3000 * 1.25 = 3750)
        description = self.service.get_income_bracket_description(
            self.mock_schedule, monthly_income=5000
        )

        self.assertIn("above", description.lower())
        self.assertIn("solidarity", description.lower())
