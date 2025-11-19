#!/usr/bin/env python3
"""
Test script to verify fixture validator works correctly.

Usage:
    python scripts/test_fixture_validator.py
"""

import sys
import os

# Add the apps directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import frappe
from verenigingen.tests.utils.fixture_validator import (
    FixtureValidator,
    validate_test_fixtures,
    get_missing_fixtures
)


def test_fixture_validator():
    """Test the fixture validator functionality"""
    print("\n" + "=" * 60)
    print("Testing Fixture Validator")
    print("=" * 60 + "\n")

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    # Test 1: Validate all required fixtures
    print("Test 1: Validating required fixtures...")
    validator = FixtureValidator(strict_mode=False)
    validation_passed = validator.validate()

    if validation_passed:
        print("✅ All required fixtures are loaded!\n")
    else:
        print("❌ Some fixtures are missing:\n")
        validator.print_validation_report()

    # Test 2: Get missing fixtures programmatically
    print("\nTest 2: Getting missing fixtures programmatically...")
    missing = get_missing_fixtures(categories=["roles", "regions"])
    if missing:
        print(f"Missing fixtures: {missing}")
    else:
        print("✅ No missing fixtures in checked categories\n")

    # Test 3: Validate specific categories
    print("\nTest 3: Validating only roles...")
    roles_valid = validate_test_fixtures(categories=["roles"], quiet=True)
    print(f"Roles validation: {'✅ PASSED' if roles_valid else '❌ FAILED'}")

    print("\nTest 4: Validating only regions...")
    regions_valid = validate_test_fixtures(categories=["regions"], quiet=True)
    print(f"Regions validation: {'✅ PASSED' if regions_valid else '❌ FAILED'}")

    # Test 5: Check specific fixtures exist
    print("\n" + "=" * 60)
    print("Checking individual fixtures:")
    print("=" * 60)

    required_roles = [
        "Verenigingen Administrator",
        "Verenigingen Member",
        "Chapter Leader"
    ]

    for role_name in required_roles:
        exists = frappe.db.exists("Role", role_name)
        status = "✅" if exists else "❌"
        print(f"{status} Role: {role_name}")

    required_regions = ["Utrecht", "Noord-Holland", "Zuid-Holland"]
    print()
    for region_name in required_regions:
        exists = frappe.db.exists("Region", region_name)
        status = "✅" if exists else "❌"
        print(f"{status} Region: {region_name}")

    print("\n" + "=" * 60)
    print("Fixture validation test complete!")
    print("=" * 60 + "\n")

    frappe.destroy()


if __name__ == "__main__":
    test_fixture_validator()
