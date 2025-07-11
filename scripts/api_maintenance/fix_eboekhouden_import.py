import frappe
from frappe import _


@frappe.whitelist()
def analyze_import_issues():
    """Analyze eBoekhouden import issues"""

    # 1. Check payable accounts
    print("=== PAYABLE ACCOUNTS ===")
    payable_accounts = frappe.get_all(
        "Account",
        filters={"company": "Ned Ver Vegan", "account_type": "Payable", "is_group": 0},
        fields=["name", "account_name", "account_number"],
    )

    for acc in payable_accounts:
        print(f"  - {acc.name}")

    # 2. Check account 18100
    acc_18100 = frappe.get_doc("Account", "18100 - Te betalen sociale lasten - NVV")
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
    pinvs = frappe.get_all(
        "Purchase Invoice",
        filters={"supplier": "E-Boekhouden Import"},
        fields=["name", "credit_to", "bill_no"],
        limit=5,
    )

    for pinv in pinvs:
        print(f"  - {pinv.name}: credit_to = {pinv.credit_to}")

    # 6. Check Sales Invoice customer issues
    print("\n=== SAMPLE SALES INVOICES ===")
    sinvs = frappe.get_all(
        "Sales Invoice",
        filters={"customer": "E-Boekhouden Import"},
        fields=["name", "customer_name", "title"],
        limit=5,
    )

    for sinv in sinvs:
        print(f"  - {sinv.name}: customer_name = {sinv.customer_name}, title = {sinv.title}")

    # 7. Check a specific Sales Invoice mutation data
    print("\n=== CHECKING SPECIFIC MUTATION DATA ===")
    # Get a Sales Invoice with eBoekhouden mutation
    sinv_with_mutation = frappe.db.sql(
        """
        SELECT si.name, si.eboekhouden_mutation_nr, si.customer, si.customer_name
        FROM `tabSales Invoice` si
        WHERE si.eboekhouden_mutation_nr IS NOT NULL
        AND si.eboekhouden_mutation_nr != ''
        LIMIT 1
    """,
        as_dict=True,
    )

    if sinv_with_mutation:
        mutation_nr = sinv_with_mutation[0].eboekhouden_mutation_nr
        print(f"Checking mutation {mutation_nr}")

        # Get mutation data from cache
        cached_data = frappe.db.get_value(
            "EBoekhouden REST Mutation Cache", {"mutation_id": mutation_nr}, "mutation_data"
        )

        if cached_data:
            import json

            mutation_data = json.loads(cached_data)
            print(f"  Description: {mutation_data.get('description', 'N/A')}")
            print(f"  Relation ID: {mutation_data.get('relationId', 'N/A')}")

    # 8. Check cost centers
    print("\n=== COST CENTERS ===")
    main_cost_center = frappe.db.get_value(
        "Cost Center", {"company": "Ned Ver Vegan", "cost_center_name": "Main", "is_group": 0}, "name"
    )
    print(f"Main cost center: {main_cost_center}")

    # Check what cost centers are being used
    cost_centers = frappe.db.sql(
        """
        SELECT DISTINCT pii.cost_center, COUNT(*) as count
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.supplier = 'E-Boekhouden Import'
        GROUP BY pii.cost_center
        LIMIT 5
    """,
        as_dict=True,
    )

    print("\nCost centers used in Purchase Invoices:")
    for cc in cost_centers:
        print(f"  - {cc.cost_center}: {cc.count} items")

    return {"correct_payable_account": correct_payable, "main_cost_center": main_cost_center}
