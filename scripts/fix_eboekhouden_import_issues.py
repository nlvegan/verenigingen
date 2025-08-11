import frappe
from frappe import _

@frappe.whitelist()
def analyze_import_issues():
    """Analyze eBoekhouden import issues"""
    
    # 1. Check payable accounts
    print("=== PAYABLE ACCOUNTS ===")
    payable_accounts = frappe.get_all('Account', 
        filters={
            'company': 'Ned Ver Vegan', 
            'account_type': 'Payable', 
            'is_group': 0
        }, 
        fields=['name', 'account_name', 'account_number']
    )
    
    for acc in payable_accounts:
        print(f"  - {acc.name}")
    
    # 2. Check account 18100
    acc_18100 = frappe.get_doc('Account', '18100 - Te betalen sociale lasten - NVV')
    print(f"\nAccount 18100: {acc_18100.account_name} (Type: {acc_18100.account_type})")
    
    # 3. Find correct payable account
    correct_payable = None
    for acc in payable_accounts:
        if "19290" in acc.name or "te betalen bedragen" in acc.account_name.lower():
            correct_payable = acc.name
            print(f"\nCorrect payable account found: {correct_payable}")
            break
    
    # 4. Check current default in code
    print("\n=== CHECKING CURRENT CODE DEFAULT ===")
    current_default = frappe.db.get_value(
        "Account", {"company": "Ned Ver Vegan", "account_type": "Payable", "is_group": 0}, "name"
    )
    print(f"Current code would select: {current_default}")
    
    # 5. Check some Purchase Invoices
    print("\n=== SAMPLE PURCHASE INVOICES ===")
    pinvs = frappe.get_all('Purchase Invoice',
        filters={'supplier': 'E-Boekhouden Import'},
        fields=['name', 'credit_to', 'bill_no'],
        limit=5
    )
    
    for pinv in pinvs:
        print(f"  - {pinv.name}: credit_to = {pinv.credit_to}")
    
    # 6. Check Sales Invoice customer issues
    print("\n=== SAMPLE SALES INVOICES ===")
    sinvs = frappe.get_all('Sales Invoice',
        filters={'customer': 'E-Boekhouden Import'},
        fields=['name', 'customer_name', 'title'],
        limit=5
    )
    
    for sinv in sinvs:
        print(f"  - {sinv.name}: customer_name = {sinv.customer_name}, title = {sinv.title}")
        
    # 7. Check a specific Sales Invoice mutation data
    print("\n=== CHECKING SPECIFIC MUTATION DATA ===")
    # Get a Sales Invoice with eBoekhouden mutation
    sinv_with_mutation = frappe.db.sql("""
        SELECT si.name, si.eboekhouden_mutation_nr, si.customer, si.customer_name
        FROM `tabSales Invoice` si
        WHERE si.eboekhouden_mutation_nr IS NOT NULL 
        AND si.eboekhouden_mutation_nr != ''
        LIMIT 1
    """, as_dict=True)
    
    if sinv_with_mutation:
        mutation_nr = sinv_with_mutation[0].eboekhouden_mutation_nr
        print(f"Checking mutation {mutation_nr}")
        
        # Check if there are any E-Boekhouden migrations that might contain this data
        migration_records = frappe.get_all(
            'E-Boekhouden Migration',
            filters={'migration_status': 'Completed'},
            fields=['name', 'migration_summary']
        )
        
        found_migration = False
        for migration in migration_records:
            if migration.migration_summary and mutation_nr in str(migration.migration_summary):
                print(f"  Found in migration: {migration.name}")
                found_migration = True
                break
        
        if not found_migration:
            print("  No migration data found for this mutation")
            
    # 8. Check cost centers
    print("\n=== COST CENTERS ===")
    main_cost_center = frappe.db.get_value(
        "Cost Center", 
        {"company": "Ned Ver Vegan", "cost_center_name": "Main", "is_group": 0}, 
        "name"
    )
    print(f"Main cost center: {main_cost_center}")
    
    # Check what cost centers are being used
    cost_centers = frappe.db.sql("""
        SELECT DISTINCT pii.cost_center, COUNT(*) as count
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.supplier = 'E-Boekhouden Import'
        GROUP BY pii.cost_center
        LIMIT 5
    """, as_dict=True)
    
    print("\nCost centers used in Purchase Invoices:")
    for cc in cost_centers:
        print(f"  - {cc.cost_center}: {cc.count} items")

    return {
        'correct_payable_account': correct_payable,
        'main_cost_center': main_cost_center
    }

