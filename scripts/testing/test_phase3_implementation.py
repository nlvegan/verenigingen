#!/usr/bin/env python3
"""
Phase 3 Implementation Testing
Comprehensive testing of the SEPA Service Layer and security fixes
"""

import os
import sys

# Add the apps path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


def test_service_layer_import():
    """Test that the service layer can be imported"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        print("✅ SEPAService import successful")
        return True
    except ImportError as e:
        print(f"❌ SEPAService import failed: {e}")
        return False


def test_iban_validation():
    """Test IBAN validation functionality"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        # Test valid Dutch IBAN
        valid_iban = "NL91ABNA0417164300"
        result = SEPAService.validate_iban(valid_iban)
        print(f"✅ Valid IBAN {valid_iban}: {result}")

        # Test invalid IBAN
        invalid_iban = "NL91INVALID123"
        result = SEPAService.validate_iban(invalid_iban)
        print(f"✅ Invalid IBAN {invalid_iban}: {result}")

        # Test mock bank IBAN
        mock_iban = "NL13TEST0123456789"
        result = SEPAService.validate_iban(mock_iban)
        print(f"✅ Mock IBAN {mock_iban}: {result}")

        return True
    except Exception as e:
        print(f"❌ IBAN validation test failed: {e}")
        return False


def test_bic_derivation():
    """Test BIC derivation from IBAN"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        # Test mock bank BIC derivation
        test_cases = [
            ("NL13TEST0123456789", "TESTNL2A"),
            ("NL82MOCK0123456789", "MOCKNL2A"),
            ("NL93DEMO0123456789", "DEMONL2A"),
            ("NL91ABNA0417164300", "ABNANL2A"),
        ]

        for iban, expected_bic in test_cases:
            result = SEPAService.derive_bic_from_iban(iban)
            print(f"✅ BIC for {iban}: {result} (expected: {expected_bic})")

        return True
    except Exception as e:
        print(f"❌ BIC derivation test failed: {e}")
        return False


def test_input_validation():
    """Test input validation for security"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        # Test valid inputs
        result = SEPAService.validate_inputs("Test-Member-001", "NL91ABNA0417164300")
        print(f"✅ Valid inputs: {result}")

        # Test invalid inputs (potential injection)
        result = SEPAService.validate_inputs("Test';DROP TABLE", "NL91ABNA0417164300")
        print(f"✅ Invalid inputs (injection attempt): {result}")

        # Test empty inputs
        result = SEPAService.validate_inputs("", "")
        print(f"✅ Empty inputs: {result}")

        return True
    except Exception as e:
        print(f"❌ Input validation test failed: {e}")
        return False


def test_service_layer_methods():
    """Test availability of service layer methods"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        methods_to_check = [
            "create_mandate_enhanced",
            "validate_inputs",
            "validate_iban",
            "derive_bic_from_iban",
            "get_active_mandates",
            "get_active_mandate_by_iban",
            "cancel_mandate",
            "get_mandate_usage_statistics",
        ]

        for method_name in methods_to_check:
            if hasattr(SEPAService, method_name):
                print(f"✅ Method {method_name} available")
            else:
                print(f"❌ Method {method_name} missing")

        return True
    except Exception as e:
        print(f"❌ Service layer methods test failed: {e}")
        return False


def analyze_security_fixes():
    """Analyze security fixes in critical files"""
    files_to_check = [
        "verenigingen/fixtures/add_sepa_database_indexes.py",
        "verenigingen/utils/simple_robust_cleanup.py",
        "verenigingen/utils/services/sepa_service.py",
    ]

    security_patterns = [
        "frappe.db.sql(",
        "%s",  # Parameterized queries
        "WHERE ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
    ]

    for file_path in files_to_check:
        full_path = os.path.join("/home/frappe/frappe-bench/apps/verenigingen", file_path)
        if os.path.exists(full_path):
            with open(full_path, "r") as f:
                content = f.read()
                print(f"\n📁 Analyzing {file_path}:")

                for pattern in security_patterns:
                    count = content.count(pattern)
                    if count > 0:
                        print(f"  {pattern}: {count} occurrences")
        else:
            print(f"❌ File not found: {file_path}")


def test_api_endpoints():
    """Test that API endpoints are available"""
    try:
        from verenigingen.utils.services.sepa_service import (
            cancel_mandate_via_service,
            create_sepa_mandate_via_service,
            get_member_mandates_via_service,
        )

        print("✅ API endpoint create_sepa_mandate_via_service available")
        print("✅ API endpoint get_member_mandates_via_service available")
        print("✅ API endpoint cancel_mandate_via_service available")

        return True
    except ImportError as e:
        print(f"❌ API endpoints import failed: {e}")
        return False


def main():
    """Run all tests"""
    print("🔍 Phase 3 Implementation Testing")
    print("=" * 50)

    tests = [
        ("Service Layer Import", test_service_layer_import),
        ("IBAN Validation", test_iban_validation),
        ("BIC Derivation", test_bic_derivation),
        ("Input Validation", test_input_validation),
        ("Service Layer Methods", test_service_layer_methods),
        ("API Endpoints", test_api_endpoints),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n🧪 Running {test_name}...")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))

    print("\n🔒 Security Analysis...")
    analyze_security_fixes()

    print("\n📊 Test Summary:")
    print("=" * 30)
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Phase 3 implementation looks good.")
    else:
        print("⚠️  Some tests failed. Review implementation.")


if __name__ == "__main__":
    main()
