#!/usr/bin/env python3
"""
Generate valid test IBANs for SEPA mandate tests
"""


def calculate_iban_checksum(country_code, bank_code, account_number):
    """Calculate the correct checksum for an IBAN"""
    # Create IBAN without checksum (use 00 as placeholder)
    temp_iban = country_code + "00" + bank_code + account_number

    # Move first 4 characters to end
    rearranged = temp_iban[4:] + temp_iban[:4]

    # Convert letters to numbers (A=10, B=11, ..., Z=35)
    numeric_iban = ""
    for char in rearranged:
        if char.isdigit():
            numeric_iban += char
        else:
            numeric_iban += str(ord(char) - ord("A") + 10)

    # Calculate checksum (98 - (number mod 97))
    checksum = 98 - (int(numeric_iban) % 97)

    # Return as 2-digit string
    return f"{checksum:02d}"


def generate_valid_test_iban(bank_code, account_number="0001234567"):
    """Generate a valid test IBAN for a given bank code"""
    checksum = calculate_iban_checksum("NL", bank_code, account_number)
    return f"NL{checksum}{bank_code}{account_number}"


# Generate valid IBANs for the banks in the test
test_banks = [
    ("ABNA", "ABNANL2A"),  # ABN AMRO
    ("INGB", "INGBNL2A"),  # ING Bank
    ("RABO", "RABONL2U"),  # Rabobank
    ("TRIO", "TRIONL2U"),  # Triodos Bank
]

print("=== Valid Test IBANs for SEPA Tests ===")
for bank_code, expected_bic in test_banks:
    valid_iban = generate_valid_test_iban(bank_code)
    print(f'("{valid_iban}", "{expected_bic}"),  # {bank_code}')
