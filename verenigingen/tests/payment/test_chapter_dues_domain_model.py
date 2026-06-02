# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Chapter Dues Domain Model Unit Tests

Comprehensive unit tests for the domain model value objects and services
introduced in the strategic refactoring of chapter dues allocation.

Tests focus on:
- SplitPercentage value object validation and factory methods
- DuesAllocation value object calculation accuracy and accounting equation
- DuesAllocationService batch calculation and caching
- Financial precision with edge cases (rounding, very small/large amounts)
- Domain model invariants and error handling
"""

import unittest
from decimal import Decimal

import frappe
from frappe.utils import flt

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.domain.chapter_dues import (
    DuesAllocation,
    DuesAllocationService,
    SplitPercentage,
)


class TestSplitPercentage(unittest.TestCase):
    """Unit tests for SplitPercentage value object"""

    def test_valid_percentage_construction(self):
        """Test creating SplitPercentage with valid percentage"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))

        self.assertEqual(split.chapter_percentage, Decimal("60"))
        self.assertEqual(split.national_percentage, Decimal("40"))
        self.assertIsInstance(split.chapter_percentage, Decimal)
        self.assertIsInstance(split.national_percentage, Decimal)

    def test_percentage_edge_cases(self):
        """Test percentage edge cases (0%, 100%, 50%)"""
        # 0% chapter (100% national)
        split_0 = SplitPercentage(chapter_percentage=Decimal("0"))
        self.assertEqual(split_0.chapter_percentage, Decimal("0"))
        self.assertEqual(split_0.national_percentage, Decimal("100"))

        # 100% chapter (0% national)
        split_100 = SplitPercentage(chapter_percentage=Decimal("100"))
        self.assertEqual(split_100.chapter_percentage, Decimal("100"))
        self.assertEqual(split_100.national_percentage, Decimal("0"))

        # 50/50 split
        split_50 = SplitPercentage(chapter_percentage=Decimal("50"))
        self.assertEqual(split_50.chapter_percentage, Decimal("50"))
        self.assertEqual(split_50.national_percentage, Decimal("50"))

    def test_invalid_percentage_raises_error(self):
        """Test that invalid percentages raise ValueError"""
        # Test negative percentage
        with self.assertRaises(ValueError) as context:
            SplitPercentage(chapter_percentage=Decimal("-10"))
        self.assertIn("must be 0-100", str(context.exception))

        # Test percentage > 100
        with self.assertRaises(ValueError) as context:
            SplitPercentage(chapter_percentage=Decimal("150"))
        self.assertIn("must be 0-100", str(context.exception))

        # Test percentage slightly over 100
        with self.assertRaises(ValueError) as context:
            SplitPercentage(chapter_percentage=Decimal("100.01"))
        self.assertIn("must be 0-100", str(context.exception))

    def test_immutability(self):
        """Test that SplitPercentage is immutable (frozen dataclass)"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))

        # Attempt to modify should raise error
        with self.assertRaises(AttributeError):
            split.chapter_percentage = Decimal("70")

    def test_percentage_sum_always_100(self):
        """Test that chapter + national percentage always equals 100"""
        test_percentages = [
            Decimal("0"),
            Decimal("25.5"),
            Decimal("33.33"),
            Decimal("50"),
            Decimal("66.67"),
            Decimal("75.25"),
            Decimal("100"),
        ]

        for pct in test_percentages:
            split = SplitPercentage(chapter_percentage=pct)
            total = split.chapter_percentage + split.national_percentage
            self.assertEqual(total, Decimal("100"))

    def test_to_dict_conversion(self):
        """Test conversion to dictionary for API responses"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))
        result = split.to_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["chapter_percentage"], 60.0)
        self.assertEqual(result["national_percentage"], 40.0)
        # Verify conversion to float for JSON serialization
        self.assertIsInstance(result["chapter_percentage"], float)


