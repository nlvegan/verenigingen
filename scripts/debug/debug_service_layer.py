#!/usr/bin/env python3
"""
Debug script to test Phase 3 service layer implementation
Run via: bench --site dev.veganisme.net console < debug_service_layer.py
"""

print("=== Phase 3 Service Layer Testing ===")

# Test 1: Import the service layer
try:
    from verenigingen.utils.services.sepa_service import SEPAService, get_sepa_service

    print("✅ Service layer import successful")

    # Test service factory
    service = get_sepa_service()
    print(f"✅ Service factory: {type(service)}")

except Exception as e:
    print(f"❌ Service layer import failed: {e}")

# Test 2: IBAN validation
try:
    print("\n--- IBAN Validation Tests ---")
    test_ibans = [
        ("NL91ABNA0417164300", True, "Valid real IBAN"),
        ("NL13TEST0123456789", True, "TEST mock bank"),
        ("NL82MOCK0123456789", True, "MOCK bank"),
        ("NL93DEMO0123456789", True, "DEMO bank"),
        ("INVALID", False, "Invalid IBAN"),
        ("", False, "Empty IBAN"),
    ]

    for iban, expected, description in test_ibans:
        result = SEPAService.validate_iban(iban)
        status = "✅" if result == expected else "❌"
        print(f"{status} {description}: {iban} -> {result}")

except Exception as e:
    print(f"❌ IBAN validation tests failed: {e}")

# Test 3: BIC derivation
try:
    print("\n--- BIC Derivation Tests ---")
    test_cases = [
        ("NL13TEST0123456789", "TESTNL2A"),
        ("NL82MOCK0123456789", "MOCKNL2A"),
        ("NL93DEMO0123456789", "DEMONL2A"),
        ("NL91ABNA0417164300", "ABNANL2A"),
    ]

    for iban, expected_bic in test_cases:
        result = SEPAService.derive_bic_from_iban(iban)
        status = "✅" if result == expected_bic else "❌"
        print(f"{status} {iban} -> {result} (expected: {expected_bic})")

except Exception as e:
    print(f"❌ BIC derivation tests failed: {e}")

# Test 4: Input validation
try:
    print("\n--- Input Validation Tests ---")
    test_cases = [
        ("Test-Member-001", "NL91ABNA0417164300", True, "Valid inputs"),
        ("Test';DROP TABLE", "NL91ABNA0417164300", False, "SQL injection attempt"),
        ("Test<script>", "NL91ABNA0417164300", False, "XSS attempt"),
        ("", "NL91ABNA0417164300", False, "Empty member name"),
        ("Test-Member-001", "", False, "Empty IBAN"),
    ]

    for member, iban, expected, description in test_cases:
        result = SEPAService.validate_inputs(member, iban)
        status = "✅" if result == expected else "❌"
        print(f"{status} {description}: {result}")

except Exception as e:
    print(f"❌ Input validation tests failed: {e}")

# Test 5: Method availability
try:
    print("\n--- Service Methods Check ---")
    methods = [
        "create_mandate_enhanced",
        "validate_inputs",
        "validate_iban",
        "derive_bic_from_iban",
        "get_active_mandates",
        "get_active_mandate_by_iban",
        "cancel_mandate",
        "get_mandate_usage_statistics",
    ]

    for method in methods:
        has_method = hasattr(SEPAService, method)
        status = "✅" if has_method else "❌"
        print(f"{status} {method}")

except Exception as e:
    print(f"❌ Method availability check failed: {e}")

# Test 6: API endpoints
try:
    print("\n--- API Endpoints Check ---")
    from verenigingen.utils.services.sepa_service import (
        cancel_mandate_via_service,
        create_sepa_mandate_via_service,
        get_member_mandates_via_service,
    )

    print("✅ create_sepa_mandate_via_service")
    print("✅ get_member_mandates_via_service")
    print("✅ cancel_mandate_via_service")

except Exception as e:
    print(f"❌ API endpoints check failed: {e}")

# Test 7: Mixin integration
try:
    print("\n--- Mixin Integration Check ---")
    from verenigingen.verenigingen.doctype.member.mixins.sepa_mixin import SEPAMandateMixin

    has_service_method = hasattr(SEPAMandateMixin, "create_sepa_mandate_via_service")
    has_old_method = hasattr(SEPAMandateMixin, "create_sepa_mandate")

    status1 = "✅" if has_service_method else "❌"
    status2 = "✅" if has_old_method else "❌"

    print(f"{status1} Service integration method available")
    print(f"{status2} Backward compatibility (old method available)")

except Exception as e:
    print(f"❌ Mixin integration check failed: {e}")

print("\n=== Phase 3 Service Layer Testing Complete ===")
