#!/usr/bin/env python3
"""
Quick test of BIC derivation to identify the issue
"""

# Test the IBAN validation first
test_iban = "NL91INGB0001234567"

print("=== Testing BIC Derivation Issue ===")
print(f"Test IBAN: {test_iban}")

# Test IBAN cleaning
iban_clean = test_iban.replace(" ", "").upper()
print(f"Cleaned IBAN: {iban_clean}")

# Extract components
country_code = iban_clean[:2]
bank_code = iban_clean[4:8]
print(f"Country: {country_code}, Bank Code: {bank_code}")

# Test BIC mapping
nl_bic_codes = {
    "INGB": "INGBNL2A",
    "ABNA": "ABNANL2A",
    "RABO": "RABONL2U",
    "TRIO": "TRIONL2U",
}

expected_bic = nl_bic_codes.get(bank_code)
print(f"Expected BIC: {expected_bic}")

print("\n=== Testing Actual Functions ===")

try:
    # Import the actual functions
    import sys

    sys.path.append("/home/frappe/frappe-bench/apps/verenigingen")

    from verenigingen.utils.iban_validator import derive_bic_from_iban, validate_iban

    # Test IBAN validation
    validation_result = validate_iban(test_iban)
    print(f"IBAN Validation: {validation_result}")

    # Test BIC derivation
    bic_result = derive_bic_from_iban(test_iban)
    print(f"BIC Derivation: {bic_result}")
    print(f"BIC Type: {type(bic_result)}")

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
