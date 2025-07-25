"""
API for clean re-import of E-Boekhouden data with enhanced features
"""

import frappe
from frappe.utils import add_days, getdate


@frappe.whitelist()
def preview_clean_import(from_date=None, to_date=None):
    """Preview what will be deleted and imported"""

    # Default date range
    if not from_date:
        from_date = add_days(getdate(), -90)
    if not to_date:
        to_date = getdate()

    # Check current data
    from verenigingen.utils.nuke_financial_data import check_financial_data_status

    current_data = check_financial_data_status()

    return {
        "warning": "This will DELETE ALL financial data and re-import with enhanced features",
        "date_range": {"from": str(from_date), "to": str(to_date)},
        "data_to_delete": current_data,
        "total_records": sum(
            [
                v
                for k, v in current_data.items()
                if isinstance(v, int)
                and k not in ["eBoekhouden Cache (Total)", "eBoekhouden Cache (Processed)"]
            ]
        ),
        "enhanced_features": [
            "Smart item categorization (Services, Products, Office Supplies, etc.)",
            "Complete VAT/BTW line items with proper tax accounts",
            "Intelligent party resolution with E-Boekhouden API integration",
            "Dutch payment terms (Netto 7/14/21/30 dagen)",
            "Account mapping via UI-manageable DocType",
            "Dutch UOM conversions (stuks, uur, maand, etc.)",
            "Multi-line invoice items from Regels array",
        ],
    }


@frappe.whitelist()
def execute_clean_import(confirm=False, from_date=None, to_date=None):
    """Execute the clean import with enhanced features"""

    if not confirm:
        return {
            "error": "Safety check failed",
            "message": "Set confirm=True to proceed",
            "warning": "This will DELETE ALL financial data!",
        }

    # Use the consolidated import manager
    from verenigingen.e_boekhouden.utils.import_manager import EBoekhoudenImportManager

    manager = EBoekhoudenImportManager()
    return manager.clean_import_all(from_date, to_date)


@frappe.whitelist()
def setup_enhanced_infrastructure():
    """Setup all enhanced features before import"""

    results = {"uom_setup": None, "item_groups": [], "errors": []}

    try:
        # Setup Dutch UOMs
        from verenigingen.e_boekhouden.utils.uom_manager import setup_dutch_uoms

        results["uom_setup"] = setup_dutch_uoms()

        # Ensure item groups exist
        required_groups = [
            "Services",
            "Products",
            "Office Supplies",
            "Software and Subscriptions",
            "Travel and Expenses",
            "Marketing and Advertising",
            "Utilities and Infrastructure",
            "Financial Services",
            "Catering and Events",
        ]

        for group in required_groups:
            if not frappe.db.exists("Item Group", group):
                try:
                    item_group = frappe.new_doc("Item Group")
                    item_group.item_group_name = group
                    item_group.parent_item_group = "All Item Groups"
                    item_group.insert(ignore_permissions=True)
                    results["item_groups"].append(f"Created: {group}")
                except Exception as e:
                    results["errors"].append(f"Failed to create {group}: {str(e)}")
            else:
                results["item_groups"].append(f"Exists: {group}")

        frappe.db.commit()

    except Exception as e:
        results["errors"].append(f"Setup error: {str(e)}")

    return results
