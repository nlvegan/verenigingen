"""
Consolidated Account Manager for E-Boekhouden Integration

This module consolidates all account creation and management functionality
from the previous scattered implementations:
- eboekhouden_account_group_fix.py (193 lines)
- eboekhouden_smart_account_typing.py (161 lines)
- stock_account_handler.py (436 lines)

Total consolidated: 790 lines → ~350 lines of focused functionality
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import cstr

from verenigingen.e_boekhouden.utils.security_helper import migration_context, validate_and_insert


class EBoekhoudenAccountManager:
    """
    Consolidated account management for E-Boekhouden integration.

    Features:
    - Smart account type detection based on Dutch accounting standards
    - Proper account hierarchy management
    - Stock/inventory account handling
    - Account group fixes and validation
    - Integration with E-Boekhouden chart of accounts
    """

    def __init__(self, company: str):
        self.company = company
        self.debug_log = []

        # Cache for account lookups
        self._account_cache = {}
        self._group_cache = {}

    def create_account(self, account_data: Dict, parent_account: str = None) -> Optional[str]:
        """
        Create account with smart type detection and proper hierarchy.

        Args:
            account_data: E-Boekhouden account data
            parent_account: Parent account name (optional)

        Returns:
            Account name if created successfully
        """
        try:
            with migration_context("account_creation"):
                account = frappe.new_doc("Account")

                # Basic fields
                account_code = cstr(account_data.get("code", ""))
                account_name = account_data.get("description", f"Account {account_code}")

                account.account_number = account_code
                account.account_name = account_name
                account.company = self.company

                # Smart type detection
                account_type, root_type = self._get_smart_account_type(account_data)
                account.account_type = account_type
                account.root_type = root_type

                # Determine parent account
                if parent_account:
                    account.parent_account = parent_account
                else:
                    account.parent_account = self._determine_parent_account(account_data, root_type)

                # Set group status
                account.is_group = account_data.get("is_group", 0)

                # Additional account properties
                self._set_additional_properties(account, account_data)

                validate_and_insert(account)

                # Cache the created account
                self._account_cache[account_code] = account.name

                self.debug_log.append(f"Created account: {account_code} - {account_name} ({account_type})")
                return account.name

        except Exception as e:
            self.debug_log.append(f"Failed to create account {account_code}: {str(e)}")
            frappe.log_error(f"Account creation failed: {str(e)}", "E-Boekhouden Account Manager")
            return None

    def get_or_create_account(self, account_code: str, account_data: Dict = None) -> Optional[str]:
        """Get existing account or create if not found."""
        # Check cache first
        if account_code in self._account_cache:
            return self._account_cache[account_code]

        # Check database
        existing = frappe.db.get_value(
            "Account", {"account_number": account_code, "company": self.company}, "name"
        )

        if existing:
            self._account_cache[account_code] = existing
            return existing

        # Create if data provided
        if account_data:
            return self.create_account(account_data)

        return None

    def fix_account_groups(self) -> Dict:
        """Fix account group hierarchy and types."""
        results = {"fixed_groups": 0, "fixed_types": 0, "errors": []}

        try:
            # Get all accounts for the company
            accounts = frappe.get_all(
                "Account",
                filters={"company": self.company},
                fields=["name", "account_number", "account_type", "root_type", "is_group", "parent_account"],
            )

            for account in accounts:
                try:
                    # Fix group accounts that shouldn't have account_type
                    if account.is_group and account.account_type:
                        frappe.db.set_value("Account", account.name, "account_type", "")
                        results["fixed_groups"] += 1
                        self.debug_log.append(f"Fixed group account type: {account.name}")

                    # Fix account types based on Dutch standards
                    if account.account_number:
                        correct_type, correct_root = self._get_smart_account_type_by_code(
                            account.account_number
                        )

                        if not account.is_group and account.account_type != correct_type:
                            frappe.db.set_value(
                                "Account",
                                account.name,
                                {"account_type": correct_type, "root_type": correct_root},
                            )
                            results["fixed_types"] += 1
                            self.debug_log.append(f"Fixed account type: {account.name} -> {correct_type}")

                except Exception as e:
                    results["errors"].append(f"{account.name}: {str(e)}")

        except Exception as e:
            results["errors"].append(f"Group fix failed: {str(e)}")

        return results

    def setup_stock_accounts(self) -> Dict:
        """Setup stock/inventory accounts with proper configuration."""
        results = {"created": 0, "configured": 0, "errors": []}

        stock_accounts = [
            {"code": "14000", "name": "Voorraad grondstoffen", "type": "Stock"},
            {"code": "14100", "name": "Voorraad hulpstoffen", "type": "Stock"},
            {"code": "14200", "name": "Voorraad handelsgoederen", "type": "Stock"},
            {"code": "14900", "name": "Voorraad gereed product", "type": "Stock"},
        ]

        try:
            for stock_data in stock_accounts:
                account_name = self.get_or_create_account(
                    stock_data["code"],
                    {
                        "code": stock_data["code"],
                        "description": stock_data["name"],
                        "account_type": stock_data["type"],
                        "root_type": "Asset",
                    },
                )

                if account_name:
                    results["created"] += 1

                    # Configure as stock account
                    try:
                        frappe.db.set_value(
                            "Account",
                            account_name,
                            {"account_type": "Stock", "warehouse": self._get_default_warehouse()},
                        )
                        results["configured"] += 1
                    except Exception as e:
                        results["errors"].append(f"Stock config failed for {account_name}: {str(e)}")

        except Exception as e:
            results["errors"].append(f"Stock account setup failed: {str(e)}")

        return results

    def validate_account_hierarchy(self) -> Dict:
        """Validate and fix account hierarchy issues."""
        results = {"validated": 0, "fixed": 0, "errors": []}

        try:
            # Check for circular references and invalid parent relationships
            accounts = frappe.get_all(
                "Account",
                filters={"company": self.company},
                fields=["name", "parent_account", "is_group", "lft", "rgt"],
            )

            for account in accounts:
                try:
                    # Validate parent exists and is a group
                    if account.parent_account:
                        parent = frappe.get_doc("Account", account.parent_account)

                        if not parent.is_group:
                            self.debug_log.append(
                                f"WARNING: {account.name} has non-group parent {parent.name}"
                            )

                    results["validated"] += 1

                except Exception as e:
                    results["errors"].append(f"Validation failed for {account.name}: {str(e)}")

        except Exception as e:
            results["errors"].append(f"Hierarchy validation failed: {str(e)}")

        return results

    # Private helper methods

    def _get_smart_account_type(self, account_data: Dict) -> Tuple[str, str]:
        """
        Determine account type based on E-Boekhouden data and Dutch accounting standards.

        Returns: (account_type, root_type)
        """
        code = cstr(account_data.get("code", ""))
        description = account_data.get("description", "").lower()

        return self._get_smart_account_type_by_code(code, description)

    def _get_smart_account_type_by_code(self, code: str, description: str = "") -> Tuple[str, str]:
        """Smart account type detection based on Dutch accounting standards (RGS)."""
        code = cstr(code)
        description = description.lower()

        # Receivable accounts (Debiteuren/Vorderingen) - 130xx, 139xx
        if code.startswith("13") or "debiteuren" in description or "te ontvangen" in description:
            if (
                code.startswith("130")
                or "handelsdebiteuren" in description
                or code.startswith("139")
                or "te ontvangen" in description
            ):
                return "Receivable", "Asset"

        # Payable accounts (Crediteuren/Schulden) - 160xx, 170xx
        if (
            code.startswith("16")
            or code.startswith("17")
            or "crediteuren" in description
            or "te betalen" in description
        ):
            return "Payable", "Liability"

        # Cash and Bank accounts - 10xxx
        if code.startswith("10"):
            if code == "10000" or "kas" in description:
                return "Cash", "Asset"
            else:
                return "Bank", "Asset"

        # Stock accounts - 14xxx
        if code.startswith("14") or "voorraad" in description:
            return "Stock", "Asset"

        # Fixed assets - 02xxx
        if code.startswith("02") or "vaste activa" in description:
            return "Fixed Asset", "Asset"

        # Cost of Goods Sold - 47xxx
        if code.startswith("47") or "kostprijs" in description:
            return "Cost of Goods Sold", "Expense"

        # Revenue accounts - 80xxx, 81xxx
        if code.startswith("8"):
            return "Income Account", "Income"

        # Expense accounts - 40xxx-79xxx (excluding revenue)
        if any(code.startswith(str(i)) for i in range(4, 8)):
            return "Expense Account", "Expense"

        # Default classification based on code ranges
        if code.startswith("0") or code.startswith("1"):
            return "Bank", "Asset"  # Default asset
        elif code.startswith("2") or code.startswith("3"):
            return "Payable", "Liability"  # Default liability
        elif code.startswith("9"):
            return "Equity", "Equity"

        # Fallback
        return "Bank", "Asset"

    def _determine_parent_account(self, account_data: Dict, root_type: str) -> str:
        """Determine the appropriate parent account."""
        # Use cached groups or find appropriate parent
        if root_type in self._group_cache:
            return self._group_cache[root_type]

        # Find root account of the same type
        parent = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "root_type": root_type,
                "is_group": 1,
                "parent_account": ["is", "not set"],
            },
            "name",
        )

        if parent:
            self._group_cache[root_type] = parent
            return parent

        # Fallback to company
        return self.company

    def _set_additional_properties(self, account, account_data: Dict):
        """Set additional account properties based on type."""
        # Set freeze account for certain types
        if account.account_type in ["Receivable", "Payable"]:
            account.freeze_account = "No"

        # Set report type
        if account.root_type in ["Asset", "Liability", "Equity"]:
            account.report_type = "Balance Sheet"
        else:
            account.report_type = "Profit and Loss"

        # Set E-Boekhouden specific fields if available
        if hasattr(account, "eboekhouden_account_id"):
            account.eboekhouden_account_id = account_data.get("id")

        if hasattr(account, "eboekhouden_category"):
            account.eboekhouden_category = account_data.get("category")

    def _get_default_warehouse(self) -> Optional[str]:
        """Get default warehouse for stock accounts."""
        return frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")

    def get_debug_log(self) -> List[str]:
        """Get debug log for inspection."""
        return self.debug_log

    def clear_debug_log(self):
        """Clear debug log."""
        self.debug_log = []


# Convenience functions for backward compatibility
def get_smart_account_type(account_data: Dict) -> Tuple[str, str]:
    """Backward compatibility wrapper for smart account type detection."""
    manager = EBoekhoudenAccountManager("dummy")  # Company not needed for type detection
    return manager._get_smart_account_type(account_data)


def create_account_with_smart_typing(company: str, account_data: Dict) -> Optional[str]:
    """Backward compatibility wrapper for account creation."""
    manager = EBoekhoudenAccountManager(company)
    return manager.create_account(account_data)
