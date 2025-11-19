#!/usr/bin/env python3
"""
Script to analyze specific E-Boekhouden mutations to understand payment API structure.
This will help us understand:
1. The actual field structure of payment mutations
2. Whether payments can have multiple linked invoices
3. How bank accounts are represented in the API
4. Any other capabilities or limitations
"""

import json
import sys
from datetime import datetime

import frappe

# Initialize Frappe
frappe.init(site="dev.veganisme.net")
frappe.connect()


def analyze_specific_mutations():
    """Fetch and analyze mutations 7833, 5473, 6217 as requested"""
    from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

    # Initialize API
    settings = frappe.get_single("E-Boekhouden Settings")
    api = EBoekhoudenAPI(settings)

    # Specific mutations to analyze
    target_mutations = [7833, 5473, 6217]

    results = {
        "timestamp": datetime.now().isoformat(),
        "mutations_analyzed": [],
        "api_structure_findings": {},
        "payment_capabilities": {},
        "recommendations": [],
    }

    print(f"\n{'='*80}")
    print("E-Boekhouden Payment Mutation Analysis")
    print(f"Analyzing mutations: {', '.join(map(str, target_mutations))}")
    print(f"{'='*80}\n")

    # Fetch each mutation
    for mutation_id in target_mutations:
        print(f"\nFetching mutation {mutation_id}...")

        try:
            # Try to get mutation by ID directly
            result = api.make_request(f"v1/mutation/{mutation_id}", "GET")

            if result["success"]:
                mutation_data = json.loads(result["data"])

                # Analyze the mutation structure
                analysis = analyze_mutation_structure(mutation_data)
                results["mutations_analyzed"].append(analysis)

                # Print summary
                print(f"\nMutation {mutation_id} Summary:")
                print(f"  Type: {analysis['type']} ({analysis['type_name']})")
                print(f"  Date: {analysis['date']}")
                print(f"  Description: {analysis['description'][:100]}...")
                print(f"  Amount: {analysis['total_amount']}")
                print(f"  Has Invoice Number: {analysis['has_invoice_number']}")
                print(f"  Has Multiple Invoices: {analysis['has_multiple_invoices']}")
                print(f"  Row Count: {analysis['row_count']}")

                if analysis["is_payment_type"]:
                    print("\n  Payment Details:")
                    print(f"    Payment Direction: {analysis['payment_direction']}")
                    print(f"    Linked Invoices: {analysis['linked_invoices']}")
                    print(f"    Bank Account Info: {analysis['bank_account_info']}")

            else:
                print(f"  ERROR: {result['error']}")
                results["mutations_analyzed"].append(
                    {"id": mutation_id, "error": result["error"], "success": False}
                )

        except Exception as e:
            print(f"  EXCEPTION: {str(e)}")
            results["mutations_analyzed"].append({"id": mutation_id, "error": str(e), "success": False})

    # Analyze findings across all mutations
    analyze_api_capabilities(results)

    # Generate recommendations
    generate_recommendations(results)

    # Save detailed results
    output_file = f"/home/frappe/frappe-bench/apps/verenigingen/payment_mutation_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n\nDetailed analysis saved to: {output_file}")

    # Print summary findings
    print_summary(results)

    return results


