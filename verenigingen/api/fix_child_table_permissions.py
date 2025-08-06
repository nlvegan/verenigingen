import json

import frappe


@frappe.whitelist()
def fix_child_table_permissions():
    """Fix read permissions for child table DocTypes that need them for functionality"""

    # List of child table DocTypes that need read permissions
    child_tables = [
        "Verenigingen Chapter Board Member",
        "Chapter Member",
        "Chapter Membership History",
        "Communication History",
        "Direct Debit Batch Invoice",
        "Donation History",
        "Donor Relationships",
        "Member Fee Change History",
        "Member Payment History",
        "Member SEPA Mandate Link",
        "Member Volunteer Expenses",
        "Pledge History",
        "SEPA Mandate Usage",
        "Team Member",
        "Team Responsibility",
        "Termination Audit Entry",
        "Volunteer Assignment",
        "Volunteer Development Goal",
        "Volunteer Interest Area",
        "Volunteer Skill",
    ]

    results = {"fixed": [], "errors": [], "already_fixed": [], "total_processed": 0}

    try:
        for doctype_name in child_tables:
            results["total_processed"] += 1

            try:
                # Check if DocType exists and is a child table
                doctype_path = f"/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/{doctype_name.lower().replace(' ', '_')}/{doctype_name.lower().replace(' ', '_')}.json"

                # Read the DocType JSON file
                try:
                    with open(doctype_path, "r") as f:
                        doctype_data = json.load(f)
                except FileNotFoundError:
                    results["errors"].append(f"{doctype_name}: JSON file not found at {doctype_path}")
                    continue

                # Verify it's a child table
                if not doctype_data.get("istable"):
                    results["errors"].append(f"{doctype_name}: Not a child table (istable=False)")
                    continue

                # Check current permissions
                permissions = doctype_data.get("permissions", [])

                # Check if any role already has read permission
                has_read_permission = any(perm.get("read") for perm in permissions)

                if has_read_permission:
                    results["already_fixed"].append(f"{doctype_name}: Already has read permissions")
                    continue

                # Add basic read permission for All role (standard for child tables)
                new_permission = {"read": 1, "role": "All"}

                # Add the permission
                if "permissions" not in doctype_data:
                    doctype_data["permissions"] = []

                doctype_data["permissions"].append(new_permission)

                # Write back to file
                with open(doctype_path, "w") as f:
                    json.dump(doctype_data, f, indent=1)

                results["fixed"].append(f"{doctype_name}: Added read permission for All role")

            except Exception as e:
                results["errors"].append(f"{doctype_name}: Error - {str(e)}")

        # Summary
        results["summary"] = {
            "total_child_tables": len(child_tables),
            "successfully_fixed": len(results["fixed"]),
            "already_had_permissions": len(results["already_fixed"]),
            "errors": len(results["errors"]),
        }

        return results

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def verify_child_table_permissions():
    """Verify that child table permissions are working correctly"""

    child_tables = [
        "Verenigingen Chapter Board Member",
        "Chapter Member",
        "Chapter Membership History",
        "Communication History",
        "Direct Debit Batch Invoice",
        "Donation History",
        "Donor Relationships",
        "Member Fee Change History",
        "Member Payment History",
        "Member SEPA Mandate Link",
        "Member Volunteer Expenses",
        "Pledge History",
        "SEPA Mandate Usage",
        "Team Member",
        "Team Responsibility",
        "Termination Audit Entry",
        "Volunteer Assignment",
        "Volunteer Development Goal",
        "Volunteer Interest Area",
        "Volunteer Skill",
    ]

    verification_results = {"verified": [], "issues": [], "missing_doctypes": []}

    for doctype_name in child_tables:
        try:
            # Check if we can get meta for this DocType
            meta = frappe.get_meta(doctype_name)

            # Check if it's a child table
            if not meta.istable:
                verification_results["issues"].append(f"{doctype_name}: Not marked as child table")
                continue

            # Check permissions
            has_read = False
            for perm in meta.permissions:
                if perm.read:
                    has_read = True
                    break

            if has_read:
                verification_results["verified"].append(f"{doctype_name}: Has read permissions")
            else:
                verification_results["issues"].append(f"{doctype_name}: Missing read permissions")

        except frappe.DoesNotExistError:
            verification_results["missing_doctypes"].append(f"{doctype_name}: DocType does not exist")
        except Exception as e:
            verification_results["issues"].append(f"{doctype_name}: Error - {str(e)}")

    return verification_results
