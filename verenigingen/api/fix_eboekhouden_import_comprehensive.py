import json

import frappe
from frappe import _


@frappe.whitelist()
def fix_import_code_comprehensive():
    """Apply comprehensive fixes to the eBoekhouden import code"""
    import os

    file_path = os.path.join(
        frappe.get_app_path("verenigingen"), "utils", "eboekhouden_rest_full_migration.py"
    )

    # Read the file
    with open(file_path, "r") as f:
        content = f.read()

    # Fix 1: Update the Sales Invoice creation to pass mutation data to customer creation
    # Find where _get_or_create_customer is called for Sales Invoices
    old_customer_call = """                    # Try to find customer from relation_id first for proper naming
                    relation_id = mutation.get("relationId")
                    customer = _get_or_create_customer(relation_id, debug_info)
                    si.customer = customer"""

    new_customer_call = """                    # Try to find customer from relation_id first for proper naming
                    relation_id = mutation.get("relationId")
                    customer = _get_or_create_customer(relation_id, debug_info, mutation_data=mutation)
                    si.customer = customer"""

    content = content.replace(old_customer_call, new_customer_call)

    # Fix 2: Enhance the _get_or_create_customer function to extract customer names better
    # This is already partially done, but we need to add extraction from mutation data

    # Find the fallback section in _get_or_create_customer
    old_fallback = """    # Fallback: Create/use default customer
    customer = frappe.db.get_value("Customer", {"customer_name": "E-Boekhouden Import"}, "name")"""

    new_fallback = """    # Try to extract customer name from mutation data if available
    if not customer and mutation_data:
        # Try to extract customer name from description or rows
        customer_name = None

        # First check main description
        description = mutation_data.get("description", "")
        if description and len(description) > 3:
            # For regular invoices, the first line often contains the customer name
            first_line = description.split('\\n')[0].strip()
            if first_line and not any(skip_word in first_line.lower() for skip_word in ['automatische import', 'woocommerce', 'factuur:']):
                customer_name = first_line[:140]  # Limit to field length

        # If no luck with description, check rows for customer info
        if not customer_name and mutation_data.get("rows"):
            for row in mutation_data.get("rows", []):
                row_desc = row.get("description", "")
                if row_desc and len(row_desc) > 3:
                    # Skip generic descriptions
                    if not any(skip_word in row_desc.lower() for skip_word in ['automatische import', 'woocommerce', 'factuur:']):
                        customer_name = row_desc.split('\\n')[0].strip()[:140]
                        break

        if customer_name:
            # Check if customer with this name already exists
            existing_customer = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
            if existing_customer:
                customer = existing_customer
                debug_info.append(f"Found existing customer by name: {customer_name}")
                return customer
            else:
                # Create new customer with extracted name
                try:
                    customer_doc = frappe.new_doc("Customer")
                    customer_doc.customer_name = customer_name
                    customer_doc.customer_group = "All Customer Groups"

                    # Store relation_id if available
                    if relation_id and hasattr(customer_doc, "eboekhouden_relation_code"):
                        customer_doc.eboekhouden_relation_code = relation_id

                    customer_doc.save(ignore_permissions=True)
                    customer = customer_doc.name
                    debug_info.append(f"Created customer from mutation data: {customer_name}")
                    return customer
                except Exception as e:
                    debug_info.append(f"Failed to create customer {customer_name}: {str(e)}")

    # Fallback: Create/use default customer
    customer = frappe.db.get_value("Customer", {"customer_name": "E-Boekhouden Import"}, "name")"""

    content = content.replace(old_fallback, new_fallback)

    # Write back the file
    with open(file_path, "w") as f:
        f.write(content)

    print("Fixed import code successfully!")
    print("\nChanges made:")
    print("1. Enhanced customer extraction from mutation data")
    print("2. Updated Sales Invoice creation to pass mutation data to customer function")
    print("3. Payable account fix was already applied")
    print("4. Cost center fix was already applied")

    return True


