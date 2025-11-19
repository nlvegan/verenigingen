"""
Account Mapping Logic for E-Boekhouden Migration

This module handles all account creation, mapping, and chart of accounts
migration functionality.
"""

import frappe
from frappe.utils import now


class AccountMapper:
    """Handles account mapping and creation for E-Boekhouden migration"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.company = migration_doc.company

    def migrate_chart_of_accounts(self, settings):
        """Migrate Chart of Accounts from e-Boekhouden"""
        try:
            # Use the enhanced chart of accounts migration with group support
            from verenigingen.e_boekhouden.utils.eboekhouden_migration_enhancements import (
                migrate_chart_of_accounts_enhanced,
            )

            # Run the enhanced migration
            result = migrate_chart_of_accounts_enhanced(self.migration_doc, settings)

            if result.get("success"):
                self.migration_doc.imported_records += result.get("created", 0)
                self.migration_doc.total_records += result.get("total", 0)

                if result.get("errors"):
                    for error in result["errors"][:5]:  # Log first 5 errors
                        self.migration_doc.log_error(f"CoA error: {error}")

                return result.get("message", "Chart of Accounts migration completed")
            else:
                return f"Error: {result.get('error', 'Unknown error')}"

        except Exception as e:
            return f"Error migrating Chart of Accounts: {str(e)}"

    def clear_existing_accounts(self, settings):
        """Clear existing accounts before migration"""
        try:
            from verenigingen.e_boekhouden.utils.debug_cleanup_all_imported_data import (
                debug_cleanup_all_imported_data,
            )

            result = debug_cleanup_all_imported_data(settings.default_company)
            return result

        except Exception as e:
            frappe.log_error(f"Error clearing accounts: {str(e)}")
            return {"success": False, "error": str(e)}

    def parse_account_group_mappings(self, settings):
        """Parse account group mappings from settings"""
        try:
            if not hasattr(settings, "account_group_mappings"):
                return {}

            mappings_text = settings.account_group_mappings or ""
            mappings = {}

            for line in mappings_text.split("\n"):
                if ":" in line:
                    group, account = line.split(":", 1)
                    mappings[group.strip()] = account.strip()

            return mappings

        except Exception as e:
            frappe.log_error(f"Error parsing account group mappings: {str(e)}")
            return {}

    def create_account(self, account_data, use_enhanced=False):
        """Create an account in ERPNext"""
        try:
            if use_enhanced:
                return self._create_account_enhanced(account_data)
            else:
                return self._create_account_basic(account_data)

        except Exception as e:
            frappe.log_error(f"Error creating account: {str(e)}")
            return None

    def _create_account_basic(self, account_data):
        """Create account using basic method"""
        try:
            # Check if account already exists
            account_name = f"{account_data['Code']} - {account_data['Omschrijving']} - {self.company}"

            if frappe.db.exists("Account", account_name):
                return account_name

            # Create new account
            account = frappe.new_doc("Account")
            account.account_name = account_data["Omschrijving"]
            account.account_number = account_data["Code"]
            account.company = self.company
            account.account_type = self._determine_account_type(account_data)
            account.parent_account = self._get_parent_account(
                account.account_type, account.root_type, self.company
            )

            account.insert()
            return account.name

        except Exception as e:
            frappe.log_error(f"Error creating basic account: {str(e)}")
            return None

    def _create_account_enhanced(self, account_data):
        """Create account using enhanced method with better type detection"""
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_migration_enhancements import AccountCreator

            creator = AccountCreator(self.migration_doc)
            return creator.create_account(account_data)

        except Exception as e:
            frappe.log_error(f"Error creating enhanced account: {str(e)}")
            return None

    def _determine_account_type(self, account_data):
        """Determine account type based on E-Boekhouden data"""
        code = account_data.get("Code", "")
        category = account_data.get("Categorie", "")
        group = account_data.get("Groep", "")

        # Use smart account typing
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_smart_account_typing import (
                suggest_account_type_smart,
            )

            return suggest_account_type_smart(code, account_data.get("Omschrijving", ""), category)
        except:
            # Fallback to basic logic
            return self._basic_account_type_detection(code, category, group)

    def _basic_account_type_detection(self, code, category, group):
        """Basic account type detection logic"""
        try:
            code_num = int(code)
        except (ValueError, TypeError):
            return "Expense Account"

        # Dutch chart of accounts patterns
        if 1000 <= code_num <= 1199:
            return "Receivable"
        elif 1200 <= code_num <= 1299:
            return "Bank"
        elif 1300 <= code_num <= 1399:
            return "Receivable"
        elif 1400 <= code_num <= 1599:
            return "Stock"
        elif 1600 <= code_num <= 1999:
            return "Fixed Asset"
        elif 2000 <= code_num <= 2999:
            return "Payable"
        elif 3000 <= code_num <= 3999:
            return "Equity"
        elif 4000 <= code_num <= 6999:
            return "Expense Account"
        elif 8000 <= code_num <= 8999:
            return "Income Account"
        else:
            return "Expense Account"

    def get_parent_account(self, account_type, root_type, company):
        """Get or create parent account"""
        try:
            # Look for existing parent accounts
            parent_patterns = {
                "Income Account": [f"8000 - Revenue - {company}", f"Income - {company}"],
                "Expense Account": [f"6000 - Expenses - {company}", f"Expenses - {company}"],
                "Receivable": [f"1300 - Accounts Receivable - {company}", f"Accounts Receivable - {company}"],
                "Payable": [f"2000 - Accounts Payable - {company}", f"Accounts Payable - {company}"],
                "Bank": [f"1200 - Bank Accounts - {company}", f"Bank - {company}"],
                "Fixed Asset": [f"1600 - Fixed Assets - {company}", f"Fixed Assets - {company}"],
                "Stock": [f"1400 - Stock Assets - {company}", f"Stock - {company}"],
                "Equity": [f"3000 - Capital - {company}", f"Equity - {company}"],
            }

            patterns = parent_patterns.get(account_type, [])

            for pattern in patterns:
                if frappe.db.exists("Account", pattern):
                    return pattern

            # If no parent found, create one
            return self._create_parent_account(account_type, root_type, company)

        except Exception as e:
            frappe.log_error(f"Error getting parent account: {str(e)}")
            return None

    def _create_parent_account(self, account_type, root_type, company):
        """Create a parent account if it doesn't exist"""
        try:
            # Define parent account names
            parent_names = {
                "Income Account": "Revenue",
                "Expense Account": "Expenses",
                "Receivable": "Accounts Receivable",
                "Payable": "Accounts Payable",
                "Bank": "Bank Accounts",
                "Fixed Asset": "Fixed Assets",
                "Stock": "Stock Assets",
                "Equity": "Capital",
            }

            parent_name = parent_names.get(account_type, "Miscellaneous")
            full_name = f"{parent_name} - {company}"

            if frappe.db.exists("Account", full_name):
                return full_name

            # Create parent account
            parent = frappe.new_doc("Account")
            parent.account_name = parent_name
            parent.company = company
            parent.is_group = 1
            parent.root_type = root_type
            parent.account_type = account_type if account_type in ["Receivable", "Payable", "Bank"] else None

            parent.insert()
            return parent.name

        except Exception as e:
            frappe.log_error(f"Error creating parent account: {str(e)}")
            return None

    def ensure_root_accounts(self, settings):
        """Ensure root accounts exist"""
        try:
            company = self.company

            root_accounts = [
                {"account_name": "Activa", "root_type": "Asset", "account_number": "1"},
                {"account_name": "Passiva", "root_type": "Liability", "account_number": "2"},
                {"account_name": "Eigen Vermogen", "root_type": "Equity", "account_number": "3"},
                {"account_name": "Opbrengsten", "root_type": "Income", "account_number": "8"},
                {"account_name": "Kosten", "root_type": "Expense", "account_number": "6"},
            ]

            created = []
            existing = []
            errors = []

            for acc in root_accounts:
                try:
                    # Check if root account exists
                    existing_account = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "root_type": acc["root_type"],
                            "parent_account": ["in", ["", None]],
                            "is_group": 1,
                        },
                        "name",
                    )

                    if existing_account:
                        existing.append(f"{acc['account_name']} ({existing_account})")
                        continue

                    # Create root account
                    account = frappe.new_doc("Account")
                    account.account_name = acc["account_name"]
                    account.company = company
                    account.root_type = acc["root_type"]
                    account.is_group = 1
                    account.account_number = acc["account_number"]

                    account.save(ignore_permissions=True)
                    created.append(f"{acc['account_name']} ({acc['root_type']})")

                except Exception as e:
                    errors.append(f"{acc['account_name']}: {str(e)}")

            return {
                "success": True,
                "created": created,
                "existing": existing,
                "errors": errors,
                "message": f"Root accounts ready: {len(created)} created, {len(existing)} existing",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
