#!/usr/bin/env python3
"""
Test validation functions for Member CSV Import.
"""

import os
import sys

sys.path.append("/home/frappe/frappe-bench/apps/verenigingen")


# Test the validation functions directly
def test_validation_functions():
    """Test individual validation functions."""

    # Import the validation functions
    from verenigingen.verenigingen.doctype.member_csv_import.member_csv_import import MemberCSVImport

    # Create instance for testing
    import_doc = MemberCSVImport()

    print("Testing validation functions...")

    # Test email validation
    test_emails = [
        ("test@example.com", True),
        ("invalid-email", False),
        ("user+tag@domain.co.uk", True),
        ("@invalid.com", False),
        ("test@", False),
    ]

    print("\\nEmail validation tests:")
    for email, expected in test_emails:
        result = import_doc._is_valid_email(email)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {email}: {result} (expected {expected})")

    # Test IBAN validation
    test_ibans = [
        ("NL91ABNA0417164300", True),
        ("NL 91 ABNA 0417 1643 00", True),
        ("", False),
        ("123", False),
        ("1234567890", False),
    ]

    print("\\nIBAN validation tests:")
    for iban, expected in test_ibans:
        result = import_doc._is_valid_iban(iban)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{iban}': {result} (expected {expected})")

    # Test date parsing
    test_dates = [
        ("1990-01-15", "1990-01-15"),
        ("15-01-1990", "1990-01-15"),
        ("15/01/1990", "1990-01-15"),
        ("invalid-date", None),
        ("", None),
    ]

    print("\\nDate parsing tests:")
    for date_str, expected in test_dates:
        result = import_doc._parse_date(date_str)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{date_str}': {result} (expected {expected})")

    # Test value cleaning
    test_values = [
        ("€ 25,50", "dues_rate", 25.50),
        ("25.00", "dues_rate", 25.00),
        ("Ja", "privacy_accepted", True),
        ("Nee", "privacy_accepted", False),
        ("NL 91 ABNA 0417 1643 00", "iban", "NL91ABNA0417164300"),
        ("Test@Example.Com", "email", "test@example.com"),
    ]

    print("\\nValue cleaning tests:")
    for value, field_type, expected in test_values:
        result = import_doc._clean_value(value, field_type)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{value}' ({field_type}): {result} (expected {expected})")

    print("\\nAll validation tests completed!")


if __name__ == "__main__":
    test_validation_functions()