@frappe.whitelist()
def fix_import_code():
    """Fix the eBoekhouden import code"""
    import os
    
    file_path = os.path.join(
        frappe.get_app_path('verenigingen'),
        'utils',
        'eboekhouden_rest_full_migration.py'
    )
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Fix 1: Update _get_payable_account to return correct account
    old_payable = 'return payable_account or "1600 - Crediteuren - NVV"  # Fallback'
    new_payable = '''# First try to get the general payables account
    general_payable = frappe.db.get_value(
        "Account", 
        {"company": company, "account_name": ["like", "%Te betalen bedragen%"], "is_group": 0}, 
        "name"
    )
    if general_payable:
        return general_payable
        
    # Then try any payable account that's not social security
    payable_not_social = frappe.db.sql("""
        SELECT name 
        FROM `tabAccount` 
        WHERE company = %s 
        AND account_type = 'Payable' 
        AND is_group = 0 
        AND account_name NOT LIKE '%%sociale lasten%%'
        LIMIT 1
    """, company)
    
    if payable_not_social:
        return payable_not_social[0][0]
    
    # Final fallback
    return payable_account or "19290 - Te betalen bedragen - NVV"  # Updated fallback'''
    
    content = content.replace(old_payable, new_payable)
    
    # Fix 2: Add cost center to Purchase Invoice items
    # Find the line where items are appended
    old_item_append = '''pi.append("items", line_dict)'''
    new_item_append = '''# Set cost center to Main
                                    if line_dict and isinstance(line_dict, dict):
                                        line_dict["cost_center"] = _get_main_cost_center(company)
                                    pi.append("items", line_dict)'''
    
    content = content.replace(old_item_append, new_item_append)
    
    # Also fix the fallback item creation
    old_fallback = '''pi.append(
                                        "items",
                                        {
                                            "item_code": "E-Boekhouden Import Item",
                                            "item_name": row_description[:60]
                                            if row_description
                                            else "Import Item",
                                            "qty": 1,
                                            "rate": abs(row_amount),
                                            "description": row_description,
                                        },
                                    )'''
    
    new_fallback = '''pi.append(
                                        "items",
                                        {
                                            "item_code": "E-Boekhouden Import Item",
                                            "item_name": row_description[:60]
                                            if row_description
                                            else "Import Item",
                                            "qty": 1,
                                            "rate": abs(row_amount),
                                            "description": row_description,
                                            "cost_center": _get_main_cost_center(company),
                                        },
                                    )'''
    
    content = content.replace(old_fallback, new_fallback)
    
    # Fix 3: Add helper function for cost center
    # Add after _get_payable_account function
    cost_center_func = '''

def _get_main_cost_center(company):
    """Get main cost center for company"""
    main_cc = frappe.db.get_value(
        "Cost Center", 
        {"company": company, "cost_center_name": "Main", "is_group": 0}, 
        "name"
    )
    
    if not main_cc:
        # Try to find any non-group cost center
        main_cc = frappe.db.get_value(
            "Cost Center",
            {"company": company, "is_group": 0},
            "name"
        )
    
    return main_cc
'''
    
    # Insert after _get_payable_account function
    insert_pos = content.find('def map_rest_type_to_soap_type(')
    if insert_pos > 0:
        content = content[:insert_pos] + cost_center_func + '\n\n' + content[insert_pos:]
    
    # Write back the file
    with open(file_path, 'w') as f:
        f.write(content)
    
    print("Fixed import code!")
    return True

@frappe.whitelist() 
def fix_existing_invoices():
    """Fix existing Purchase Invoices with wrong payable account"""
    
    # Get correct payable account
    correct_payable = frappe.db.get_value(
        "Account", 
        {"company": "Ned Ver Vegan", "account_name": ["like", "%Te betalen bedragen%"], "is_group": 0}, 
        "name"
    )
    
    if not correct_payable:
        correct_payable = "19290 - Te betalen bedragen - NVV"
    
    # Get main cost center
    main_cc = frappe.db.get_value(
        "Cost Center", 
        {"company": "Ned Ver Vegan", "cost_center_name": "Main", "is_group": 0}, 
        "name"
    )
    
    print(f"Using payable account: {correct_payable}")
    print(f"Using cost center: {main_cc}")
    
    # Update Purchase Invoices
    affected_pinvs = frappe.db.sql("""
        UPDATE `tabPurchase Invoice`
        SET credit_to = %s
        WHERE supplier = 'E-Boekhouden Import'
        AND credit_to = '18100 - Te betalen sociale lasten - NVV'
        AND docstatus < 2
    """, correct_payable)
    
    # Update cost centers in Purchase Invoice Items
    if main_cc:
        frappe.db.sql("""
            UPDATE `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            SET pii.cost_center = %s
            WHERE pi.supplier = 'E-Boekhouden Import'
            AND pi.docstatus < 2
        """, main_cc)
    
    frappe.db.commit()
    
    print(f"Updated Purchase Invoices and their items")
    
    return True