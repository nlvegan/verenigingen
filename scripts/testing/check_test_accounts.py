#!/usr/bin/env python3
"""
Check available accounts for testing
"""

import frappe

@frappe.whitelist()
def check_accounts():
    """Check available accounts for testing"""
    
    print("\nChecking available accounts for testing...")
    
    # Check income accounts
    income_accounts = frappe.db.get_all(
        "Account", 
        filters={"account_type": "Income", "is_group": 0, "disabled": 0}, 
        fields=["name", "account_name"], 
        limit=5
    )
    print(f"\nIncome accounts ({len(income_accounts)} found):")
    for acc in income_accounts:
        print(f"  - {acc.name}")
    
    # Check receivable accounts
    receivable_accounts = frappe.db.get_all(
        "Account", 
        filters={"account_type": "Receivable", "is_group": 0, "disabled": 0}, 
        fields=["name", "account_name"], 
        limit=5
    )
    print(f"\nReceivable accounts ({len(receivable_accounts)} found):")
    for acc in receivable_accounts:
        print(f"  - {acc.name}")
    
    # Check cash accounts
    cash_accounts = frappe.db.get_all(
        "Account", 
        filters={"account_type": "Cash", "is_group": 0, "disabled": 0}, 
        fields=["name", "account_name"], 
        limit=5
    )
    print(f"\nCash accounts ({len(cash_accounts)} found):")
    for acc in cash_accounts:
        print(f"  - {acc.name}")
    
    # Check customer groups
    customer_groups = frappe.db.get_all(
        "Customer Group", 
        filters={"is_group": 0}, 
        fields=["name"], 
        limit=5
    )
    print(f"\nCustomer groups ({len(customer_groups)} found):")
    for group in customer_groups:
        print(f"  - {group.name}")
    
    return {
        "income_accounts": income_accounts,
        "receivable_accounts": receivable_accounts,
        "cash_accounts": cash_accounts,
        "customer_groups": customer_groups
    }

if __name__ == "__main__":
    frappe.init("dev.veganisme.net")
    frappe.connect()
    check_accounts()