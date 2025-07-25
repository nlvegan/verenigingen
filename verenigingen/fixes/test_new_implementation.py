"""
Test script for new E-Boekhouden implementation
Run this to validate the improved data fetching and mapping
"""

import json

import frappe
from frappe.utils import flt


@frappe.whitelist()
def test_data_comparison():
    """Compare what data we get from current vs new approach"""

    # Test with a known mutation ID
    test_mutation_id = 7420  # You can change this to any valid ID

    from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    iterator = EBoekhoudenRESTIterator()

    try:
        # Current approach - summary data only
        summary_data = iterator.fetch_mutation_by_id(test_mutation_id)

        # New approach - full detailed data
        detail_data = iterator.fetch_mutation_detail(test_mutation_id)

        comparison = {
            "mutation_id": test_mutation_id,
            "current_approach": analyze_data_structure(summary_data, "Summary"),
            "new_approach": analyze_data_structure(detail_data, "Detail"),
            "improvement_analysis": {},
        }

        # Calculate improvements
        if detail_data:
            comparison["improvement_analysis"] = {
                "has_line_items": "Regels" in detail_data,
                "line_item_count": len(detail_data.get("Regels", [])),
                "vat_codes_found": extract_vat_codes(detail_data),
                "payment_terms": detail_data.get("Betalingstermijn"),
                "references": detail_data.get("Referentie"),
                "additional_fields": get_additional_fields(summary_data, detail_data),
            }

            # Show line item details if available
            if "Regels" in detail_data:
                comparison["sample_line_items"] = detail_data["Regels"][:3]  # First 3 items

        return comparison

    except Exception as e:
        return {"error": str(e), "mutation_id": test_mutation_id}


def analyze_data_structure(data, data_type):
    """Analyze the structure of returned data"""
    if not data:
        return {"available": False, "reason": "No data returned"}

    return {
        "available": True,
        "field_count": len(data.keys()),
        "fields": list(data.keys()),
        "sample_data": {k: v for i, (k, v) in enumerate(data.items()) if i < 5},
    }


def extract_vat_codes(detail_data):
    """Extract VAT codes from line items"""
    vat_codes = set()

    if "Regels" in detail_data:
        for regel in detail_data["Regels"]:
            btw_code = regel.get("BTWCode")
            if btw_code:
                vat_codes.add(btw_code)

    return list(vat_codes)


def get_additional_fields(summary_data, detail_data):
    """Find fields available in detail but not in summary"""
    if not summary_data or not detail_data:
        return []

    summary_fields = set(summary_data.keys())
    detail_fields = set(detail_data.keys())

    return list(detail_fields - summary_fields)


@frappe.whitelist()
def test_invoice_creation_comparison(mutation_id=None):
    """Test creating invoice with old vs new method"""

    if not mutation_id:
        mutation_id = 7420  # Default test ID

    mutation_id = int(mutation_id)

    from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    iterator = EBoekhoudenRESTIterator()
    company = frappe.get_single("E-Boekhouden Settings").default_company

    # Get the data
    mutation_detail = iterator.fetch_mutation_detail(mutation_id)

    if not mutation_detail:
        return {"error": f"Mutation {mutation_id} not found"}

    mutation_type = mutation_detail.get("type", 0)

    if mutation_type not in [1, 2]:  # Only test invoices
        return {"error": f"Mutation {mutation_id} is not an invoice (type: {mutation_type})"}

    # Simulate what current implementation would create
    current_simulation = simulate_current_implementation(mutation_detail)

    # Show what new implementation would create
    new_simulation = simulate_new_implementation(mutation_detail)

    return {
        "mutation_id": mutation_id,
        "mutation_type": mutation_type,
        "current_implementation": current_simulation,
        "new_implementation": new_simulation,
        "improvements": calculate_improvements(current_simulation, new_simulation),
    }


def simulate_current_implementation(mutation_detail):
    """Simulate what current poor implementation creates"""
    return {
        "method": "Current (Poor) Implementation",
        "data_used": "Summary only",
        "customer_supplier": mutation_detail.get("relationId", "Guest Customer"),  # Uses ID directly!
        "line_items": [
            {
                "item_code": "Service Item",  # Everything is Service Item!
                "description": "Generic description",
                "qty": 1,
                "rate": abs(flt(mutation_detail.get("amount", 0))),  # Total amount as single line
                "account": "Hardcoded account",  # No proper mapping
            }
        ],
        "tax_lines": [],  # NO VAT HANDLING AT ALL!
        "payment_terms": None,  # Not captured
        "due_date": None,  # Not calculated
        "references": None,  # Not captured
        "metadata_captured": ["id", "date", "amount", "relationId"],
    }


