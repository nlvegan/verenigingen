"""
Test Fixture Validation System

Validates that required fixtures are loaded before running tests.
Prevents cryptic errors like "LinkValidationError: Could not find Region: Utrecht"
by providing clear diagnostic messages about missing fixtures.

Author: Verenigingen Development Team
Created: 2025-10-08
"""

import frappe
from typing import Dict, List, Optional, Set


class FixtureValidator:
    """
    Validates required fixtures are loaded in the test database.

    Provides clear error messages and suggestions when fixtures are missing.
    """

    # Define required fixtures by category
    REQUIRED_FIXTURES = {
        "roles": [
            "Verenigingen Administrator",
            "Verenigingen Member",
            "Verenigingen Staff",
            "Verenigingen Chapter Board Member",
            "Verenigingen Volunteer",
            "Chapter Leader",  # Added in test infrastructure fixes
        ],
        "regions": [
            "Utrecht",
            "Noord-Holland",
            "Zuid-Holland",
        ],
        "membership_types": [
            # Optional - tests usually create their own
        ],
        "chapter_roles": [
            # Optional - tests usually create their own
        ],
    }

    # Fixtures that are optional but commonly needed
    OPTIONAL_FIXTURES = {
        "payment_modes": ["Cash", "Bank Transfer", "SEPA Direct Debit"],
        "teams": [],  # Tests create their own
    }

    def __init__(self, strict_mode: bool = False):
        """
        Initialize fixture validator.

        Args:
            strict_mode: If True, also validate optional fixtures
        """
        self.strict_mode = strict_mode
        self.missing_fixtures: Dict[str, List[str]] = {}
        self.validation_passed = False

    def validate(self, categories: Optional[List[str]] = None) -> bool:
        """
        Validate required fixtures exist.

        Args:
            categories: Specific categories to validate. If None, validates all.

        Returns:
            bool: True if all required fixtures exist

        Raises:
            FixtureValidationError: If required fixtures are missing (only in strict mode)
        """
        self.missing_fixtures = {}

        # Determine which fixtures to check
        fixtures_to_check = self.REQUIRED_FIXTURES
        if self.strict_mode:
            fixtures_to_check = {**self.REQUIRED_FIXTURES, **self.OPTIONAL_FIXTURES}

        # Filter by categories if specified
        if categories:
            fixtures_to_check = {
                cat: fixtures_to_check[cat]
                for cat in categories
                if cat in fixtures_to_check
            }

        # Validate each category
        for category, fixture_names in fixtures_to_check.items():
            if not fixture_names:
                continue  # Skip empty categories

            missing = self._validate_category(category, fixture_names)
            if missing:
                self.missing_fixtures[category] = missing

        self.validation_passed = len(self.missing_fixtures) == 0
        return self.validation_passed

    def _validate_category(self, category: str, fixture_names: List[str]) -> List[str]:
        """Validate fixtures in a specific category"""
        doctype_map = {
            "roles": "Role",
            "regions": "Region",
            "membership_types": "Membership Type",
            "chapter_roles": "Chapter Role",
            "payment_modes": "Mode of Payment",
            "teams": "Team",
        }

        doctype = doctype_map.get(category)
        if not doctype:
            return []  # Unknown category, skip

        missing = []
        for fixture_name in fixture_names:
            if not frappe.db.exists(doctype, fixture_name):
                missing.append(fixture_name)

        return missing

    def get_validation_report(self) -> str:
        """
        Generate a human-readable validation report.

        Returns:
            str: Formatted report of validation results
        """
        if self.validation_passed:
            return "✅ All required fixtures are loaded"

        report_lines = [
            "❌ Missing Required Fixtures",
            "=" * 50,
            "",
            "The following fixtures are missing from your test database:",
            ""
        ]

        for category, missing_items in self.missing_fixtures.items():
            report_lines.append(f"📋 {category.upper()}:")
            for item in missing_items:
                report_lines.append(f"  - {item}")
            report_lines.append("")

        report_lines.extend([
            "💡 HOW TO FIX:",
            "=" * 50,
            "",
            "1. Load fixtures from the repository:",
            "   bench --site dev.veganisme.net import-doc /home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/",
            "",
            "2. Or load specific fixture files:",
            "   bench --site dev.veganisme.net import-doc /path/to/fixture.json",
            "",
            "3. Clear cache after loading:",
            "   bench --site dev.veganisme.net clear-cache",
            "",
        ])

        return "\n".join(report_lines)

    def print_validation_report(self):
        """Print validation report to console"""
        print(self.get_validation_report())

    def assert_valid(self, message: Optional[str] = None):
        """
        Assert that validation passed, raise error if not.

        Args:
            message: Optional custom error message

        Raises:
            FixtureValidationError: If validation failed
        """
        if not self.validation_passed:
            error_message = message or self.get_validation_report()
            raise FixtureValidationError(error_message)


class FixtureValidationError(Exception):
    """Raised when required fixtures are missing"""
    pass


def validate_test_fixtures(
    strict_mode: bool = False,
    categories: Optional[List[str]] = None,
    quiet: bool = False
) -> bool:
    """
    Convenience function to validate test fixtures.

    Args:
        strict_mode: If True, also validate optional fixtures
        categories: Specific categories to validate
        quiet: If True, don't print validation report

    Returns:
        bool: True if validation passed

    Example:
        ```python
        # In test setUp:
        if not validate_test_fixtures(categories=["roles", "regions"]):
            self.skipTest("Required fixtures not loaded")
        ```
    """
    validator = FixtureValidator(strict_mode=strict_mode)
    validator.validate(categories=categories)

    if not quiet and not validator.validation_passed:
        validator.print_validation_report()

    return validator.validation_passed


def get_missing_fixtures(categories: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Get dictionary of missing fixtures by category.

    Args:
        categories: Specific categories to check

    Returns:
        Dict mapping category names to lists of missing fixture names
    """
    validator = FixtureValidator()
    validator.validate(categories=categories)
    return validator.missing_fixtures