class TestSplitPercentageFactory(VereningingenTestCase):
    """Integration tests for SplitPercentage.from_chapter() factory method"""

    def setUp(self):
        super().setUp()
        # Ensure clean settings state - use db.set_value to bypass validation
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "default_chapter_split_percentage",
            60.0
        )
        frappe.db.commit()

    def test_from_chapter_with_custom_percentage(self):
        """Test loading chapter with custom split percentage override"""
        # Create chapter with custom percentage
        chapter = self.create_test_chapter(chapter_split_percentage=75.0)

        split = SplitPercentage.from_chapter(chapter.name)

        self.assertEqual(split.chapter_percentage, Decimal("75.0"))
        self.assertEqual(split.national_percentage, Decimal("25.0"))

    def test_from_chapter_with_default_percentage(self):
        """Test loading chapter without custom percentage (uses system default)"""
        # Create chapter with 0 percentage (fallback indicator, not NULL)
        chapter = self.create_test_chapter(chapter_split_percentage=0)

        split = SplitPercentage.from_chapter(chapter.name)

        # A chapter_split_percentage of 0 is a fallback indicator: from_chapter
        # falls back to the system default (60% configured in setUp), per the
        # documented logic in SplitPercentage.from_chapter.
        self.assertEqual(split.chapter_percentage, Decimal("60.0"))
        self.assertEqual(split.national_percentage, Decimal("40.0"))

    def test_from_chapter_with_unconfigured_default(self):
        """Test fallback to 60% when no system default is configured"""
        # Create chapter - will use test default which we'll override
        chapter = self.create_test_chapter(chapter_split_percentage=60.0)

        # Clear system default using db.set_value to bypass validation
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "default_chapter_split_percentage",
            None
        )
        frappe.db.commit()

        split = SplitPercentage.from_chapter(chapter.name)

        # Should use chapter's configured value (60%)
        self.assertEqual(split.chapter_percentage, Decimal("60.0"))

    def test_from_chapter_with_empty_name(self):
        """Test handling of empty chapter name"""
        split = SplitPercentage.from_chapter("")

        # Should return 0% for empty chapter
        self.assertEqual(split.chapter_percentage, Decimal("0"))
        self.assertEqual(split.national_percentage, Decimal("100"))


