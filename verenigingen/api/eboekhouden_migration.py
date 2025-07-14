"""
API endpoints for E-Boekhouden clean migration
"""

import frappe
from frappe.utils import getdate


@frappe.whitelist()
def preview_migration(from_date=None, to_date=None):
    """Preview what will be migrated"""
    from verenigingen.utils.eboekhouden.migration_clean_import import get_migration_preview

    return get_migration_preview(from_date, to_date)


@frappe.whitelist()
def execute_migration(from_date=None, to_date=None, confirm=False):
    """Execute the clean migration"""
    if not confirm:
        return {
            "error": "Please confirm the migration by setting confirm=True",
            "warning": "This will delete all existing E-Boekhouden imports and re-import them",
        }

    from verenigingen.utils.eboekhouden.migration_clean_import import execute_clean_migration

    return execute_clean_migration(from_date, to_date)


@frappe.whitelist()
def test_single_mutation(mutation_id):
    """Test import of a single mutation with enhanced features"""
    from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import _process_single_mutation
    from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

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
