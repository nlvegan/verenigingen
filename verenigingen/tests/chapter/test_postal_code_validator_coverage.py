"""
Supplemental coverage tests for the chapter ``PostalCodeValidator``
(``verenigingen/verenigingen/doctype/chapter/validators/postal_code_validator.py``).

The existing ``test_postal_code_validator.py`` is already thorough; this file pins
the few remaining uncovered branches:

* empty-pattern / empty-postal-code error paths
  (``validate_single_pattern("")``, ``_validate_simple_postal_code("")``)
* invalid wildcard base (non-alphanumeric)
* the ``validate_postal_codes`` path that MERGES per-pattern errors and records
  both valid and invalid patterns in ``context``
* ``_estimate_coverage`` for the *non-numeric* range / wildcard-range / wildcard
  branches (string bases -> the rough fallbacks)
* ``_matches_pattern`` dispatch for a wildcard-range pattern
* ``_get_setting`` reading a real value from Verenigingen Settings (DB-backed)
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.chapter.validators.postal_code_validator import (
    PostalCodeValidator,
)


class TestPostalCodeValidatorCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = PostalCodeValidator()

    # ----------------------------------------------------------- empty inputs

    def test_validate_single_pattern_empty_errors(self):
        result = self.v.validate_single_pattern("")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Empty postal code pattern" in e for e in result.errors))

    def test_validate_simple_postal_code_empty_errors(self):
        result = self.v._validate_simple_postal_code("")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Empty postal code" in e for e in result.errors))

    # --------------------------------------------------- invalid wildcard base

    def test_wildcard_base_non_alphanumeric_rejected(self):
        # base "1.0" contains a dot -> fails the ^[A-Z0-9]+$ base check
        result = self.v.validate_single_pattern("1.0*")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Invalid base for wildcard pattern" in e for e in result.errors))

    # -------------------------------- validate_postal_codes merges invalids

    def test_validate_postal_codes_records_valid_and_invalid(self):
        # mix of one valid NL code and one invalid (3-digit) code
        result = self.v.validate_postal_codes("1234, 123")
        self.assertFalse(result.is_valid)
        self.assertEqual(self.v.context["valid_patterns"], ["1234"])
        self.assertEqual(self.v.context["invalid_patterns"], ["123"])
        # the invalid code produced at least one merged error
        self.assertTrue(len(result.errors) >= 1)

    # ------------------------------------- _estimate_coverage non-numeric paths

    def test_estimate_coverage_alpha_range_fallback(self):
        # alphanumeric range endpoints -> the "rough estimate" 10 branch
        cov = self.v._estimate_coverage(["AA00-AZ99"])
        self.assertEqual(cov["range"], 10)

    def test_estimate_coverage_alpha_wildcard_range_fallback(self):
        # alphanumeric wildcard-range bases -> the "rough estimate" 100 branch
        cov = self.v._estimate_coverage(["AA*-AZ*"])
        self.assertEqual(cov["range"], 100)

    def test_estimate_coverage_alpha_wildcard_fallback(self):
        # non-digit wildcard base -> the 100 fallback
        cov = self.v._estimate_coverage(["AB*"])
        self.assertEqual(cov["wildcard"], 100)

    # ------------------------------------------- _matches_pattern dispatch

    def test_matches_pattern_dispatches_wildcard_range(self):
        # routes through _matches_pattern -> _matches_wildcard_range
        self.assertTrue(self.v._matches_pattern("2500", "1*-3*"))
        self.assertFalse(self.v._matches_pattern("4500", "1*-3*"))

    def test_matches_pattern_simple_equality(self):
        self.assertTrue(self.v._matches_pattern("1234", "1234"))
        self.assertFalse(self.v._matches_pattern("1234", "1235"))

    # --------------------------------------------------------- _get_setting

    def test_get_setting_reads_default_when_unset(self):
        # max_patterns is read from Verenigingen Settings at __init__; with no
        # custom setting it falls back to the documented default of 50.
        v = PostalCodeValidator()
        self.assertEqual(v.max_patterns, 50)

    def test_get_setting_returns_provided_default_for_unknown_key(self):
        # An attribute that does not exist on the Settings single returns the default.
        v = PostalCodeValidator()
        self.assertEqual(v._get_setting("definitely_not_a_real_setting_xyz", 7), 7)


if __name__ == "__main__":
    import unittest

    unittest.main()
