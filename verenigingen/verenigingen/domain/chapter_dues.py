"""
Domain Model for Chapter Dues Allocation

This module contains value objects and domain services that encapsulate
the business rules for splitting membership dues between chapters and national.

Architecture:
- Value objects enforce invariants at construction time
- Domain service orchestrates batch calculations
- Uses Decimal for financial accuracy
- Provides clean separation from data access layer
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

import frappe


@dataclass(frozen=True)
class SplitPercentage:
    """
    Value object representing a validated split percentage.

    Invariants:
        - chapter_percentage is between 0 and 100
        - chapter_percentage + national_percentage = 100

    Examples:
        >>> split = SplitPercentage(chapter_percentage=Decimal("60.0"))
        >>> split.national_percentage
        Decimal('40.0')
    """

    chapter_percentage: Decimal

    def __post_init__(self):
        """Validate business rules on construction"""
        if not (0 <= self.chapter_percentage <= 100):
            raise ValueError(f"Chapter percentage must be 0-100, got {self.chapter_percentage}")

    @property
    def national_percentage(self) -> Decimal:
        """Computed property ensuring percentages sum to 100"""
        return Decimal(100) - self.chapter_percentage

    @classmethod
    def from_chapter(cls, chapter_name: str) -> "SplitPercentage":
        """
        Factory method to load percentage from chapter configuration.

        Logic:
            1. Check chapter-specific override
            2. Fall back to system default
            3. Default to 60% if unconfigured

        Args:
            chapter_name: Name of the Chapter

        Returns:
            SplitPercentage with configured or default value
        """
        if not chapter_name:
            return cls(chapter_percentage=Decimal(0))

        # Try chapter-specific override
        chapter_pct = frappe.db.get_value("Chapter", chapter_name, "chapter_split_percentage")

        # Only use chapter-specific value if it's explicitly set and non-zero
        # Chapters with 0 should fall back to the default
        if chapter_pct is not None and chapter_pct != 0:
            return cls(chapter_percentage=Decimal(str(chapter_pct)))

        # Fall back to system default
        default_pct = frappe.db.get_single_value("Verenigingen Settings", "default_chapter_split_percentage")

        if default_pct is not None:
            return cls(chapter_percentage=Decimal(str(default_pct)))

        # Ultimate fallback
        return cls(chapter_percentage=Decimal("60.0"))

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        return {
            "chapter_percentage": float(self.chapter_percentage),
            "national_percentage": float(self.national_percentage),
        }


@dataclass(frozen=True)
class DuesAllocation:
    """
    Value object representing a calculated dues split.

    This encapsulates the result of splitting a total amount according
    to configured percentages.

    Invariants:
        - chapter_amount + national_amount = total_amount (accounting equation)
    """

    total_amount: Decimal
    chapter_amount: Decimal
    national_amount: Decimal
    split_percentage: SplitPercentage

    def __post_init__(self):
        """Validate accounting equation"""
        if self.chapter_amount + self.national_amount != self.total_amount:
            raise ValueError(
                f"Amounts don't balance: {self.chapter_amount} + {self.national_amount} != {self.total_amount}"
            )

    @classmethod
    def calculate(cls, total_amount: float, split_percentage: SplitPercentage) -> "DuesAllocation":
        """
        Calculate allocation from total amount and split percentage.

        Uses banker's rounding to ensure accounting accuracy.
        The national amount is computed as remainder to ensure perfect balance.

        Args:
            total_amount: Total dues amount to split
            split_percentage: Configured split percentage

        Returns:
            DuesAllocation with calculated amounts

        Examples:
            >>> split = SplitPercentage(Decimal("60"))
            >>> allocation = DuesAllocation.calculate(100.0, split)
            >>> allocation.chapter_amount
            Decimal('60.00')
            >>> allocation.national_amount
            Decimal('40.00')
        """
        total = Decimal(str(total_amount))
        chapter_pct = split_percentage.chapter_percentage

        # Calculate chapter amount with precise rounding
        chapter_amt = (total * chapter_pct / Decimal(100)).quantize(Decimal("0.01"))

        # National amount is remainder to ensure perfect balance
        national_amt = total - chapter_amt

        return cls(
            total_amount=total,
            chapter_amount=chapter_amt,
            national_amount=national_amt,
            split_percentage=split_percentage,
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        return {
            "total_amount": float(self.total_amount),
            "chapter_amount": float(self.chapter_amount),
            "national_amount": float(self.national_amount),
            **self.split_percentage.to_dict(),
        }


class DuesAllocationService:
    """
    Domain service for chapter dues allocation operations.

    This service orchestrates allocation calculations across multiple chapters
    while maintaining consistency with configuration and business rules.

    Features:
        - Batch configuration loading to avoid N+1 queries
        - Percentage caching for performance
        - Consistent calculation logic across all operations
    """

    def __init__(self):
        """Initialize service with empty cache"""
        self._percentage_cache: Dict[str, SplitPercentage] = {}

    def get_split_percentage(self, chapter_name: str) -> SplitPercentage:
        """
        Get split percentage with caching.

        Args:
            chapter_name: Name of the Chapter

        Returns:
            Cached or freshly loaded SplitPercentage
        """
        if chapter_name not in self._percentage_cache:
            self._percentage_cache[chapter_name] = SplitPercentage.from_chapter(chapter_name)
        return self._percentage_cache[chapter_name]

    def calculate_allocation(self, total_amount: float, chapter_name: str) -> DuesAllocation:
        """
        Calculate allocation for a single chapter.

        Args:
            total_amount: Total dues amount
            chapter_name: Name of the Chapter

        Returns:
            DuesAllocation with calculated split
        """
        split_pct = self.get_split_percentage(chapter_name)
        return DuesAllocation.calculate(total_amount, split_pct)

    def batch_calculate(self, chapter_amounts: Dict[str, float]) -> Dict[str, DuesAllocation]:
        """
        Calculate allocations for multiple chapters efficiently.

        Batch-loads all chapter configurations to avoid N+1 queries.

        Args:
            chapter_amounts: Dict mapping chapter_name -> total_amount

        Returns:
            Dict mapping chapter_name -> DuesAllocation

        Performance:
            - 1 database query for all chapter configurations
            - O(1) lookups for percentage retrieval
            - Significant performance improvement over per-chapter queries
        """
        chapter_names = list(chapter_amounts.keys())

        if chapter_names:
            # Batch-load all chapter percentages in single query
            configs = frappe.db.get_all(
                "Chapter",
                filters={"name": ["in", chapter_names]},
                fields=["name", "chapter_split_percentage"],
            )

            # Get default percentage once for all chapters without custom splits
            # Query directly from database to avoid any caching issues
            default_pct = frappe.db.get_single_value(
                "Verenigingen Settings", "default_chapter_split_percentage"
            )
            default_split = Decimal(str(default_pct)) if default_pct is not None else Decimal("60.0")

            # Pre-populate cache for ALL chapters
            chapters_with_config = {c.name for c in configs}
            for config in configs:
                # Only use chapter-specific value if it's explicitly set and non-zero
                # Chapters with 0 should fall back to the default
                if config.chapter_split_percentage is not None and config.chapter_split_percentage != 0:
                    # Chapter has custom split (non-zero)
                    self._percentage_cache[config.name] = SplitPercentage(
                        chapter_percentage=Decimal(str(config.chapter_split_percentage))
                    )
                else:
                    # Chapter uses default split (either NULL or 0 in database)
                    self._percentage_cache[config.name] = SplitPercentage(chapter_percentage=default_split)

            # Handle chapters that weren't found in database (edge case)
            for chapter_name in chapter_names:
                if chapter_name not in chapters_with_config:
                    self._percentage_cache[chapter_name] = SplitPercentage(chapter_percentage=default_split)

        # Calculate allocations using cached percentages
        allocations = {}
        for chapter_name, amount in chapter_amounts.items():
            allocations[chapter_name] = self.calculate_allocation(amount, chapter_name)

        return allocations
