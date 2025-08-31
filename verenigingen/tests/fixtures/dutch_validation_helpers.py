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