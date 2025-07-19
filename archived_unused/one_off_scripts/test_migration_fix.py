import frappe

from .eboekhouden_rest_full_migration import _process_single_mutation


@frappe.whitelist()
def test_mutation_7296_processing():
    """Test processing mutation 7296 with the duplicate fix"""

    # Create the mutation data as it would come from the API
    mutation_7296 = {
        "id": 7296,
        "type": 1,
        "date": "2025-05-31",
        "description": "",
        "termOfPayment": 30,
        "ledgerId": 13201883,
        "relationId": 36133712,
        "inExVat": "EX",
        "invoiceNumber": "20250601",
        "entryNumber": "",
        "rows": [
            {
                "ledgerId": 31760397,
                "vatCode": "GEEN",
                "amount": 113.08,
                "description": "eten voor op vrijwilligersdag",
            }
        ],
        "vat": [],
    }

    debug_info = []

    try:
        # Get default company and cost center
        company = frappe.defaults.get_defaults().get("company") or frappe.db.get_value("Company", {}, "name")
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        # Process the mutation
        result = _process_single_mutation(mutation_7296, company, cost_center, debug_info)

        return {
            "success": True,
            "result": {
                "doctype": result.doctype,
                "name": result.name,
                "eboekhouden_mutation_nr": result.get("eboekhouden_mutation_nr"),
                "eboekhouden_invoice_number": result.get("eboekhouden_invoice_number"),
            },
            "debug_info": debug_info,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "debug_info": debug_info}
