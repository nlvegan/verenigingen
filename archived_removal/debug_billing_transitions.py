import frappe

from verenigingen.tests.fixtures.billing_transition_personas import BillingTransitionPersonas


@frappe.whitelist()
def test_mike_transition():
    """Test Mike's monthly to annual transition"""
    try:
        frappe.db.begin()

        # Create Mike's full test data
        mike = BillingTransitionPersonas.create_monthly_to_annual_mike()

        result = {
            "success": True,
            "member": mike["member"].name,
            "membership": mike["membership"].name,
            "monthly_schedule": mike["monthly_schedule"].name,
            "transition_request": mike["transition_request"].name,
        }

        frappe.db.rollback()
        return result

        result = {
            "success": True,
            "member": mike["member"].name,
            "membership": mike["membership"].name,
            "monthly_schedule": mike["monthly_schedule"].name,
            "transition_request": mike["transition_request"].name,
            "transition_details": {
                "current_billing": mike["transition_request"].current_billing_frequency,
                "requested_billing": mike["transition_request"].requested_billing_frequency,
                "current_amount": mike["transition_request"].current_amount,
                "requested_amount": mike["transition_request"].requested_amount,
                "effective_date": str(mike["transition_request"].effective_date),
                "prorated_credit": mike["transition_request"].prorated_credit,
            },
        }

        frappe.db.rollback()
        return result

    except Exception as e:
        frappe.db.rollback()
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_anna_transition():
    """Test Anna's annual to quarterly transition"""
    try:
        frappe.db.begin()

        # Create Anna's test data
        anna = BillingTransitionPersonas.create_annual_to_quarterly_anna()

        result = {
            "success": True,
            "member": anna["member"].name,
            "membership": anna["membership"].name,
            "annual_schedule": anna["annual_schedule"].name,
            "transition_request": anna["transition_request"].name,
            "transition_details": {
                "current_billing": anna["transition_request"].current_billing_frequency,
                "requested_billing": anna["transition_request"].requested_billing_frequency,
                "current_amount": anna["transition_request"].current_amount,
                "requested_amount": anna["transition_request"].requested_amount,
                "effective_date": str(anna["transition_request"].effective_date),
                "prorated_credit": anna["transition_request"].prorated_credit,
            },
        }

        frappe.db.rollback()
        return result

    except Exception as e:
        frappe.db.rollback()
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def check_membership_type_settings():
    """Check the billing frequency settings for membership types"""
    membership_types = [
        "Monthly Standard",
        "Annual Premium",
        "Quarterly Basic",
        "Daily Access",
        "Annual Standard",
        "Flexible Membership",
        "Annual Access",
    ]

    results = []
    for mt_name in membership_types:
        if frappe.db.exists("Membership Type", mt_name):
            mt = frappe.get_doc("Membership Type", mt_name)
            results.append(
                {
                    "name": mt_name,
                    "amount": mt.minimum_amount,
                    "billing_frequency": getattr(mt, "billing_frequency", "Not Set"),
                    "fields": [f.fieldname for f in mt.meta.fields if "billing" in f.fieldname.lower()],
                }
            )
        else:
            results.append({"name": mt_name, "status": "Does not exist"})

    return results


@frappe.whitelist()
def list_existing_test_members():
    """List all existing test members from billing transition tests"""
    members = frappe.get_all(
        "Member",
        filters=[
            [
                "last_name",
                "in",
                [
                    "MonthlyToAnnual",
                    "AnnualToQuarterly",
                    "QuarterlyToMonthly",
                    "DailyToAnnual",
                    "SwitchyMcSwitchface",
                    "Backdated",
                ],
            ]
        ],
        fields=["name", "first_name", "last_name", "status"],
    )

    for member in members:
        # Get membership info
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "membership_type", "status", "docstatus"],
        )
        member["memberships"] = memberships

        # Get dues schedules
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name},
            fields=["name", "status", "billing_frequency", "dues_rate"],
        )
        member["schedules"] = schedules

    return members
