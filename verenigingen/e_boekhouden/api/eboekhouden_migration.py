"""
API endpoints for E-Boekhouden clean migration
"""

import frappe
from frappe.utils import getdate


@frappe.whitelist()
def debug_opening_balance_import():
    """Debug the opening balance import issue"""
    try:
        # Test basic imports
        result = {"tests": []}

        # Test 1: Import the migration module
        try:
            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration import e_boekhouden_migration

            result["tests"].append("✓ Migration module import successful")
        except Exception as e:
            result["tests"].append(f"✗ Migration module import failed: {e}")
            return result

        # Test 2: Get the function
        try:
            func = getattr(e_boekhouden_migration, "import_opening_balances_only")
            result["tests"].append("✓ Function found in module")
        except Exception as e:
            result["tests"].append(f"✗ Function not found: {e}")
            return result

        # Test 3: Import the REST migration module
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                _import_opening_balances,
            )

            result["tests"].append("✓ REST migration module import successful")
        except Exception as e:
            result["tests"].append(f"✗ REST migration module import failed: {e}")
            import traceback

            result["traceback"] = traceback.format_exc()

        # Test 4: Get latest migration
        try:
            migrations = frappe.get_all(
                "E-Boekhouden Migration", filters={"docstatus": ["!=", 2]}, order_by="creation desc", limit=1
            )
            if migrations:
                result["tests"].append(f"✓ Found migration: {migrations[0].name}")
                result["migration_name"] = migrations[0].name

                # Test 5: Call the function
                try:
                    test_result = func(migrations[0].name)
                    result["tests"].append(f"✓ Function executed: {test_result}")
                    result["function_result"] = test_result
                except Exception as e:
                    result["tests"].append(f"✗ Function execution failed: {e}")
                    import traceback

                    result["execution_traceback"] = traceback.format_exc()
            else:
                result["tests"].append("✗ No migrations found")
        except Exception as e:
            result["tests"].append(f"✗ Error getting migration: {e}")

        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def preview_migration(from_date=None, to_date=None):
    """Preview what will be migrated"""
    from verenigingen.e_boekhouden.utils.migration_clean_import import get_migration_preview

    return get_migration_preview(from_date, to_date)


@frappe.whitelist()
def execute_migration(from_date=None, to_date=None, confirm=False):
    """Execute the clean migration"""
    if not confirm:
        return {
            "error": "Please confirm the migration by setting confirm=True",
            "warning": "This will delete all existing E-Boekhouden imports and re-import them",
        }

    from verenigingen.e_boekhouden.utils.migration_clean_import import execute_clean_migration

    return execute_clean_migration(from_date, to_date)


@frappe.whitelist()
def test_single_mutation(mutation_id):
    """Test import of a single mutation with enhanced features"""
    from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _process_single_mutation
    from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    settings = frappe.get_single("E-Boekhouden Settings")
    company = settings.company
    cost_center = frappe.db.get_value("Company", company, "cost_center")

    # Fetch mutation detail
    iterator = EBoekhoudenRESTIterator()
    mutation_detail = iterator.fetch_mutation_detail(mutation_id)

    if not mutation_detail:
        return {"error": f"Mutation {mutation_id} not found"}

    # Process with debug info
    debug_info = []
    try:
        doc = _process_single_mutation(mutation_detail, company, cost_center, debug_info)

        return {
            "success": True,
            "document": doc.name if doc else None,
            "doctype": doc.doctype if doc else None,
            "debug_info": debug_info,
            "enhanced_features": {
                "line_items": len(doc.items) if doc and hasattr(doc, "items") else 0,
                "tax_lines": len(doc.taxes) if doc and hasattr(doc, "taxes") else 0,
                "has_payment_terms": bool(doc.payment_terms_template)
                if doc and hasattr(doc, "payment_terms_template")
                else False,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e), "debug_info": debug_info}