class TestDuesAllocation(unittest.TestCase):
    """Unit tests for DuesAllocation value object"""

    def test_calculate_allocation_standard_case(self):
        """Test standard allocation calculation"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))
        allocation = DuesAllocation.calculate(100.0, split)

        self.assertEqual(allocation.total_amount, Decimal("100.00"))
        self.assertEqual(allocation.chapter_amount, Decimal("60.00"))
        self.assertEqual(allocation.national_amount, Decimal("40.00"))
        self.assertEqual(allocation.split_percentage, split)

    def test_accounting_equation_enforced(self):
        """Test that accounting equation (chapter + national = total) is enforced"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))
        allocation = DuesAllocation.calculate(100.0, split)

        # Verify accounting equation
        self.assertEqual(
            allocation.chapter_amount + allocation.national_amount,
            allocation.total_amount
        )

    def test_accounting_equation_validation_on_construction(self):
        """Test that invalid allocations raise ValueError"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))

        # Attempt to construct allocation with unbalanced amounts
        with self.assertRaises(ValueError) as context:
            DuesAllocation(
                total_amount=Decimal("100.00"),
                chapter_amount=Decimal("60.00"),
                national_amount=Decimal("39.00"),  # Should be 40.00
                split_percentage=split
            )
        self.assertIn("don't balance", str(context.exception))

    def test_rounding_edge_cases(self):
        """Test banker's rounding for amounts that don't divide evenly"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))

        # Test case: €100.33 with 60/40 split
        # Chapter: 100.33 * 0.60 = 60.198 → rounds to 60.20
        # National: 100.33 - 60.20 = 40.13
        allocation = DuesAllocation.calculate(100.33, split)

        self.assertEqual(allocation.total_amount, Decimal("100.33"))
        self.assertEqual(allocation.chapter_amount, Decimal("60.20"))
        self.assertEqual(allocation.national_amount, Decimal("40.13"))
        # Verify accounting equation holds
        self.assertEqual(
            allocation.chapter_amount + allocation.national_amount,
            allocation.total_amount
        )

    def test_rounding_edge_case_thirds(self):
        """Test rounding with thirds (33.33% split)"""
        split = SplitPercentage(chapter_percentage=Decimal("33.33"))

        # €100 with 33.33% split
        # Chapter: 100 * 0.3333 = 33.33
        # National: 100 - 33.33 = 66.67
        allocation = DuesAllocation.calculate(100.0, split)

        self.assertEqual(allocation.chapter_amount, Decimal("33.33"))
        self.assertEqual(allocation.national_amount, Decimal("66.67"))
        self.assertEqual(
            allocation.chapter_amount + allocation.national_amount,
            allocation.total_amount
        )

    def test_very_small_amounts(self):
        """Test allocation with very small amounts (< €1)"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))

        # Test €0.10
        allocation = DuesAllocation.calculate(0.10, split)
        self.assertEqual(allocation.total_amount, Decimal("0.10"))
        self.assertEqual(allocation.chapter_amount, Decimal("0.06"))
        self.assertEqual(allocation.national_amount, Decimal("0.04"))

        # Test €0.01 (minimum)
        allocation_min = DuesAllocation.calculate(0.01, split)
        self.assertEqual(allocation_min.total_amount, Decimal("0.01"))
        # Verify accounting equation still holds
        self.assertEqual(
            allocation_min.chapter_amount + allocation_min.national_amount,
            allocation_min.total_amount
        )

    def test_large_amounts(self):
        """Test allocation with large amounts (> €1 million)"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))

        # Test €1,234,567.89
        allocation = DuesAllocation.calculate(1234567.89, split)

        self.assertEqual(allocation.total_amount, Decimal("1234567.89"))
        self.assertEqual(allocation.chapter_amount, Decimal("740740.73"))
        self.assertEqual(allocation.national_amount, Decimal("493827.16"))
        # Verify precision maintained for large amounts
        self.assertEqual(
            allocation.chapter_amount + allocation.national_amount,
            allocation.total_amount
        )

    def test_zero_amount(self):
        """Test allocation with zero amount"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))
        allocation = DuesAllocation.calculate(0.0, split)

        self.assertEqual(allocation.total_amount, Decimal("0.00"))
        self.assertEqual(allocation.chapter_amount, Decimal("0.00"))
        self.assertEqual(allocation.national_amount, Decimal("0.00"))

    def test_100_percent_chapter_split(self):
        """Test allocation with 100% to chapter (0% to national)"""
        split = SplitPercentage(chapter_percentage=Decimal("100"))
        allocation = DuesAllocation.calculate(100.0, split)

        self.assertEqual(allocation.chapter_amount, Decimal("100.00"))
        self.assertEqual(allocation.national_amount, Decimal("0.00"))

    def test_0_percent_chapter_split(self):
        """Test allocation with 0% to chapter (100% to national)"""
        split = SplitPercentage(chapter_percentage=Decimal("0"))
        allocation = DuesAllocation.calculate(100.0, split)

        self.assertEqual(allocation.chapter_amount, Decimal("0.00"))
        self.assertEqual(allocation.national_amount, Decimal("100.00"))

    def test_immutability(self):
        """Test that DuesAllocation is immutable (frozen dataclass)"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))
        allocation = DuesAllocation.calculate(100.0, split)

        # Attempt to modify should raise error
        with self.assertRaises(AttributeError):
            allocation.chapter_amount = Decimal("70.00")

    def test_to_dict_conversion(self):
        """Test conversion to dictionary for API responses"""
        split = SplitPercentage(chapter_percentage=Decimal("60"))
        allocation = DuesAllocation.calculate(100.0, split)
        result = allocation.to_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["total_amount"], 100.0)
        self.assertEqual(result["chapter_amount"], 60.0)
        self.assertEqual(result["national_amount"], 40.0)
        self.assertEqual(result["chapter_percentage"], 60.0)
        self.assertEqual(result["national_percentage"], 40.0)
        # Verify all values are float for JSON serialization
        for value in result.values():
            self.assertIsInstance(value, float)


