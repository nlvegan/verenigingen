"""
Test script for eBoekhouden import functions
Tests: Full import, 90-day import, CoA import, and single mutation import
"""

import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, getdate


def test_all_imports():
    """Test all import functions and analyze their code paths"""

    results = {"timestamp": datetime.now().isoformat(), "tests": {}}

    # Check if settings exist
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.api_token:
            results["error"] = "E-Boekhouden Settings missing API token"
            return results

        results["settings"] = {
            "company": settings.default_company,
            "api_url": settings.api_url,
            "has_token": bool(settings.api_token),
            "source_application": settings.source_application,
        }
    except Exception as e:
        results["error"] = f"Failed to get settings: {str(e)}"
        return results

    # Test 1: Chart of Accounts Import
    print("\n=== Testing Chart of Accounts Import ===")
    results["tests"]["coa_import"] = test_coa_import(settings)

    # Test 2: Single Mutation Import
    print("\n=== Testing Single Mutation Import ===")
    results["tests"]["single_mutation"] = test_single_mutation(settings)

    # Test 3: 90-Day Import (dry run)
    print("\n=== Testing 90-Day Import ===")
    results["tests"]["ninety_day_import"] = test_90_day_import(settings)

    # Test 4: Full Import Analysis (dry run)
    print("\n=== Analyzing Full Import ===")
    results["tests"]["full_import_analysis"] = analyze_full_import(settings)

    # Test 5: Code Path Analysis
    print("\n=== Code Path Analysis ===")
    results["tests"]["code_paths"] = analyze_code_paths()

    return results


