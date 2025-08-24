"""
Test Mollie integration fixes after quality control improvements
"""
import frappe


def test_mollie_validator():
    """Test MollieDataValidator functionality"""
    print("Testing MollieDataValidator...")

    # Test validator creation
    try:
        from verenigingen.utils.mollie_data_validator import get_mollie_validator

        validator = get_mollie_validator()
        print("✓ MollieDataValidator created successfully")
    except Exception as e:
        print(f"✗ Failed to create validator: {e}")
        return False

    # Test valid data
    valid_data = {
        "custom_mollie_customer_id": "cst_1234567890abcd",
        "custom_mollie_subscription_id": "sub_1234567890abcd",
        "custom_subscription_status": "active",
    }

    is_valid, errors, warnings = validator.validate_customer_data(valid_data)
    if is_valid:
        print("✓ Valid Mollie data passes validation")
    else:
        print(f"✗ Valid data rejected: {errors}")
        return False

    # Test invalid data
    invalid_data = {
        "custom_mollie_customer_id": "invalid_format",
        "custom_mollie_subscription_id": "sub_1234567890abcd",
        "custom_subscription_status": "invalid_status",
    }

    is_valid, errors, warnings = validator.validate_customer_data(invalid_data)
    if not is_valid and len(errors) > 0:
        print("✓ Invalid Mollie data properly rejected")
    else:
        print("✗ Invalid data was accepted")
        return False

    return True


def test_csv_injection_prevention():
    """Test CSV injection prevention in mijnrood import"""
    print("Testing CSV injection prevention...")

    try:
        from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (
            MijnroodCSVImport,
        )

        import_doc = MijnroodCSVImport()

        # Test dangerous values that should be rejected
        dangerous_values = [
            "=cmd|'/bin/bash'!A1",  # Excel formula injection
            "+2+2+cmd|' /bin/bash'!A1",  # Addition formula
            "@SUM(1+1)*cmd|'/bin/bash'!A1",  # Function formula
            "\t=1+1",  # Tab character
            "-command",  # Command starting with dash (but longer than 1 char)
        ]

        for dangerous_value in dangerous_values:
            try:
                # This should throw an exception
                cleaned_value = import_doc._clean_value(dangerous_value, "test_field")
                print(f"✗ Dangerous value '{dangerous_value[:20]}...' was not rejected")
                return False
            except Exception as e:
                if "dangerous content" in str(e).lower() or "formula" in str(e).lower():
                    print(f"✓ Dangerous value properly rejected: {dangerous_value[:20]}...")
                else:
                    print(f"✗ Unexpected error for '{dangerous_value[:20]}...': {e}")
                    return False

        # Test safe values that should pass
        safe_values = ["-", "test@example.com", "John Doe", "123"]
        for safe_value in safe_values:
            try:
                cleaned_value = import_doc._clean_value(safe_value, "test_field")
                if cleaned_value is not None or safe_value == "-":  # "-" becomes None which is expected
                    print(f"✓ Safe value '{safe_value}' accepted")
                else:
                    print(f"✗ Safe value '{safe_value}' was rejected")
                    return False
            except Exception as e:
                print(f"✗ Safe value '{safe_value}' caused error: {e}")
                return False

        return True

    except Exception as e:
        print(f"✗ Error testing CSV injection prevention: {e}")
        return False


def test_donor_optional_email():
    """Test that donor email field is now optional"""
    print("Testing optional donor email field...")

    try:
        # Check donor doctype field metadata
        donor_meta = frappe.get_meta("Donor")
        email_field = None
        for field in donor_meta.fields:
            if field.fieldname == "donor_email":
                email_field = field
                break

        if email_field is None:
            print("✗ donor_email field not found")
            return False

        if not email_field.reqd:  # reqd should be 0 (False)
            print("✓ donor_email field is optional")
            return True
        else:
            print("✗ donor_email field is still required")
            return False

    except Exception as e:
        print(f"✗ Error checking donor email field: {e}")
        return False


def test_customer_validation_hook():
    """Test that Customer validation hook is properly registered"""
    print("Testing Customer validation hook registration...")

    try:
        from verenigingen.hooks import doc_events

        if "Customer" in doc_events:
            if "validate" in doc_events["Customer"]:
                hook_function = doc_events["Customer"]["validate"]
                if "mollie_data_validator" in hook_function:
                    print("✓ Customer validation hook properly registered")
                    return True
                else:
                    print("✗ Customer validation hook not pointing to mollie_data_validator")
                    return False
            else:
                print("✗ No validate hook registered for Customer")
                return False
        else:
            print("✗ No Customer hooks registered")
            return False

    except Exception as e:
        print(f"✗ Error checking Customer validation hook: {e}")
        return False


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("MOLLIE INTEGRATION QUALITY FIXES TEST SUITE")
    print("=" * 60)

    tests = [
        ("MollieDataValidator", test_mollie_validator),
        ("CSV Injection Prevention", test_csv_injection_prevention),
        ("Optional Donor Email", test_donor_optional_email),
        ("Customer Validation Hook", test_customer_validation_hook),
    ]

    results = []
    for test_name, test_function in tests:
        print(f"\n--- {test_name} ---")
        try:
            result = test_function()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            results.append((test_name, False))

    # Print summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)

    passed = 0
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name:<30} [{status}]")
        if result:
            passed += 1

    print(f"\nOverall: {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("\n🎉 ALL TESTS PASSED! Quality control fixes are working correctly.")
        return True
    else:
        print(f"\n⚠️  {len(results) - passed} test(s) failed. Please review implementation.")
        return False


if __name__ == "__main__":
    run_all_tests()
