"""
Dutch Validation Helpers for Test Data Generation
=================================================

Utilities for generating valid Dutch tax identifiers (BSN/RSIN) and other 
compliance data for real database testing.

This addresses the critical issue identified in the code review where 
invalid BSN numbers were causing all ANBI tests to fail.
"""

import random


def generate_valid_bsn():
    """
    Generate a valid Dutch BSN (Burgerservicenummer) that passes eleven-proof validation.
    
    The eleven-proof validation algorithm:
    1. Take the first 8 digits
    2. Multiply by weights [9, 8, 7, 6, 5, 4, 3, 2]  
    3. Sum the products
    4. The 9th digit should make the sum divisible by 11
    5. Special case: if 9th digit would be 10, check if sum+1 is divisible by 11
    
    Returns:
        str: Valid BSN that passes eleven-proof validation
    """
    while True:
        # Generate first 8 digits randomly
        first_eight = [random.randint(1, 9) if i == 0 else random.randint(0, 9) for i in range(8)]
        
        # Calculate weighted sum
        weights = [9, 8, 7, 6, 5, 4, 3, 2]
        weighted_sum = sum(digit * weight for digit, weight in zip(first_eight, weights))
        
        # Calculate 9th digit that makes sum divisible by 11
        remainder = weighted_sum % 11
        ninth_digit = (11 - remainder) % 11
        
        # Special case: if ninth_digit is 10, try the alternative calculation
        if ninth_digit == 10:
            # Alternative: check if weighted_sum - 1 is divisible by 11
            if (weighted_sum - 1) % 11 == 0:
                ninth_digit = 1
            else:
                continue  # Generate new number
        
        # Construct final BSN
        bsn_digits = first_eight + [ninth_digit]
        bsn = ''.join(map(str, bsn_digits))
        
        # Verify our calculation
        if validate_bsn(bsn):
            return bsn


def generate_valid_rsin():
    """
    Generate a valid Dutch RSIN (Rechtspersonen Samenwerkingsverbanden Informatienummer).
    
    RSIN uses the same eleven-proof validation as BSN but for organizations.
    Format: 9 digits that pass eleven-proof validation.
    
    Returns:
        str: Valid RSIN that passes eleven-proof validation
    """
    while True:
        # Generate first 8 digits randomly (RSIN can start with 0)
        first_eight = [random.randint(0, 9) for _ in range(8)]
        
        # Calculate weighted sum using RSIN weights
        weights = [9, 8, 7, 6, 5, 4, 3, 2]
        weighted_sum = sum(digit * weight for digit, weight in zip(first_eight, weights))
        
        # Calculate 9th digit that makes sum divisible by 11
        remainder = weighted_sum % 11
        ninth_digit = (11 - remainder) % 11
        
        # For RSIN, if ninth_digit is 10, it's invalid - try again
        if ninth_digit == 10:
            continue
        
        # Construct final RSIN
        rsin_digits = first_eight + [ninth_digit]
        rsin = ''.join(map(str, rsin_digits))
        
        # Verify our calculation
        if validate_rsin(rsin):
            return rsin


def validate_bsn(bsn_str):
    """
    Validate Dutch BSN using eleven-proof algorithm.
    
    Args:
        bsn_str (str): BSN to validate
        
    Returns:
        bool: True if BSN passes eleven-proof validation
    """
    if not bsn_str or len(bsn_str) != 9:
        return False
    
    try:
        digits = [int(d) for d in bsn_str]
    except ValueError:
        return False
    
    # Eleven-proof validation
    weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]  # Note: last weight is -1 for BSN
    weighted_sum = sum(digit * weight for digit, weight in zip(digits, weights))
    
    return weighted_sum % 11 == 0


def validate_rsin(rsin_str):
    """
    Validate Dutch RSIN using eleven-proof algorithm.
    
    Args:
        rsin_str (str): RSIN to validate
        
    Returns:
        bool: True if RSIN passes eleven-proof validation
    """
    if not rsin_str or len(rsin_str) != 9:
        return False
    
    try:
        digits = [int(d) for d in rsin_str]
    except ValueError:
        return False
    
    # Eleven-proof validation for RSIN
    weights = [9, 8, 7, 6, 5, 4, 3, 2, 1]  # Note: last weight is 1 for RSIN
    weighted_sum = sum(digit * weight for digit, weight in zip(digits, weights))
    
    return weighted_sum % 11 == 0


