"""
Link E-Boekhouden Ledger Mappings to ERPNext Accounts
"""

import frappe


@frappe.whitelist()
def auto_link_ledgers_to_accounts():
    """Automatically link ledger mappings to ERPNext accounts based on code matching"""

    try:
        # Get all ledger mappings
        mappings = frappe.get_all(
            "E-Boekhouden Ledger Mapping",
            fields=["name", "ledger_id", "ledger_code", "ledger_name", "erpnext_account"],
            limit=500,
        )

        linked_count = 0
        already_linked = 0
        not_found = []

        for mapping in mappings:
            # Skip if already linked
            if mapping.erpnext_account:
                already_linked += 1
                continue

            # Try to find matching account
            account = None

            # First try exact match on account_number
            account = frappe.db.get_value(
                "Account", {"company": "Ned Ver Vegan", "account_number": mapping.ledger_code}, "name"
            )

            # If not found, try eboekhouden_grootboek_nummer
            if not account:
                account = frappe.db.get_value(
                    "Account",
                    {"company": "Ned Ver Vegan", "eboekhouden_grootboek_nummer": mapping.ledger_code},
                    "name",
                )

            # If found, link it
            if account:
                frappe.db.set_value("E-Boekhouden Ledger Mapping", mapping.name, "erpnext_account", account)
                linked_count += 1
            else:
                not_found.append(
                    {
                        "ledger_id": mapping.ledger_id,
                        "ledger_code": mapping.ledger_code,
                        "ledger_name": mapping.ledger_name,
                    }
                )

        frappe.db.commit()

        return {
            "success": True,
            "total_mappings": len(mappings),
            "linked": linked_count,
            "already_linked": already_linked,
            "not_found": len(not_found),
            "not_found_samples": not_found[:20],  # First 20 samples
            "message": "Linked {linked_count} ledgers to accounts",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_mapping_status():
    """Check the status of ledger to account mappings"""

    try:
        # Count total mappings
        total_mappings = frappe.db.count("E-Boekhouden Ledger Mapping")

        # Count linked mappings
        linked_mappings = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabE-Boekhouden Ledger Mapping`
            WHERE erpnext_account IS NOT NULL
            AND erpnext_account != ''
        """
        )[0][0]

        # Get some unlinked samples
        unlinked_samples = frappe.db.sql(
            """
            SELECT ledger_id, ledger_code, ledger_name
            FROM `tabE-Boekhouden Ledger Mapping`
            WHERE erpnext_account IS NULL
            OR erpnext_account = ''
            LIMIT 20
        """,
            as_dict=True,
        )

        # Check some specific problem ledgers from errors
        problem_ledgers = ["36971231", "15916395", "13201883", "13201876", "13201869"]
        problem_status = []

        for ledger_id in problem_ledgers:
            mapping = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping",
                {"ledger_id": ledger_id},
                ["ledger_code", "ledger_name", "erpnext_account"],
                as_dict=True,
            )
            if mapping:
                problem_status.append(
                    {
                        "ledger_id": ledger_id,
                        "ledger_code": mapping.ledger_code,
                        "ledger_name": mapping.ledger_name,
                        "linked_to": mapping.erpnext_account,
                    }
                )

        return {
            "success": True,
            "total_mappings": total_mappings,
            "linked_mappings": linked_mappings,
            "unlinked_mappings": total_mappings - linked_mappings,
            "link_percentage": round((linked_mappings / total_mappings * 100), 2)
            if total_mappings > 0
            else 0,
            "unlinked_samples": unlinked_samples,
            "problem_ledgers": problem_status,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def create_missing_accounts_from_ledgers():
    """Create ERPNext accounts for unlinked ledgers"""

    try:
        # Get unlinked ledgers
        unlinked = frappe.db.sql(
            """
            SELECT name, ledger_id, ledger_code, ledger_name
            FROM `tabE-Boekhouden Ledger Mapping`
            WHERE (erpnext_account IS NULL OR erpnext_account = '')
            AND ledger_code NOT LIKE 'TEMP-%'
        """,
            as_dict=True,
        )

        created = 0
        errors = []

        for ledger in unlinked:
            try:
                # Determine account type based on code range
                account_type = "Expense Account"  # Default
                parent_account = "44009 - Onvoorziene kosten - NVV"  # Default parent

                code = int(ledger.ledger_code) if ledger.ledger_code.isdigit() else 99999

                # Determine type and parent based on code ranges (Dutch CoA)
                if 0 <= code < 1000:
                    account_type = "Fixed Asset"
                    parent_account = "Fixed Assets - NVV"
                elif 1000 <= code < 2000:
                    account_type = "Bank"
                    parent_account = "Bank Accounts - NVV"
                elif 2000 <= code < 3000:
                    account_type = "Stock"
                    parent_account = "Stock Assets - NVV"
                elif 3000 <= code < 4000:
                    account_type = "Receivable"
                    parent_account = "Accounts Receivable - NVV"
                elif 4000 <= code < 5000:
                    account_type = "Expense Account"
                    parent_account = "Direct Expenses - NVV"
                elif 5000 <= code < 6000:
                    account_type = "Equity"
                    parent_account = "Equity - NVV"
                elif 6000 <= code < 7000:
                    account_type = "Payable"
                    parent_account = "Accounts Payable - NVV"
                elif 7000 <= code < 8000:
                    account_type = "Cost of Goods Sold"
                    parent_account = "Cost of Goods Sold - NVV"
                elif 8000 <= code < 9000:
                    account_type = "Income Account"
                    parent_account = "Direct Income - NVV"
                elif 9000 <= code < 10000:
                    account_type = "Income Account"
                    parent_account = "Indirect Income - NVV"

                # Create the account
                account = frappe.new_doc("Account")
                account.account_name = ledger.ledger_name
                account.account_number = ledger.ledger_code
                account.parent_account = parent_account
                account.account_type = account_type
                account.company = "Ned Ver Vegan"
                account.is_group = 0

                account.insert()

                # Link to ledger mapping
                frappe.db.set_value(
                    "E-Boekhouden Ledger Mapping", ledger.name, "erpnext_account", account.name
                )

                created += 1

            except Exception as e:
                errors.append({"ledger_code": ledger.ledger_code, "error": str(e)})

        frappe.db.commit()

        return {
            "success": True,
            "created": created,
            "errors": errors,
            "message": "Created {created} new accounts",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
