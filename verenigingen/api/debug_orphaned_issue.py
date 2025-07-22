from datetime import datetime, timedelta

import frappe


@frappe.whitelist()
def debug_orphaned_member_issue():
    """Debug the orphaned member Assoc-Member-2025-07-2897"""

    member_name = "Assoc-Member-2025-07-2897"

    # Get member details
    member = frappe.get_doc("Member", member_name)

    # Get dues schedule
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name},
        fields=["name", "membership", "creation", "schedule_name", "billing_frequency", "dues_rate"],
    )

    # Check what might have created a dues schedule without membership
    creation_time = member.creation

    # Check other test members created around same time (±5 minutes)
    start_time = creation_time - timedelta(minutes=5)
    end_time = creation_time + timedelta(minutes=5)

    similar_members = frappe.db.sql(
        """
        SELECT name, full_name, email, creation
        FROM `tabMember`
        WHERE creation BETWEEN %s AND %s
        AND name != %s
        ORDER BY creation
    """,
        [start_time, end_time, member_name],
        as_dict=True,
    )

    # Check if there are any memberships that should be linked
    all_memberships = frappe.get_all(
        "Membership", filters={"member": member_name}, fields=["name", "status", "creation", "docstatus"]
    )

    # Look for test patterns
    analysis = {
        "member_details": {
            "name": member.name,
            "full_name": member.full_name,
            "email": member.email,
            "creation": str(member.creation),
        },
        "schedules": schedules,
        "memberships": all_memberships,
        "similar_members": similar_members,
        "analysis": {
            "has_membership": len(all_memberships) > 0,
            "has_dues_schedule": len(schedules) > 0,
            "email_pattern": "coverage.test.timestamp@verenigingen.example",
            "name_pattern": "Coverage Test",
            "issue": "Member has dues schedule but no membership",
            "likely_cause": "Test framework created dues schedule independently of membership",
            "recommendations": [
                "Find test that creates 'Coverage Test' members",
                "Fix test to properly link membership and dues schedule",
                "Improve test cleanup to prevent orphaned records",
            ],
        },
    }

    return analysis


@frappe.whitelist()
def simulate_orphaned_member_creation():
    """Simulate how the orphaned member might have been created"""

    # This would be similar to the problematic test pattern
    timestamp = int(datetime.now().timestamp())
    test_email = f"debug.test.{timestamp}@verenigingen.example"

    try:
        # Step 1: Create member (this succeeds)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Debug",
                "last_name": "Test",
                "email": test_email,
                "status": "Active",
            }
        )
        member.insert()

        # Step 2: Create dues schedule directly (this might succeed even without membership)
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Schedule-{member.name}-Debug-001",
                "member": member.name,
                "membership_type": "Daily Access",  # This might not require membership link
                "billing_frequency": "Daily",
                "dues_rate": 8.0,
                "status": "Paused",
            }
        )
        schedule.insert()

        # Step 3: Membership creation would fail here (simulated)
        # This is where the test might fail, leaving orphaned data

        return {
            "success": True,
            "message": "Successfully simulated orphaned member creation",
            "member": member.name,
            "schedule": schedule.name,
            "note": "This demonstrates how a test could create orphaned data",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error during simulation"}
    finally:
        # Clean up test data
        if "member" in locals():
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except:
                pass
        if "schedule" in locals():
            try:
                frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)
            except:
                pass
