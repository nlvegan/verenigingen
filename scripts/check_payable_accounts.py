import frappe

frappe.init(site="dev.veganisme.net")
frappe.connect()

# Get all payable accounts
payable_accounts = frappe.get_all('Account', 
    filters={
        'company': 'Ned Ver Vegan', 
        'account_type': 'Payable', 
        'is_group': 0
    }, 
    fields=['name', 'account_name', 'account_number']
)

print("Payable Accounts in Ned Ver Vegan:")
for acc in payable_accounts:
    print(f"  - {acc.name} (Number: {acc.account_number or 'N/A'})")

# Check what account 18100 is
acc_18100 = frappe.get_doc('Account', '18100 - Te betalen sociale lasten - NVV')
print(f"\nAccount 18100 details:")
print(f"  Name: {acc_18100.account_name}")
print(f"  Type: {acc_18100.account_type}")
print(f"  Is Group: {acc_18100.is_group}")

# Find account 19290
try:
    acc_19290 = frappe.get_doc('Account', '19290 - Te betalen bedragen - Ned Ver Vegan')
    print(f"\nAccount 19290 details:")
    print(f"  Name: {acc_19290.account_name}")
    print(f"  Type: {acc_19290.account_type}")
    print(f"  Is Group: {acc_19290.is_group}")
except:
    print("\nAccount 19290 not found with full name, searching...")
    accounts = frappe.get_all('Account', 
        filters={'account_number': '19290', 'company': 'Ned Ver Vegan'}, 
        fields=['name', 'account_name', 'account_type']
    )
    if accounts:
        print(f"Found: {accounts[0]}")

frappe.db.close()