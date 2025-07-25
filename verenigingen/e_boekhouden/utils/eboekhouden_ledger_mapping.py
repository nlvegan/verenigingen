"""
E-Boekhouden Ledger ID to Account Code Mapping
Maps internal E-Boekhouden ledger IDs to actual account codes
"""


import frappe
import requests


@frappe.whitelist()
def fetch_and_create_ledger_mapping():
    """Fetch all ledger accounts from E-Boekhouden and create mapping"""

    try:
        # Use the REST iterator which already handles authentication
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get session token
        session_token = iterator._get_session_token()
        if not session_token:
            return {"success": False, "error": "Could not obtain session token"}

        # REST API endpoint for ledgers
        base_url = iterator.base_url

        headers = {"Authorization": session_token, "Accept": "application/json"}

        # Fetch all ledger accounts with pagination
        all_ledgers = []
        limit = 1000
        offset = 0

        while True:
            ledger_url = f"{base_url}/v1/ledger?limit={limit}&offset={offset}"

            response = requests.get(ledger_url, headers=headers, timeout=30)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": "API returned status {response.status_code}: {response.text}",
                }

            data = response.json()
            items = data.get("items", [])

            if not items:
                break

            all_ledgers.extend(items)

            # Check if we have all items
            if len(all_ledgers) >= data.get("count", 0):
                break

            offset += limit

        ledgers = all_ledgers

        if not ledgers:
            return {"success": False, "error": "No ledgers returned from API"}

        # Create or update mapping doctype entries
        created = 0
        updated = 0
        errors = []

        for ledger in ledgers:
            try:
                ledger_id = str(ledger.get("id"))
                ledger_code = ledger.get("code")
                ledger_name = ledger.get("description", "")

                if not ledger_id or not ledger_code:
                    continue

                # Check if mapping exists
                existing = frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id})

                if existing:
                    # Update existing
                    doc = frappe.get_doc("E-Boekhouden Ledger Mapping", existing)
                    doc.ledger_code = ledger_code
                    doc.ledger_name = ledger_name
                    doc.save()
                    updated += 1
                else:
                    # Create new
                    doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
                    doc.ledger_id = ledger_id
                    doc.ledger_code = ledger_code
                    doc.ledger_name = ledger_name
                    doc.insert()
                    created += 1

            except Exception as e:
                errors.append({"ledger_id": ledger.get("id"), "error": str(e)})

        frappe.db.commit()

        return {
            "success": True,
            "created": created,
            "updated": updated,
            "errors": errors,
            "total_ledgers": len(ledgers),
            "message": "Created {created} and updated {updated} ledger mappings",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def get_account_code_from_ledger_id(ledger_id):
    """Get account code from E-Boekhouden ledger ID"""

    if not ledger_id:
        return None

    # Convert to string for consistency
    ledger_id = str(ledger_id)

    # Check mapping table
    ledger_code = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "ledger_code")

    return ledger_code


@frappe.whitelist()
def create_ledger_mapping_doctype():
    """Create the E-Boekhouden Ledger Mapping DocType"""

    try:
        # Check if doctype already exists
        if frappe.db.exists("DocType", "E-Boekhouden Ledger Mapping"):
            return {"success": True, "message": "DocType already exists"}

        # Create the doctype
        doctype = frappe.new_doc("DocType")
        doctype.name = "E-Boekhouden Ledger Mapping"
        doctype.module = "Verenigingen"
        doctype.custom = 0
        doctype.is_submittable = 0
        doctype.issingle = 0
        doctype.istable = 0
        doctype.editable_grid = 1
        doctype.track_changes = 1
        doctype.autoname = "field:ledger_id"

        # Add fields
        doctype.append(
            "fields",
            {
                "fieldname": "ledger_id",
                "label": "Ledger ID",
                "fieldtype": "Data",
                "reqd": 1,
                "unique": 1,
                "in_list_view": 1,
            },
        )

        doctype.append(
            "fields",
            {
                "fieldname": "ledger_code",
                "label": "Ledger Code",
                "fieldtype": "Data",
                "reqd": 1,
                "in_list_view": 1,
            },
        )

        doctype.append(
            "fields",
            {"fieldname": "ledger_name", "label": "Ledger Name", "fieldtype": "Data", "in_list_view": 1},
        )

        doctype.append(
            "fields",
            {
                "fieldname": "erpnext_account",
                "label": "ERPNext Account",
                "fieldtype": "Link",
                "options": "Account",
                "in_list_view": 1,
            },
        )

        # Add permissions
        doctype.append(
            "permissions", {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}
        )

        doctype.insert()

        return {"success": True, "message": "E-Boekhouden Ledger Mapping DocType created successfully"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def quick_create_mapping_from_logs():
    """Quick create mapping from error logs to fix immediate issue"""

    try:
        # Get unique ledger IDs from error logs
        ledger_ids = frappe.db.sql(
            """
            SELECT DISTINCT
                SUBSTRING_INDEX(SUBSTRING_INDEX(error, 'Account code ', -1), ' not found', 1) as ledger_id
            FROM `tabError Log`
            WHERE error LIKE 'Account code % not found in company Ned Ver Vegan'
            AND creation > '2025-01-01'
            LIMIT 100
        """,
            as_dict=True,
        )

        # For now, create a simple mapping based on patterns
        # This is a temporary solution until we can fetch from API
        created = 0

        for row in ledger_ids:
            ledger_id = row.ledger_id
            if ledger_id and ledger_id.isdigit():
                # Create a temporary mapping
                # We'll need to update these with actual codes later
                existing = frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id})

                if not existing:
                    doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
                    doc.ledger_id = ledger_id
                    doc.ledger_code = f"TEMP-{ledger_id}"  # Temporary code
                    doc.ledger_name = f"Unmapped Ledger {ledger_id}"
                    doc.insert()
                    created += 1

        frappe.db.commit()

        return {
            "success": True,
            "created": created,
            "message": "Created {created} temporary mappings. Run fetch_and_create_ledger_mapping to get actual codes.",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