def analyze_mutation_structure(mutation_data):
    """Analyze the structure of a single mutation"""
    analysis = {
        "id": mutation_data.get("id"),
        "type": mutation_data.get("type"),
        "type_name": get_mutation_type_name(mutation_data.get("type")),
        "date": mutation_data.get("date"),
        "description": mutation_data.get("description", ""),
        "invoice_number": mutation_data.get("invoiceNumber"),
        "relation_id": mutation_data.get("relationId"),
        "has_invoice_number": bool(mutation_data.get("invoiceNumber")),
        "raw_data": mutation_data,
        "success": True,
    }

    # Check if this is a payment type
    payment_types = [3, 4]  # FactuurbetalingOntvangen, FactuurbetalingVerstuurd
    analysis["is_payment_type"] = mutation_data.get("type") in payment_types

    if analysis["is_payment_type"]:
        analysis["payment_direction"] = "incoming" if mutation_data.get("type") == 3 else "outgoing"

    # Analyze rows
    rows = mutation_data.get("rows", [])
    analysis["row_count"] = len(rows)
    analysis["rows"] = []

    total_amount = 0
    linked_invoices = []
    bank_accounts = []

    for i, row in enumerate(rows):
        row_analysis = {
            "index": i,
            "ledger_id": row.get("ledgerId"),
            "amount": float(row.get("amount", 0)),
            "description": row.get("description", ""),
            "invoice_number": row.get("invoiceNumber"),
            "relation_id": row.get("relationId"),
        }

        total_amount += row_analysis["amount"]

        # Check for invoice references
        if row.get("invoiceNumber"):
            linked_invoices.append(
                {
                    "row_index": i,
                    "invoice_number": row.get("invoiceNumber"),
                    "amount": row_analysis["amount"],
                    "description": row_analysis["description"],
                }
            )

        # Look for bank account references
        if row.get("ledgerId"):
            # Check if this might be a bank account
            ledger_mapping = get_ledger_mapping(row.get("ledgerId"))
            if ledger_mapping and "bank" in ledger_mapping.get("account_name", "").lower():
                bank_accounts.append(
                    {
                        "ledger_id": row.get("ledgerId"),
                        "account_name": ledger_mapping.get("account_name"),
                        "amount": row_analysis["amount"],
                    }
                )

        analysis["rows"].append(row_analysis)

    analysis["total_amount"] = total_amount
    analysis["linked_invoices"] = linked_invoices
    analysis["has_multiple_invoices"] = len(linked_invoices) > 1
    analysis["bank_account_info"] = bank_accounts

    # Check for invoice references in main mutation fields
    if mutation_data.get("invoiceNumber") and mutation_data.get("invoiceNumber") not in [
        inv["invoice_number"] for inv in linked_invoices
    ]:
        linked_invoices.insert(
            0,
            {
                "row_index": -1,  # Main mutation level
                "invoice_number": mutation_data.get("invoiceNumber"),
                "amount": total_amount,
                "description": "Main mutation invoice reference",
            },
        )
        analysis["linked_invoices"] = linked_invoices
        analysis["has_multiple_invoices"] = len(linked_invoices) > 1

    # Look for any other invoice/payment related fields
    analysis["additional_fields"] = {}
    for key, value in mutation_data.items():
        if key not in ["id", "type", "date", "description", "invoiceNumber", "relationId", "rows"] and value:
            analysis["additional_fields"][key] = value

    return analysis


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


def get_ledger_mapping(ledger_id):
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


def analyze_api_capabilities(results):
    """Analyze API capabilities based on fetched mutations"""
    capabilities = results["api_structure_findings"]

    # Analyze payment mutations
    payment_mutations = [
        m for m in results["mutations_analyzed"] if m.get("success") and m.get("is_payment_type")
    ]

    if payment_mutations:
        capabilities["payment_structure"] = {
            "supports_multiple_invoices": any(m.get("has_multiple_invoices") for m in payment_mutations),
            "invoice_reference_locations": [],
            "bank_account_representation": [],
            "amount_handling": {},
        }

        # Check where invoice references appear
        invoice_ref_locations = set()
        for m in payment_mutations:
            if m.get("invoice_number"):
                invoice_ref_locations.add("main_mutation")
            for inv in m.get("linked_invoices", []):
                if inv["row_index"] >= 0:
                    invoice_ref_locations.add("row_level")

        capabilities["payment_structure"]["invoice_reference_locations"] = list(invoice_ref_locations)

        # Analyze bank account representation
        bank_patterns = []
        for m in payment_mutations:
            if m.get("bank_account_info"):
                for bank in m["bank_account_info"]:
                    bank_patterns.append(
                        {"ledger_id": bank["ledger_id"], "account_name": bank.get("account_name", "Unknown")}
                    )

        capabilities["payment_structure"]["bank_account_representation"] = bank_patterns

        # Analyze amount handling
        capabilities["payment_structure"]["amount_handling"] = {
            "split_amounts_supported": any(len(m.get("rows", [])) > 1 for m in payment_mutations),
            "negative_amounts_found": any(
                any(r["amount"] < 0 for r in m.get("rows", [])) for m in payment_mutations
            ),
        }

    # Analyze all mutation types found
    all_types = set()
    for m in results["mutations_analyzed"]:
        if m.get("success") and m.get("type") is not None:
            all_types.add(m.get("type"))

    capabilities["mutation_types_found"] = list(all_types)

    # Check for additional fields
    additional_fields = set()
    for m in results["mutations_analyzed"]:
        if m.get("success") and m.get("additional_fields"):
            additional_fields.update(m["additional_fields"].keys())

    capabilities["additional_fields_discovered"] = list(additional_fields)

    results["payment_capabilities"] = capabilities


