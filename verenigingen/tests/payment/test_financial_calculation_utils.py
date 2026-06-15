# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for financial_calculation_utils module.

Pure-math utilities for the Mollie/settlement reconciliation integration:
- convert_decimal_dict_to_float / convert_nested_decimals_to_float
- prorate_amount_by_days
- calculate_date_overlap
- find_gap_periods
- safe_decimal_from_dict

These are exact financial calculations; tests assert Decimal type, rounding
direction, and cent-level correctness with real values. No mocking.
"""

import unittest
from datetime import datetime
from decimal import Decimal

# NOTE: financial_calculation_utils imports cleanly without frappe context
# (pure stdlib). Tests below are plain unittest with real values, no mocking.
from verenigingen.verenigingen_payments.utils.financial_calculation_utils import (
    calculate_date_overlap,
    convert_decimal_dict_to_float,
    convert_nested_decimals_to_float,
    find_gap_periods,
    prorate_amount_by_days,
    safe_decimal_from_dict,
)


class TestConvertDecimalDictToFloat(unittest.TestCase):
    """convert_decimal_dict_to_float() - in-place Decimal -> float conversion."""

    def test_converts_all_decimals_when_keys_none(self):
        data = {"total": Decimal("123.45"), "count": 5, "name": "x"}
        result = convert_decimal_dict_to_float(data)
        # Mutates in place, returns None
        self.assertIsNone(result)
        self.assertIsInstance(data["total"], float)
        self.assertEqual(data["total"], 123.45)
        # Non-decimal values untouched
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["name"], "x")

    def test_only_specified_keys_converted(self):
        data = {"a": Decimal("1.5"), "b": Decimal("2.5")}
        convert_decimal_dict_to_float(data, keys=["a"])
        self.assertIsInstance(data["a"], float)
        self.assertIsInstance(data["b"], Decimal)

    def test_specified_key_missing_is_ignored(self):
        data = {"a": Decimal("1.5")}
        # Should not raise on missing key
        convert_decimal_dict_to_float(data, keys=["a", "missing"])
        self.assertEqual(data["a"], 1.5)
        self.assertNotIn("missing", data)

    def test_specified_key_non_decimal_untouched(self):
        data = {"a": 7}  # int, not Decimal
        convert_decimal_dict_to_float(data, keys=["a"])
        self.assertIsInstance(data["a"], int)
        self.assertEqual(data["a"], 7)

    def test_recursive_converts_nested_dicts(self):
        data = {"current_month": {"total": Decimal("100")}, "flat": Decimal("5")}
        convert_decimal_dict_to_float(data, recursive=True)
        self.assertIsInstance(data["current_month"]["total"], float)
        self.assertEqual(data["current_month"]["total"], 100.0)
        self.assertIsInstance(data["flat"], float)

    def test_non_recursive_leaves_nested_untouched(self):
        data = {"current_month": {"total": Decimal("100")}}
        convert_decimal_dict_to_float(data)  # recursive defaults to False
        # Nested dict's Decimal is NOT converted
        self.assertIsInstance(data["current_month"]["total"], Decimal)

    def test_recursive_with_keys_none_only(self):
        # recursive only takes effect when keys is None
        data = {"outer": {"v": Decimal("9")}}
        convert_decimal_dict_to_float(data, keys=["outer"], recursive=True)
        # With keys given, recursive branch is not entered; outer is a dict not Decimal
        self.assertIsInstance(data["outer"]["v"], Decimal)

    def test_empty_dict(self):
        data = {}
        convert_decimal_dict_to_float(data)
        self.assertEqual(data, {})


class TestConvertNestedDecimalsToFloat(unittest.TestCase):
    """convert_nested_decimals_to_float() - per-inner-key conversion."""

    def test_converts_specified_inner_keys(self):
        data = {
            "current_month": {
                "transaction_fees": Decimal("10.50"),
                "chargeback_fees": Decimal("5.00"),
                "total_costs": Decimal("15.50"),
                "count": 3,
            }
        }
        convert_nested_decimals_to_float(
            data, ["transaction_fees", "chargeback_fees", "total_costs"]
        )
        self.assertIsInstance(data["current_month"]["transaction_fees"], float)
        self.assertEqual(data["current_month"]["transaction_fees"], 10.5)
        self.assertIsInstance(data["current_month"]["total_costs"], float)
        # Unspecified key untouched
        self.assertEqual(data["current_month"]["count"], 3)

    def test_multiple_outer_keys(self):
        data = {
            "current_month": {"total": Decimal("1")},
            "previous_month": {"total": Decimal("2")},
        }
        convert_nested_decimals_to_float(data, ["total"])
        self.assertIsInstance(data["current_month"]["total"], float)
        self.assertIsInstance(data["previous_month"]["total"], float)

    def test_non_dict_inner_value_skipped(self):
        data = {"meta": "not a dict", "real": {"total": Decimal("3")}}
        # Should not raise on the string value
        convert_nested_decimals_to_float(data, ["total"])
        self.assertEqual(data["meta"], "not a dict")
        self.assertIsInstance(data["real"]["total"], float)

    def test_missing_inner_key_ignored(self):
        data = {"current_month": {"other": Decimal("1")}}
        convert_nested_decimals_to_float(data, ["total"])
        self.assertIsInstance(data["current_month"]["other"], Decimal)

    def test_non_decimal_inner_value_untouched(self):
        data = {"current_month": {"total": 100}}  # int
        convert_nested_decimals_to_float(data, ["total"])
        self.assertIsInstance(data["current_month"]["total"], int)


class TestProrateAmountByDays(unittest.TestCase):
    """prorate_amount_by_days() - ratio-based proration returning Decimal."""

    def test_half_period(self):
        result = prorate_amount_by_days(Decimal("100"), 30, 15)
        self.assertEqual(result, Decimal("50"))
        self.assertIsInstance(result, Decimal)

    def test_full_coverage_returns_original_decimal(self):
        amount = Decimal("100")
        result = prorate_amount_by_days(amount, 30, 30)
        self.assertEqual(result, Decimal("100"))
        # Same object returned (already Decimal)
        self.assertIs(result, amount)

    def test_over_coverage_returns_original(self):
        result = prorate_amount_by_days(Decimal("100"), 30, 45)
        self.assertEqual(result, Decimal("100"))

    def test_zero_actual_days_returns_zero(self):
        result = prorate_amount_by_days(Decimal("100"), 30, 0)
        self.assertEqual(result, Decimal("0"))
        self.assertIsInstance(result, Decimal)

    def test_negative_actual_days_returns_zero(self):
        result = prorate_amount_by_days(Decimal("100"), 30, -5)
        self.assertEqual(result, Decimal("0"))

    def test_total_days_zero_raises(self):
        with self.assertRaises(ValueError):
            prorate_amount_by_days(Decimal("100"), 0, 5)

    def test_total_days_negative_raises(self):
        with self.assertRaises(ValueError):
            prorate_amount_by_days(Decimal("100"), -10, 5)

    def test_float_amount_converted_via_str(self):
        # float input goes through Decimal(str(amount)) to avoid binary float artifacts
        result = prorate_amount_by_days(100.10, 30, 15)
        # 100.10 * (15/30) = 50.05 exactly via str conversion
        self.assertEqual(result, Decimal("50.05"))
        self.assertIsInstance(result, Decimal)

    def test_exact_decimal_precision_one_third(self):
        # 1/3 of a period: ratio is a repeating decimal; result is NOT rounded by this fn
        result = prorate_amount_by_days(Decimal("90"), 30, 10)
        # 90 * (10/30) = 90 * 0.3333... ; Decimal division uses default context (28 digits)
        self.assertEqual(result, Decimal("90") * (Decimal("10") / Decimal("30")))
        # Should be very close to 30
        self.assertAlmostEqual(float(result), 30.0, places=20)

    def test_no_premature_rounding(self):
        # Function returns full-precision Decimal; caller is responsible for quantizing
        result = prorate_amount_by_days(Decimal("100"), 7, 3)
        expected = Decimal("100") * (Decimal("3") / Decimal("7"))
        self.assertEqual(result, expected)

    def test_int_amount(self):
        result = prorate_amount_by_days(100, 30, 15)
        self.assertEqual(result, Decimal("50"))
        self.assertIsInstance(result, Decimal)


class TestCalculateDateOverlap(unittest.TestCase):
    """calculate_date_overlap() - inclusive overlap days between two ranges."""

    def test_partial_overlap(self):
        start, end, days = calculate_date_overlap(
            datetime(2025, 1, 1),
            datetime(2025, 1, 31),
            datetime(2025, 1, 15),
            datetime(2025, 2, 15),
        )
        self.assertEqual(start, datetime(2025, 1, 15))
        self.assertEqual(end, datetime(2025, 1, 31))
        # Jan 15..Jan 31 inclusive = 17 days
        self.assertEqual(days, 17)

    def test_no_overlap_range1_before_range2(self):
        start, end, days = calculate_date_overlap(
            datetime(2025, 1, 1),
            datetime(2025, 1, 15),
            datetime(2025, 2, 1),
            datetime(2025, 2, 28),
        )
        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertEqual(days, 0)

    def test_no_overlap_range2_before_range1(self):
        start, end, days = calculate_date_overlap(
            datetime(2025, 2, 1),
            datetime(2025, 2, 28),
            datetime(2025, 1, 1),
            datetime(2025, 1, 15),
        )
        self.assertEqual((start, end, days), (None, None, 0))

    def test_full_containment(self):
        start, end, days = calculate_date_overlap(
            datetime(2025, 1, 1),
            datetime(2025, 1, 31),
            datetime(2025, 1, 10),
            datetime(2025, 1, 20),
        )
        self.assertEqual(start, datetime(2025, 1, 10))
        self.assertEqual(end, datetime(2025, 1, 20))
        self.assertEqual(days, 11)

    def test_identical_ranges(self):
        start, end, days = calculate_date_overlap(
            datetime(2025, 1, 1),
            datetime(2025, 1, 31),
            datetime(2025, 1, 1),
            datetime(2025, 1, 31),
        )
        self.assertEqual(days, 31)

    def test_single_point_touching_overlap(self):
        # range1 ends exactly where range2 starts -> inclusive single-day overlap
        start, end, days = calculate_date_overlap(
            datetime(2025, 1, 1),
            datetime(2025, 1, 15),
            datetime(2025, 1, 15),
            datetime(2025, 1, 31),
        )
        self.assertEqual(start, datetime(2025, 1, 15))
        self.assertEqual(end, datetime(2025, 1, 15))
        self.assertEqual(days, 1)

    def test_overlap_with_time_components(self):
        # Sub-day time components: .days truncates the fractional remainder
        start, end, days = calculate_date_overlap(
            datetime(2025, 1, 1, 0, 0),
            datetime(2025, 1, 2, 12, 0),
            datetime(2025, 1, 1, 6, 0),
            datetime(2025, 1, 3, 0, 0),
        )
        # overlap_start=Jan1 06:00, overlap_end=Jan2 12:00 -> 1.25 days -> .days=1, +1=2
        self.assertEqual(start, datetime(2025, 1, 1, 6, 0))
        self.assertEqual(end, datetime(2025, 1, 2, 12, 0))
        self.assertEqual(days, 2)


class TestFindGapPeriods(unittest.TestCase):
    """find_gap_periods() - uncovered sub-ranges within a window."""

    def test_no_covered_periods_returns_whole_range(self):
        gaps = find_gap_periods([], datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(
            gaps, [{"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 31)}]
        )

    def test_single_interior_gap(self):
        covered = [
            {"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 15)},
            {"start": datetime(2025, 1, 20), "end": datetime(2025, 1, 31)},
        ]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(len(gaps), 1)
        # Gap Jan 16 .. Jan 19
        self.assertEqual(gaps[0]["start"], datetime(2025, 1, 16))
        self.assertEqual(gaps[0]["end"], datetime(2025, 1, 19))

    def test_fully_covered_no_gaps(self):
        covered = [{"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 31)}]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(gaps, [])

    def test_gap_at_start(self):
        covered = [{"start": datetime(2025, 1, 10), "end": datetime(2025, 1, 31)}]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["start"], datetime(2025, 1, 1))
        self.assertEqual(gaps[0]["end"], datetime(2025, 1, 9))

    def test_gap_at_end(self):
        covered = [{"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 20)}]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["start"], datetime(2025, 1, 21))
        self.assertEqual(gaps[0]["end"], datetime(2025, 1, 31))

    def test_unsorted_input_is_sorted(self):
        covered = [
            {"start": datetime(2025, 1, 20), "end": datetime(2025, 1, 31)},
            {"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 15)},
        ]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["start"], datetime(2025, 1, 16))
        self.assertEqual(gaps[0]["end"], datetime(2025, 1, 19))

    def test_multiple_gaps(self):
        covered = [
            {"start": datetime(2025, 1, 5), "end": datetime(2025, 1, 10)},
            {"start": datetime(2025, 1, 15), "end": datetime(2025, 1, 20)},
        ]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        # Gaps: Jan1-4, Jan11-14, Jan21-31
        self.assertEqual(len(gaps), 3)
        self.assertEqual(gaps[0]["start"], datetime(2025, 1, 1))
        self.assertEqual(gaps[0]["end"], datetime(2025, 1, 4))
        self.assertEqual(gaps[1]["start"], datetime(2025, 1, 11))
        self.assertEqual(gaps[1]["end"], datetime(2025, 1, 14))
        self.assertEqual(gaps[2]["start"], datetime(2025, 1, 21))
        self.assertEqual(gaps[2]["end"], datetime(2025, 1, 31))

    def test_overlapping_covered_periods(self):
        # Overlapping coverage should still yield no spurious gaps
        covered = [
            {"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 20)},
            {"start": datetime(2025, 1, 10), "end": datetime(2025, 1, 31)},
        ]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(gaps, [])

    def test_covered_period_beyond_range_end(self):
        # A covered period extending past range_end should not produce a trailing gap
        covered = [{"start": datetime(2025, 1, 1), "end": datetime(2025, 2, 28)}]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        self.assertEqual(gaps, [])

    def test_covered_period_entirely_before_range(self):
        covered = [{"start": datetime(2024, 12, 1), "end": datetime(2024, 12, 31)}]
        gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        # Entire range is a gap
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["start"], datetime(2025, 1, 1))
        self.assertEqual(gaps[0]["end"], datetime(2025, 1, 31))


class TestSafeDecimalFromDict(unittest.TestCase):
    """safe_decimal_from_dict() - tolerant nested Decimal extraction."""

    def test_nested_extraction(self):
        data = {"amountNet": {"value": "123.45"}}
        result = safe_decimal_from_dict(data, "amountNet", "value")
        self.assertEqual(result, Decimal("123.45"))
        self.assertIsInstance(result, Decimal)

    def test_single_key(self):
        data = {"value": "10.00"}
        self.assertEqual(safe_decimal_from_dict(data, "value"), Decimal("10.00"))

    def test_missing_key_returns_default(self):
        data = {"amountNet": {"value": "1"}}
        self.assertEqual(safe_decimal_from_dict(data, "missing", "value"), Decimal("0"))

    def test_custom_default(self):
        data = {}
        result = safe_decimal_from_dict(data, "x", default=Decimal("9.99"))
        self.assertEqual(result, Decimal("9.99"))

    def test_intermediate_not_dict_returns_default(self):
        # Traversing into a non-dict mid-path
        data = {"a": "scalar"}
        self.assertEqual(safe_decimal_from_dict(data, "a", "b"), Decimal("0"))

    def test_value_none_returns_default(self):
        data = {"a": {"value": None}}
        self.assertEqual(safe_decimal_from_dict(data, "a", "value"), Decimal("0"))

    def test_invalid_string_returns_default(self):
        """A malformed numeric string returns the default Decimal('0').

        Regression for a fixed BUG: Decimal(str("not-a-number")) raises
        decimal.InvalidOperation (an ArithmeticError, NOT a ValueError); the
        except clause previously caught only (ValueError, TypeError,
        AttributeError), so the "safe" extractor crashed on exactly the malformed
        Mollie-API-response amounts it exists to guard. InvalidOperation is now in
        the caught tuple."""
        data = {"value": "not-a-number"}
        self.assertEqual(safe_decimal_from_dict(data, "value"), Decimal("0"))

    def test_numeric_value(self):
        # Int/float values go through str() then Decimal
        data = {"value": 42}
        self.assertEqual(safe_decimal_from_dict(data, "value"), Decimal("42"))

    def test_float_value_via_str(self):
        data = {"value": 1.5}
        self.assertEqual(safe_decimal_from_dict(data, "value"), Decimal("1.5"))

    def test_no_keys_converts_whole_dict_to_default(self):
        """Calling safe_decimal_from_dict with no keys passes the whole dict to
        Decimal(str({...})), which raises decimal.InvalidOperation; the function
        now returns the default Decimal('0') instead of raising.

        Same root cause / fix as test_invalid_string_returns_default."""
        data = {"value": "1"}
        self.assertEqual(safe_decimal_from_dict(data), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
