"""
Check if opening balances mutation (type 0) includes a date
"""

import traceback
from typing import Any, Dict

import frappe

from verenigingen.utils.operation_result import OperationResult

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def check_opening_balance_mutation_date() -> OperationResult[Dict[str, Any]]:
    """Check what date information is available in opening balance mutations"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get type 0 mutations (opening balances)
        opening_balance_mutations = iterator.fetch_mutations_by_type(mutation_type=0, limit=10)

        results = []
        for mutation in opening_balance_mutations:
            mutation_analysis = {
                "mutation_id": mutation.get("id"),
                "type": mutation.get("type"),
                "date": mutation.get("date"),
                "description": mutation.get("description", "")[:100],
                "amount": mutation.get("amount"),
                "ledger_id": mutation.get("ledgerId"),
                "relation_id": mutation.get("relationId"),
                "invoice_number": mutation.get("invoiceNumber"),
                "has_date": mutation.get("date") is not None,
                "date_format": type(mutation.get("date")).__name__ if mutation.get("date") else None,
            }

            # Also check rows for additional date info
            rows = mutation.get("rows", [])
            if rows:
                mutation_analysis["row_count"] = len(rows)
                mutation_analysis["first_row_sample"] = {
                    "amount": rows[0].get("amount"),
                    "description": rows[0].get("description", "")[:50],
                    "ledger_id": rows[0].get("ledgerId"),
                }

            results.append(mutation_analysis)

        data = {
            "opening_balance_mutations_found": len(opening_balance_mutations),
            "mutations": results,
            "analysis": "Shows date information available in opening balance mutations (type 0)",
        }

        return OperationResult.ok(
            data, message=_("Opening balance mutation date information retrieved successfully")
        )

    except Exception as e:
        frappe.log_error(
            title=_("Opening Balance Mutation Date Check Failed"),
            message=f"{str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(_("Failed to check opening balance mutation dates"), errors=[str(e)])


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def check_earliest_mutation_date() -> OperationResult[Dict[str, Any]]:
    """Check the earliest mutation date across all types to see the true start of data"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        earliest_dates = {}

        # Check each mutation type for earliest dates
        for mutation_type in [0, 1, 2, 3, 4, 5, 6, 7]:
            try:
                mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=50)

                if mutations:
                    dates = []
                    for mutation in mutations:
                        if mutation.get("date"):
                            dates.append(mutation.get("date"))

                    if dates:
                        earliest_dates[mutation_type] = {
                            "type_name": {
                                0: "Opening Balances",
                                1: "Purchase Invoices",
                                2: "Sales Invoices",
                                3: "Customer Payments",
                                4: "Supplier Payments",
                                5: "Money Received",
                                6: "Money Paid",
                                7: "Memorial Bookings",
                            }.get(mutation_type, f"Type {mutation_type}"),
                            "earliest_date": min(dates),
                            "latest_date": max(dates),
                            "total_mutations_checked": len(mutations),
                            "mutations_with_dates": len(dates),
                        }
            except Exception as e:
                earliest_dates[mutation_type] = {"error": str(e)}

        # Find the absolute earliest date
        all_earliest = [
            info.get("earliest_date")
            for info in earliest_dates.values()
            if isinstance(info, dict) and "earliest_date" in info
        ]

        absolute_earliest = min(all_earliest) if all_earliest else None

        data = {
            "earliest_dates_by_type": earliest_dates,
            "absolute_earliest_date": absolute_earliest,
            "recommendation": (
                f"Use {absolute_earliest} as the start date for complete history import"
                if absolute_earliest
                else "No dates found"
            ),
            "analysis": "Shows the earliest transaction date by mutation type to determine true data range",
        }

        return OperationResult.ok(data, message=_("Earliest mutation dates retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Earliest Mutation Date Check Failed"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(_("Failed to check earliest mutation dates"), errors=[str(e)])


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_opening_balance_date_for_js() -> OperationResult[Dict[str, Any]]:
    """Get the opening balance date that can be used by JavaScript for date_from setting"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # First try to get opening balance mutation date
        opening_balance_mutations = iterator.fetch_mutations_by_type(mutation_type=0, limit=5)

        opening_balance_date = None
        if opening_balance_mutations:
            # Get the date from the first opening balance mutation
            for mutation in opening_balance_mutations:
                if mutation.get("date"):
                    opening_balance_date = mutation.get("date")
                    break

        # If no opening balance date, get the earliest date from any mutation type
        if not opening_balance_date:
            earliest_date = None
            for mutation_type in [1, 2, 3, 4, 5, 6, 7]:  # Skip type 0 since we already checked
                try:
                    mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=20)
                    for mutation in mutations:
                        if mutation.get("date"):
                            if not earliest_date or mutation.get("date") < earliest_date:
                                earliest_date = mutation.get("date")
                except Exception:
                    continue
            opening_balance_date = earliest_date

        data = {
            "opening_balance_date": opening_balance_date,
            "has_date": opening_balance_date is not None,
            "usage": "This date can be used as window.eboekhouden_date_range.earliest_date in JavaScript",
        }

        return OperationResult.ok(data, message=_("Opening balance date retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Opening Balance Date Retrieval Failed"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(_("Failed to retrieve opening balance date"), errors=[str(e)])
