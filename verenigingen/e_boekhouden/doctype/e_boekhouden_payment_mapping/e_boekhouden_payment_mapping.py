# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EBoekhoudenPaymentMapping(Document):
    def validate(self):
        self.validate_duplicate()
        self.validate_account_company()

    def validate_duplicate(self):
        """Ensure no duplicate mappings for same company and account code"""
        existing = frappe.db.exists(
            "E-Boekhouden Payment Mapping",
            {
                "company": self.company,
                "eboekhouden_account_code": self.eboekhouden_account_code,
                "name": ["!=", self.name],
            },
        )

        if existing:
            frappe.throw(
                f"A mapping already exists for account code {self.eboekhouden_account_code} in company {self.company}"
            )

    def validate_account_company(self):
        """Ensure ERPNext account belongs to the same company"""
        account_company = frappe.db.get_value("Account", self.erpnext_account, "company")
        if account_company != self.company:
            frappe.throw(f"Account {self.erpnext_account} does not belong to company {self.company}")


@frappe.whitelist()
def get_payment_account_mapping(company, account_code):
    """Get payment account mapping for a company and account code"""
    mapping = frappe.db.get_value(
        "E-Boekhouden Payment Mapping",
        {"company": company, "eboekhouden_account_code": account_code, "active": 1},
        ["erpnext_account", "account_type", "mode_of_payment", "account_name"],
        as_dict=True,
    )

    return mapping


@frappe.whitelist()
def import_default_mappings(company):
    """Import default payment mappings for a company"""
    from verenigingen.e_boekhouden.utils_migration_config import PAYMENT_ACCOUNT_CONFIG

    imported = 0

    # Import bank accounts
    for code, config in PAYMENT_ACCOUNT_CONFIG.get("bank_accounts", {}).items():
        # Check if ERPNext account exists
        account = frappe.db.get_value("Account", {"account_name": config["name"], "company": company})

        if account and not frappe.db.exists(
            "E-Boekhouden Payment Mapping", {"company": company, "eboekhouden_account_code": code}
        ):
            mapping = frappe.new_doc("E-Boekhouden Payment Mapping")
            mapping.company = company
            mapping.eboekhouden_account_code = code
            mapping.account_name = config["name"]
            mapping.erpnext_account = account
            mapping.account_type = config["type"]
            mapping.mode_of_payment = config["mode_of_payment"]
            mapping.active = 1
            mapping.insert()
            imported += 1

    # Import cash accounts
    for code, config in PAYMENT_ACCOUNT_CONFIG.get("cash_accounts", {}).items():
        account = frappe.db.get_value("Account", {"account_name": config["name"], "company": company})

        if account and not frappe.db.exists(
            "E-Boekhouden Payment Mapping", {"company": company, "eboekhouden_account_code": code}
        ):
            mapping = frappe.new_doc("E-Boekhouden Payment Mapping")
            mapping.company = company
            mapping.eboekhouden_account_code = code
            mapping.account_name = config["name"]
            mapping.erpnext_account = account
            mapping.account_type = config["type"]
            mapping.mode_of_payment = config["mode_of_payment"]
            mapping.active = 1
            mapping.insert()
            imported += 1

    return {"imported": imported}