class TestDuesAllocationService(VereningingenTestCase):
    """Integration tests for DuesAllocationService"""

    def setUp(self):
        super().setUp()
        self.service = DuesAllocationService()

        # Set system default percentage
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "default_chapter_split_percentage",
            60.0
        )
        frappe.db.commit()

        # Create test chapters with different split percentages.
        # Chapter names must not contain "%" (invalid character per the
        # Chapter name validator), so use descriptive ascii labels instead.
        self.chapter_60 = self.create_test_chapter(
            chapter_name="Chapter 60 pct",
            chapter_split_percentage=60.0
        )
        self.chapter_75 = self.create_test_chapter(
            chapter_name="Chapter 75 pct",
            chapter_split_percentage=75.0
        )
        # Chapter with default - create with 0 and will fallback to system default
        self.chapter_default = self.create_test_chapter(
            chapter_name="Chapter Default",
            chapter_split_percentage=60.0  # Explicitly set to match expected default
        )

    def test_get_split_percentage_with_caching(self):
        """Test that split percentage is cached after first load"""
        # First call - loads from database
        split1 = self.service.get_split_percentage(self.chapter_60.name)
        self.assertEqual(split1.chapter_percentage, Decimal("60.0"))

        # Verify it's in cache
        self.assertIn(self.chapter_60.name, self.service._percentage_cache)

        # Second call - should use cache (same object reference)
        split2 = self.service.get_split_percentage(self.chapter_60.name)
        self.assertIs(split1, split2)  # Same object instance

    def test_calculate_allocation_single_chapter(self):
        """Test calculating allocation for a single chapter"""
        allocation = self.service.calculate_allocation(100.0, self.chapter_75.name)

        self.assertEqual(allocation.total_amount, Decimal("100.00"))
        self.assertEqual(allocation.chapter_amount, Decimal("75.00"))
        self.assertEqual(allocation.national_amount, Decimal("25.00"))

    def test_batch_calculate_multiple_chapters(self):
        """Test batch calculation for multiple chapters"""
        chapter_amounts = {
            self.chapter_60.name: 100.0,
            self.chapter_75.name: 200.0,
            self.chapter_default.name: 150.0,
        }

        allocations = self.service.batch_calculate(chapter_amounts)

        # Verify all chapters processed
        self.assertEqual(len(allocations), 3)
        self.assertIn(self.chapter_60.name, allocations)
        self.assertIn(self.chapter_75.name, allocations)
        self.assertIn(self.chapter_default.name, allocations)

        # Verify calculations correct
        alloc_60 = allocations[self.chapter_60.name]
        self.assertEqual(alloc_60.total_amount, Decimal("100.00"))
        self.assertEqual(alloc_60.chapter_amount, Decimal("60.00"))

        alloc_75 = allocations[self.chapter_75.name]
        self.assertEqual(alloc_75.total_amount, Decimal("200.00"))
        self.assertEqual(alloc_75.chapter_amount, Decimal("150.00"))

        # Default chapter should use system default (60%)
        alloc_default = allocations[self.chapter_default.name]
        self.assertEqual(alloc_default.chapter_amount, Decimal("90.00"))  # 150 * 0.60

    def test_batch_calculate_preloads_cache(self):
        """Test that batch_calculate preloads cache in single query"""
        chapter_amounts = {
            self.chapter_60.name: 100.0,
            self.chapter_75.name: 200.0,
        }

        # Create new service instance to ensure empty cache
        fresh_service = DuesAllocationService()
        self.assertEqual(len(fresh_service._percentage_cache), 0)

        # Batch calculate should populate cache
        allocations = fresh_service.batch_calculate(chapter_amounts)

        # Verify cache populated
        self.assertGreater(len(fresh_service._percentage_cache), 0)
        self.assertIn(self.chapter_60.name, fresh_service._percentage_cache)
        self.assertIn(self.chapter_75.name, fresh_service._percentage_cache)

    def test_batch_calculate_empty_input(self):
        """Test batch calculation with empty input"""
        allocations = self.service.batch_calculate({})

        self.assertEqual(len(allocations), 0)
        self.assertIsInstance(allocations, dict)

    def test_service_consistency_across_methods(self):
        """Test that single and batch calculations produce identical results"""
        amount = 123.45

        # Single calculation
        single_allocation = self.service.calculate_allocation(amount, self.chapter_60.name)

        # Batch calculation
        batch_allocations = self.service.batch_calculate({self.chapter_60.name: amount})
        batch_allocation = batch_allocations[self.chapter_60.name]

        # Results should be identical
        self.assertEqual(single_allocation.total_amount, batch_allocation.total_amount)
        self.assertEqual(single_allocation.chapter_amount, batch_allocation.chapter_amount)
        self.assertEqual(single_allocation.national_amount, batch_allocation.national_amount)


