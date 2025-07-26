import frappe


@frappe.whitelist()
def check_membership_types():
    """Debug function to check membership types and their settings"""
    try:
        # Get all membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "minimum_amount"], order_by="name"
        )

        return {"success": True, "membership_types": membership_types, "total_count": len(membership_types)}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_test_membership_type():
    """Create a test membership type with low minimum amount"""
    try:
        # Check if test membership type already exists
        existing = frappe.db.exists("Membership Type", "Test Membership Type")
        if existing:
            return {"success": True, "message": "Test Membership Type already exists", "name": existing}

        # Create new test membership type
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type = "Test Membership Type"
        membership_type.minimum_amount = 5.0
        membership_type.description = "Test membership type for automated testing"
        membership_type.save()

        return {"success": True, "message": "Test Membership Type created", "name": membership_type.name}

    except Exception as e:
        return {"success": False, "error": str(e)}
