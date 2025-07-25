"""
Stock Account Handler for eBoekhouden Integration

This module provides enhanced handling for stock accounts during opening balance import.
Stock accounts in ERPNext can only be updated via Stock transactions, not Journal Entries.
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, flt


class StockAccountHandler:
    """Handler for stock accounts in eBoekhouden opening balance import"""

    def __init__(self, company: str, debug_info: List[str]):
        self.company = company
        self.debug_info = debug_info
        self.stock_accounts_found = []
        self.stock_account_options = {}

    def is_stock_account(self, account_name: str) -> bool:
        """Check if an account is a stock account"""
        try:
            account_doc = frappe.get_doc("Account", account_name)
            return account_doc.account_type == "Stock"
        except frappe.DoesNotExistError:
            return False

    def get_stock_accounts_from_balances(self, balances: List[Dict]) -> List[Dict]:
        """Extract stock accounts from opening balances"""
        stock_accounts = []

        for balance in balances:
            ledger_id = balance.get("ledgerId")
            if not ledger_id:
                continue

            # Get account mapping
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account
                   FROM `tabE-Boekhouden Ledger Mapping`
                   WHERE ledger_id = %s
                   LIMIT 1""",
                ledger_id,
            )

            if mapping_result:
                account = mapping_result[0][0]
                if self.is_stock_account(account):
                    stock_accounts.append(
                        {
                            "ledger_id": ledger_id,
                            "account": account,
                            "balance": balance.get("balance", 0),
                            "description": balance.get("description", ""),
                        }
                    )

        return stock_accounts

    def get_stock_handling_options(self) -> Dict[str, Any]:
        """Get available options for handling stock accounts"""
        return {
            "skip_stock_accounts": {
                "label": "Skip Stock Accounts",
                "description": "Skip stock accounts during opening balance import (recommended)",
                "recommended": True,
            },
            "remap_to_asset": {
                "label": "Remap to Asset Account",
                "description": "Temporarily remap stock accounts to generic asset accounts",
                "recommended": False,
            },
            "create_stock_reconciliation": {
                "label": "Create Stock Reconciliation",
                "description": "Create Stock Reconciliation entries for stock accounts",
                "recommended": False,
                "note": "Requires item mappings and warehouse setup",
            },
        }

    def skip_stock_accounts(self, balances: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Skip stock accounts from opening balances
        Returns: (filtered_balances, skipped_stock_accounts)
        """
        filtered_balances = []
        skipped_stock_accounts = []

        for balance in balances:
            ledger_id = balance.get("ledgerId")
            if not ledger_id:
                filtered_balances.append(balance)
                continue

            # Get account mapping
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account
                   FROM `tabE-Boekhouden Ledger Mapping`
                   WHERE ledger_id = %s
                   LIMIT 1""",
                ledger_id,
            )

            if mapping_result:
                account = mapping_result[0][0]
                if self.is_stock_account(account):
                    skipped_stock_accounts.append(
                        {
                            "ledger_id": ledger_id,
                            "account": account,
                            "balance": balance.get("balance", 0),
                            "description": balance.get("description", ""),
                            "reason": "Stock account - requires Stock transactions",
                        }
                    )
                    self.debug_info.append(
                        f"Skipped stock account {account} (balance: {balance.get('balance', 0)})"
                    )
                    continue

            filtered_balances.append(balance)

        return filtered_balances, skipped_stock_accounts

    def create_alternative_asset_mappings(self, stock_accounts: List[Dict]) -> Dict[str, str]:
        """
        Create temporary mappings from stock accounts to asset accounts
        Returns: mapping of stock_account -> asset_account
        """
        asset_mappings = {}

        # Find or create a generic asset account for stock value
        generic_asset_account = self.get_or_create_generic_asset_account()

        for stock_account_info in stock_accounts:
            stock_account = stock_account_info["account"]
            asset_mappings[stock_account] = generic_asset_account

            self.debug_info.append(
                f"Stock account {stock_account} mapped to asset account {generic_asset_account}"
            )

        return asset_mappings

    def get_or_create_generic_asset_account(self) -> str:
        """Get or create a generic asset account for stock value"""
        account_name = f"Stock Value (Opening Balance) - {self.company}"

        # Check if account exists
        if frappe.db.exists("Account", account_name):
            return account_name

        # Create the account
        try:
            # Get the parent account for Current Assets
            parent_account = self.get_current_assets_account()

            account = frappe.new_doc("Account")
            account.account_name = "Stock Value (Opening Balance)"
            account.parent_account = parent_account
            account.company = self.company
            account.account_type = "Temporary"  # Use Temporary account type
            account.root_type = "Asset"
            account.is_group = 0
            account.insert()

            self.debug_info.append(f"Created temporary asset account: {account.name}")
            return account.name

        except Exception as e:
            self.debug_info.append(f"Failed to create temporary asset account: {str(e)}")
            # Try with Asset account type as fallback
            try:
                account = frappe.new_doc("Account")
                account.account_name = "Stock Value (Opening Balance)"
                account.parent_account = parent_account
                account.company = self.company
                account.account_type = "Asset"  # Fallback to Asset type
                account.root_type = "Asset"
                account.is_group = 0
                account.insert()

                self.debug_info.append(f"Created asset account (fallback): {account.name}")
                return account.name

            except Exception as e2:
                self.debug_info.append(f"Failed to create fallback asset account: {str(e2)}")
                # Final fallback to existing account
                return self.get_existing_temporary_account()

    def get_current_assets_account(self) -> str:
        """Get the Current Assets parent account"""
        # Look for common Current Assets account names
        current_assets_accounts = [
            f"Current Assets - {self.company}",
            f"1000 - Current Assets - {self.company}",
            "Current Assets - NVV",
            "1000 - Current Assets - NVV",
        ]

        for account_name in current_assets_accounts:
            if frappe.db.exists("Account", account_name):
                return account_name

        # If not found, find any Asset account that is a group
        result = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s
               AND root_type = 'Asset'
               AND is_group = 1
               AND account_name LIKE '%Current%'
               LIMIT 1""",
            self.company,
        )

        if result:
            return result[0][0]

        # Final fallback
        return f"Application of Funds (Assets) - {self.company}"

    def get_existing_temporary_account(self) -> str:
        """Get an existing temporary or suspense account"""
        # Look for common temporary account names
        temp_accounts = [
            f"Temporary Opening - {self.company}",
            f"Suspense Account - {self.company}",
            f"Temporary Differences - {self.company}",
            f"Retained Earnings - {self.company}",
            f"Capital Stock - {self.company}",
        ]

        for account_name in temp_accounts:
            if frappe.db.exists("Account", account_name):
                self.debug_info.append(f"Using existing temporary account: {account_name}")
                return account_name

        # If no temporary accounts found, find any Equity account
        equity_accounts = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s
               AND root_type = 'Equity'
               AND is_group = 0
               LIMIT 1""",
            self.company,
        )

        if equity_accounts:
            account_name = equity_accounts[0][0]
            self.debug_info.append(f"Using equity account as fallback: {account_name}")
            return account_name

        # Ultimate fallback
        return f"Application of Funds (Assets) - {self.company}"

    def create_stock_reconciliation_suggestion(self, stock_accounts: List[Dict]) -> Dict[str, Any]:
        """
        Create a suggestion for handling stock accounts via Stock Reconciliation
        """
        return {
            "method": "Stock Reconciliation",
            "description": "Create Stock Reconciliation entries for opening stock balances",
            "stock_accounts": stock_accounts,
            "requirements": [
                "Item master data must be created for all stock items",
                "Warehouse must be configured",
                "Stock UOM must be defined for each item",
                "Opening stock quantities must be determined",
            ],
            "steps": [
                "1. Create Items for all stock entries",
                "2. Set up Default Warehouse",
                "3. Create Stock Reconciliation document",
                "4. Enter opening quantities and rates",
                "5. Submit Stock Reconciliation",
            ],
            "note": "This method requires manual setup of item master data and is not automated",
        }

    def generate_stock_account_report(self, stock_accounts: List[Dict]) -> Dict[str, Any]:
        """Generate a report of stock accounts found during import"""
        total_stock_value = sum(flt(acc.get("balance", 0)) for acc in stock_accounts)

        return {
            "total_stock_accounts": len(stock_accounts),
            "total_stock_value": total_stock_value,
            "stock_accounts": stock_accounts,
            "recommendations": [
                "Stock accounts should be handled via Stock Reconciliation in ERPNext",
                "Consider if stock tracking is needed for this organization",
                "If stock is not actively managed, remap to generic asset accounts",
                "For active stock management, set up proper Item masters and Warehouses",
            ],
        }