def test_coa_import(settings):
    """Test Chart of Accounts import"""
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI(settings)

        # Get CoA from API
        result = api.get_chart_of_accounts()

        if result.get("success"):
            accounts = result.get("accounts", [])
            return {
                "success": True,
                "account_count": len(accounts),
                "sample_accounts": accounts[:5] if accounts else [],
                "has_mappings": bool(getattr(settings, "account_group_mappings", None)),
                "code_path": "eboekhouden_api.get_chart_of_accounts() -> Direct API call",
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "code_path": "Failed at API level",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def test_single_mutation(settings):
    """Test single mutation import"""
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI
        from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import test_single_mutation_import

        # First, get a sample mutation ID from the API
        api = EBoekhoudenAPI(settings)

        # Get recent mutations to find a valid ID
        mutations_result = api.get_mutations()  # No limit parameter

        if isinstance(mutations_result, list) and len(mutations_result) > 0:
            # Get first mutation ID
            sample_mutation = mutations_result[0]
            mutation_id = sample_mutation.get("id") or sample_mutation.get("Id")

            # Test importing this single mutation
            import_result = test_single_mutation_import(mutation_id)

            return {
                "success": import_result.get("success", False),
                "mutation_id": mutation_id,
                "mutation_type": sample_mutation.get("type") or sample_mutation.get("Type"),
                "mutation_date": sample_mutation.get("date") or sample_mutation.get("Datum"),
                "import_result": import_result,
                "code_path": "test_single_mutation_import() -> _import_rest_mutations_batch() with single item",
            }
        else:
            return {
                "success": False,
                "error": "No mutations found in API response",
                "api_result": mutations_result,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def test_90_day_import(settings):
    """Test 90-day import (analysis only, no actual import)"""
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        # Calculate date range
        date_to = getdate()
        date_from = add_days(date_to, -90)

        # Use the REST iterator which handles date filtering
        iterator = EBoekhoudenRESTIterator()

        # Get mutations for date range using params
        mutations_result = []
        count = 0
        for mutation in iterator.iter_mutations(
            date_from=date_from.strftime("%Y%m%d"), date_to=date_to.strftime("%Y%m%d")  # YYYYMMDD format
        ):
            mutations_result.append(mutation)
            count += 1
            if count >= 10:  # Just get sample
                break

        if mutations_result:
            # Analyze mutation types
            type_counts = {}
            for m in mutations_result:
                m_type = m.get("type", m.get("Type", "Unknown"))
                type_counts[m_type] = type_counts.get(m_type, 0) + 1

            return {
                "success": True,
                "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
                "sample_count": len(mutations_result),
                "mutation_types": type_counts,
                "sample_mutations": mutations_result[:3],  # First 3 for analysis
                "would_process": "Would call _import_rest_mutations_batch() with date-filtered mutations",
                "code_path": "migrate_transactions_data() -> start_full_rest_import() with date range -> _import_rest_mutations_batch()",
            }
        else:
            return {
                "success": False,
                "error": "No mutations found for date range",
                "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def analyze_full_import(settings):
    """Analyze what a full import would do"""
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        # Get sample mutations to analyze
        iterator = EBoekhoudenRESTIterator()

        # Get first few mutations to analyze
        sample_mutations = []
        mutation_types = {}
        count = 0

        for mutation in iterator.iter_mutations():
            sample_mutations.append(mutation)
            m_type = mutation.get("type", mutation.get("Type", "Unknown"))
            mutation_types[m_type] = mutation_types.get(m_type, 0) + 1
            count += 1
            if count >= 50:  # Sample size
                break

        # Estimate total based on mutation IDs
        if sample_mutations:
            last_id = max(m.get("id", m.get("Id", 0)) for m in sample_mutations)
            first_id = min(m.get("id", m.get("Id", 0)) for m in sample_mutations)

            return {
                "success": True,
                "analysis": {
                    "sample_size": len(sample_mutations),
                    "mutation_id_range": f"{first_id} to {last_id}",
                    "mutation_types_found": mutation_types,
                    "would_import": [
                        "All historical transactions",
                        "Opening balances (type 0)",
                        "Sales Invoices (type 1)",
                        "Purchase Invoices (type 2)",
                        "Payment Entries (type 3, 4)",
                        "Journal Entries (type 5-10)",
                    ],
                    "processing_method": "Batch processing via _import_rest_mutations_batch()",
                    "uses_enhanced": frappe.db.get_single_value(
                        "E-Boekhouden Settings", "use_enhanced_payment_processing"
                    ),
                },
                "code_path": "migrate_transactions_data() -> start_full_rest_import() -> REST iterator -> _import_rest_mutations_batch()",
            }
        else:
            return {"success": False, "error": "No mutations found"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def analyze_code_paths():
    """Analyze the code paths for different import types"""
    return {
        "summary": {
            "shared_processing": "_import_rest_mutations_batch() is used by all transaction imports",
            "routing_function": "_process_single_mutation() routes to specific handlers",
            "document_creators": {
                "invoices": "_create_sales_invoice() and _create_purchase_invoice()",
                "payments": "_create_payment_entry()",
                "journals": "_create_journal_entry()",
            },
        },
        "import_paths": {
            "full_import": {
                "entry": "E-Boekhouden Migration DocType",
                "flow": [
                    "migrate_transactions_data()",
                    "start_full_rest_import() OR execute_enhanced_migration()",
                    "REST API iterator fetches all mutations",
                    "_import_rest_mutations_batch() processes in batches",
                    "_process_single_mutation() for each mutation",
                    "Routes to appropriate _create_*() function",
                ],
            },
            "90_day_import": {
                "entry": "Same as full import with date range",
                "difference": "REST iterator uses date_from and date_to parameters",
                "processing": "Identical to full import",
            },
            "coa_import": {
                "entry": "E-Boekhouden Migration DocType",
                "flow": [
                    "migrate_chart_of_accounts()",
                    "EBoekhoudenAPI.get_chart_of_accounts()",
                    "Direct Account document creation",
                    "No transaction processing",
                ],
                "separate": True,
            },
            "single_mutation": {
                "entry": "test_single_mutation_import() function",
                "flow": [
                    "Fetch single mutation by ID",
                    "_import_rest_mutations_batch() with list of 1",
                    "Same processing as batch",
                ],
            },
        },
        "refactoring_opportunities": {
            "minimal_changes_needed": "Code is already well-structured with good reuse",
            "potential_improvements": [
                "Use TransactionCoordinator for cleaner interface",
                "Merge enhanced and standard migration paths",
                "Better progress tracking and error aggregation",
            ],
        },
    }


if __name__ == "__main__":
    # Run tests
    results = test_all_imports()

    # Print results
    print("\n" + "=" * 60)
    print("eBOEKHOUDEN IMPORT FUNCTION TEST RESULTS")
    print("=" * 60)
    print(json.dumps(results, indent=2, default=str))

    # Save results
    with open("/tmp/eboekhouden_import_test_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to: /tmp/eboekhouden_import_test_results.json")
