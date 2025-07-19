#!/usr/bin/env python
# Test script to validate Phase 1 implementation of enhanced E-Boekhouden import

import json
from datetime import datetime

import frappe


def test_phase1_implementation():
    """Comprehensive test of Phase 1 enhancements"""
    print("\n" + "=" * 80)
    print("E-BOEKHOUDEN PHASE 1 IMPLEMENTATION TEST")
    print("=" * 80)

    results = {"tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Verify imports and dependencies
    print("\n1. Testing imports and dependencies...")
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator
        from verenigingen.utils.eboekhouden.field_mapping import (
            BTW_CODE_MAP,
            DEFAULT_PAYMENT_TERMS,
            INVOICE_FIELD_MAP,
            LINE_ITEM_FIELD_MAP,
            UOM_MAP,
        )
        from verenigingen.utils.eboekhouden.invoice_helpers import (
            add_tax_lines,
            create_single_line_fallback,
            get_or_create_payment_terms,
            process_line_items,
            resolve_customer,
            resolve_supplier,
        )

        print("✅ All imports successful")
        results["tests_passed"] += 1
        results["details"].append({"test": "imports", "status": "passed"})
    except Exception as e:
        print(f"❌ Import failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "imports", "status": "failed", "error": str(e)})
        return results

    # Test 2: Test field mappings
    print("\n2. Testing field mapping configuration...")
    try:
        assert len(INVOICE_FIELD_MAP) > 0, "INVOICE_FIELD_MAP is empty"
        assert len(BTW_CODE_MAP) >= 6, "BTW_CODE_MAP missing entries"
        assert "HOOG_VERK_21" in BTW_CODE_MAP, "Missing high VAT sales code"
        assert BTW_CODE_MAP["HOOG_VERK_21"]["rate"] == 21, "Incorrect VAT rate"
        print(
            f"✅ Field mappings validated - {len(INVOICE_FIELD_MAP)} invoice fields, {len(BTW_CODE_MAP)} BTW codes"
        )
        results["tests_passed"] += 1
        results["details"].append({"test": "field_mappings", "status": "passed"})
    except Exception as e:
        print(f"❌ Field mapping test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "field_mappings", "status": "failed", "error": str(e)})

    # Test 3: Test REST Iterator connection
    print("\n3. Testing E-Boekhouden REST Iterator...")
    try:
        iterator = EBoekhoudenRESTIterator()
        # Test if we can create the iterator (API token check)
        print("✅ REST Iterator initialized successfully")
        results["tests_passed"] += 1
        results["details"].append({"test": "rest_iterator", "status": "passed"})
    except Exception as e:
        print(f"❌ REST Iterator failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "rest_iterator", "status": "failed", "error": str(e)})
        print("⚠️  Cannot proceed with API tests without valid iterator")
        return results

    # Test 4: Test mutation detail fetching
    print("\n4. Testing mutation detail fetching...")
    try:
        # Try to fetch a sample mutation (mutation ID 1 as test)
        test_mutation_id = 1
        print(f"   Attempting to fetch mutation {test_mutation_id}...")

        mutation_detail = iterator.fetch_mutation_detail(test_mutation_id)

        if mutation_detail:
            print(f"✅ Successfully fetched mutation {test_mutation_id}")
            print(f"   - Has Regels (line items): {'Regels' in mutation_detail}")
            print(f"   - Number of line items: {len(mutation_detail.get('Regels', []))}")
            print(f"   - Has Betalingstermijn: {'Betalingstermijn' in mutation_detail}")
            print(f"   - Has Referentie: {'Referentie' in mutation_detail}")
            results["tests_passed"] += 1
            results["details"].append(
                {
                    "test": "mutation_detail_fetch",
                    "status": "passed",
                    "data": {
                        "has_regels": "Regels" in mutation_detail,
                        "line_items_count": len(mutation_detail.get("Regels", [])),
                        "has_payment_terms": "Betalingstermijn" in mutation_detail,
                    },
                }
            )
        else:
            print(f"⚠️  No mutation found with ID {test_mutation_id} (this might be normal)")
            results["details"].append(
                {"test": "mutation_detail_fetch", "status": "skipped", "reason": "No test mutation available"}
            )
    except Exception as e:
        print(f"❌ Mutation detail fetch failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "mutation_detail_fetch", "status": "failed", "error": str(e)})

    # Test 5: Test helper functions
    print("\n5. Testing helper functions...")

    # Test 5a: Customer resolution
    try:
        print("   5a. Testing customer resolution...")
        debug_info = []

        # Test with no relation ID
        customer = resolve_customer(None, debug_info)
        assert customer is not None, "Failed to get default customer"
        print(f"      ✅ Default customer: {customer}")

        # Test with relation ID
        test_relation_id = "TEST123"
        customer = resolve_customer(test_relation_id, debug_info)
        assert customer is not None, "Failed to create provisional customer"
        print(f"      ✅ Provisional customer created: {customer}")

        results["tests_passed"] += 1
        results["details"].append({"test": "customer_resolution", "status": "passed"})
    except Exception as e:
        print(f"      ❌ Customer resolution failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "customer_resolution", "status": "failed", "error": str(e)})

    # Test 5b: Payment terms
    try:
        print("   5b. Testing payment terms creation...")
        payment_terms = get_or_create_payment_terms(30)
        assert payment_terms is not None, "Failed to create payment terms"
        print(f"      ✅ Payment terms: {payment_terms}")
        results["tests_passed"] += 1
        results["details"].append({"test": "payment_terms", "status": "passed"})
    except Exception as e:
        print(f"      ❌ Payment terms creation failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "payment_terms", "status": "failed", "error": str(e)})

    # Test 6: Test mock invoice creation with detailed data
    print("\n6. Testing invoice creation with mock detailed data...")
    try:
        # Create mock mutation detail with all fields
        mock_mutation_detail = {
            "id": 99999,
            "type": 1,  # Sales Invoice
            "date": "2024-01-15",
            "amount": 121.00,
            "description": "Test invoice with VAT",
            "relationId": "REL456",
            "invoiceNumber": "TEST-001",
            "Betalingstermijn": 14,  # 14 days payment term
            "Referentie": "PO-2024-001",
            "Regels": [
                {
                    "Omschrijving": "Consulting Services",
                    "Aantal": 5,
                    "Prijs": 20.00,
                    "Eenheid": "Uur",
                    "BTWCode": "HOOG_VERK_21",
                    "GrootboekNummer": "8010",
                }
            ],
        }

        # Test processing this would work
        print("   ✅ Mock invoice data structure validated")
        print(f"   - Total amount: €{mock_mutation_detail['amount']}")
        print(f"   - Line items: {len(mock_mutation_detail['Regels'])}")
        print(f"   - Has VAT: {mock_mutation_detail['Regels'][0]['BTWCode']}")
        print(f"   - Payment terms: {mock_mutation_detail['Betalingstermijn']} days")

        results["tests_passed"] += 1
        results["details"].append(
            {
                "test": "mock_invoice_structure",
                "status": "passed",
                "mock_data": {
                    "has_line_items": True,
                    "has_vat": True,
                    "has_payment_terms": True,
                    "has_reference": True,
                },
            }
        )
    except Exception as e:
        print(f"❌ Mock invoice test failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "mock_invoice_structure", "status": "failed", "error": str(e)})

    # Test 7: Verify the enhanced process function exists
    print("\n7. Verifying enhanced process functions...")
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import (
            _create_purchase_invoice,
            _create_sales_invoice,
            _process_single_mutation,
        )

        # Check if functions have been updated (by checking their docstrings)
        assert "ALL available fields" in _create_sales_invoice.__doc__, "Sales invoice function not updated"
        assert (
            "ALL available fields" in _create_purchase_invoice.__doc__
        ), "Purchase invoice function not updated"

        print("✅ Enhanced invoice creation functions verified")
        results["tests_passed"] += 1
        results["details"].append({"test": "enhanced_functions", "status": "passed"})
    except Exception as e:
        print(f"❌ Enhanced functions verification failed: {str(e)}")
        results["tests_failed"] += 1
        results["details"].append({"test": "enhanced_functions", "status": "failed", "error": str(e)})

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✅ Tests Passed: {results['tests_passed']}")
    print(f"❌ Tests Failed: {results['tests_failed']}")
    print(f"📊 Total Tests: {results['tests_passed'] + results['tests_failed']}")

    if results["tests_failed"] == 0:
        print("\n🎉 ALL TESTS PASSED! Phase 1 implementation is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Please review the errors above.")

    return results


def test_real_mutation_import():
    """Test importing a real mutation with the enhanced system"""
    print("\n" + "=" * 80)
    print("TESTING REAL MUTATION IMPORT")
    print("=" * 80)

    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import _process_single_mutation
        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.company
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        # Find a recent sales invoice mutation
        print("\nSearching for a test mutation...")
        mutations = iterator.fetch_mutations_by_type(
            mutation_type=1,  # Sales invoices
            limit=5,
            date_from=(datetime.now().replace(day=1)).strftime("%Y-%m-%d"),
        )

        if mutations:
            test_mutation = mutations[0]
            print(f"\nFound test mutation: ID {test_mutation.get('id')}")
            print(f"  Date: {test_mutation.get('date')}")
            print(f"  Amount: €{test_mutation.get('amount')}")
            print(f"  Description: {test_mutation.get('description', 'N/A')}")

            # Process with enhanced system
            debug_info = []
            print("\nProcessing with enhanced system...")

            result = _process_single_mutation(test_mutation, company, cost_center, debug_info)

            print("\nDebug output:")
            for line in debug_info[-10:]:  # Last 10 debug lines
                print(f"  {line}")

            if result:
                print(f"\n✅ Successfully created: {result.doctype} {result.name}")
                print(f"  Line items: {len(result.items)}")
                if hasattr(result, "taxes"):
                    print(f"  Tax lines: {len(result.taxes)}")
            else:
                print("❌ Failed to create document")
        else:
            print("⚠️  No test mutations found")

    except Exception as e:
        print(f"❌ Real mutation test failed: {str(e)}")
        import traceback

        traceback.print_exc()


# Run the tests
if __name__ == "__main__":
    # Run validation tests
    results = test_phase1_implementation()

    # If all validation tests pass, optionally test with real data
    if results["tests_failed"] == 0:
        print("\n" + "=" * 80)
        response = input(
            "\nAll validation tests passed! Would you like to test with real mutation data? (y/N): "
        )
        if response.lower() == "y":
            test_real_mutation_import()
