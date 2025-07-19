"""
Quick test script to test single mutation import
"""

import json

import frappe


def test_single_mutation():
    """Test importing a single mutation"""

    # Test with a known mutation ID from the response
    mutation_id = 17  # First non-zero ID from the API response

    from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import test_single_mutation_import

    result = test_single_mutation_import(mutation_id)

    print(f"\nSingle Mutation Import Test (ID: {mutation_id})")
    print("=" * 50)

    if result.get("success"):
        print("✅ SUCCESS")
        print(f"Mutation Type: {result.get('mutation_data', {}).get('type')}")
        print(f"Date: {result.get('mutation_data', {}).get('date')}")
        print(f"Invoice: {result.get('mutation_data', {}).get('invoiceNumber')}")
        print(f"Amount: {result.get('mutation_data', {}).get('amount')}")
        print(f"\nImport Result: {result.get('import_result')}")
    else:
        print("❌ FAILED")
        print(f"Error: {result.get('error')}")

    return result


if __name__ == "__main__":
    test_single_mutation()
