"""
Check and fix account group mappings
"""

import frappe


@frappe.whitelist()
def get_account_group_mappings():
    """Get the configured account group mappings from settings"""

    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Parse the account group mappings
        mappings = {}
        if settings.account_group_mappings:
            lines = settings.account_group_mappings.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line and " " in line:
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        code = parts[0].strip()
                        name = parts[1].strip()
                        mappings[code] = name

        # Get current account structure
        current_groups = frappe.db.sql(
            """
            SELECT
                name,
                account_name,
                account_number,
                parent_account,
                is_group
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND is_group = 1
            ORDER BY account_number
        """,
            as_dict=True,
        )

        # Check specific accounts mentioned (14500 etc)
        problem_accounts = frappe.db.sql(
            """
            SELECT
                name,
                account_name,
                account_number,
                parent_account,
                account_type
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND account_number IN ('14500', '14200', '14700', '13900', '19290')
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "account_group_mappings": mappings,
            "current_groups": current_groups,
            "problem_accounts": problem_accounts,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def create_missing_account_groups():
    """Create missing account groups based on E-Boekhouden structure"""

    try:
        # Standard Dutch CoA groups
        standard_groups = {
            "001": {"name": "Vaste activa", "parent": "Application of Funds (Assets) - NVV", "type": "Asset"},
            "002": {
                "name": "Vlottende activa",
                "parent": "Application of Funds (Assets) - NVV",
                "type": "Asset",
            },
            "003": {"name": "Liquide middelen", "parent": "Current Assets - NVV", "type": "Asset"},
            "004": {"name": "Vorderingen", "parent": "Current Assets - NVV", "type": "Asset"},
            "005": {
                "name": "Eigen vermogen",
                "parent": "Source of Funds (Liabilities) - NVV",
                "type": "Liability",
            },
            "006": {"name": "Schulden", "parent": "Current Liabilities - NVV", "type": "Liability"},
            "007": {"name": "Kosten", "parent": "Expenses - NVV", "type": "Expense"},
            "008": {"name": "Opbrengsten", "parent": "Income - NVV", "type": "Income"},
        }

        created = []

        for code, info in standard_groups.items():
            group_name = f"{code} - {info['name']} - NVV"

            if not frappe.db.exists("Account", group_name):
                account = frappe.new_doc("Account")
                account.account_name = f"{code} - {info['name']}"
                account.account_number = code
                account.parent_account = info["parent"]
                account.company = "Ned Ver Vegan"
                account.is_group = 1

                # Ensure parent exists
                if frappe.db.exists("Account", info["parent"]):
                    account.insert()
                    created.append(group_name)

        frappe.db.commit()

        return {"success": True, "created": created, "message": f"Created {len(created)} account groups"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def fix_account_parents():
    """Fix parent accounts based on account number ranges"""

    try:
        # Define parent mapping based on account number ranges
        parent_mappings = [
            # Vorderingen (Receivables/Claims) - 1xxxx range
            {
                "range": (10000, 14999),
                "parent": "Vorderingen - NVV",
                "accounts": [
                    "10002 - Overlopende posten - NVV",
                    "13500 - Te ontvangen contributies - NVV",
                    "13510 - Te ontvangen donaties - NVV",
                    "13600 - Te ontvangen rente - NVV",
                    "13900 - Te ontvangen bedragen - NVV",
                    "14200 - Vooruitbetaalde verzekeringen - NVV",
                    "14500 - Vooruitbetaalde bedragen - NVV",
                    "14700 - Overlopende Posten 2018 - NVV",
                ],
            },
            # Schulden (Liabilities/Debts) - 18xxx-19xxx range
            {
                "range": (18000, 19999),
                "parent": "Schulden - NVV",
                "accounts": ["18100 - Te betalen sociale lasten - NVV", "19290 - Te betalen bedragen - NVV"],
            },
        ]

        fixed = []

        for mapping in parent_mappings:
            # Now update the accounts
            for account_name in mapping["accounts"]:
                if frappe.db.exists("Account", account_name):
                    frappe.db.set_value("Account", account_name, "parent_account", mapping["parent"])
                    fixed.append({"account": account_name, "new_parent": mapping["parent"]})

        frappe.db.commit()

        return {
            "success": True,
            "fixed": fixed,
            "message": f"Fixed {len(fixed)} account parent relationships",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
