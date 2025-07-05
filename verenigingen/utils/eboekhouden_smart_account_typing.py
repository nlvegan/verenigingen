"""
Smart account type detection for E-Boekhouden imports
Correctly identifies Receivable/Payable accounts based on Dutch accounting standards
"""

import frappe


def get_smart_account_type(account_data):
    """
    Determine the correct ERPNext account type based on E-Boekhouden account data

    Returns: (account_type, root_type)
    """
    code = str(account_data.get("code", ""))
    description = account_data.get("description", "").lower()
    category = account_data.get("category", "")

    # Special handling for specific account codes that MUST be Receivable/Payable
    # These are based on Dutch accounting standards (RGS)

    # Receivable accounts (Debiteuren/Vorderingen)
    if code.startswith("13") or "debiteuren" in description:
        # 130xx range is typically trade debtors
        if code.startswith("130") or "handelsdebiteuren" in description:
            return "Receivable", "Asset"
        # 139xx range is typically amounts to be received
        elif code.startswith("139") or "te ontvangen" in description:
            return "Receivable", "Asset"
        # Other 13xxx might be general current assets
        else:
            # Check for specific keywords that indicate receivables
            receivable_keywords = [
                "debiteuren",
                "debiteur",
                "te ontvangen",
                "te vorderen",
                "vordering op",
                "nog te factureren",
                "nog te ontvangen",
            ]
            if any(keyword in description for keyword in receivable_keywords):
                return "Receivable", "Asset"
            else:
                return "Current Asset", "Asset"

    # Payable accounts (Crediteuren/Schulden)
    elif code.startswith("44") or "crediteuren" in description:
        # 440xx range is typically trade creditors
        if code.startswith("440") or "handelscrediteuren" in description:
            return "Payable", "Liability"
        # 449xx range is typically amounts to be paid
        elif code.startswith("449") or "te betalen" in description:
            return "Payable", "Liability"
        # Other 44xxx might be general current liabilities
        else:
            # Check for specific keywords that indicate payables
            payable_keywords = [
                "crediteuren",
                "crediteur",
                "te betalen",
                "schuld aan",
                "nog te betalen",
                "nog te ontvangen facturen",
            ]
            if any(keyword in description for keyword in payable_keywords):
                return "Payable", "Liability"
            else:
                return "Current Liability", "Liability"

    # Other current assets that might need special handling
    elif code.startswith("12"):
        # 12xxx is typically other receivables
        if "te ontvangen" in description or "vordering" in description:
            return "Receivable", "Asset"
        else:
            return "Current Asset", "Asset"

    # Other current liabilities that might need special handling
    elif code.startswith("45") or code.startswith("46"):
        # 45xxx/46xxx often includes amounts payable
        if "te betalen" in description or "schuld" in description:
            return "Payable", "Liability"
        else:
            return "Current Liability", "Liability"

    # Bank and Cash accounts
    elif code.startswith("10"):
        if code == "10000" or "kas" in description:
            return "Cash", "Asset"
        else:
            return "Bank", "Asset"

    # Fixed Assets
    elif code.startswith("0"):
        return "Fixed Asset", "Asset"

    # Inventory/Stock
    elif code.startswith("3") or "voorraad" in description:
        return "Stock", "Asset"

    # Equity accounts
    elif code.startswith("5") or category == "EIG":
        return "Equity", "Equity"

    # Income accounts
    elif code.startswith("8") or code.startswith("9"):
        return "Income Account", "Income"

    # Expense accounts
    elif code.startswith("4") or code.startswith("6") or code.startswith("7"):
        # But not 44xxx which is creditors
        if not code.startswith("44"):
            return "Expense Account", "Expense"

    # Tax accounts
    elif "btw" in description or "belasting" in description:
        return "Tax", "Liability"

    # Default fallbacks based on category
    if category:
        category_mapping = {
            "DEB": ("Receivable", "Asset"),
            "CRED": ("Payable", "Liability"),
            "FIN": ("Bank", "Asset"),
            "KAS": ("Cash", "Asset"),
            "VW": ("Expense Account", "Expense"),  # Verbruiksrekeningen
            "BTW": ("Tax", "Liability"),
            "EIG": ("Equity", "Equity"),
            "BAL": ("Current Asset", "Asset"),  # Balance sheet - needs context
        }

        if category in category_mapping:
            return category_mapping[category]

    # Final fallback based on code ranges
    if code:
        first_digit = code[0]
        if first_digit in ["0", "1", "2", "3"]:
            return "Current Asset", "Asset"
        elif first_digit == "4":
            return "Current Liability", "Liability"
        elif first_digit == "5":
            return "Equity", "Equity"
        elif first_digit in ["6", "7"]:
            return "Expense Account", "Expense"
        elif first_digit in ["8", "9"]:
            return "Income Account", "Income"

    # Ultimate fallback
    return "Current Asset", "Asset"


@frappe.whitelist()
def test_account_type_detection(account_code=None):
    """Test function to check what type would be assigned to an account"""
    if not account_code:
        # Test with some common examples
        test_accounts = [
            {"code": "13000", "description": "Handelsdebiteuren"},
            {"code": "13900", "description": "Te ontvangen bedragen"},
            {"code": "13100", "description": "Overige vorderingen"},
            {"code": "44000", "description": "Handelscrediteuren"},
            {"code": "44900", "description": "Te betalen bedragen"},
            {"code": "10000", "description": "Kas"},
            {"code": "10100", "description": "Bank"},
            {"code": "70000", "description": "Personeelskosten"},
            {"code": "80000", "description": "Omzet"},
        ]

        results = []
        for acc in test_accounts:
            account_type, root_type = get_smart_account_type(acc)
            results.append(
                {
                    "code": acc["code"],
                    "description": acc["description"],
                    "account_type": account_type,
                    "root_type": root_type,
                }
            )

        return {"success": True, "results": results}
    else:
        # Test specific account
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Get account from E-Boekhouden
        accounts = api.get_chart_of_accounts()
        if accounts["success"]:
            import json

            all_accounts = json.loads(accounts["data"]).get("items", [])

            for acc in all_accounts:
                if str(acc.get("code")) == str(account_code):
                    account_type, root_type = get_smart_account_type(acc)
                    return {
                        "success": True,
                        "account": acc,
                        "detected_type": account_type,
                        "detected_root": root_type,
                    }

        return {"success": False, "error": f"Account {account_code} not found"}
