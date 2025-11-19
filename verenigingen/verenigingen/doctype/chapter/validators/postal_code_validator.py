# verenigingen/verenigingen/doctype/chapter/validators/postal_codevalidator.py
import re
from typing import Dict, List

import frappe

from .base_validator import BaseValidator, ValidationResult


class PostalCodeValidator(BaseValidator):
    """Validator for postal code patterns"""

    # Default validation patterns for different countries
    COUNTRY_PATTERNS = {
        "NL": r"^[1-9][0-9]{3}$",  # Netherlands: 1000-9999
        "BE": r"^[1-9][0-9]{3}$",  # Belgium: 1000-9999
        "DE": r"^[0-9]{5}$",  # Germany: 00000-99999
        "US": r"^[0-9]{5}$",  # USA: 00000-99999
        "UK": r"^[A-Z]{1,2}[0-9][0-9A-Z]?$",  # UK: A0, A00, AA0, AA00
        "FR": r"^[0-9]{5}$",  # France: 00000-99999
    }

    def __init__(self, chapter_doc=None, default_country="NL"):
        super().__init__(chapter_doc)
        self.default_country = default_country
        self.max_patterns = self._get_setting("max_postal_patterns", 50)

    def validate_postal_codes(self, postal_codes: str) -> ValidationResult:
        """Validate postal code patterns string"""
        result = self.create_result()

        if not postal_codes:
            return result

        # Parse patterns
        patterns = self._parse_postal_codes(postal_codes)

        # Check maximum number of patterns
        if len(patterns) > self.max_patterns:
            result.add_error(
                ("Maximum {0} postal code patterns allowed, found {1}").format(
                    self.max_patterns, len(patterns)
                )
            )
            return result

        # Validate each pattern
        valid_patterns = []
        for pattern in patterns:
            pattern_result = self.validate_single_pattern(pattern)
            if pattern_result.is_valid:
                valid_patterns.append(pattern)
            else:
                result.merge(pattern_result)

        # Store valid patterns for reference
        self.context["valid_patterns"] = valid_patterns
        self.context["invalid_patterns"] = [p for p in patterns if p not in valid_patterns]

        return result

    def validate_single_pattern(self, pattern: str) -> ValidationResult:
        """Validate a single postal code pattern"""
        result = self.create_result()

        if not pattern:
            result.add_error(("Empty postal code pattern"))
            return result

        pattern = pattern.strip().upper()

        # Check pattern type and validate accordingly
        if self._is_range_pattern(pattern):
            range_result = self._validate_range_pattern(pattern)
            result.merge(range_result)
        elif self._is_wildcard_pattern(pattern):
            wildcard_result = self._validate_wildcard_pattern(pattern)
            result.merge(wildcard_result)
        else:
            # Simple postal code
            simple_result = self._validate_simple_postal_code(pattern)
            result.merge(simple_result)

        return result

    def _parse_postal_codes(self, postal_codes: str) -> List[str]:
        """Parse comma-separated postal codes into list"""
        if not postal_codes:
            return []

        return [p.strip() for p in postal_codes.split(",") if p.strip()]

    def _is_range_pattern(self, pattern: str) -> bool:
        """Check if pattern is a range (e.g., 1000-1099)"""
        return "-" in pattern and pattern.count("-") == 1

    def _is_wildcard_pattern(self, pattern: str) -> bool:
        """Check if pattern contains wildcards (e.g., 10)"""
        return "*" in pattern

    def _validate_range_pattern(self, pattern: str) -> ValidationResult:
        """Validate range pattern like 1000-1099"""
        result = self.create_result()

        parts = pattern.split("-")
        if len(parts) != 2:
            result.add_error(("Invalid range pattern: {0}").format(pattern))
            return result

        start, end = parts
        start = start.strip()
        end = end.strip()

        # Validate both parts are valid postal codes
        start_result = self._validate_simple_postal_code(start)
        end_result = self._validate_simple_postal_code(end)

        if not start_result.is_valid:
            result.add_error(("Invalid start of range: {0}").format(start))

        if not end_result.is_valid:
            result.add_error(("Invalid end of range: {0}").format(end))

        if start_result.is_valid and end_result.is_valid:
            # For numeric postal codes, ensure start <= end
            if start.isdigit() and end.isdigit():
                if int(start) > int(end):
                    result.add_error(
                        ("Range start {0} cannot be greater than range end {1}").format(start, end)
                    )

        return result

    def _validate_wildcard_pattern(self, pattern: str) -> ValidationResult:
        """Validate wildcard pattern like 10*"""
        result = self.create_result()

        # Check for valid wildcard usage
        if pattern.count("*") > 1:
            result.add_error(("Multiple wildcards not allowed: {0}").format(pattern))
            return result

        if not pattern.endswith("*"):
            result.add_error(("Wildcard must be at the end: {0}").format(pattern))
            return result

        # Validate the base part (without *)
        base = pattern[:-1]
        if not base:
            result.add_error(("Wildcard pattern must have a base: {0}").format(pattern))
            return result

        # Base should be alphanumeric
        if not re.match(r"^[A-Z0-9]+$", base):
            result.add_error(("Invalid base for wildcard pattern: {0}").format(base))
            return result

        # Check minimum base length
        min_base_length = 2
        if len(base) < min_base_length:
            result.add_warning(("Wildcard base '{0}' is very short, may match too many codes").format(base))

        return result

    def _validate_simple_postal_code(self, postal_code: str) -> ValidationResult:
        """Validate a simple postal code"""
        result = self.create_result()

        if not postal_code:
            result.add_error(("Empty postal code"))
            return result

        # Get validation pattern for country
        pattern = self._get_country_pattern(self.default_country)

        if pattern and not re.match(pattern, postal_code):
            result.add_error(
                ("Invalid postal code format for {0}: {1}").format(self.default_country, postal_code)
            )
        elif not pattern:
            # Fallback to basic alphanumeric validation
            if not re.match(r"^[A-Z0-9]+$", postal_code):
                result.add_error(("Postal code must be alphanumeric: {0}").format(postal_code))

        return result

    def _get_country_pattern(self, country_code: str) -> str:
        """Get regex pattern for country"""
        return self.COUNTRY_PATTERNS.get(country_code.upper())

    def test_postal_code_match(self, postal_code: str, patterns: List[str]) -> bool:
        """Test if a postal code matches any of the given patterns"""
        if not postal_code or not patterns:
            return False

        postal_code = postal_code.strip().upper()

        for pattern in patterns:
            if self._matches_pattern(postal_code, pattern.strip().upper()):
                return True

        return False

    def _matches_pattern(self, postal_code: str, pattern: str) -> bool:
        """Check if postal code matches a specific pattern"""
        if self._is_range_pattern(pattern):
            return self._matches_range(postal_code, pattern)
        elif self._is_wildcard_pattern(pattern):
            return self._matches_wildcard(postal_code, pattern)
        else:
            return postal_code == pattern

    def _matches_range(self, postal_code: str, range_pattern: str) -> bool:
        """Check if postal code matches range pattern"""
        try:
            start, end = range_pattern.split("-")
            start = start.strip()
            end = end.strip()

            # For numeric postal codes
            if postal_code.isdigit() and start.isdigit() and end.isdigit():
                return int(start) <= int(postal_code) <= int(end)

            # For alphanumeric, use string comparison (less precise)
            return start <= postal_code <= end
        except (ValueError, AttributeError):
            return False

    def _matches_wildcard(self, postal_code: str, wildcard_pattern: str) -> bool:
        """Check if postal code matches wildcard pattern"""
        base = wildcard_pattern[:-1]  # Remove the *
        return postal_code.startswith(base)

    def get_pattern_summary(self, postal_codes: str) -> Dict:
        """Get summary of postal code patterns"""
        if not postal_codes:
            return {"total_patterns": 0, "valid_patterns": [], "invalid_patterns": [], "pattern_types": {}}

        patterns = self._parse_postal_codes(postal_codes)
        valid_patterns = []
        invalid_patterns = []
        pattern_types = {"simple": 0, "range": 0, "wildcard": 0}

        for pattern in patterns:
            result = self.validate_single_pattern(pattern)
            if result.is_valid:
                valid_patterns.append(pattern)

                # Count pattern types
                if self._is_range_pattern(pattern):
                    pattern_types["range"] += 1
                elif self._is_wildcard_pattern(pattern):
                    pattern_types["wildcard"] += 1
                else:
                    pattern_types["simple"] += 1
            else:
                invalid_patterns.append(pattern)

        return {
            "total_patterns": len(patterns),
            "valid_patterns": valid_patterns,
            "invalid_patterns": invalid_patterns,
            "pattern_types": pattern_types,
            "coverage_estimate": self._estimate_coverage(valid_patterns),
        }

    def _estimate_coverage(self, patterns: List[str]) -> Dict:
        """Estimate how many postal codes are covered by patterns"""
        # This is a rough estimate
        coverage = {"exact": 0, "range": 0, "wildcard": 0}

        for pattern in patterns:
            if self._is_range_pattern(pattern):
                try:
                    start, end = pattern.split("-")
                    if start.isdigit() and end.isdigit():
                        coverage["range"] += int(end) - int(start) + 1
                    else:
                        coverage["range"] += 10  # Rough estimate
                except Exception:
                    coverage["range"] += 10
            elif self._is_wildcard_pattern(pattern):
                base = pattern[:-1]
                # Rough estimate based on base length
                if base.isdigit():
                    coverage["wildcard"] += 10 ** (4 - len(base))  # Assume 4-digit postal codes
                else:
                    coverage["wildcard"] += 100  # Rough estimate
            else:
                coverage["exact"] += 1

        return coverage

    def suggest_optimizations(self, postal_codes: str) -> List[str]:
        """Suggest optimizations for postal code patterns"""
        suggestions = []

        if not postal_codes:
            return suggestions

        patterns = self._parse_postal_codes(postal_codes)

        # Look for consecutive postal codes that could be ranges
        numeric_patterns = [p for p in patterns if p.isdigit()]
        numeric_patterns.sort()

        ranges = []
        current_range = [numeric_patterns[0]] if numeric_patterns else []

        for i in range(1, len(numeric_patterns)):
            prev = int(numeric_patterns[i - 1])
            curr = int(numeric_patterns[i])

            if curr == prev + 1:
                if len(current_range) == 1:
                    current_range.append(numeric_patterns[i])
                else:
                    current_range[-1] = numeric_patterns[i]
            else:
                if len(current_range) > 1:
                    ranges.append(current_range)
                current_range = [numeric_patterns[i]]

        if len(current_range) > 1:
            ranges.append(current_range)

        for range_patterns in ranges:
            if len(range_patterns) >= 3:  # Only suggest if 3+ consecutive codes
                suggestions.append(
                    ("Consider using range {0}-{1} instead of individual codes {2}").format(
                        range_patterns[0], range_patterns[-1], ", ".join(range_patterns)
                    )
                )

        return suggestions

    def _get_setting(self, setting_name: str, default_value):
        """Get setting from Verenigingen Settings"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return getattr(settings, setting_name, default_value)
        except Exception:
            return default_value
