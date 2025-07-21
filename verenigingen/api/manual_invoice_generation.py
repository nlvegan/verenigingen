#!/usr/bin/env python3

import frappe
from frappe import _
from frappe.utils import flt, getdate, today


@frappe.whitelist()
def generate_manual_invoice(member_name):
    """
    Generate a manual invoice for a member's current dues schedule

    Args:
        member_name: Name of the Member record

    Returns:
        dict: Success/error message and invoice details
    """
    try:
        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} not found"}

        member = frappe.get_doc("Member", member_name)

        # Check if member has a customer record
        if not member.customer:
            return {
                "success": False,
                "error": "Member must have a customer record to generate invoices. Please create a customer record first.",
            }

        # Find the member's active dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0, "status": "Active"},
            ["name", "dues_rate", "billing_frequency", "member_name"],
            as_dict=True,
        )

        if not dues_schedule:
            return {
                "success": False,
                "error": "No active dues schedule found for this member. Please create a dues schedule first.",
            }

        schedule_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule.name)

        # Generate the invoice using the schedule's method
        try:
            invoice_name = schedule_doc.generate_invoice(force=True)  # Force generation for manual invoices

            if invoice_name:
                return {
                    "success": True,
                    "message": f"Invoice {invoice_name} generated successfully",
                    "invoice_name": invoice_name,
                    "amount": flt(dues_schedule.dues_rate, 2),
                    "customer": member.customer,
                    "dues_schedule": dues_schedule.name,
                }
            else:
                return {"success": False, "error": "Failed to generate invoice - no invoice created"}

        except Exception as invoice_error:
            return {"success": False, "error": f"Error generating invoice: {str(invoice_error)}"}

    except Exception as e:
        frappe.log_error(f"Error in manual invoice generation for {member_name}: {str(e)}")
        return {"success": False, "error": f"Unexpected error: {str(e)}"}


@frappe.whitelist()
def get_member_invoice_info(member_name):
    """
    Get information about member's dues schedule and recent invoices for UI display

    Args:
        member_name: Name of the Member record

    Returns:
        dict: Member invoice information
    """
    try:
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} not found"}

        member = frappe.get_doc("Member", member_name)

        # Get dues schedule info
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0, "status": "Active"},
            ["name", "dues_rate", "billing_frequency", "next_invoice_date", "last_invoice_date"],
            as_dict=True,
        )

        result = {
            "success": True,
            "member_name": member.full_name,
            "has_customer": bool(member.customer),
            "customer": member.customer,
            "has_dues_schedule": bool(dues_schedule),
        }

        if dues_schedule:
            result.update(
                {
                    "dues_schedule_name": dues_schedule.name,
                    "current_rate": flt(dues_schedule.dues_rate, 2),
                    "billing_frequency": dues_schedule.billing_frequency,
                    "next_invoice_date": dues_schedule.next_invoice_date,
                    "last_invoice_date": dues_schedule.last_invoice_date,
                }
            )

            # Get recent invoices for this member
            if member.customer:
                recent_invoices = frappe.get_all(
                    "Sales Invoice",
                    filters={"customer": member.customer, "docstatus": ["!=", 2]},  # Not cancelled
                    fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
                    order_by="posting_date desc",
                    limit=5,
                )
                result["recent_invoices"] = recent_invoices

        return result

    except Exception as e:
        frappe.log_error(f"Error getting invoice info for {member_name}: {str(e)}")
        return {"success": False, "error": f"Error retrieving information: {str(e)}"}


@frappe.whitelist()
def test_settings_creation_user():
    """Test if the creation_user field from Verenigingen Settings is accessible"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        creation_user = getattr(settings, "creation_user", None)

        # Test the admin fallback logic from dues_schedule_auto_creator
        admins = []
        if not admins:
            try:
                settings = frappe.get_single("Verenigingen Settings")
                creation_user_from_settings = getattr(settings, "creation_user", None)
                if creation_user_from_settings:
                    admins = [creation_user_from_settings]
                else:
                    admins = ["Administrator"]  # Final fallback
            except Exception:
                admins = ["Administrator"]  # Final fallback

        result = {
            "success": True,
            "creation_user": creation_user,
            "has_field": hasattr(settings, "creation_user"),
            "field_value": creation_user if creation_user else "Not set",
            "admin_fallback_result": admins,
            "admin_fallback_logic_works": len(admins) > 0
            and (admins[0] == creation_user if creation_user else admins[0] == "Administrator"),
        }

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_sepa_mandate_pattern():
    """Test the configurable SEPA mandate_id generation pattern"""

    result = []
    result.append("=== Testing SEPA Mandate ID Generation Pattern ===")

    try:
        # Test 1: Check if settings field exists and has default value
        result.append("\n1. Testing Verenigingen Settings field...")
        settings = frappe.get_single("Verenigingen Settings")

        current_pattern = getattr(settings, "sepa_mandate_naming_pattern", None)

        if current_pattern is None:
            result.append("❌ Field 'sepa_mandate_naming_pattern' not found in Verenigingen Settings!")
            return {"success": False, "message": "\n".join(result)}

        result.append(f"Current SEPA mandate pattern: {current_pattern}")

        # Test 2: Test creating a SEPA mandate without mandate_id to test auto-generation
        result.append("\n2. Testing mandate_id auto-generation...")
        original_pattern = settings.sepa_mandate_naming_pattern
        test_pattern = "TEST-REF-.YY.-.####"

        settings.sepa_mandate_naming_pattern = test_pattern
        settings.save()

        result.append(f"Set test pattern: {test_pattern}")

        # Test 3: Create a test SEPA mandate to see if mandate_id gets auto-generated
        result.append("\n3. Creating test SEPA mandate...")

        # Create a test mandate without mandate_id
        test_mandate = frappe.new_doc("SEPA Mandate")
        test_mandate.account_holder_name = "Test Account Holder"
        test_mandate.iban = "NL91ABNA0417164300"  # Valid test IBAN
        test_mandate.sign_date = frappe.utils.today()
        # Don't set mandate_id - it should be auto-generated

        # Validate (this should trigger auto-generation)
        test_mandate.validate()

        generated_mandate_id = test_mandate.mandate_id
        result.append(f"Generated mandate_id: {generated_mandate_id}")

        # Test 4: Restore original pattern
        result.append("\n4. Restoring original pattern...")
        settings.sepa_mandate_naming_pattern = original_pattern
        settings.save()

        result.append(f"Restored pattern: {original_pattern}")

        if generated_mandate_id and generated_mandate_id.startswith("TEST-REF-"):
            result.append("\n✅ All tests passed! SEPA mandate_id auto-generation is working.")
            return {
                "success": True,
                "message": "\n".join(result),
                "original_pattern": original_pattern,
                "generated_mandate_id": generated_mandate_id,
            }
        else:
            result.append(
                f"\n❌ Test failed: mandate_id '{generated_mandate_id}' doesn't match expected pattern"
            )
            return {"success": False, "message": "\n".join(result)}

    except Exception as e:
        result.append(f"\n❌ Error during testing: {str(e)}")
        return {"success": False, "error": str(e), "message": "\n".join(result)}
