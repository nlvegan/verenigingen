"""
API endpoints for E-Boekhouden mapping setup
"""

import frappe


@frappe.whitelist()
def setup_eboekhouden_mapping_fields():
    """Add custom fields needed for E-Boekhouden mapping functionality"""

    fields_added = []

    # Add eboekhouden_invoice_number to Journal Entry if not exists
    if not frappe.db.has_column("Journal Entry", "eboekhouden_invoice_number"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Journal Entry",
                "fieldname": "eboekhouden_invoice_number",
                "fieldtype": "Data",
                "label": "E-Boekhouden Invoice Number",
                "unique": 1,
                "no_copy": 1,
                "insert_after": "user_remark",
            }
        ).insert(ignore_permissions=True)
        fields_added.append("Journal Entry.eboekhouden_invoice_number")

    # Add custom fields from the original migration
    from verenigingen.utils.eboekhouden_soap_migration import add_eboekhouden_custom_fields

    add_eboekhouden_custom_fields()

    # Create default mappings
    from verenigingen.utils.eboekhouden_account_analyzer import create_default_range_mappings

    mapping_result = create_default_range_mappings()

    return {
        "success": True,
        "fields_added": fields_added,
        "mappings_created": mapping_result.get("created", 0),
        "message": "E-Boekhouden mapping setup completed",
    }


@frappe.whitelist()
def get_mapping_summary():
    """Get a summary of current mapping configuration"""

    total_mappings = frappe.db.count("E-Boekhouden Account Mapping", {"is_active": 1})

    # Get mappings by type
    journal_mappings = frappe.db.count(
        "E-Boekhouden Account Mapping", {"is_active": 1, "document_type": "Journal Entry"}
    )

    purchase_mappings = frappe.db.count(
        "E-Boekhouden Account Mapping", {"is_active": 1, "document_type": "Purchase Invoice"}
    )

    # Get sample mappings
    sample_mappings = frappe.get_all(
        "E-Boekhouden Account Mapping",
        filters={"is_active": 1},
        fields=["account_code", "account_name", "document_type", "transaction_category"],
        limit=5,
        order_by="priority desc",
    )

    return {
        "total_mappings": total_mappings,
        "journal_mappings": journal_mappings,
        "purchase_mappings": purchase_mappings,
        "sample_mappings": sample_mappings,
        "mapping_review_url": "/eboekhouden_mapping_review",
    }


@frappe.whitelist()
def test_mutation_mapping(mutation_nr=None, account_code=None, description=None):
    """Test how a specific mutation would be mapped"""

    if not account_code and not description:
        frappe.throw("Either account code or description must be provided")

    from verenigingen.verenigingen.doctype.e_boekhouden_account_mapping.e_boekhouden_account_mapping import (
        get_mapping_for_mutation,
    )

    # Get the mapping
    mapping = get_mapping_for_mutation(account_code, description)

    # Get details if mapping was found
    mapping_details = None
    if mapping.get("name"):
        mapping_doc = frappe.get_doc("E-Boekhouden Account Mapping", mapping["name"])
        mapping_details = {
            "name": mapping_doc.name,
            "account_code": mapping_doc.account_code,
            "account_name": mapping_doc.account_name,
            "priority": mapping_doc.priority,
            "reasons": [],
        }

        if mapping_doc.account_code == account_code:
            mapping_details["reasons"].append("Exact account code match")
        elif mapping_doc.account_range_start and mapping_doc.account_range_end:
            mapping_details["reasons"].append(
                f"Account in range {mapping_doc.account_range_start} - {mapping_doc.account_range_end}"
            )

        if mapping_doc.description_patterns and description:
            patterns = [p.strip() for p in mapping_doc.description_patterns.split("\n") if p.strip()]
            matched_patterns = [p for p in patterns if p.lower() in description.lower()]
            if matched_patterns:
                mapping_details["reasons"].append(f"Description matches: {', '.join(matched_patterns)}")

    return {
        "mutation_nr": mutation_nr,
        "account_code": account_code,
        "description": description,
        "mapped_to": mapping["document_type"],
        "category": mapping["transaction_category"],
        "mapping_used": mapping_details,
        "default_used": not mapping.get("name"),
    }
