import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def should_remove_prepare_system_button():
    """
    Analysis of whether the 'Prepare System' button should be removed
    """

    return {
        "recommendation": "Transform, don't remove",
        "reasons": [
            "SOAP API now handles all account/customer/supplier creation dynamically",
            "Account type fixing is now intelligent and based on actual usage patterns",
            "No need to pre-create cost centers or parties - they're created as needed",
            "System preparation steps are now integrated into the migration process itself",
        ],
        "useful_features_to_keep": [
            "Date range detection - helps users understand their data scope",
            "Connection testing - validates API credentials",
            "Data statistics - shows what will be imported",
        ],
        "suggested_changes": {
            "rename_to": "Analyze E-Boekhouden Data",
            "new_functionality": [
                "Show date range of available transactions",
                "Display count of mutations by type",
                "Preview account usage patterns",
                "Identify potential issues before migration",
            ],
            "remove": [
                "Cost center creation",
                "Party creation",
                "Account type adjustments",
                "Manual system preparation steps",
            ],
        },
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def analyze_eboekhouden_data():
    """
    Analyze E-Boekhouden data without making any system changes
    This replaces the old 'prepare_system' functionality
    """

    from verenigingen.e_boekhouden.utils_date_analyzer import get_actual_date_range
    from verenigingen.e_boekhouden.utils_soap_api import EBoekhoudenSOAPAPI

    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenSOAPAPI(settings)

        # Get actual date range from the data
        date_range_result = get_actual_date_range()

        if not date_range_result["success"]:
            return {"success": False, "error": date_range_result.get("error", "Failed to get date range")}

        # Get mutations for analysis
        # IMPORTANT: SOAP API only returns the most recent 500 mutations
        # regardless of date range or mutation number parameters
        result = api.get_mutations()

        if not result["success"]:
            return {"success": False, "error": result.get("error")}

        mutations = result["mutations"]

        # Analyze the data
        analysis = {
            "date_range": {
                "earliest_date": date_range_result["earliest_date"],
                "latest_date": date_range_result["latest_date"],
            },
            "mutation_types": {},
            "account_usage": {
                "receivable_accounts": set(),
                "payable_accounts": set(),
                "bank_accounts": set(),
                "income_accounts": set(),
                "expense_accounts": set(),
            },
            "entities": {"unique_customers": set(), "unique_suppliers": set()},
        }

        for mut in mutations:
            # We already have the actual date range from get_actual_date_range()

            # Count mutation types
            mutation_type = mut.get("Soort", "Unknown")
            analysis["mutation_types"][mutation_type] = analysis["mutation_types"].get(mutation_type, 0) + 1

            # Analyze account usage
            account_code = mut.get("Rekening")
            if account_code:
                if mutation_type == "FactuurVerstuurd":
                    analysis["account_usage"]["receivable_accounts"].add(account_code)
                elif mutation_type == "FactuurOntvangen":
                    analysis["account_usage"]["payable_accounts"].add(account_code)
                elif mutation_type in ["GeldOntvangen", "GeldUitgegeven"]:
                    analysis["account_usage"]["bank_accounts"].add(account_code)

            # Count entities
            relation_code = mut.get("RelatieCode")
            if relation_code:
                if mutation_type in ["FactuurVerstuurd", "FactuurbetalingOntvangen"]:
                    analysis["entities"]["unique_customers"].add(relation_code)
                elif mutation_type in ["FactuurOntvangen", "FactuurbetalingVerstuurd"]:
                    analysis["entities"]["unique_suppliers"].add(relation_code)

            # Analyze line items for account usage
            for regel in mut.get("MutatieRegels", []):
                account_code = regel.get("TegenrekeningCode")
                if account_code:
                    if mutation_type in ["FactuurVerstuurd", "GeldOntvangen"]:
                        analysis["account_usage"]["income_accounts"].add(account_code)
                    elif mutation_type in ["FactuurOntvangen", "GeldUitgegeven"]:
                        analysis["account_usage"]["expense_accounts"].add(account_code)

        # Also get the actual account counts from the system
        actual_receivable_count = 0
        if frappe.db.exists("Company", settings.default_company):
            actual_receivable_count = frappe.db.count(
                "Account", {"company": settings.default_company, "account_type": "Receivable", "is_group": 0}
            )

        # Get the highest mutation number from the available data
        total_estimate = None
        mutation_numbers = []
        for mut in mutations:
            if mut.get("MutatieNr"):
                try:
                    mutation_numbers.append(int(mut.get("MutatieNr")))
                except Exception:
                    pass

        if mutation_numbers:
            highest_num = max(mutation_numbers)
            lowest_num = min(mutation_numbers)
            # If we have 500 mutations and they're not starting from 1,
            # there are definitely more mutations in the system
            if len(mutations) == 500 and lowest_num > 1:
                total_estimate = f"{highest_num}+ (showing only last 500)"

        # Convert sets to counts for JSON serialization
        summary = {
            "success": True,
            "date_range": {
                "earliest_date": date_range_result["earliest_date"],
                "latest_date": date_range_result["latest_date"],
                "earliest_formatted": date_range_result["earliest_formatted"],
                "latest_formatted": date_range_result["latest_formatted"],
            },
            "total_mutations": len(mutations),
            "total_estimate": total_estimate,
            "mutation_types": analysis["mutation_types"],
            "account_summary": {
                "receivable_accounts": len(analysis["account_usage"]["receivable_accounts"]),
                "payable_accounts": len(analysis["account_usage"]["payable_accounts"]),
                "bank_accounts": len(analysis["account_usage"]["bank_accounts"]),
                "income_accounts": len(analysis["account_usage"]["income_accounts"]),
                "expense_accounts": len(analysis["account_usage"]["expense_accounts"]),
                "actual_receivable_accounts": actual_receivable_count,
            },
            "entity_summary": {
                "unique_customers": len(analysis["entities"]["unique_customers"]),
                "unique_suppliers": len(analysis["entities"]["unique_suppliers"]),
            },
            "insights": generate_insights(analysis, len(mutations)),
        }

        return summary

    except Exception as e:
        frappe.log_error(f"E-Boekhouden analysis error: {str(e)}", "E-Boekhouden Analysis")
        return {"success": False, "error": str(e)}


def generate_insights(analysis, mutation_count=0):
    """Generate helpful insights from the analysis"""
    insights = []

    # Date range insight
    if analysis["date_range"]["earliest_date"] and analysis["date_range"]["latest_date"]:
        from datetime import datetime

        earliest = datetime.strptime(analysis["date_range"]["earliest_date"], "%Y-%m-%d")
        latest = datetime.strptime(analysis["date_range"]["latest_date"], "%Y-%m-%d")
        days = (latest - earliest).days
        insights.append(f"Your E-Boekhouden data spans {days} days ({days // 365} years)")

    # Account type insights
    total_accounts = sum(len(accounts) for accounts in analysis["account_usage"].values())
    if total_accounts > 0:
        insights.append(f"Found {total_accounts} unique accounts in use across all transaction types")

    # Transaction volume insights
    total_mutations = sum(analysis["mutation_types"].values())
    if total_mutations > 100:
        insights.append("You have a substantial transaction history - migration may take several minutes")
    elif total_mutations < 10:
        insights.append("Light transaction volume detected - migration should be quick")

    # Entity insights
    customers = len(analysis["entities"]["unique_customers"])
    suppliers = len(analysis["entities"]["unique_suppliers"])
    if customers > 0 or suppliers > 0:
        insights.append(f"Will create {customers} customers and {suppliers} suppliers during migration")

    # Add warning about limited data
    if mutation_count == 500:
        insights.insert(0, "⚠️ SOAP API limitation: Analysis shows only the most recent 500 mutations.")
        insights.insert(1, "The actual migration will also be limited to these 500 most recent transactions.")
        insights.insert(2, "To import older transactions, REST API credentials are required.")

    return insights