@frappe.whitelist()
def analyze_stock_accounts_in_opening_balances(company: str = None) -> Dict[str, Any]:
    """
    Analyze stock accounts in opening balances and provide handling options
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    debug_info = []
    handler = StockAccountHandler(company, debug_info)

    try:
        # Get opening balances from eBoekhouden
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()
        result = api.make_request("v1/mutation", method="GET", params={"type": 0})

        if not result or not result.get("success"):
            return {"success": False, "error": "Failed to fetch opening balances from eBoekhouden"}

        balances = result.get("data", [])
        stock_accounts = handler.get_stock_accounts_from_balances(balances)

        if not stock_accounts:
            return {
                "success": True,
                "message": "No stock accounts found in opening balances",
                "stock_accounts": [],
                "debug_info": debug_info,
            }

        # Generate report and options
        report = handler.generate_stock_account_report(stock_accounts)
        options = handler.get_stock_handling_options()

        return {
            "success": True,
            "stock_accounts_found": len(stock_accounts),
            "stock_accounts": stock_accounts,
            "report": report,
            "handling_options": options,
            "debug_info": debug_info,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "debug_info": debug_info}


@frappe.whitelist()
def import_opening_balances_with_stock_handling(
    company: str = None, stock_handling_method: str = "skip_stock_accounts"
) -> Dict[str, Any]:
    """
    Import opening balances with enhanced stock account handling

    Args:
        company: Company name
        stock_handling_method: Method for handling stock accounts
            - "skip_stock_accounts": Skip stock accounts (recommended)
            - "remap_to_asset": Remap to generic asset accounts
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    debug_info = []
    handler = StockAccountHandler(company, debug_info)

    try:
        # Get opening balances from eBoekhouden
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()
        result = api.make_request("v1/mutation", method="GET", params={"type": 0})

        if not result or not result.get("success"):
            return {"success": False, "error": "Failed to fetch opening balances from eBoekhouden"}

        balances = result.get("data", [])

        # Handle stock accounts based on selected method
        if stock_handling_method == "skip_stock_accounts":
            filtered_balances, skipped_stock_accounts = handler.skip_stock_accounts(balances)

            # Import the filtered balances using the existing function
            # Get cost center
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                _import_opening_balances_from_data,
                get_default_cost_center,
            )

            cost_center = get_default_cost_center(company)

            if not cost_center:
                return {"success": False, "error": "No cost center found for company"}

            # Import with filtered balances
            import_result = _import_opening_balances_from_data(
                filtered_balances, company, cost_center, debug_info
            )

            return {
                "success": True,
                "import_result": import_result,
                "stock_accounts_skipped": len(skipped_stock_accounts),
                "skipped_accounts": skipped_stock_accounts,
                "debug_info": debug_info,
                "message": f"Opening balances imported successfully. {len(skipped_stock_accounts)} stock accounts were skipped.",
            }

        elif stock_handling_method == "remap_to_asset":
            # This would require more complex logic - for now, return a message
            return {
                "success": False,
                "error": "Asset remapping not yet implemented. Please use 'skip_stock_accounts' method.",
                "debug_info": debug_info,
            }

        else:
            return {
                "success": False,
                "error": f"Unknown stock handling method: {stock_handling_method}",
                "debug_info": debug_info,
            }

    except Exception as e:
        import traceback

        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "debug_info": debug_info,
        }
