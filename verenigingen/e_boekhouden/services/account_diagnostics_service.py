"""
Account Diagnostics Service

Provides diagnostic and analysis functions for Chart of Accounts,
including structure validation, tax account checking, and account hierarchy analysis.
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


class AccountDiagnosticsService:
    """Service for diagnosing Chart of Accounts issues"""

    def __init__(self, company):
        """
        Initialize the service.

        Args:
            company: Company name to diagnose accounts for
        """
        self.company = company

    def diagnose_account_structure(self):
        """
        Comprehensive diagnosis of account structure.

        Returns:
            dict: Diagnostic information including root accounts, groups, and sample accounts
        """
        results = {
            "company": self.company,
            "root_accounts": {},
            "existing_groups": [],
            "sample_debtor_accounts": [],
            "sample_creditor_accounts": [],
            "sample_tax_accounts": [],
        }

        # Check root accounts for each type
        for root_type in ["Asset", "Liability", "Equity", "Income", "Expense"]:
            root_accounts = frappe.db.get_all(
                "Account",
                filters={"company": self.company, "root_type": root_type, "is_group": 1},
                fields=["name", "parent_account", "account_number", "lft", "rgt"],
                order_by="lft",
                limit=5,
            )
            results["root_accounts"][root_type] = root_accounts

        # Check for organizational group accounts
        group_patterns = [
            "Vorderingen",
            "Schulden",
            "Receivable",
            "Payable",
            "Debtor",
            "Creditor",
            "Belastingen",
            "Tax",
        ]
        for pattern in group_patterns:
            groups = frappe.db.get_all(
                "Account",
                filters={"company": self.company, "account_name": ["like", f"%{pattern}%"], "is_group": 1},
                fields=["name", "account_name", "account_number", "root_type", "parent_account"],
            )
            results["existing_groups"].extend(groups)

        # Sample debtor accounts (13xx range)
        results["sample_debtor_accounts"] = frappe.db.get_all(
            "Account",
            filters={"company": self.company, "account_number": ["like", "13%"], "is_group": 0},
            fields=["name", "account_number", "account_name", "parent_account", "root_type"],
            limit=10,
        )

        # Sample creditor accounts (16xx, 17xx ranges). A single Frappe filter
        # can't express "starts with 16 OR 17", so query each prefix and merge.
        creditor_accounts = []
        for prefix in ("16", "17"):
            creditor_accounts.extend(
                frappe.db.get_all(
                    "Account",
                    filters={
                        "company": self.company,
                        "account_number": ["like", f"{prefix}%"],
                        "is_group": 0,
                        "root_type": "Liability",
                    },
                    fields=["name", "account_number", "account_name", "parent_account", "root_type"],
                    limit=10,
                )
            )
        results["sample_creditor_accounts"] = creditor_accounts[:10]

        # Sample tax accounts
        results["sample_tax_accounts"] = frappe.db.sql(
            """
            SELECT name, account_number, account_name, parent_account, root_type, account_type
            FROM `tabAccount`
            WHERE company = %s
              AND (account_name LIKE '%%BTW%%'
                   OR account_name LIKE '%%belasting%%'
                   OR account_type = 'Tax')
            LIMIT 10
        """,
            (self.company,),
            as_dict=True,
        )

        return results

    def check_tax_accounts(self):
        """
        Check all tax/BTW accounts and their placement.

        Returns:
            dict: Information about all tax accounts
        """
        tax_accounts = frappe.db.sql(
            """
            SELECT name, account_number, account_name, parent_account,
                   root_type, account_type, is_group
            FROM `tabAccount`
            WHERE company = %s
              AND (account_name LIKE '%%BTW%%'
                   OR account_name LIKE '%%belasting%%'
                   OR account_type = 'Tax')
            ORDER BY account_number
        """,
            (self.company,),
            as_dict=True,
        )

        return {"tax_accounts": tax_accounts}

    def check_account_hierarchy(self, account_name):
        """
        Check the full hierarchy for a specific account.

        Args:
            account_name: Name of the account to check

        Returns:
            dict: Hierarchy information
        """
        account = frappe.get_doc("Account", account_name)

        hierarchy = []
        current = account

        while current.parent_account:
            parent = frappe.get_doc("Account", current.parent_account)
            hierarchy.append(
                {
                    "name": parent.name,
                    "account_name": parent.account_name,
                    "account_number": parent.account_number,
                    "is_group": parent.is_group,
                    "root_type": parent.root_type,
                }
            )
            current = parent

        return {
            "account": {
                "name": account.name,
                "account_name": account.account_name,
                "account_number": account.account_number,
                "root_type": account.root_type,
                "is_group": account.is_group,
            },
            "hierarchy": hierarchy,
        }

    def find_misplaced_accounts(self):
        """
        Find accounts that appear to be in the wrong group.

        Returns:
            dict: Lists of potentially misplaced accounts
        """
        results = {
            "debtors_not_under_vorderingen": [],
            "creditors_not_under_schulden": [],
            "tax_accounts_not_grouped": [],
        }

        # Find Vorderingen group
        vorderingen = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_number": "4", "is_group": 1, "root_type": "Asset"},
            "name",
        )

        if vorderingen:
            # Find 13xx accounts not under Vorderingen
            misplaced_debtors = frappe.db.sql(
                """
                SELECT name, account_number, account_name, parent_account
                FROM `tabAccount`
                WHERE company = %s
                  AND account_number LIKE '13%%'
                  AND is_group = 0
                  AND parent_account != %s
            """,
                (self.company, vorderingen),
                as_dict=True,
            )
            results["debtors_not_under_vorderingen"] = misplaced_debtors

        # Find Schulden group
        schulden = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Schulden%"],
                "is_group": 1,
                "root_type": "Liability",
            },
            "name",
        )

        if schulden:
            # Find 16xx/17xx accounts not under Schulden
            misplaced_creditors = frappe.db.sql(
                """
                SELECT name, account_number, account_name, parent_account
                FROM `tabAccount`
                WHERE company = %s
                  AND (account_number LIKE '16%%' OR account_number LIKE '17%%')
                  AND is_group = 0
                  AND root_type = 'Liability'
                  AND parent_account != %s
            """,
                (self.company, schulden),
                as_dict=True,
            )
            results["creditors_not_under_schulden"] = misplaced_creditors

        # Find tax accounts not in Belastingen groups
        belastingen_groups = frappe.db.get_all(
            "Account",
            filters={"company": self.company, "account_name": ["like", "%Belastingen%"], "is_group": 1},
            pluck="name",
        )

        if belastingen_groups:
            misplaced_tax = frappe.db.sql(
                """
                SELECT name, account_number, account_name, parent_account, root_type
                FROM `tabAccount`
                WHERE company = %s
                  AND (account_name LIKE '%%BTW%%' OR account_type = 'Tax')
                  AND is_group = 0
                  AND parent_account NOT IN %s
            """,
                (self.company, belastingen_groups),
                as_dict=True,
            )
            results["tax_accounts_not_grouped"] = misplaced_tax

        return results


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def diagnose_account_structure(company=None):
    """
    API endpoint for account structure diagnosis.

    Args:
        company: Company name (optional)

    Returns:
        dict: Diagnostic results
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return {"success": False, "error": "No company specified"}

    service = AccountDiagnosticsService(company)
    data = service.diagnose_account_structure()

    return {"success": True, "data": data}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_tax_accounts(company=None):
    """
    API endpoint for checking tax accounts.

    Args:
        company: Company name (optional)

    Returns:
        dict: Tax account information
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return {"success": False, "error": "No company specified"}

    service = AccountDiagnosticsService(company)
    data = service.check_tax_accounts()

    return {"success": True, **data}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def find_misplaced_accounts(company=None):
    """
    API endpoint for finding misplaced accounts.

    Args:
        company: Company name (optional)

    Returns:
        dict: Lists of misplaced accounts
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return {"success": False, "error": "No company specified"}

    service = AccountDiagnosticsService(company)
    data = service.find_misplaced_accounts()

    return {"success": True, "data": data}