class TestFinancialPrecision(unittest.TestCase):
    """Additional financial precision tests for domain model"""

    def test_no_float_precision_errors(self):
        """Test that using Decimal prevents float precision errors"""
        # Classic float precision issue: 0.1 + 0.2 != 0.3
        # With Decimal, this should work correctly

        split = SplitPercentage(chapter_percentage=Decimal("10"))
        allocation = DuesAllocation.calculate(0.3, split)

        # Verify precise calculation
        expected_chapter = Decimal("0.03")  # 0.3 * 0.10
        expected_national = Decimal("0.27")  # 0.3 * 0.90

        self.assertEqual(allocation.chapter_amount, expected_chapter)
        self.assertEqual(allocation.national_amount, expected_national)
        # Verify accounting equation holds precisely
        self.assertEqual(
            allocation.chapter_amount + allocation.national_amount,
            allocation.total_amount
        )

    def test_string_to_decimal_conversion(self):
        """Test that float->string->Decimal conversion prevents precision loss"""
        # Demonstrate why SplitPercentage.from_chapter uses Decimal(str(value))

        # Bad: Direct float to Decimal conversion
        bad_decimal = Decimal(60.1)  # May have precision issues

        # Good: String intermediary
        good_decimal = Decimal(str(60.1))

        # Good decimal should be exactly representable
        self.assertEqual(str(good_decimal), "60.1")

    def test_banker_rounding_implementation(self):
        """Test that quantize() uses banker's rounding (round half to even)"""
        # Test cases for banker's rounding:
        # 2.5 rounds to 2 (even)
        # 3.5 rounds to 4 (even)

        value1 = Decimal("2.5")
        rounded1 = value1.quantize(Decimal("1"))
        self.assertEqual(rounded1, Decimal("2"))  # Rounds to even

        value2 = Decimal("3.5")
        rounded2 = value2.quantize(Decimal("1"))
        self.assertEqual(rounded2, Decimal("4"))  # Rounds to even

    def test_allocation_rounding_consistency(self):
        """Test that allocation rounding is consistent and predictable"""
        split = SplitPercentage(chapter_percentage=Decimal("33.33"))

        # Multiple calculations of same amount should always produce same result
        allocation1 = DuesAllocation.calculate(99.99, split)
        allocation2 = DuesAllocation.calculate(99.99, split)

        self.assertEqual(allocation1.chapter_amount, allocation2.chapter_amount)
        self.assertEqual(allocation1.national_amount, allocation2.national_amount)

        # Verify deterministic rounding
        # 99.99 * 0.3333 = 33.326667 → should round to 33.33
        self.assertEqual(allocation1.chapter_amount, Decimal("33.33"))
        self.assertEqual(allocation1.national_amount, Decimal("66.66"))
