# Copyright (c) 2025, Nederlandse Vereniging voor Veganisme and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class EBoekhoudenAccountMap(Document):
    """Modern account mapping for E-Boekhouden to ERPNext integration"""

    def validate(self):
        """Validate the account mapping"""
        # Validate ERPNext account exists
        if not frappe.db.exists("Account", self.erpnext_account):
            frappe.throw(f"ERPNext Account {self.erpnext_account} does not exist")

        # Validate account type matches ERPNext account type
        erpnext_account_type = frappe.db.get_value("Account", self.erpnext_account, "account_type")
        if erpnext_account_type and self.account_type != erpnext_account_type:
            frappe.msgprint(
                f"Warning: Account type mismatch. ERPNext account is '{erpnext_account_type}' but mapping shows '{self.account_type}'"
            )

        # Set company from account if not set
        if not self.company:
            self.company = frappe.db.get_value("Account", self.erpnext_account, "company")

    def before_save(self):
        """Actions before saving"""
        # Auto-set account name from ERPNext if empty
        if not self.account_name and self.erpnext_account:
            account_doc = frappe.get_doc("Account", self.erpnext_account)
            self.account_name = account_doc.account_name

        # Set account type from ERPNext account
        if self.erpnext_account:
            erpnext_account_type = frappe.db.get_value("Account", self.erpnext_account, "account_type")
            if erpnext_account_type:
                self.account_type = erpnext_account_type

    def on_update(self):
        """Actions after saving"""
        # Update last used timestamp when mapping is used
        pass

    @classmethod
    def get_account_mapping(cls, grootboek_code, company=None):
        """Get ERPNext account for E-Boekhouden grootboek code"""
        filters = {"eboekhouden_grootboek": str(grootboek_code), "is_active": 1}

        if company:
            filters["company"] = company

        mapping = frappe.db.get_value(
            "E-Boekhouden Account Map", filters, ["erpnext_account", "account_type"], as_dict=True
        )

        if mapping:
            # Update last used timestamp
            frappe.db.set_value(
                "E-Boekhouden Account Map", {"eboekhouden_grootboek": str(grootboek_code)}, "last_used", now()
            )
            return mapping

        return None

    @classmethod
    def create_auto_mapping(cls, grootboek_code, account_name, company):
        """Create automatic mapping based on account number ranges"""
        # Try to find appropriate ERPNext account
        erpnext_account = cls._find_best_account_match(grootboek_code, account_name, company)

        if erpnext_account:
            # Create mapping
            mapping = frappe.new_doc("E-Boekhouden Account Map")
            mapping.eboekhouden_grootboek = str(grootboek_code)
            mapping.account_name = account_name
            mapping.erpnext_account = erpnext_account
            mapping.company = company
            mapping.auto_created = 1
            mapping.description = f"Auto-created mapping for {account_name}"

            mapping.insert()
            return mapping.name

        return None

    @classmethod
    def _find_best_account_match(cls, grootboek_code, account_name, company):
        """Find best matching ERPNext account"""
        try:
            code_num = int(grootboek_code)
        except (ValueError, TypeError):
            return None

        # Dutch chart of accounts mapping
        account_patterns = {
            # Assets (1000-1999)
            (1000, 1199): "Receivable",
            (1200, 1299): "Bank",
            (1300, 1399): "Receivable",
            (1400, 1599): "Stock",
            (1600, 1999): "Fixed Asset",
            # Liabilities (2000-2999)
            (2000, 2199): "Payable",
            (2200, 2999): "Payable",
            # Equity (3000-3999)
            (3000, 3999): "Equity",
            # Expenses (4000-6999)
            (4000, 6999): "Expense Account",
            # Income (8000-8999)
            (8000, 8999): "Income Account",
            # VAT/Tax (1500-1599, 2100-2199)
            (1500, 1599): "Tax",
            (2100, 2199): "Tax",
        }

        # Find account type based on number
        account_type = None
        for (start, end), acc_type in account_patterns.items():
            if start <= code_num <= end:
                account_type = acc_type
                break

        if not account_type:
            return None

        # Search for existing account with similar number or name
        search_patterns = [
            f"{grootboek_code} - %",  # Exact code match
            f"% - {company}",  # Company accounts
        ]

        for pattern in search_patterns:
            account = frappe.db.get_value(
                "Account",
                {"name": ["like", pattern], "account_type": account_type, "company": company, "is_group": 0},
                "name",
            )
            if account:
                return account

        # Fallback to default account for type
        defaults = {
            "Income Account": f"8000 - Revenue - {company}",
            "Expense Account": f"5000 - Expenses - {company}",
            "Receivable": f"1300 - Accounts Receivable - {company}",
            "Payable": f"2000 - Accounts Payable - {company}",
            "Bank": f"1200 - Bank Accounts - {company}",
            "Tax": f"2150 - VAT - {company}",
        }

        default_account = defaults.get(account_type, f"6000 - Miscellaneous - {company}")

        # Check if default exists
        if frappe.db.exists("Account", default_account):
            return default_account

        return None

    @frappe.whitelist()
    def test_mapping(self):
        """Test this account mapping"""
        return {
            "grootboek_code": self.eboekhouden_grootboek,
            "erpnext_account": self.erpnext_account,
            "account_type": self.account_type,
            "company": self.company,
            "is_active": self.is_active,
        }
