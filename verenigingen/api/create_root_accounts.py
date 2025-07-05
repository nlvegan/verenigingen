import frappe


@frappe.whitelist()
def create_root_accounts():
    """Create the basic root accounts for the company"""
    frappe.set_user("Administrator")

    company = "Ned Ver Vegan"

    # Define root accounts based on Dutch Grootboekschema
    root_accounts = [
        # Balance Sheet accounts
        {"account_name": "Activa", "root_type": "Asset", "account_number": "0"},
        {"account_name": "Passiva", "root_type": "Liability", "account_number": "3"},
        {"account_name": "Eigen Vermogen", "root_type": "Equity", "account_number": "5"},
        # P&L accounts
        {"account_name": "Opbrengsten", "root_type": "Income", "account_number": "8"},
        {"account_name": "Kosten", "root_type": "Expense", "account_number": "6"},
    ]

    created = []
    errors = []

    for acc in root_accounts:
        try:
            # Check if already exists
            existing = frappe.db.exists(
                "Account",
                {
                    "company": company,
                    "root_type": acc["root_type"],
                    "parent_account": ["in", ["", None]],
                    "is_group": 1,
                },
            )

            if existing:
                print(f"Root account for {acc['root_type']} already exists: {existing}")
                continue

            # Create the account using the new_doc method with special handling for root accounts
            account = frappe.new_doc("Account")
            account.account_name = acc["account_name"]
            account.company = company
            account.root_type = acc["root_type"]
            account.is_group = 1
            account.account_number = acc["account_number"]

            # Special handling: Use save() which might handle root account validation differently
            account.flags.ignore_validate = True
            account.flags.ignore_mandatory = True
            account.save(ignore_permissions=True)
            created.append(f"{acc['account_name']} ({acc['root_type']})")
            print(f"Created root account: {account.name}")

        except Exception as e:
            errors.append(f"{acc['account_name']}: {str(e)}")
            print(f"Error creating {acc['account_name']}: {str(e)}")

    frappe.db.commit()

    print("\n=== Summary ===")
    print(f"Created: {len(created)} accounts")
    if created:
        for c in created:
            print(f"  - {c}")

    if errors:
        print(f"\nErrors: {len(errors)}")
        for e in errors:
            print(f"  - {e}")

    return {"created": created, "errors": errors}


@frappe.whitelist()
def create_standard_coa_groups():
    """Create standard account groups under root accounts"""
    frappe.set_user("Administrator")

    company = "Ned Ver Vegan"

    # Get root accounts
    root_accounts = {}
    for root_type in ["Asset", "Liability", "Equity", "Income", "Expense"]:
        root = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "parent_account": ["in", ["", None]], "is_group": 1},
            "name",
        )
        if root:
            root_accounts[root_type] = root

    print(f"Found root accounts: {root_accounts}")

    # Define standard groups based on Dutch accounting
    groups = [
        # Under Assets
        {"account_name": "Vaste Activa", "parent": root_accounts.get("Asset"), "account_number": "02"},
        {"account_name": "Vlottende Activa", "parent": root_accounts.get("Asset"), "account_number": "1"},
        {"account_name": "Liquide Middelen", "parent": root_accounts.get("Asset"), "account_number": "10"},
        {"account_name": "Voorraden", "parent": root_accounts.get("Asset"), "account_number": "30"},
        # Under Liabilities
        {
            "account_name": "Kort Vreemd Vermogen",
            "parent": root_accounts.get("Liability"),
            "account_number": "4",
        },
        {
            "account_name": "Lang Vreemd Vermogen",
            "parent": root_accounts.get("Liability"),
            "account_number": "3",
        },
        # Under Equity
        {"account_name": "Reserves", "parent": root_accounts.get("Equity"), "account_number": "50"},
        # Under Income
        {"account_name": "Inkomsten Algemeen", "parent": root_accounts.get("Income"), "account_number": "80"},
        {"account_name": "Overige Inkomsten", "parent": root_accounts.get("Income"), "account_number": "88"},
        # Under Expense
        {"account_name": "Personeelskosten", "parent": root_accounts.get("Expense"), "account_number": "60"},
        {"account_name": "Algemene Kosten", "parent": root_accounts.get("Expense"), "account_number": "61"},
        {
            "account_name": "Huisvestingskosten",
            "parent": root_accounts.get("Expense"),
            "account_number": "62",
        },
        {"account_name": "Verkoopkosten", "parent": root_accounts.get("Expense"), "account_number": "63"},
        {"account_name": "Afschrijvingen", "parent": root_accounts.get("Expense"), "account_number": "65"},
        {"account_name": "Overige Kosten", "parent": root_accounts.get("Expense"), "account_number": "69"},
    ]

    created = []
    errors = []

    for grp in groups:
        if not grp["parent"]:
            errors.append(f"{grp['account_name']}: No parent root account found")
            continue

        try:
            # Check if already exists
            existing = frappe.db.exists(
                "Account",
                {"company": company, "account_name": grp["account_name"], "parent_account": grp["parent"]},
            )

            if existing:
                print(f"Group {grp['account_name']} already exists")
                continue

            # Determine root_type from parent
            parent_root_type = frappe.db.get_value("Account", grp["parent"], "root_type")

            # Create the group account
            account = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": grp["account_name"],
                    "company": company,
                    "parent_account": grp["parent"],
                    "root_type": parent_root_type,
                    "is_group": 1,
                    "account_number": grp["account_number"],
                }
            )

            account.insert(ignore_permissions=True)
            created.append(f"{grp['account_name']} under {grp['parent']}")
            print(f"Created group: {account.name}")

        except Exception as e:
            errors.append(f"{grp['account_name']}: {str(e)}")
            print(f"Error creating {grp['account_name']}: {str(e)}")

    frappe.db.commit()

    print("\n=== Summary ===")
    print(f"Created: {len(created)} groups")
    if errors:
        print(f"Errors: {len(errors)}")

    return {"created": created, "errors": errors}
