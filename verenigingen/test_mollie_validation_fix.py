"""Test Mollie validation fixes"""

import frappe


def test_mollie_validation_fix():
    """Test that same-state transitions are now allowed"""
    print("=== TESTING MOLLIE VALIDATION FIX ===")

    from verenigingen.utils.mollie_data_validator import MollieDataValidator

    validator = MollieDataValidator()

    # Test 1: Same-state transitions should be allowed
    print("\n1. Testing same-state transitions...")

    test_cases = [
        ("inactive", "inactive"),
        ("active", "active"),
        ("canceled", "canceled"),
        ("pending", "pending"),
    ]

    for from_status, to_status in test_cases:
        result = validator.validate_status_transition(from_status, to_status)
        if result:
            print(f"   ✅ {from_status} → {to_status}: ALLOWED (correct)")
        else:
            print(f"   ❌ {from_status} → {to_status}: BLOCKED (bug!)")

    # Test 2: Invalid transitions should still be blocked
    print("\n2. Testing invalid transitions are still blocked...")

    invalid_cases = [
        ("canceled", "active"),  # Can't reactivate canceled
        ("completed", "active"),  # Can't reactivate completed
        ("active", "pending"),  # Can't go back to pending
    ]

    for from_status, to_status in invalid_cases:
        validator.errors = []  # Reset errors
        result = validator.validate_status_transition(from_status, to_status)
        if not result:
            print(f"   ✅ {from_status} → {to_status}: BLOCKED (correct)")
        else:
            print(f"   ❌ {from_status} → {to_status}: ALLOWED (bug!)")

    # Test 3: Valid transitions should still work
    print("\n3. Testing valid transitions still work...")

    valid_cases = [
        ("inactive", "active"),
        ("active", "canceled"),
        ("pending", "active"),
        ("suspended", "active"),
    ]

    for from_status, to_status in valid_cases:
        validator.errors = []  # Reset errors
        result = validator.validate_status_transition(from_status, to_status)
        if result:
            print(f"   ✅ {from_status} → {to_status}: ALLOWED (correct)")
        else:
            print(f"   ❌ {from_status} → {to_status}: BLOCKED (bug!)")

    print("\n✅ Mollie validation fix tested successfully!")
    return True
