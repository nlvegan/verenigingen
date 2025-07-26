#!/usr/bin/env python3
"""
API endpoint to validate SQL fixes
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_fixed_queries():
    """Test the SQL queries that were fixed"""

    results = {"status": "success", "tests": [], "errors": []}

    # Test 1: Chapter Board Member field existence
    try:
        frappe.db.sql("SELECT volunteer FROM `tabChapter Board Member` LIMIT 1")
        results["tests"].append(
            {
                "test": "Chapter Board Member.volunteer field",
                "status": "✅ PASS",
                "message": "Field exists in database",
            }
        )
    except Exception as e:
        results["tests"].append(
            {"test": "Chapter Board Member.volunteer field", "status": "❌ FAIL", "message": str(e)}
        )
        results["errors"].append(f"Chapter Board Member field issue: {e}")

    # Test 2: Donor fields
    try:
        frappe.db.sql("SELECT donor_email, anbi_consent FROM `tabDonor` LIMIT 1")
        results["tests"].append(
            {
                "test": "Donor.donor_email and anbi_consent fields",
                "status": "✅ PASS",
                "message": "Fields exist in database",
            }
        )
    except Exception as e:
        results["tests"].append(
            {"test": "Donor.donor_email and anbi_consent fields", "status": "❌ FAIL", "message": str(e)}
        )
        results["errors"].append(f"Donor field issue: {e}")

    # Test 3: Membership Dues Schedule fields
    try:
        frappe.db.sql(
            "SELECT next_invoice_date, next_billing_period_start_date FROM `tabMembership Dues Schedule` LIMIT 1"
        )
        results["tests"].append(
            {
                "test": "Membership Dues Schedule period fields",
                "status": "✅ PASS",
                "message": "Fields exist in database",
            }
        )
    except Exception as e:
        results["tests"].append(
            {"test": "Membership Dues Schedule period fields", "status": "❌ FAIL", "message": str(e)}
        )
        results["errors"].append(f"Membership Dues Schedule field issue: {e}")

    # Test 4: Sample Chapter Board Member query
    try:
        result = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE cbm.is_active = 1
            LIMIT 3
        """,
            as_dict=True,
        )
        results["tests"].append(
            {
                "test": "Chapter Board Member query execution",
                "status": "✅ PASS",
                "message": f"Query executed successfully, returned {len(result)} rows",
            }
        )
    except Exception as e:
        results["tests"].append(
            {"test": "Chapter Board Member query execution", "status": "❌ FAIL", "message": str(e)}
        )
        results["errors"].append(f"Chapter Board Member query failed: {e}")

    # Test 5: Sample Donor query
    try:
        result = frappe.db.sql(
            """
            SELECT DISTINCT
                donor.name,
                donor.donor_name,
                donor.donor_email
            FROM `tabDonor` donor
            WHERE donor.donor_email IS NOT NULL
            AND donor.donor_email != ''
            LIMIT 3
        """,
            as_dict=1,
        )
        results["tests"].append(
            {
                "test": "Donor query execution",
                "status": "✅ PASS",
                "message": f"Query executed successfully, returned {len(result)} rows",
            }
        )
    except Exception as e:
        results["tests"].append({"test": "Donor query execution", "status": "❌ FAIL", "message": str(e)})
        results["errors"].append(f"Donor query failed: {e}")

    # Set overall status
    if results["errors"]:
        results["status"] = "error"
        results["summary"] = f"❌ {len(results['errors'])} test(s) failed"
    else:
        results["summary"] = f"✅ All {len(results['tests'])} tests passed"

    return results