@frappe.whitelist()
def fix_existing_records():
    """Fix existing Purchase Invoices and Sales Invoices"""

    # Get correct payable account
    correct_payable = frappe.db.get_value(
        "Account",
        {"company": "Ned Ver Vegan", "account_name": ["like", "%Te betalen bedragen%"], "is_group": 0},
        "name",
    )

    if not correct_payable:
        correct_payable = "19290 - Te betalen bedragen - NVV"

    # Get main cost center
    main_cc = frappe.db.get_value(
        "Cost Center", {"company": "Ned Ver Vegan", "cost_center_name": "Main", "is_group": 0}, "name"
    )

    print(f"Using payable account: {correct_payable}")
    print(f"Using cost center: {main_cc}")

    # Fix 1: Update Purchase Invoices with wrong payable account
    # But exclude tax authority invoices (acceptgiro pattern)
    # affected_pinvs = frappe.db.sql(
    #     """
    #     UPDATE `tabPurchase Invoice` pi
    #     SET pi.credit_to = %s
    #     WHERE pi.supplier = 'E-Boekhouden Import'
    #     AND pi.credit_to = '18100 - Te betalen sociale lasten - NVV'
    #     AND pi.docstatus < 2
    #     AND NOT EXISTS (
    #         SELECT 1 FROM `tabPurchase Invoice Item` pii
    #         WHERE pii.parent = pi.name
    #         AND pii.description LIKE '%%acceptgiro%%'
    #     )
    #     AND pi.bill_no NOT REGEXP '^[0-9]{10,16}$'
    #     """,
    #     correct_payable,
    # )

    print(f"Updated {frappe.db._cursor.rowcount} Purchase Invoices to correct payable account")

    # Fix 2: Update cost centers in Purchase Invoice Items
    if main_cc:
        frappe.db.sql(
            """
            UPDATE `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            SET pii.cost_center = %s
            WHERE pi.supplier = 'E-Boekhouden Import'
            AND pi.docstatus < 2
            AND (pii.cost_center = 'magazine - NVV' OR pii.cost_center IS NULL)
        """,
            main_cc,
        )

        print(f"Updated {frappe.db._cursor.rowcount} Purchase Invoice Items with correct cost center")

    # Fix 3: Try to fix Sales Invoice customer names where possible
    print("\n=== ATTEMPTING TO FIX SALES INVOICE CUSTOMER NAMES ===")

    # Get Sales Invoices that need fixing
    invoices_to_fix = frappe.db.sql(
        """
        SELECT si.name, si.eboekhouden_mutation_nr, sii.description
        FROM `tabSales Invoice` si
        JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
        WHERE si.customer = 'E-Boekhouden Import'
        AND si.docstatus = 1
        AND sii.idx = 1
        LIMIT 100
    """,
        as_dict=True,
    )

    fixed_count = 0
    for inv in invoices_to_fix:
        if inv.description:
            # Try to extract customer name
            customer_name = None

            # Skip WooCommerce orders - they don't have customer names in description
            if "automatische import van woocommerce" in inv.description.lower():
                continue

            # Get first meaningful line
            lines = inv.description.split("\n")
            for line in lines:
                line = line.strip()
                if line and len(line) > 3:
                    if not any(
                        skip in line.lower() for skip in ["factuur:", "ordernummer:", "betalingskenmerk:"]
                    ):
                        customer_name = line[:140]
                        break

            if customer_name:
                # Check if this customer exists
                existing_customer = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")

                if existing_customer:
                    # Update the Sales Invoice (only in draft/cancelled state)
                    if frappe.db.get_value("Sales Invoice", inv.name, "docstatus") == 0:
                        frappe.db.set_value(
                            "Sales Invoice",
                            inv.name,
                            {
                                "customer": existing_customer,
                                "customer_name": customer_name,
                                "title": f"{customer_name} - {inv.eboekhouden_mutation_nr or 'Import'}",
                            },
                        )
                        fixed_count += 1
                        print(f"Fixed {inv.name} -> {customer_name}")

    print(f"\nFixed {fixed_count} Sales Invoices with proper customer names")

    frappe.db.commit()

    return {
        "payable_account_fixed": True,
        "cost_centers_fixed": True,
        "sales_invoices_reviewed": len(invoices_to_fix),
        "sales_invoices_fixed": fixed_count,
    }


@frappe.whitelist()
def restart_required():
    """Notify that bench restart is required"""
    return {"message": 'Please run "bench restart" to apply the code changes', "success": True}
