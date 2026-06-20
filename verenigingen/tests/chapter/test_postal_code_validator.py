"""
Unit tests for the chapter ``PostalCodeValidator``
(``verenigingen/verenigingen/doctype/chapter/validators/postal_code_validator.py``).

The validator is almost entirely pure logic: it parses comma-separated postal-code
pattern strings, validates each pattern (simple / range / wildcard / wildcard-range),
tests whether a concrete postal code matches a set of patterns, and produces
summaries / coverage estimates / optimization suggestions. These tests drive that
logic directly with plain inputs (no DB rows required), pinning the matching rules
and edge cases so a regression in the pattern engine would be caught.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.chapter.validators.postal_code_validator import (
    PostalCodeValidator,
)


class TestPostalCodeValidator(VereningingenTestCase):
    """Drive PostalCodeValidator's pure pattern logic directly."""

    def setUp(self):
        super().setUp()
        # No chapter doc needed; default country NL.
        self.v = PostalCodeValidator()

    # ------------------------------------------------------- parse / empty input

    def test_empty_string_is_valid_no_patterns(self):
        result = self.v.validate_postal_codes("")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_parse_strips_and_drops_blanks(self):
        parsed = self.v._parse_postal_codes(" 1000 , ,2000,  3000 ")
        self.assertEqual(parsed, ["1000", "2000", "3000"])

    # ----------------------------------------------------------- simple patterns

    def test_valid_simple_nl_codes(self):
        result = self.v.validate_postal_codes("1000,2500,9999")
        self.assertTrue(result.is_valid, result.errors)
        self.assertEqual(self.v.context["valid_patterns"], ["1000", "2500", "9999"])
        self.assertEqual(self.v.context["invalid_patterns"], [])

    def test_invalid_simple_nl_code_rejected(self):
        # NL pattern is ^[1-9][0-9]{3}$ -> leading zero and 3-digit codes invalid
        result = self.v.validate_postal_codes("0999,123")
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 2)
        self.assertIn("0999", self.v.context["invalid_patterns"])
        self.assertIn("123", self.v.context["invalid_patterns"])

    def test_country_without_pattern_falls_back_to_alphanumeric(self):
        # Unknown country -> no regex -> alphanumeric fallback in _validate_simple_postal_code
        v = PostalCodeValidator(default_country="ZZ")
        ok = v.validate_single_pattern("ABC123")
        self.assertTrue(ok.is_valid, ok.errors)
        bad = v.validate_single_pattern("AB-12")  # not a range (has '-'? -> treated as range) so use space
        # '12 34' contains a space -> alphanumeric check fails
        bad2 = v.validate_single_pattern("12 34")
        self.assertFalse(bad2.is_valid)

    # ------------------------------------------------------------ range patterns

    def test_valid_range_pattern(self):
        result = self.v.validate_single_pattern("1000-1099")
        self.assertTrue(result.is_valid, result.errors)

    def test_range_start_greater_than_end_rejected(self):
        result = self.v.validate_single_pattern("2000-1000")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("cannot be greater" in e for e in result.errors))

    def test_range_with_invalid_endpoint_rejected(self):
        result = self.v.validate_single_pattern("1000-123")  # 123 invalid NL code
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Invalid end of range" in e for e in result.errors))

    # --------------------------------------------------------- wildcard patterns

    def test_valid_wildcard_pattern(self):
        result = self.v.validate_single_pattern("10*")
        self.assertTrue(result.is_valid, result.errors)

    def test_wildcard_must_be_at_end(self):
        result = self.v.validate_single_pattern("1*0")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("must be at the end" in e for e in result.errors))

    def test_multiple_wildcards_rejected(self):
        result = self.v.validate_single_pattern("1**")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Multiple wildcards" in e for e in result.errors))

    def test_wildcard_without_base_rejected(self):
        result = self.v.validate_single_pattern("*")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("must have a base" in e for e in result.errors))

    def test_short_wildcard_base_warns(self):
        result = self.v.validate_single_pattern("1*")
        self.assertTrue(result.is_valid)
        self.assertTrue(any("very short" in w for w in result.warnings))

    # ----------------------------------------------------- wildcard-range patterns

    def test_valid_wildcard_range(self):
        result = self.v.validate_single_pattern("10*-50*")
        self.assertTrue(result.is_valid, result.errors)

    def test_wildcard_range_mismatched_base_length_rejected(self):
        result = self.v.validate_single_pattern("10*-500*")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("same length" in e for e in result.errors))

    def test_wildcard_range_start_gt_end_rejected(self):
        result = self.v.validate_single_pattern("50*-10*")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("cannot be greater" in e for e in result.errors))

    # ----------------------------------------------------------- max patterns cap

    def test_exceeding_max_patterns_rejected(self):
        v = PostalCodeValidator()
        v.max_patterns = 3
        result = v.validate_postal_codes("1000,2000,3000,4000")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Maximum" in e for e in result.errors))

    # ==================================================== test_postal_code_match

    def test_match_simple_exact(self):
        self.assertTrue(self.v.test_postal_code_match("1234", ["1234"]))
        self.assertFalse(self.v.test_postal_code_match("1234", ["1235"]))

    def test_match_empty_inputs_return_false(self):
        self.assertFalse(self.v.test_postal_code_match("", ["1234"]))
        self.assertFalse(self.v.test_postal_code_match("1234", []))

    def test_match_numeric_range(self):
        self.assertTrue(self.v.test_postal_code_match("1050", ["1000-1099"]))
        self.assertFalse(self.v.test_postal_code_match("1100", ["1000-1099"]))
        # boundaries inclusive
        self.assertTrue(self.v.test_postal_code_match("1000", ["1000-1099"]))
        self.assertTrue(self.v.test_postal_code_match("1099", ["1000-1099"]))

    def test_match_wildcard(self):
        self.assertTrue(self.v.test_postal_code_match("1099", ["10*"]))
        self.assertFalse(self.v.test_postal_code_match("2099", ["10*"]))

    def test_match_wildcard_range(self):
        # 1*-3* covers prefixes 1..3 of length 1
        self.assertTrue(self.v.test_postal_code_match("2500", ["1*-3*"]))
        self.assertFalse(self.v.test_postal_code_match("4500", ["1*-3*"]))

    def test_match_wildcard_range_prefix_too_short_returns_false(self):
        # base length 2 but code shorter than 2 chars
        self.assertFalse(self.v.test_postal_code_match("1", ["10*-50*"]))

    def test_match_first_of_multiple_patterns_short_circuits(self):
        self.assertTrue(self.v.test_postal_code_match("9999", ["1000", "9*"]))

    def test_match_range_alphanumeric_string_comparison(self):
        # non-digit endpoints fall to string comparison branch
        self.assertTrue(self.v.test_postal_code_match("AB12", ["AA00-AZ99"]))

    def test_match_malformed_range_returns_false(self):
        # split on '-' producing != 2 parts is not reachable via _matches (guards),
        # but a value error inside _matches_range yields False
        self.assertFalse(self.v._matches_range("1234", "not-a-real-range-xx"))

    # ============================================================ get_pattern_summary

    def test_pattern_summary_counts_types(self):
        summary = self.v.get_pattern_summary("1234,1000-1099,10*,1*-3*")
        self.assertEqual(summary["total_patterns"], 4)
        self.assertEqual(summary["pattern_types"]["simple"], 1)
        self.assertEqual(summary["pattern_types"]["wildcard"], 1)
        # both range and wildcard-range counted under "range"
        self.assertEqual(summary["pattern_types"]["range"], 2)
        self.assertIn("coverage_estimate", summary)

    def test_pattern_summary_empty(self):
        summary = self.v.get_pattern_summary("")
        self.assertEqual(summary["total_patterns"], 0)
        self.assertEqual(summary["valid_patterns"], [])

    def test_pattern_summary_separates_invalid(self):
        summary = self.v.get_pattern_summary("1234,123")
        self.assertEqual(summary["valid_patterns"], ["1234"])
        self.assertEqual(summary["invalid_patterns"], ["123"])

    # ============================================================ coverage estimate

    def test_coverage_estimate_numeric_range(self):
        cov = self.v._estimate_coverage(["1000-1099"])
        self.assertEqual(cov["range"], 100)  # 1099-1000+1

    def test_coverage_estimate_wildcard(self):
        cov = self.v._estimate_coverage(["10*"])
        # base "10" len 2 -> 10 ** (4-2) = 100
        self.assertEqual(cov["wildcard"], 100)

    def test_coverage_estimate_exact(self):
        cov = self.v._estimate_coverage(["1234"])
        self.assertEqual(cov["exact"], 1)

    def test_coverage_estimate_wildcard_range_numeric(self):
        cov = self.v._estimate_coverage(["1*-3*"])
        # bases 1..3 => 3 bases, codes_per_base = 10 ** (4-1) = 1000 -> 3000
        self.assertEqual(cov["range"], 3000)

    # ============================================================ optimizations

    def test_suggest_optimizations_finds_consecutive_run(self):
        suggestions = self.v.suggest_optimizations("1000,1001,1002,2000")
        self.assertEqual(len(suggestions), 1)
        self.assertIn("1000-1002", suggestions[0])

    def test_suggest_optimizations_ignores_short_runs(self):
        # only 2 consecutive -> below the 3+ threshold
        suggestions = self.v.suggest_optimizations("1000,1001,3000")
        self.assertEqual(suggestions, [])

    def test_suggest_optimizations_empty(self):
        self.assertEqual(self.v.suggest_optimizations(""), [])


if __name__ == "__main__":
    frappe.init(site="test_site_2")
    frappe.connect()
    import unittest

    unittest.main()
