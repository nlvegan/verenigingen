# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EBoekhoudenItemMapping(Document):
    def validate(self):
        """Validate the mapping"""
        # Ensure account exists
        if self.account_code:
            account = frappe.db.get_value(
                "Account",
                {"account_number": self.account_code, "company": self.company},
                ["name", "account_name"],
                as_dict=True,
            )

            if account:
                self.account_name = account.account_name
            else:
                frappe.throw(f"Account with code {self.account_code} not found in company {self.company}")

        # Ensure item exists
        if self.item_code and not frappe.db.exists("Item", self.item_code):
            frappe.throw(f"Item {self.item_code} does not exist")

        # Check for duplicates
        existing = frappe.db.exists(
            "E-Boekhouden Item Mapping",
            {
                "account_code": self.account_code,
                "company": self.company,
                "transaction_type": self.transaction_type,
                "name": ["!=", self.name],
            },
        )

        if existing:
            frappe.throw(
                f"A mapping already exists for account {self.account_code} and transaction type {self.transaction_type}"
            )


@frappe.whitelist()
def get_item_for_account(account_code, company, transaction_type="Both"):
    """Get the mapped item for an E-boekhouden account"""
    if not account_code:
        return None

    # First try exact match with transaction type
    mapping = frappe.db.get_value(
        "E-Boekhouden Item Mapping",
        {
            "account_code": account_code,
            "company": company,
            "transaction_type": transaction_type,
            "is_active": 1,
        },
        "item_code",
    )

    if mapping:
        return mapping

    # Try with "Both" transaction type
    if transaction_type != "Both":
        mapping = frappe.db.get_value(
            "E-Boekhouden Item Mapping",
            {"account_code": account_code, "company": company, "transaction_type": "Both", "is_active": 1},
            "item_code",
        )

    return mapping


@frappe.whitelist()
def create_default_mappings(company):
    """Create default mappings based on common account patterns"""
    frappe.set_user("Administrator")

    # Get accounts from the company
    accounts = frappe.db.get_all(
        "Account",
        {"company": company, "account_number": ["is", "set"], "is_group": 0},
        ["account_number", "account_name", "account_type", "root_type"],
    )

    created_count = 0

    # Common patterns
    item_patterns = {
        # Income accounts
        "contributie": "Membership Contribution",
        "donatie": "Donation",
        "verkoop": "Product Sales",
        "advertentie": "Advertisement Income",
        "commissie": "Commission Income",
        "rente": "Interest Income",
        "subsidie": "Subsidy Income",
        "fondsen": "Fund Income",
        "evenement": "Event Income",
        # Expense accounts
        "lonen": "Salary Expense",
        "sociale lasten": "Social Security Expense",
        "huur": "Rent Expense",
        "telefoon": "Telephone Expense",
        "internet": "Internet Expense",
        "verzekering": "Insurance Expense",
        "administratie": "Administration Expense",
        "bank": "Bank Charges",
        "drukwerk": "Printing Expense",
        "porto": "Postage Expense",
        "kantoor": "Office Supplies",
        "reis": "Travel Expense",
        "marketing": "Marketing Expense",
        "accountant": "Accounting Fees",
        "afschrijving": "Depreciation",
    }

    for account in accounts:
        account_name_lower = account.account_name.lower()

        # Skip if mapping already exists
        if frappe.db.exists(
            "E-Boekhouden Item Mapping", {"account_code": account.account_number, "company": company}
        ):
            continue

        # Find matching pattern
        matched_item = None
        for pattern, item_name in item_patterns.items():
            if pattern in account_name_lower:
                matched_item = item_name
                break

        if matched_item:
            # Check if item exists, if not create it
            if not frappe.db.exists("Item", matched_item):
                item = frappe.new_doc("Item")
                item.item_code = matched_item
                item.item_name = matched_item
                item.item_group = "Services" if account.root_type in ["Income", "Expense"] else "Products"
                item.stock_uom = "Nos"
                item.is_stock_item = 0
                item.insert(ignore_permissions=True)

            # Create mapping
            mapping = frappe.new_doc("E-Boekhouden Item Mapping")
            mapping.account_code = account.account_number
            mapping.account_name = account.account_name
            mapping.company = company
            mapping.item_code = matched_item
            mapping.transaction_type = (
                "Sales"
                if account.root_type == "Income"
                else "Purchase"
                if account.root_type == "Expense"
                else "Both"
            )
            mapping.is_active = 1
            mapping.insert(ignore_permissions=True)
            created_count += 1

    frappe.db.commit()
    return {"success": True, "created": created_count}
