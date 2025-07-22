import frappe


@frappe.whitelist()
def test_membership_type_validation():
    """Test if the required field validation is working"""

    try:
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "TEST-Required-Field-Check",
                "amount": 10.0,
                "billing_period": "Monthly",
                # Intentionally omitting dues_schedule_template (now required)
            }
        )
        membership_type.insert()

        return {
            "success": True,
            "message": "Membership type created without template - validation NOT working",
            "created": membership_type.name,
        }

    except frappe.ValidationError as e:
        return {
            "success": False,
            "validation_working": True,
            "error": str(e),
            "message": "Validation correctly prevented creation",
        }
    except frappe.MandatoryError as e:
        return {
            "success": False,
            "validation_working": True,
            "error": str(e),
            "message": "Mandatory field validation correctly prevented creation",
        }
    except Exception as e:
        return {
            "success": False,
            "validation_working": False,
            "error": str(e),
            "message": f"Unexpected error: {type(e).__name__}",
        }
