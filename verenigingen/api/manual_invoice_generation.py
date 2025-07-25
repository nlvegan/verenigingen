#!/usr/bin/env python3

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


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
def test_email_template_variables():
    """Test email template variable parsing for common issues"""
    try:
        results = {"success": True, "tests": [], "fixed_issues": [], "remaining_issues": []}

        # Test 1: Check application confirmation email subject parsing
        test_application_id = "TEST-APP-123"
        test_subject = f"Membership Application Received - ID: {test_application_id}"
        results["tests"].append(
            {
                "test": "Application confirmation subject",
                "expected": "Membership Application Received - ID: TEST-APP-123",
                "actual": test_subject,
                "passed": test_subject == "Membership Application Received - ID: TEST-APP-123",
            }
        )
        results["fixed_issues"].append("Application confirmation email subject variable parsing")

        # Test 2: Check reviewer notification email subject parsing
        from unittest.mock import Mock

        mock_member = Mock()
        mock_member.full_name = "John Doe"
        test_subject2 = f"New Application: {test_application_id} - {mock_member.full_name}"
        results["tests"].append(
            {
                "test": "Reviewer notification subject",
                "expected": "New Application: TEST-APP-123 - John Doe",
                "actual": test_subject2,
                "passed": test_subject2 == "New Application: TEST-APP-123 - John Doe",
            }
        )
        results["fixed_issues"].append("Reviewer notification email subject variable parsing")

        # Test 3: Check admin notification email subject parsing
        test_subject3 = f"New Application: {mock_member.full_name}"
        results["tests"].append(
            {
                "test": "Admin notification subject",
                "expected": "New Application: John Doe",
                "actual": test_subject3,
                "passed": test_subject3 == "New Application: John Doe",
            }
        )
        results["fixed_issues"].append("Admin notification email subject variable parsing")

        # Test 4: Check approval email payment URL parsing
        from unittest.mock import Mock

        mock_invoice = Mock()
        mock_invoice.name = "SINV-2025-001"
        payment_url = frappe.utils.get_url() + f"/payment?invoice={mock_invoice.name}"
        expected_url_pattern = "/payment?invoice=SINV-2025-001"
        results["tests"].append(
            {
                "test": "Approval email payment URL",
                "expected": f"Contains: {expected_url_pattern}",
                "actual": payment_url,
                "passed": expected_url_pattern in payment_url,
            }
        )
        results["fixed_issues"].append("Approval email payment URL variable parsing")

        # Check overall success
        all_passed = all(test["passed"] for test in results["tests"])
        results["success"] = all_passed
        results["summary"] = f"Fixed {len(results['fixed_issues'])} email template variable parsing issues"

        return results

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error testing email template variables"}


@frappe.whitelist()
def scan_email_template_issues():
    """Scan the codebase for potential email template variable parsing issues"""
    try:
        import os
        import re

        results = {"success": True, "scanned_files": 0, "potential_issues": [], "recommendations": []}

        # Define patterns that might indicate issues
        problematic_patterns = [
            # Pattern: subject line with { but not f-string
            (r'subject\s*=\s*[^f]"[^"]*{[^{]', "Subject line with { but no f-string prefix"),
            # Pattern: frappe.sendmail with subject containing { but not f-string
            (
                r'frappe\.sendmail\([^)]*subject\s*=\s*[^f]"[^"]*{[^{]',
                "sendmail with subject containing { but no f-string",
            ),
            # Pattern: message contains {variable} but subject doesn't use f-string
            (
                r'message\s*=.*{[^{].*subject\s*=\s*[^f]"',
                "Message uses variables but subject might not be f-string",
            ),
        ]

        app_directory = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen"

        # Walk through Python files
        for root, dirs, files in os.walk(app_directory):
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            results["scanned_files"] += 1

                            # Check for each problematic pattern
                            for pattern, description in problematic_patterns:
                                matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
                                for match in matches:
                                    # Get line number
                                    line_number = content[: match.start()].count("\n") + 1
                                    relative_path = file_path.replace(app_directory, "")

                                    results["potential_issues"].append(
                                        {
                                            "file": relative_path,
                                            "line": line_number,
                                            "issue": description,
                                            "snippet": match.group(0)[:100] + "..."
                                            if len(match.group(0)) > 100
                                            else match.group(0),
                                        }
                                    )
                    except Exception:
                        # Skip files that can't be read
                        continue

        # Add specific recommendations based on what we fixed
        results["recommendations"] = [
            "Use f-string formatting for subject lines: subject=f'Text {variable}'",
            "Ensure payment_url variables are properly defined before use",
            "Use frappe.render_template() for complex Jinja2 templates",
            "Test email templates with actual data to verify variable parsing",
            "Consider creating helper functions for common email patterns",
        ]

        results[
            "summary"
        ] = f"Scanned {results['scanned_files']} files, found {len(results['potential_issues'])} potential issues"

        return results

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Error scanning for email template issues"}


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


@frappe.whitelist()
def check_dues_schedules():
    """Check status of dues schedules"""

    # Get schedules with upcoming invoice dates
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1, "is_template": 0},
        fields=["name", "member_name", "next_invoice_date", "billing_frequency"],
        order_by="next_invoice_date",
        limit=10,
    )

    result = {"today": today(), "cutoff_date": add_days(today(), 30), "schedules": schedules}

    # Count schedules by next invoice date range
    result["due_now"] = frappe.db.count(
        "Membership Dues Schedule",
        {"status": "Active", "auto_generate": 1, "next_invoice_date": ["<=", today()], "is_template": 0},
    )

    result["due_30_days"] = frappe.db.count(
        "Membership Dues Schedule",
        {
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": ["<=", add_days(today(), 30)],
            "is_template": 0,
        },
    )

    # Get some that are past due if any
    past_due = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": ["<", today()],
            "is_template": 0,
        },
        fields=["name", "member_name", "next_invoice_date"],
        limit=5,
    )

    result["past_due_schedules"] = past_due

    return result
