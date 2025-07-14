# Check ledger mappings for bank accounts

# Check if ledger 13201869 exists
mapping = frappe.db.get_value(
    "E-Boekhouden Ledger Mapping",
    {"ledger_id": 13201869},
    ["ledger_code", "ledger_name", "erpnext_account"],
    as_dict=True,
)

if mapping:
    print(f"Ledger 13201869 mapped to: {mapping}")
    # Check account type
    if mapping.get("erpnext_account"):
        account_type = frappe.db.get_value("Account", mapping["erpnext_account"], "account_type")
        print(f"Account type: {account_type}")
else:
    print("Ledger 13201869 NOT MAPPED")

# Check available bank accounts
bank_accounts = frappe.db.sql(
    """
    SELECT name, account_number, account_name
    FROM `tabAccount`
    WHERE account_type IN ('Bank', 'Cash')
    AND company = %s
    AND disabled = 0
    LIMIT 10
""",
    frappe.db.get_single_value("Global Defaults", "default_company"),
    as_dict=True,
)

print("\nAvailable bank accounts:")
for acc in bank_accounts:
    print(f"  {acc.name} (Number: {acc.account_number})")

# Check if we have Triodos
triodos = frappe.db.get_value(
    "Account",
    {"account_number": "10440", "company": frappe.db.get_single_value("Global Defaults", "default_company")},
    "name",
)
print(f"\nTriodos account: {triodos}")

# Create mapping if needed
if not mapping:
    print("\nCreating ledger mapping for 13201869...")
    if triodos:
        new_mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
        new_mapping.ledger_id = 13201869
        new_mapping.ledger_code = "10440"
        new_mapping.ledger_name = "Triodos Bank (API)"
        new_mapping.erpnext_account = triodos
        new_mapping.save()
        print(f"Created mapping: 13201869 -> {triodos}")
    else:
        print("Cannot create mapping - Triodos account not found")
