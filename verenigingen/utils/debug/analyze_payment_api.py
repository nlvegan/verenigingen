"""Analyze payment mutations from E-Boekhouden API"""

import json
from datetime import datetime

import frappe


@frappe.whitelist()
def analyze_payment_mutations():
    """Fetch and analyze specific payment mutations: 7833, 5473, 6217"""
    from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

    # Initialize API
    settings = frappe.get_single("E-Boekhouden Settings")
    api = EBoekhoudenAPI(settings)

    # Specific mutations to analyze
    target_mutations = [7833, 5473, 6217]
    results = {
        "timestamp": datetime.now().isoformat(),
        "mutations": [],
        "findings": {
            "multiple_invoice_support": False,
            "invoice_reference_locations": set(),
            "payment_types_found": set(),
            "bank_account_patterns": [],
            "additional_fields": set(),
        },
    }

    for mutation_id in target_mutations:
        try:
            # Try to get mutation by ID directly
            result = api.make_request(f"v1/mutation/{mutation_id}", "GET")

            if result["success"]:
                mutation_data = json.loads(result["data"])

                # Analyze the mutation
                analysis = {
                    "id": mutation_id,
                    "success": True,
                    "type": mutation_data.get("type"),
                    "type_name": get_mutation_type_name(mutation_data.get("type")),
                    "date": mutation_data.get("date"),
                    "description": mutation_data.get("description", ""),
                    "invoice_number": mutation_data.get("invoiceNumber"),
                    "relation_id": mutation_data.get("relationId"),
                    "row_count": len(mutation_data.get("rows", [])),
                    "raw_data": mutation_data,
                }

                # Track payment types
                if mutation_data.get("type") is not None:
                    results["findings"]["payment_types_found"].add(mutation_data.get("type"))

                # Check for invoice references
                invoice_refs = []
                if mutation_data.get("invoiceNumber"):
                    invoice_refs.append(
                        {"location": "main", "invoice_number": mutation_data.get("invoiceNumber")}
                    )
                    results["findings"]["invoice_reference_locations"].add("main_mutation")

                # Analyze rows
                rows = mutation_data.get("rows", [])
                for i, row in enumerate(rows):
                    if row.get("invoiceNumber"):
                        invoice_refs.append(
                            {
                                "location": f"row_{i}",
                                "invoice_number": row.get("invoiceNumber"),
                                "amount": row.get("amount"),
                            }
                        )
                        results["findings"]["invoice_reference_locations"].add("row_level")

                    # Check for bank accounts
                    if row.get("ledgerId"):
                        ledger_info = get_ledger_info(row.get("ledgerId"))
                        if ledger_info and "bank" in ledger_info.get("account_name", "").lower():
                            results["findings"]["bank_account_patterns"].append(
                                {
                                    "mutation_id": mutation_id,
                                    "ledger_id": row.get("ledgerId"),
                                    "account_name": ledger_info.get("account_name"),
                                }
                            )

                analysis["invoice_references"] = invoice_refs
                analysis["has_multiple_invoices"] = (
                    len(set(ref["invoice_number"] for ref in invoice_refs)) > 1
                )

                if analysis["has_multiple_invoices"]:
                    results["findings"]["multiple_invoice_support"] = True

                # Check for additional fields
                known_fields = {
                    "id",
                    "type",
                    "date",
                    "description",
                    "invoiceNumber",
                    "relationId",
                    "rows",
                    "amount",
                    "debit",
                    "credit",
                }
                for key in mutation_data.keys():
                    if key not in known_fields:
                        results["findings"]["additional_fields"].add(key)

                results["mutations"].append(analysis)

            else:
                results["mutations"].append({"id": mutation_id, "success": False, "error": result["error"]})

        except Exception as e:
            results["mutations"].append({"id": mutation_id, "success": False, "error": str(e)})

    # Convert sets to lists for JSON serialization
    results["findings"]["invoice_reference_locations"] = list(
        results["findings"]["invoice_reference_locations"]
    )
    results["findings"]["payment_types_found"] = list(results["findings"]["payment_types_found"])
    results["findings"]["additional_fields"] = list(results["findings"]["additional_fields"])

    # Generate summary
    results["summary"] = generate_summary(results)

    return results


def get_mutation_type_name(mutation_type):
    """Get human-readable name for mutation type"""
    type_mapping = {
        0: "Openstaande post (Opening Balance)",
        1: "Factuurontvangst (Purchase Invoice)",
        2: "Factuurbetaling (Sales Invoice)",
        3: "FactuurbetalingOntvangen (Customer Payment)",
        4: "FactuurbetalingVerstuurd (Supplier Payment)",
        5: "GeldOntvangen (Money Received)",
        6: "GeldUitgegeven (Money Spent)",
        7: "Memoriaal (Memorial/Journal)",
    }
    return type_mapping.get(mutation_type, f"Unknown Type {mutation_type}")


def get_ledger_info(ledger_id):
    """Get ledger mapping information"""
    try:
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(ledger_id)},
            ["erpnext_account", "ledger_code", "ledger_description"],
            as_dict=True,
        )

        if mapping and mapping.get("erpnext_account"):
            account_info = frappe.db.get_value(
                "Account", mapping["erpnext_account"], ["account_name", "account_type"], as_dict=True
            )
            if account_info:
                mapping.update(account_info)

        return mapping
    except:
        return None


def generate_summary(results):
    """Generate a summary of findings"""
    successful = len([m for m in results["mutations"] if m.get("success")])

    summary = {
        "mutations_analyzed": len(results["mutations"]),
        "successful_fetches": successful,
        "failed_fetches": len(results["mutations"]) - successful,
        "key_findings": [],
    }

    # Key findings
    if results["findings"]["multiple_invoice_support"]:
        summary["key_findings"].append("✓ Multiple invoice payments are supported in the API")

        # Find examples
        multi_invoice_examples = []
        for m in results["mutations"]:
            if m.get("has_multiple_invoices"):
                multi_invoice_examples.append(
                    {"mutation_id": m["id"], "invoice_count": len(m.get("invoice_references", []))}
                )

        if multi_invoice_examples:
            summary["multiple_invoice_examples"] = multi_invoice_examples
    else:
        summary["key_findings"].append("✗ No multiple invoice payments found in these samples")

    if "row_level" in results["findings"]["invoice_reference_locations"]:
        summary["key_findings"].append(
            "✓ Invoice references can appear at row level (important for allocation)"
        )

    if results["findings"]["bank_account_patterns"]:
        summary["key_findings"].append("✓ Bank accounts are identifiable through ledger mappings")

    if results["findings"]["additional_fields"]:
        summary["key_findings"].append(
            f"✓ Additional API fields discovered: {', '.join(results['findings']['additional_fields'])}"
        )

    # Payment type analysis
    payment_types = results["findings"]["payment_types_found"]
    if 3 in payment_types or 4 in payment_types:
        summary["key_findings"].append(
            "✓ Standard payment types (3: Customer Payment, 4: Supplier Payment) found"
        )

    return summary
