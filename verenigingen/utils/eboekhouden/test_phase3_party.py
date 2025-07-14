#!/usr/bin/env python
# Test script to validate Phase 3 Party Management implementation

import json
from datetime import datetime

import frappe


def test_phase3_party_management():
    """Comprehensive test of Phase 3 Party Management enhancements"""
    print("\n" + "=" * 80)
    print("E-BOEKHOUDEN PHASE 3 PARTY MANAGEMENT TEST")
    print("=" * 80)

    results = {"tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Test party resolver imports
    print("\n1. Testing party resolver imports...")
    try:
        from verenigingen.utils.eboekhouden.party_resolver import (
            EBoekhoudenPartyResolver,
            resolve_customer,
            resolve_supplier,
        )

        # Create resolver instance
        resolver = EBoekhoudenPartyResolver()
        assert resolver is not None, "Failed to create party resolver"

        print("✅ Party resolver imports successful")
        results["tests_passed"] += 1
        results["details"].append({"test": "party_resolver_imports", "status": "passed"})
    except Exception as e:
        print(f"❌ Party resolver import test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "party_resolver_imports", "status": "failed", "error": str(e)})
        return results

    # Test 2: Test default customer/supplier creation
    print("\n2. Testing default party creation...")
    try:
        debug_info = []

        # Test default customer
        default_customer = resolver.get_default_customer()
        assert default_customer is not None, "Failed to get default customer"
        assert frappe.db.exists("Customer", default_customer), "Default customer doesn't exist"

        # Test default supplier
        default_supplier = resolver.get_default_supplier()
        assert default_supplier is not None, "Failed to get default supplier"
        assert frappe.db.exists("Supplier", default_supplier), "Default supplier doesn't exist"

        print(f"✅ Default parties created:")
        print(f"   - Customer: {default_customer}")
        print(f"   - Supplier: {default_supplier}")

        results["tests_passed"] += 1
        results["details"].append(
            {
                "test": "default_parties",
                "status": "passed",
                "default_customer": default_customer,
                "default_supplier": default_supplier,
            }
        )
    except Exception as e:
        print(f"❌ Default party creation test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "default_parties", "status": "failed", "error": str(e)})

    # Test 3: Test provisional party creation
    print("\n3. Testing provisional party creation...")
    try:
        debug_info = []

        # Test provisional customer
        test_relation_id = "TEST-CUST-999"
        provisional_customer = resolver.create_provisional_customer(test_relation_id, debug_info)

        assert provisional_customer is not None, "Failed to create provisional customer"

        # Check if customer exists and has correct data
        customer_data = frappe.db.get_value(
            "Customer",
            provisional_customer,
            ["customer_name", "eboekhouden_relation_code", "custom_needs_enrichment"],
            as_dict=True,
        )

        assert customer_data["eboekhouden_relation_code"] == test_relation_id, "Incorrect relation code"
        assert customer_data["custom_needs_enrichment"] == 1, "Not marked for enrichment"

        # Test provisional supplier
        test_supplier_relation_id = "TEST-SUPP-999"
        provisional_supplier = resolver.create_provisional_supplier(test_supplier_relation_id, debug_info)

        assert provisional_supplier is not None, "Failed to create provisional supplier"

        print(f"✅ Provisional parties created:")
        print(f"   - Customer: {provisional_customer} (Relation: {test_relation_id})")
        print(f"   - Supplier: {provisional_supplier} (Relation: {test_supplier_relation_id})")

        for line in debug_info[-4:]:
            print(f"   Debug: {line}")

        results["tests_passed"] += 1
        results["details"].append(
            {
                "test": "provisional_parties",
                "status": "passed",
                "provisional_customer": provisional_customer,
                "provisional_supplier": provisional_supplier,
            }
        )

        # Clean up test data
        frappe.delete_doc("Customer", provisional_customer, force=True)
        frappe.delete_doc("Supplier", provisional_supplier, force=True)

    except Exception as e:
        print(f"❌ Provisional party creation test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "provisional_parties", "status": "failed", "error": str(e)})

    # Test 4: Test party resolution logic
    print("\n4. Testing party resolution logic...")
    try:
        debug_info = []

        # Test resolving null relation ID (should return default)
        customer_none = resolver.resolve_customer(None, debug_info)
        assert customer_none == resolver.get_default_customer(), "Didn't return default for None relation"

        # Test resolving empty relation ID
        customer_empty = resolver.resolve_customer("", debug_info)
        assert customer_empty == resolver.get_default_customer(), "Didn't return default for empty relation"

        # Test resolving unknown relation ID (should create provisional)
        test_relation = "UNKNOWN-REL-123"
        customer_unknown = resolver.resolve_customer(test_relation, debug_info)

        assert customer_unknown is not None, "Failed to resolve unknown relation"
        assert customer_unknown != resolver.get_default_customer(), "Returned default for unknown relation"

        # Check that provisional customer was created
        customer_data = frappe.db.get_value(
            "Customer",
            customer_unknown,
            ["eboekhouden_relation_code", "custom_needs_enrichment"],
            as_dict=True,
        )

        assert customer_data["eboekhouden_relation_code"] == test_relation, "Incorrect relation code stored"

        print(f"✅ Party resolution logic validated:")
        print(f"   - None relation → Default customer: {customer_none}")
        print(f"   - Unknown relation → Provisional customer: {customer_unknown}")

        results["tests_passed"] += 1
        results["details"].append(
            {
                "test": "party_resolution_logic",
                "status": "passed",
                "unknown_relation_customer": customer_unknown,
            }
        )

        # Clean up
        frappe.delete_doc("Customer", customer_unknown, force=True)

    except Exception as e:
        print(f"❌ Party resolution logic test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "party_resolution_logic", "status": "failed", "error": str(e)})

    # Test 5: Test convenience functions
    print("\n5. Testing convenience functions...")
    try:
        debug_info = []

        # Test convenience resolve_customer function
        test_customer = resolve_customer("CONV-TEST-456", debug_info)
        assert test_customer is not None, "Convenience resolve_customer failed"

        # Test convenience resolve_supplier function
        test_supplier = resolve_supplier("CONV-TEST-789", debug_info)
        assert test_supplier is not None, "Convenience resolve_supplier failed"

        print(f"✅ Convenience functions validated:")
        print(f"   - resolve_customer: {test_customer}")
        print(f"   - resolve_supplier: {test_supplier}")

        results["tests_passed"] += 1
        results["details"].append(
            {
                "test": "convenience_functions",
                "status": "passed",
                "test_customer": test_customer,
                "test_supplier": test_supplier,
            }
        )

        # Clean up
        frappe.delete_doc("Customer", test_customer, force=True)
        frappe.delete_doc("Supplier", test_supplier, force=True)

    except Exception as e:
        print(f"❌ Convenience functions test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "convenience_functions", "status": "failed", "error": str(e)})

    # Test 6: Test API integration (mock)
    print("\n6. Testing API integration capabilities...")
    try:
        debug_info = []

        # Test fetch_relation_details (will likely fail due to no real API, but should handle gracefully)
        relation_details = resolver.fetch_relation_details("TEST-API-123", debug_info)

        # This should return None for unknown relations or handle API errors gracefully
        print(f"✅ API integration test completed:")
        print(f"   - API call handled gracefully (result: {relation_details is not None})")

        for line in debug_info[-3:]:
            print(f"   Debug: {line}")

        results["tests_passed"] += 1
        results["details"].append(
            {"test": "api_integration", "status": "passed", "api_result": relation_details is not None}
        )

    except Exception as e:
        print(f"❌ API integration test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "api_integration", "status": "failed", "error": str(e)})

    # Summary
    print("\n" + "=" * 80)
    print("PHASE 3 PARTY MANAGEMENT TEST SUMMARY")
    print("=" * 80)
    print(f"✅ Tests Passed: {results['tests_passed']}")
    print(f"❌ Tests Failed: {results['tests_failed']}")
    print(f"📊 Total Tests: {results['tests_passed'] + results['tests_failed']}")

    if results["tests_failed"] == 0:
        print("\n🎉 ALL PARTY MANAGEMENT TESTS PASSED! Phase 3 implementation is working correctly.")
        print("\n📋 Party Management Features Validated:")
        print("   ✅ Enhanced party resolver with API integration")
        print("   ✅ Default party creation and management")
        print("   ✅ Provisional party system for unknown relations")
        print("   ✅ Party resolution logic with intelligent fallbacks")
        print("   ✅ Convenience functions for backward compatibility")
        print("   ✅ API integration infrastructure (graceful error handling)")
    else:
        print("\n⚠️  Some party management tests failed. Please review the errors above.")

    return results


# Run the tests
if __name__ == "__main__":
    results = test_phase3_party_management()
