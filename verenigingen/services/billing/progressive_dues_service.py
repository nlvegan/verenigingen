# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
ProgressiveDuesService - Progressive dues calculation for income-based contributions.

This service handles progressive sliding scale dues calculations including:
- Income-based multiplier calculation
- Configuration validation
- Suggested dues calculation based on income

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.

Architecture:
- StatelessService base class for consistent logging and error handling
- Pure calculation functions with no database side effects
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


@dataclass
class ProgressiveDuesResult:
    """Result of progressive dues calculation."""

    multiplier: float
    percentage: float
    suggested_dues: float
    base_dues: float


class ProgressiveDuesService(StatelessService):
    """
    Service for calculating progressive dues based on income.

    Implements a linear sliding scale formula where members pay
    proportionally based on their income relative to a reference point.

    Formula:
        multiplier = (income - lower_threshold) / (reference_income - lower_threshold)
        suggested_dues = base_dues * multiplier

    Example:
        service = get_progressive_dues_service()
        result = service.calculate_progressive_dues(
            schedule_doc, monthly_income=2500
        )
        print(f"Suggested dues: €{result.suggested_dues}")
    """

    def __init__(self):
        super().__init__(service_name="ProgressiveDuesService")

    def calculate_progressive_dues(
        self,
        schedule_doc: "Document",
        monthly_income: float,
        base_dues: Optional[float] = None,
    ) -> ProgressiveDuesResult:
        """
        Calculate suggested dues based on progressive sliding scale formula.

        The formula uses a linear scale between a lower threshold (0% multiplier)
        and a reference income (100% multiplier). Incomes above the reference
        result in multipliers above 1.0.

        Args:
            schedule_doc: The dues schedule document with progressive configuration
            monthly_income: Applicant's monthly net income
            base_dues: The standard dues rate (100% reference). If None, uses suggested_amount.

        Returns:
            ProgressiveDuesResult with multiplier, percentage, and calculated dues
        """
        reference_income = getattr(schedule_doc, "progressive_reference_income", None) or 0
        lower_threshold = getattr(schedule_doc, "progressive_lower_threshold", None) or 0

        if base_dues is None:
            base_dues = schedule_doc.suggested_amount or 0

        # Handle invalid configuration
        if reference_income <= lower_threshold:
            self.logger.warning(
                f"Invalid progressive configuration for {schedule_doc.name}: "
                f"reference_income ({reference_income}) <= lower_threshold ({lower_threshold})"
            )
            return ProgressiveDuesResult(
                multiplier=1.0,
                percentage=100,
                suggested_dues=base_dues,
                base_dues=base_dues,
            )

        # Calculate multiplier using linear sliding scale
        range_amount = reference_income - lower_threshold
        multiplier = (monthly_income - lower_threshold) / range_amount

        # Floor at 0 (no negative dues), no ceiling (higher earners pay more)
        multiplier = max(0, multiplier)

        suggested_dues = round(base_dues * multiplier, 2)

        return ProgressiveDuesResult(
            multiplier=round(multiplier, 4),
            percentage=round(multiplier * 100, 1),
            suggested_dues=suggested_dues,
            base_dues=base_dues,
        )

    def validate_progressive_configuration(self, schedule_doc: "Document") -> None:
        """
        Validate progressive contribution mode settings.

        Ensures that templates have complete progressive configuration
        with valid reference income and lower threshold values.

        Args:
            schedule_doc: The dues schedule document to validate

        Raises:
            frappe.ValidationError: If configuration is invalid
        """
        if schedule_doc.contribution_mode != "Income-Based":
            return

        reference_income = getattr(schedule_doc, "progressive_reference_income", None)
        lower_threshold = getattr(schedule_doc, "progressive_lower_threshold", None)

        # Templates must have complete progressive configuration
        if schedule_doc.is_template:
            if not reference_income or reference_income <= 0:
                frappe.throw(
                    "Progressive mode requires a Reference Income (median) to be set. "
                    "This is the national median income used as the 100% reference point."
                )

            if not lower_threshold or lower_threshold < 0:
                frappe.throw(
                    "Progressive mode requires a Lower Income Threshold to be set. "
                    "This is the income level below which minimum dues apply."
                )

            if lower_threshold >= reference_income:
                frappe.throw(
                    f"Lower Income Threshold (€{lower_threshold:,.2f}) must be less than "
                    f"Reference Income (€{reference_income:,.2f})"
                )

    def get_income_bracket_description(
        self,
        schedule_doc: "Document",
        monthly_income: float,
    ) -> str:
        """
        Get a human-readable description of the income bracket.

        Useful for displaying to users during the contribution selection process.

        Args:
            schedule_doc: The dues schedule document with progressive configuration
            monthly_income: Applicant's monthly net income

        Returns:
            Description string (e.g., "Below minimum threshold", "At reference income")
        """
        reference_income = getattr(schedule_doc, "progressive_reference_income", None) or 0
        lower_threshold = getattr(schedule_doc, "progressive_lower_threshold", None) or 0

        if monthly_income <= lower_threshold:
            return "Below minimum threshold - minimum dues apply"
        elif monthly_income < reference_income * 0.75:
            return "Below average income - reduced dues"
        elif monthly_income <= reference_income * 1.25:
            return "Around average income - standard dues"
        else:
            return "Above average income - solidarity contribution"

    def calculate_dues_for_income_range(
        self,
        schedule_doc: "Document",
        income_min: float,
        income_max: float,
        steps: int = 10,
    ) -> list:
        """
        Calculate dues for a range of income values.

        Useful for generating tables or charts showing the sliding scale.

        Args:
            schedule_doc: The dues schedule document with progressive configuration
            income_min: Minimum income to calculate for
            income_max: Maximum income to calculate for
            steps: Number of data points to generate

        Returns:
            List of dicts with income, multiplier, and dues
        """
        results = []
        step_size = (income_max - income_min) / (steps - 1) if steps > 1 else 0

        for i in range(steps):
            income = income_min + (step_size * i)
            calc_result = self.calculate_progressive_dues(schedule_doc, income)
            results.append(
                {
                    "income": round(income, 2),
                    "multiplier": calc_result.multiplier,
                    "percentage": calc_result.percentage,
                    "suggested_dues": calc_result.suggested_dues,
                }
            )

        return results


def get_progressive_dues_service() -> ProgressiveDuesService:
    """Get singleton instance of ProgressiveDuesService."""
    return ProgressiveDuesService()