def generate_recommendations(results):
    """Generate recommendations based on analysis"""
    recommendations = []

    # Check if multiple invoice payments are supported
    if (
        results.get("api_structure_findings", {})
        .get("payment_structure", {})
        .get("supports_multiple_invoices")
    ):
        recommendations.append(
            {
                "finding": "Multiple Invoice Payments Supported",
                "recommendation": "Implement support for split payments across multiple invoices in Payment Entry creation",
                "priority": "high",
            }
        )

    # Check invoice reference locations
    invoice_locations = (
        results.get("api_structure_findings", {})
        .get("payment_structure", {})
        .get("invoice_reference_locations", [])
    )
    if "row_level" in invoice_locations:
        recommendations.append(
            {
                "finding": "Invoice references found at row level",
                "recommendation": "Parse row-level invoice references to properly allocate payments",
                "priority": "high",
            }
        )

    # Check bank account handling
    if (
        results.get("api_structure_findings", {})
        .get("payment_structure", {})
        .get("bank_account_representation")
    ):
        recommendations.append(
            {
                "finding": "Bank accounts identified via ledger mappings",
                "recommendation": "Use ledger mappings to identify correct bank/cash accounts for payments",
                "priority": "medium",
            }
        )

    # Check for split amounts
    if (
        results.get("api_structure_findings", {})
        .get("payment_structure", {})
        .get("amount_handling", {})
        .get("split_amounts_supported")
    ):
        recommendations.append(
            {
                "finding": "Split amount payments detected",
                "recommendation": "Handle multi-row payment mutations by creating appropriate journal entries or split allocations",
                "priority": "medium",
            }
        )

    results["recommendations"] = recommendations


def print_summary(results):
    """Print a summary of findings"""
    print(f"\n{'='*80}")
    print("ANALYSIS SUMMARY")
    print(f"{'='*80}")

    print(f"\nMutations Analyzed: {len(results['mutations_analyzed'])}")
    successful = len([m for m in results["mutations_analyzed"] if m.get("success")])
    print(f"  Successful: {successful}")
    print(f"  Failed: {len(results['mutations_analyzed']) - successful}")

    if results.get("api_structure_findings", {}).get("payment_structure"):
        payment_struct = results["api_structure_findings"]["payment_structure"]
        print("\nPayment Structure Findings:")
        print(f"  Multiple Invoice Support: {payment_struct.get('supports_multiple_invoices', False)}")
        print(
            f"  Invoice Reference Locations: {', '.join(payment_struct.get('invoice_reference_locations', []))}"
        )
        print(
            f"  Split Amounts Supported: {payment_struct.get('amount_handling', {}).get('split_amounts_supported', False)}"
        )

    if results.get("recommendations"):
        print("\nKey Recommendations:")
        for i, rec in enumerate(results["recommendations"], 1):
            print(f"  {i}. {rec['finding']}")
            print(f"     → {rec['recommendation']}")
            print(f"     Priority: {rec['priority']}")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    try:
        results = analyze_specific_mutations()
        frappe.db.commit()
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