def simulate_new_implementation(mutation_detail):
    """Simulate what new improved implementation creates"""

    # Line items from Regels
    line_items = []
    vat_lines = []

    if "Regels" in mutation_detail:
        for regel in mutation_detail["Regels"]:
            line_items.append(
                {
                    "item_code": create_item_code_from_description(regel.get("Omschrijving", "Service")),
                    "description": regel.get("Omschrijving", "Service"),
                    "qty": regel.get("Aantal", 1),
                    "rate": regel.get("Prijs", 0),
                    "account": f"GL-{regel.get('GrootboekNummer', 'DEFAULT')}",
                    "btw_code": regel.get("BTWCode"),
                    "cost_center": regel.get("KostenplaatsId"),
                }
            )

            # VAT line if applicable
            btw_code = regel.get("BTWCode")
            if btw_code and btw_code != "GEEN":
                vat_lines.append(
                    {
                        "btw_code": btw_code,
                        "rate": get_btw_rate(btw_code),
                        "taxable_amount": regel.get("Aantal", 1) * regel.get("Prijs", 0),
                    }
                )
    else:
        # Fallback line item
        line_items.append(
            {
                "item_code": create_item_code_from_description(mutation_detail.get("description", "Service")),
                "description": mutation_detail.get("description", "E-Boekhouden Import"),
                "qty": 1,
                "rate": abs(flt(mutation_detail.get("amount", 0))),
                "account": f"GL-{mutation_detail.get('ledgerId', 'DEFAULT')}",
            }
        )

    # Payment terms
    payment_days = mutation_detail.get("Betalingstermijn", 30)

    return {
        "method": "New (Improved) Implementation",
        "data_used": "Full mutation details",
        "customer_supplier": f"Resolved from {mutation_detail.get('relationId', 'N/A')}",
        "line_items": line_items,
        "tax_lines": vat_lines,
        "payment_terms": f"Netto {payment_days} dagen" if payment_days else None,
        "due_date": f"Calculated from posting_date + {payment_days} days",
        "references": mutation_detail.get("Referentie"),
        "metadata_captured": list(mutation_detail.keys()),
    }


def create_item_code_from_description(description):
    """Create item code from description"""
    if not description:
        return "SERVICE-ITEM"

    import re

    cleaned = re.sub(r"[^a-zA-Z0-9\s\-]", "", description)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    return cleaned.upper()[:20]


def get_btw_rate(btw_code):
    """Get BTW rate from code"""
    rates = {"HOOG_VERK_21": 21, "LAAG_VERK_9": 9, "HOOG_INK_21": 21, "LAAG_INK_9": 9, "GEEN": 0}
    return rates.get(btw_code, 0)


def calculate_improvements(current, new):
    """Calculate improvements from new implementation"""
    return {
        "line_items": {
            "current": len(current["line_items"]),
            "new": len(new["line_items"]),
            "improvement": f"{len(new['line_items']) - len(current['line_items'])} more line items",
        },
        "vat_handling": {
            "current": len(current["tax_lines"]),
            "new": len(new["tax_lines"]),
            "improvement": "VAT now properly handled" if new["tax_lines"] else "No VAT in this transaction",
        },
        "metadata": {
            "current": len(current["metadata_captured"]),
            "new": len(new["metadata_captured"]),
            "improvement": f"{len(new['metadata_captured']) - len(current['metadata_captured'])} more fields captured",
        },
        "party_management": {
            "current": "Uses relation ID directly",
            "new": "Resolves to proper party name",
            "improvement": "Proper customer/supplier names",
        },
        "payment_terms": {
            "current": "Not captured",
            "new": new["payment_terms"] or "Not available in this transaction",
            "improvement": "Payment terms and due dates now captured",
        },
    }


@frappe.whitelist()
def validate_api_capabilities():
    """Validate what we can get from the e-boekhouden API"""

    from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    iterator = EBoekhoudenRESTIterator()

    # Test a few different mutation IDs to see data variety
    test_ids = [100, 500, 1000, 5000, 7420]

    results = []

    for mutation_id in test_ids:
        try:
            detail_data = iterator.fetch_mutation_detail(mutation_id)

            if detail_data:
                analysis = {
                    "mutation_id": mutation_id,
                    "type": detail_data.get("type"),
                    "has_regels": "Regels" in detail_data,
                    "regels_count": len(detail_data.get("Regels", [])),
                    "has_payment_terms": "Betalingstermijn" in detail_data,
                    "has_reference": "Referentie" in detail_data,
                    "available_fields": list(detail_data.keys())[:10],  # First 10 fields
                    "sample_regel": detail_data.get("Regels", [{}])[0] if detail_data.get("Regels") else None,
                }
                results.append(analysis)
            else:
                results.append({"mutation_id": mutation_id, "error": "Not found"})

        except Exception as e:
            results.append({"mutation_id": mutation_id, "error": str(e)})

    return {
        "api_test_results": results,
        "summary": {
            "successful_fetches": len([r for r in results if "error" not in r]),
            "mutations_with_line_items": len([r for r in results if r.get("has_regels")]),
            "mutations_with_payment_terms": len([r for r in results if r.get("has_payment_terms")]),
        },
    }