def get_test_bsn_numbers():
    """
    Get a set of pre-validated BSN numbers for consistent testing.
    
    Returns:
        list: List of valid BSN strings
    """
    # Pre-calculated valid BSNs for consistent test results
    return [
        "123456782",  # Common test BSN
        "111222333",  # Sequential test BSN  
        "999991905",  # Another common test BSN
        "111111110",  # Edge case test BSN
    ]


def get_test_rsin_numbers():
    """
    Get a set of pre-validated RSIN numbers for consistent testing.
    
    Returns:
        list: List of valid RSIN strings
    """
    # Pre-calculated valid RSINs for consistent test results
    # These numbers have been verified with validate_rsin()
    return [
        "555444333",  # Valid RSIN (original confirmed)
        "035123958",  # Valid RSIN (generated and verified)
        "959488413",  # Valid RSIN (generated and verified)  
        "986475297",  # Valid RSIN (generated and verified)
    ]


def validate_dutch_iban(iban):
    """
    Validate Dutch IBAN using mod-97 algorithm

    Args:
        iban (str): IBAN to validate

    Returns:
        dict: Validation result with is_valid boolean and error messages
    """
    if not iban:
        return {"is_valid": False, "error": "IBAN is required"}

    # Remove spaces and convert to uppercase
    iban_clean = iban.replace(" ", "").upper()

    # Check minimum length
    if len(iban_clean) < 15:
        return {"is_valid": False, "error": "IBAN too short"}

    # Check if it's Dutch IBAN
    if not iban_clean.startswith("NL"):
        return {"is_valid": False, "error": "Not a Dutch IBAN (must start with NL)"}

    # Dutch IBAN should be exactly 18 characters
    if len(iban_clean) != 18:
        return {"is_valid": False, "error": "Dutch IBAN must be exactly 18 characters"}

    # Dutch IBAN format: NL + 2 check digits + 4 letter bank code + 10 digit account number
    # Validate structure: NL + 2 digits + 4 letters + 10 digits
    if not iban_clean[2:4].isdigit():
        return {"is_valid": False, "error": "Check digits must be numeric"}
    if not iban_clean[4:8].isalpha():
        return {"is_valid": False, "error": "Bank code must be 4 letters"}
    if not iban_clean[8:].isdigit():
        return {"is_valid": False, "error": "Account number must be 10 digits"}

    # Perform mod-97 validation
    # Move first 4 characters to end and replace letters with numbers
    rearranged = iban_clean[4:] + iban_clean[:4]

    # Replace letters with numbers (A=10, B=11, ..., Z=35)
    numeric_string = ""
    for char in rearranged:
        if char.isdigit():
            numeric_string += char
        else:
            numeric_string += str(ord(char) - ord('A') + 10)

    # Calculate mod 97
    try:
        remainder = int(numeric_string) % 97
        if remainder == 1:
            return {"is_valid": True, "iban": iban_clean}
        else:
            return {"is_valid": False, "error": "IBAN checksum validation failed"}
    except ValueError:
        return {"is_valid": False, "error": "IBAN contains invalid characters"}


def get_test_dutch_ibans():
    """
    Return list of valid Dutch IBANs for testing

    Returns:
        list: Valid Dutch IBANs
    """
    return [
        "NL91ABNA0417164300",  # ABN AMRO
        "NL02RABO0123456789",  # Rabobank
        "NL86INGB0002445588",  # ING Bank
        "NL39TRIO0123456789",  # Triodos Bank
        "NL13TEST0123456789",  # Test bank
    ]


# Test the generators to ensure they work
if __name__ == "__main__":
    print("Testing BSN generation:")
    for i in range(5):
        bsn = generate_valid_bsn()
        is_valid = validate_bsn(bsn)
        print(f"  BSN: {bsn} - Valid: {is_valid}")
    
    print("\nTesting RSIN generation:")
    for i in range(5):
        rsin = generate_valid_rsin()
        is_valid = validate_rsin(rsin)
        print(f"  RSIN: {rsin} - Valid: {is_valid}")
        
    print("\nTesting pre-calculated numbers:")
    for bsn in get_test_bsn_numbers():
        print(f"  BSN: {bsn} - Valid: {validate_bsn(bsn)}")
    for rsin in get_test_rsin_numbers():
        print(f"  RSIN: {rsin} - Valid: {validate_rsin(rsin)}")