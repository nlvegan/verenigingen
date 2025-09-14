"""
Fix Mollie data storage - move from Member to Customer fields
"""
import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def update_emma_customer_mollie_data():
    """Update Emma's Customer record with the correct Mollie IDs"""
    try:
        # Find Emma
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "customer"],
        )
        if not members:
            return {"error": "Emma van Subscription not found"}

        emma_member = members[0]

        # Get the Customer record
        customer = frappe.get_doc("Customer", emma_member["customer"])

        print(f"✅ Found Customer: {customer.name}")
        print(f"   Current Mollie Customer ID: {getattr(customer, 'custom_mollie_customer_id', 'None')}")
        print(
            f"   Current Mollie Subscription ID: {getattr(customer, 'custom_mollie_subscription_id', 'None')}"
        )

        # Update with the real Mollie IDs
        customer.custom_mollie_customer_id = "cst_9NfuyWyhAe"
        customer.custom_mollie_subscription_id = "sub_x2W8R6eLGd"
        customer.custom_subscription_status = "active"
        customer.custom_next_payment_date = "2025-09-30"

        customer.save()

        print("✅ Updated Customer Mollie data:")
        print(f"   Mollie Customer ID: {customer.custom_mollie_customer_id}")
        print(f"   Subscription ID: {customer.custom_mollie_subscription_id}")
        print(f"   Status: {customer.custom_subscription_status}")

        # Clear the Member fields if they exist (they shouldn't be the source of truth)
        member = frappe.get_doc("Member", emma_member["name"])
        if hasattr(member, "mollie_customer_id") and member.mollie_customer_id:
            print(f"⚠️ Clearing Member mollie_customer_id: {member.mollie_customer_id}")
            member.db_set("mollie_customer_id", None)

        if hasattr(member, "mollie_subscription_id") and member.mollie_subscription_id:
            print(f"⚠️ Clearing Member mollie_subscription_id: {member.mollie_subscription_id}")
            member.db_set("mollie_subscription_id", None)

        return {
            "success": True,
            "customer_name": customer.name,
            "mollie_customer_id": customer.custom_mollie_customer_id,
            "mollie_subscription_id": customer.custom_mollie_subscription_id,
        }

    except Exception as e:
        print(f"❌ Error updating Emma's Customer data: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def check_mollie_field_definitions():
    """Check where Mollie fields are defined in the system"""
    try:
        # Check Customer DocType for custom fields
        customer_fields = frappe.get_all(
            "Custom Field",
            filters={"dt": "Customer", "fieldname": ["like", "%mollie%"]},
            fields=["fieldname", "label", "fieldtype"],
        )

        print("🏢 Customer Mollie Fields:")
        for field in customer_fields:
            print(f"   {field['fieldname']}: {field['label']} ({field['fieldtype']})")

        # Check Member DocType JSON for mollie fields
        member_doctype = frappe.get_doc("DocType", "Member")
        member_mollie_fields = [
            field for field in member_doctype.fields if "mollie" in field.fieldname.lower()
        ]

        print("\n🧑‍💼 Member Mollie Fields:")
        for field in member_mollie_fields:
            print(f"   {field.fieldname}: {field.label} ({field.fieldtype})")

        return {
            "success": True,
            "customer_fields": len(customer_fields),
            "member_fields": len(member_mollie_fields),
        }

    except Exception as e:
        print(f"❌ Error checking field definitions: {str(e)}")
        return {"error": str(e)}
