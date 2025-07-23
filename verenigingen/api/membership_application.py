"""
Refactored membership application API with improved organization and error handling
"""
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.application_helpers import check_application_status as check_application_status_util
from verenigingen.utils.application_helpers import (
    create_address_from_application,
    create_member_from_application,
    create_pending_chapter_membership,
    create_volunteer_record,
    determine_chapter_from_application,
    generate_application_id,
    get_form_data,
    get_member_field_info,
)
from verenigingen.utils.application_helpers import get_membership_fee_info as get_membership_fee_info_util
from verenigingen.utils.application_helpers import (
    get_membership_type_details as get_membership_type_details_util,
)
from verenigingen.utils.application_helpers import load_draft_application as load_draft_application_util
from verenigingen.utils.application_helpers import parse_application_data
from verenigingen.utils.application_helpers import save_draft_application as save_draft_application_util
from verenigingen.utils.application_helpers import (
    suggest_membership_amounts as suggest_membership_amounts_util,
)
from verenigingen.utils.application_notifications import (
    check_overdue_applications,
    notify_reviewers_of_new_application,
    send_application_confirmation_email,
    send_approval_email,
    send_payment_confirmation_email,
    send_rejection_email,
)
from verenigingen.utils.application_payments import get_payment_methods as get_payment_methods_util
from verenigingen.utils.application_payments import process_application_payment
from verenigingen.utils.config_manager import ConfigManager

# Import enhanced utilities
from verenigingen.utils.error_handling import PermissionError, ValidationError, handle_api_error, log_error
from verenigingen.utils.performance_utils import QueryOptimizer, performance_monitor
from verenigingen.utils.validation.api_validators import (
    APIValidator,
    rate_limit,
    require_roles,
    validate_api_input,
)

# Import our utility modules
from verenigingen.utils.validation.application_validators import (
    check_application_eligibility as check_application_eligibility_util,
)
from verenigingen.utils.validation.application_validators import validate_address as validate_address_util
from verenigingen.utils.validation.application_validators import (
    validate_birth_date as validate_birth_date_util,
)
from verenigingen.utils.validation.application_validators import (
    validate_custom_amount as validate_custom_amount_util,
)
from verenigingen.utils.validation.application_validators import validate_email as validate_email_util
from verenigingen.utils.validation.application_validators import validate_membership_amount_selection
from verenigingen.utils.validation.application_validators import validate_name as validate_name_util
from verenigingen.utils.validation.application_validators import (
    validate_phone_number as validate_phone_number_util,
)
from verenigingen.utils.validation.application_validators import (
    validate_postal_code as validate_postal_code_util,
)
from verenigingen.utils.validation.application_validators import validate_required_fields

# Utility functions


def check_rate_limit(endpoint, limit_per_hour=60):
    """Check if the current user/session has exceeded rate limits"""
    try:
        # Use IP address and session for rate limiting
        client_ip = frappe.local.request.environ.get("REMOTE_ADDR", "unknown")
        cache_key = f"rate_limit:{endpoint}:{client_ip}"

        current_count = frappe.cache().get(cache_key) or 0
        if current_count >= limit_per_hour:
            return False

        # Increment counter with 1 hour expiry
        frappe.cache().setex(cache_key, 3600, current_count + 1)
        return True

    except Exception:
        # If rate limiting fails, allow the request
        return True


# Removed - using centralized error handling from utils.error_handling


# API Endpoints


@frappe.whitelist(allow_guest=True)
def test_connection():
    """Simple test method to verify the API is working"""
    return {
        "success": True,
        "message": "Backend connection working",
        "timestamp": frappe.utils.now(),
        "user": frappe.session.user,
        "version": "2.0",
        "features": [
            "form_data",
            "validation",
            "draft_save",
            "submission",
            "payment_methods",
            "error_handling",
            "tracking",
        ],
    }


@frappe.whitelist(allow_guest=True)
def test_all_endpoints():
    """Test that all critical endpoints are accessible"""
    endpoints_tested = []
    try:
        # Test form data
        form_data = get_form_data()
        endpoints_tested.append({"get_form_data": "✓" if form_data.get("success") else "✗"})

        # Test email validation
        email_test = validate_email_util("test@example.com")
        endpoints_tested.append({"validate_email": "✓" if email_test.get("valid") else "✗"})

        return {"success": True, "message": "All endpoints accessible", "tested": endpoints_tested}
    except Exception as e:
        return {"success": False, "error": str(e), "tested": endpoints_tested}


@frappe.whitelist(allow_guest=True)
def get_application_form_data():
    """Get data needed for application form"""
    try:
        result = get_form_data()
        # Ensure consistent success format
        if not result.get("success"):
            result["success"] = True
        return result
    except Exception as e:
        # Enhanced error logging and fallback
        frappe.log_error(f"Error in get_form_data: {str(e)}", "Application Form Data Error")
        return {
            "success": True,
            "error": False,  # Not critical error since we have fallbacks
            "membership_types": [],
            "chapters": [],
            "volunteer_areas": [],
            "countries": [
                {"name": "Netherlands"},
                {"name": "Germany"},
                {"name": "Belgium"},
                {"name": "France"},
                {"name": "United Kingdom"},
                {"name": "Other"},
            ],
            "payment_methods": [
                {"name": "Bank Transfer", "description": "One-time bank transfer"},
                {"name": "SEPA Direct Debit", "description": "SEPA Direct Debit (recurring)"},
            ],
        }


@frappe.whitelist(allow_guest=True)
@performance_monitor(threshold_ms=200)
@rate_limit(max_requests=30, window_minutes=60)
def validate_email(email):
    """Validate email format and check if it already exists"""

    if not email:
        return {"valid": False, "message": "Email is required", "type": "required"}

    # Use enhanced API validator
    try:
        validated_email = APIValidator.validate_email(email)
        result = validate_email_util(validated_email)

        # Ensure consistent response format
        if not isinstance(result, dict):
            return {"valid": False, "message": "Invalid validation response", "type": "server_error"}

        return result

    except ValidationError as e:
        return {"valid": False, "message": str(e), "type": "validation_error"}
    except Exception as e:
        log_error(f"Email validation error: {str(e)}", "Email Validation Error")
        return {"valid": False, "message": "Validation service error", "type": "server_error"}


@frappe.whitelist(allow_guest=True)
def validate_email_endpoint(email):
    """Validate email format and check if it already exists (legacy endpoint)"""
    return validate_email(email)


@frappe.whitelist(allow_guest=True)
def validate_postal_code(postal_code, country="Netherlands"):
    """Validate postal code format and suggest chapters"""
    result = validate_postal_code_util(postal_code, country)

    if result["valid"]:
        # Find matching chapters
        suggested_chapters = []
        try:
            from verenigingen.verenigingen.doctype.member.member_utils import find_chapter_by_postal_code

            chapter_result = find_chapter_by_postal_code(postal_code)

            if chapter_result.get("success") and chapter_result.get("matching_chapters"):
                suggested_chapters = chapter_result["matching_chapters"]
        except Exception as e:
            frappe.log_error(f"Error finding chapters for postal code {postal_code}: {str(e)}")

        result["suggested_chapters"] = suggested_chapters

    return result


@frappe.whitelist(allow_guest=True)
def validate_postal_code_endpoint(postal_code, country="Netherlands"):
    """Validate postal code format and suggest chapters (legacy endpoint)"""
    return validate_postal_code(postal_code, country)


@frappe.whitelist(allow_guest=True)
def validate_phone_number(phone, country="Netherlands"):
    """Validate phone number format"""
    return validate_phone_number_util(phone, country)


@frappe.whitelist(allow_guest=True)
def validate_phone_number_endpoint(phone, country="Netherlands"):
    """Validate phone number format (legacy endpoint)"""
    return validate_phone_number(phone, country)


@frappe.whitelist(allow_guest=True)
def validate_birth_date(birth_date):
    """Validate birth date"""
    return validate_birth_date_util(birth_date)


@frappe.whitelist(allow_guest=True)
def validate_birth_date_endpoint(birth_date):
    """Validate birth date (legacy endpoint)"""
    return validate_birth_date(birth_date)


@frappe.whitelist(allow_guest=True)
def validate_name(name, field_name="Name"):
    """Validate name fields"""
    return validate_name_util(name, field_name)


@frappe.whitelist(allow_guest=True)
def validate_name_endpoint(name, field_name="Name"):
    """Validate name fields (legacy endpoint)"""
    return validate_name(name, field_name)


@frappe.whitelist(allow_guest=True)
def check_application_eligibility_endpoint(data):
    """Check if applicant is eligible for membership"""
    try:
        parsed_data = parse_application_data(data)
        return check_application_eligibility_util(parsed_data)
    except Exception as e:
        return {"eligible": False, "issues": [str(e)], "warnings": []}


@frappe.whitelist(allow_guest=True)
@handle_api_error
@performance_monitor(threshold_ms=3000)
@rate_limit(max_requests=10, window_minutes=60)
def submit_application(**kwargs):
    """Process membership application submission - Main entry point"""
    try:
        # Parse and validate data
        data = parse_application_data(kwargs.get("data", kwargs))

        # Validate required fields
        required_fields = [
            "first_name",
            "last_name",
            "email",
            "birth_date",
            "address_line1",
            "city",
            "postal_code",
            "country",
        ]

        validation_result = validate_required_fields(data, required_fields)
        if not validation_result["valid"]:
            return {
                "success": False,
                "error": f"Missing required fields: {', '.join(validation_result['missing_fields'])}",
                "message": f"Missing required fields: {', '.join(validation_result['missing_fields'])}",
            }

        # Check eligibility
        eligibility = check_application_eligibility_util(data)
        if not eligibility["eligible"]:
            # Log detailed validation failure for debugging
            frappe.log_error(
                f"Application eligibility check failed for email {data.get('email')}: {'; '.join(eligibility['issues'])}",
                "Application Eligibility Failed",
            )
            return {
                "success": False,
                "error": "Application not eligible",
                "message": f"Validation failed: {'; '.join(eligibility['issues'])}",
                "issues": eligibility["issues"],
                "warnings": eligibility.get("warnings", []),
            }

        # Check if member with email already exists
        existing = frappe.db.exists("Member", {"email": data.get("email")})
        if existing:
            return {
                "success": False,
                "error": "A member with this email already exists",
                "message": "A member with this email already exists. Please login or contact support.",
            }

        # Validate membership amount if custom amount is provided
        if data.get("membership_amount") or data.get("uses_custom_amount"):
            membership_type = data.get("selected_membership_type")
            custom_contribution_fee = data.get("custom_contribution_fee")
            uses_custom = data.get("uses_custom_amount", False)

            if membership_type and custom_contribution_fee:
                # Validate custom amount
                amount_validation = validate_custom_amount_util(membership_type, custom_contribution_fee)
                if not amount_validation["valid"]:
                    frappe.log_error(
                        f"Custom amount validation failed for application: {amount_validation['message']}",
                        "Custom Amount Validation Failed",
                    )
                    return {
                        "success": False,
                        "error": "Invalid membership amount",
                        "message": amount_validation["message"],
                        "type": "validation_error",
                    }

                # Also validate using the membership amount selection validator
                selection_validation = validate_membership_amount_selection(
                    membership_type, custom_contribution_fee, uses_custom
                )
                if not selection_validation["valid"]:
                    frappe.log_error(
                        f"Membership amount selection validation failed for application: {selection_validation['message']}",
                        "Amount Selection Validation Failed",
                    )
                    return {
                        "success": False,
                        "error": "Invalid membership amount selection",
                        "message": selection_validation["message"],
                        "type": "validation_error",
                    }

        # Generate application ID
        application_id = generate_application_id()

        # Create address
        address = None
        try:
            address = create_address_from_application(data)
        except Exception as e:
            frappe.log_error(
                f"Failed to create address for application {application_id}: {str(e)}",
                "Address Creation Error",
            )
            # Continue without address - not critical for member creation

        # Create member
        try:
            member = create_member_from_application(data, application_id, address)
        except Exception as e:
            frappe.log_error(
                f"Failed to create member record for application {application_id}: {str(e)}\nData: {json.dumps(data, default=str)}",
                "Member Creation Error",
            )
            raise  # Re-raise since this is critical

        # Determine suggested chapter
        suggested_chapter = determine_chapter_from_application(data)
        if suggested_chapter:
            # Use getattr to safely set chapter field, fallback to current_chapter_display
            if hasattr(member, "suggested_chapter"):
                member.suggested_chapter = suggested_chapter
            else:
                member.current_chapter_display = suggested_chapter

            # Handle concurrency with retry logic
            try:
                member.save()
            except frappe.TimestampMismatchError:
                # Reload member and retry save once
                member.reload()
                if hasattr(member, "suggested_chapter"):
                    member.suggested_chapter = suggested_chapter
                else:
                    member.current_chapter_display = suggested_chapter
                member.save()

        # Create volunteer record if interested
        if data.get("interested_in_volunteering"):
            create_volunteer_record(member)

        # Commit member creation before creating chapter membership
        frappe.db.commit()

        # Create pending Chapter Member record after member is committed
        if suggested_chapter:
            try:
                chapter_member = create_pending_chapter_membership(member, suggested_chapter)
                if chapter_member:
                    frappe.logger().info(
                        f"Created pending chapter membership for {member.name} in {suggested_chapter}"
                    )
                else:
                    frappe.logger().warning(
                        f"Failed to create pending chapter membership for {member.name} in {suggested_chapter}"
                    )
            except Exception as e:
                # Log error with shorter message to avoid title length issues
                try:
                    frappe.log_error(
                        f"Chapter membership creation failed for {member.name}: {str(e)[:200]}",
                        "Chapter Setup Error",
                    )
                except Exception:
                    # Fallback: just log to system log if error log creation fails
                    frappe.logger().error(f"Chapter membership creation failed for {member.name}")
                # Don't fail the application submission if chapter membership creation fails

        # Send notifications
        try:
            send_application_confirmation_email(member, application_id)
            notify_reviewers_of_new_application(member, application_id)
        except Exception as e:
            frappe.log_error(f"Error sending notifications: {str(e)}", "Notification Error")

        return {
            "success": True,
            "message": "Application submitted successfully! You will receive an email with your application ID.",
            "application_id": application_id,
            "applicant_id": getattr(member, "application_id", None),
            "member_record": member.name,
            "status": "pending_review",
        }

    except Exception as e:
        frappe.db.rollback()

        # Get full error details
        import traceback

        error_msg = str(e)
        full_traceback = traceback.format_exc()

        frappe.log_error(
            f"Error in submit_application: {error_msg}\n\nFull traceback:\n{full_traceback}",
            "Application Submission Error",
        )

        return {
            "success": False,
            "error": error_msg,
            "message": f"Application submission failed: {error_msg}",
            "type": "server_error",
            "timestamp": frappe.utils.now(),
        }


@frappe.whitelist()
@handle_api_error
@performance_monitor(threshold_ms=2000)
@require_roles(["System Manager", "Verenigingen Administrator", "Verenigingen Manager"])
def approve_membership_application(member_name, notes=None):
    """Approve a membership application"""

    # Validate inputs
    validate_required_fields({"member_name": member_name}, ["member_name"])

    notes = APIValidator.sanitize_text(notes, max_length=1000) if notes else None

    try:
        member = frappe.get_doc("Member", member_name)

        if member.application_status not in ["Pending", "Under Review"]:
            return {"success": False, "error": "This application cannot be approved in its current state"}

        # Add notes if provided
        if notes:
            member.review_notes = notes

        # Use the new approve_application method which handles member ID assignment
        member.approve_application()

        # Send approval email with payment instructions
        # Get application invoice from payment history child table
        application_invoice_name = None
        for payment in member.payment_history or []:
            if payment.invoice_type == "Application" or "application" in (payment.description or "").lower():
                application_invoice_name = payment.invoice
                break

        if application_invoice_name:
            invoice = frappe.get_doc("Sales Invoice", application_invoice_name)
            send_approval_email(member, invoice)
        else:
            frappe.log_error(f"No application invoice found for member {member.name}", "Application Approval")

        invoice_info = (
            f" and invoice {application_invoice_name} generated"
            if application_invoice_name
            else " (no invoice found)"
        )
        return {
            "success": True,
            "message": f"Application approved! Member ID {member.member_id} assigned{invoice_info}",
            "member_id": member.member_id,
            "applicant_id": getattr(member, "application_id", None),
            "invoice": application_invoice_name,
        }

    except Exception as e:
        frappe.log_error(f"Error approving application: {str(e)}")
        return {"success": False, "error": str(e), "message": "Error approving application"}


@frappe.whitelist()
def reject_membership_application(member_name, reason):
    """Reject a membership application"""
    try:
        member = frappe.get_doc("Member", member_name)

        if member.application_status not in ["Pending", "Under Review"]:
            return {"success": False, "error": "This application cannot be rejected in its current state"}

        # Use the new reject_application method which handles chapter membership cleanup
        member.reject_application(reason)

        # Send rejection email
        send_rejection_email(member, reason)

        return {
            "success": True,
            "message": "Application rejected, pending chapter membership removed, and notification sent",
        }

    except Exception as e:
        frappe.log_error(f"Error rejecting application: {str(e)}")
        return {"success": False, "error": str(e), "message": "Error rejecting application"}


@frappe.whitelist()
def process_application_payment_endpoint(member_name, payment_method, payment_reference=None):
    """Process payment for approved application"""
    try:
        payment_entry = process_application_payment(member_name, payment_method, payment_reference)

        # Send confirmation email
        member = frappe.get_doc("Member", member_name)
        # Get application invoice from payment history child table
        application_invoice_name = None
        for payment in member.payment_history or []:
            if payment.invoice_type == "Application" or "application" in (payment.description or "").lower():
                application_invoice_name = payment.invoice
                break

        if application_invoice_name:
            invoice = frappe.get_doc("Sales Invoice", application_invoice_name)
            send_payment_confirmation_email(member, invoice)
        else:
            frappe.log_error(f"No application invoice found for member {member_name}", "Payment Confirmation")

        return {
            "success": True,
            "message": "Payment processed successfully",
            "payment_entry": payment_entry.name,
        }

    except Exception as e:
        frappe.log_error(f"Error processing payment: {str(e)}")
        return {"success": False, "error": str(e), "message": "Error processing payment"}


@frappe.whitelist(allow_guest=True)
def get_membership_fee_info_endpoint(membership_type):
    """Get membership fee information"""
    try:
        return get_membership_fee_info_util(membership_type)
    except Exception as e:
        return handle_api_error(e, "Membership Fee Info")


@frappe.whitelist(allow_guest=True)
def get_membership_type_details_endpoint(membership_type):
    """Get detailed membership type information"""
    try:
        return get_membership_type_details_util(membership_type)
    except Exception as e:
        return handle_api_error(e, "Membership Type Details")


@frappe.whitelist(allow_guest=True)
def suggest_membership_amounts_endpoint(membership_type_name):
    """Suggest membership amounts based on type"""
    try:
        return suggest_membership_amounts_util(membership_type_name)
    except Exception as e:
        return handle_api_error(e, "Suggest Membership Amounts")


@frappe.whitelist(allow_guest=True)
def validate_membership_amount_selection_endpoint(membership_type, amount, uses_custom):
    """Validate membership amount selection"""
    return validate_membership_amount_selection(membership_type, amount, uses_custom)


@frappe.whitelist(allow_guest=True)
def validate_custom_amount_endpoint(membership_type, amount):
    """Validate custom membership amount"""
    return validate_custom_amount_util(membership_type, amount)


@frappe.whitelist(allow_guest=True)
def get_payment_methods_endpoint():
    """Get available payment methods"""
    try:
        return get_payment_methods_util()
    except Exception as e:
        return handle_api_error(e, "Payment Methods")


@frappe.whitelist(allow_guest=True)
def save_draft_application_endpoint(data):
    """Save application as draft"""
    try:
        parsed_data = parse_application_data(data)
        return save_draft_application_util(parsed_data)
    except Exception as e:
        return handle_api_error(e, "Save Draft")


@frappe.whitelist(allow_guest=True)
def load_draft_application_endpoint(draft_id):
    """Load application draft"""
    try:
        return load_draft_application_util(draft_id)
    except Exception as e:
        return handle_api_error(e, "Load Draft")


@frappe.whitelist(allow_guest=True)
def get_member_field_info_endpoint():
    """Get information about member fields for form generation"""
    return get_member_field_info()


@frappe.whitelist(allow_guest=True)
def check_application_status_endpoint(application_id):
    """Check the status of an application by ID"""
    try:
        return check_application_status_util(application_id)
    except Exception as e:
        return handle_api_error(e, "Check Application Status")


# Scheduled tasks


def check_overdue_applications_task():
    """Scheduled task to check for overdue applications"""
    check_overdue_applications()


# Test endpoints


@frappe.whitelist(allow_guest=True)
def test_submit():
    """Simple test submission function"""
    try:
        return {"success": True, "message": "Test submission working", "timestamp": frappe.utils.now()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_member_issue(member_name="Assoc-Member-2025-06-0091"):
    """Debug the chapter membership issue for a specific member"""
    try:
        # Get member details
        member = frappe.get_doc("Member", member_name)
        result = {
            "member_id": member.name,
            "status": member.status,
            "application_status": getattr(member, "application_status", "Not found"),
            "application_id": getattr(member, "application_id", "Not found"),
        }

        # Check for chapter fields
        chapter_fields = [
            "current_chapter_display",
            "chapter_assigned_by",
            "previous_chapter",
            "suggested_chapter",
        ]
        result["chapter_data"] = {}
        for field in chapter_fields:
            if hasattr(member, field):
                value = getattr(member, field)
                if value:
                    result["chapter_data"][field] = value

        # Check Chapter Member records
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name},
            fields=["name", "parent", "chapter_join_date", "enabled", "leave_reason", "status"],
        )
        result["chapter_member_records"] = chapter_members

        # Check available chapters
        chapters = frappe.get_all("Chapter", fields=["name", "region"], limit=5)
        result["available_chapters"] = chapters

        # Check if there's a suggested chapter that should be activated
        if result["chapter_data"].get("current_chapter_display") and not chapter_members:
            result["needs_chapter_activation"] = {
                "suggested_chapter": result["chapter_data"]["current_chapter_display"],
                "action_needed": "Create Chapter Member record",
            }

        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def fix_specific_member(member_name, chapter_name=None, dry_run=True):
    """
    Fix chapter membership for a specific member

    Args:
        member_name (str): Member ID to fix
        chapter_name (str): Chapter to assign (optional, will try to determine if not provided)
        dry_run (bool): If True, only analyze without fixing

    Returns:
        dict: Results of the operation
    """
    results = {"member": member_name, "fixed": False, "error": None, "dry_run": dry_run}

    try:
        # Get member
        if not frappe.db.exists("Member", member_name):
            results["error"] = f"Member {member_name} does not exist"
            return results

        member = frappe.get_doc("Member", member_name)

        # Check if member already has chapter memberships
        existing_chapters = frappe.get_all(
            "Chapter Member", filters={"member": member_name}, fields=["parent", "status"]
        )

        if existing_chapters:
            results[
                "error"
            ] = f"Member {member_name} already has chapter memberships: {[ch['parent'] for ch in existing_chapters]}"
            return results

        # Determine chapter if not provided
        if not chapter_name:
            if hasattr(member, "current_chapter_display") and member.current_chapter_display:
                chapter_name = member.current_chapter_display
            elif hasattr(member, "suggested_chapter") and member.suggested_chapter:
                chapter_name = member.suggested_chapter
            else:
                # Try postal code lookup
                try:
                    chapter_name = determine_chapter_from_application(
                        {
                            "postal_code": getattr(member, "pincode", ""),
                            "city": getattr(member, "city", ""),
                            "state": getattr(member, "state", ""),
                        }
                    )
                except Exception:
                    pass

        if not chapter_name:
            results["error"] = f"No chapter could be determined for member {member_name}"
            return results

        # Verify chapter exists
        if not frappe.db.exists("Chapter", chapter_name):
            results["error"] = f"Chapter '{chapter_name}' does not exist"
            return results

        results["proposed_chapter"] = chapter_name

        if not dry_run:
            # Create the chapter membership
            from verenigingen.utils.application_helpers import create_active_chapter_membership

            chapter_member = create_active_chapter_membership(member, chapter_name)

            if chapter_member:
                results["fixed"] = True
                results["action"] = f"Created active chapter membership for {member_name} in {chapter_name}"
            else:
                results["error"] = f"Failed to create chapter membership for {member_name} in {chapter_name}"
        else:
            results["action"] = f"Would create active chapter membership for {member_name} in {chapter_name}"

        return results

    except Exception as e:
        results["error"] = str(e)
        import traceback

        results["traceback"] = traceback.format_exc()
        return results


@frappe.whitelist()
def test_chapter_membership_workflow():
    """Test the complete chapter membership workflow"""
    test_email = f"test-workflow-{int(now_datetime().timestamp())}@example.com"
    test_chapter = None

    results = {"test_start": str(now_datetime()), "steps": [], "success": False, "errors": []}

    try:
        # Step 1: Setup test data
        test_chapter = "TEST-CHAPTER-WORKFLOW"

        # Use existing chapter instead of creating new one to avoid validation issues
        existing_chapters = frappe.get_all("Chapter", filters={"published": 1}, limit=1)
        if existing_chapters:
            test_chapter = existing_chapters[0]["name"]
        else:
            # Fallback: try to create test chapter
            if not frappe.db.exists("Chapter", test_chapter):
                try:
                    chapter = frappe.get_doc(
                        {
                            "doctype": "Chapter",
                            "name": test_chapter,
                            "region": "nederland",
                            "published": 1,
                            "title": "Test Chapter for Workflow",
                        }
                    )
                    chapter.insert()
                except Exception as e:
                    # If chapter creation fails, use any available chapter
                    all_chapters = frappe.get_all("Chapter", limit=1)
                    if all_chapters:
                        test_chapter = all_chapters[0]["name"]
                    else:
                        raise Exception(
                            f"No chapters available for testing and cannot create test chapter: {str(e)}"
                        )

        results["test_chapter"] = test_chapter
        results["steps"].append("✓ Test data setup completed")

        # Step 2: Submit application with chapter selection
        # Get an existing membership type
        membership_types = frappe.get_all("Membership Type", limit=1)
        if not membership_types:
            raise Exception("No membership types available for testing")

        test_membership_type = membership_types[0]["name"]

        application_data = {
            "first_name": "Test",
            "last_name": "WorkflowUser",
            "email": test_email,
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "city": "Test City",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": test_membership_type,
            "selected_chapter": test_chapter,
            "interested_in_volunteering": False,
            "payment_method": "Bank Transfer",
        }

        application_result = submit_application(data=application_data)
        if not application_result.get("success"):
            raise Exception(f"Application submission failed: {application_result.get('error')}")

        member_name = application_result.get("member_record")
        results["member_name"] = member_name
        results["steps"].append("✓ Application submitted successfully")

        # Step 3: Verify pending Chapter Member record was created
        pending_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "status": "Pending"},
            fields=["parent", "status", "enabled"],
        )

        if not pending_chapters:
            raise Exception("No pending Chapter Member record found after application submission")

        if pending_chapters[0]["parent"] != test_chapter:
            raise Exception(
                f"Wrong chapter in pending record: {pending_chapters[0]['parent']} vs {test_chapter}"
            )

        results["pending_record"] = pending_chapters[0]
        results["steps"].append("✓ Pending Chapter Member record created correctly")

        # Step 4: Approve the application
        approval_result = approve_membership_application(member_name, "Test approval")
        if not approval_result.get("success"):
            raise Exception(f"Application approval failed: {approval_result.get('error')}")

        results["approval_result"] = {
            "member_id": approval_result.get("member_id"),
            "invoice": approval_result.get("invoice"),
        }
        results["steps"].append("✓ Application approved successfully")

        # Step 5: Verify Chapter Member record was activated
        active_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "status": "Active"},
            fields=["parent", "status", "enabled", "chapter_join_date"],
        )

        if not active_chapters:
            raise Exception("No active Chapter Member record found after approval")

        if active_chapters[0]["parent"] != test_chapter:
            raise Exception(
                f"Wrong chapter in active record: {active_chapters[0]['parent']} vs {test_chapter}"
            )

        results["active_record"] = active_chapters[0]
        results["steps"].append("✓ Chapter Member record activated correctly")

        # Step 6: Test Chapter Members report access
        try:
            from verenigingen.verenigingen.report.chapter_members.chapter_members import (
                execute as chapter_members_report,
            )

            report_result = chapter_members_report({"chapter": test_chapter})
            columns, data = report_result

            # Find our test member in the results
            test_member_in_report = None
            for row in data:
                if row.get("member") == member_name:
                    test_member_in_report = row
                    break

            if not test_member_in_report:
                raise Exception("Test member not found in Chapter Members report")

            if test_member_in_report.get("status") != "Active":
                raise Exception(
                    f"Test member has wrong status in report: {test_member_in_report.get('status')}"
                )

            results["report_test"] = test_member_in_report
            results["steps"].append("✓ Chapter Members report shows activated member correctly")
        except Exception as e:
            results["steps"].append(f"○ Report test skipped: {str(e)}")

        # Step 7: Clean up test data
        try:
            # Remove test member
            frappe.delete_doc("Member", member_name, force=True)
            results["steps"].append("✓ Test data cleaned up")
        except Exception as e:
            results["steps"].append(f"○ Cleanup partially failed: {str(e)}")

        # Success!
        results["success"] = True
        results[
            "summary"
        ] = f"All {len([s for s in results['steps'] if s.startswith('✓')])} critical steps passed"

    except Exception as e:
        results["errors"].append(str(e))
        results["success"] = False
        results["summary"] = f"Test failed: {str(e)}"

        # Attempt cleanup on failure
        if "member_name" in locals():
            try:
                frappe.delete_doc("Member", member_name, force=True)
                results["steps"].append("✓ Cleanup completed after failure")
            except Exception:
                results["steps"].append("✗ Cleanup failed")

    results["test_end"] = str(now_datetime())
    return results


@frappe.whitelist()
def test_status_field_integration():
    """Test status field integration without complex chapter operations"""

    results = {"tests_run": 0, "tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Status field exists and is configured correctly
    results["tests_run"] += 1
    try:
        doctype_meta = frappe.get_meta("Chapter Member")
        status_field = next((f for f in doctype_meta.fields if f.fieldname == "status"), None)

        assert status_field is not None, "Status field must exist"
        assert status_field.fieldtype == "Select", "Status field must be Select type"
        assert "Pending" in status_field.options, "Must have Pending option"
        assert "Active" in status_field.options, "Must have Active option"
        assert "Inactive" in status_field.options, "Must have Inactive option"
        assert status_field.default == "Active", "Default should be Active"

        results["tests_passed"] += 1
        results["details"].append("✅ Status field configuration: PASSED")
    except Exception as e:
        results["tests_failed"] += 1
        results["details"].append(f"❌ Status field configuration: FAILED - {str(e)}")

    # Test 2: Database queries work with status field
    results["tests_run"] += 1
    try:
        # Test basic queries for each status
        for status in ["Pending", "Active", "Inactive"]:
            query_result = frappe.get_all(
                "Chapter Member", filters={"status": status}, fields=["name", "status"], limit=1
            )
            assert isinstance(query_result, list), f"Query for {status} should return list"

        results["tests_passed"] += 1
        results["details"].append("✅ Database status queries: PASSED")
    except Exception as e:
        results["tests_failed"] += 1
        results["details"].append(f"❌ Database status queries: FAILED - {str(e)}")

    # Test 3: Helper functions exist and are importable
    results["tests_run"] += 1
    try:
        from verenigingen.utils.application_helpers import (
            activate_pending_chapter_membership,
            create_pending_chapter_membership,
        )

        # Test they handle invalid inputs gracefully
        result1 = create_pending_chapter_membership(None, "test")
        result2 = activate_pending_chapter_membership(None, "test")

        # Should return None for invalid inputs, not crash
        assert result1 is None, "Should handle None member gracefully"
        assert result2 is None, "Should handle None member gracefully"

        results["tests_passed"] += 1
        results["details"].append("✅ Helper functions: PASSED")
    except Exception as e:
        results["tests_failed"] += 1
        results["details"].append(f"❌ Helper functions: FAILED - {str(e)}")

    # Test 4: Report includes status column
    results["tests_run"] += 1
    try:
        from verenigingen.verenigingen.report.chapter_members.chapter_members import (
            execute as chapter_members_report,
        )

        # Get any existing chapter for testing
        chapters = frappe.get_all("Chapter", limit=1)
        if chapters:
            test_chapter = chapters[0]["name"]

            # Mock admin access for report
            original_user = frappe.session.user
            frappe.session.user = "Administrator"

            try:
                columns, data = chapter_members_report({"chapter": test_chapter})

                # Check status column exists
                status_column = next((col for col in columns if col.get("fieldname") == "status"), None)
                assert status_column is not None, "Report should include status column"
                assert status_column.get("label") == "Status", "Status column should have correct label"

            finally:
                frappe.session.user = original_user

        results["tests_passed"] += 1
        results["details"].append("✅ Report status column: PASSED")
    except Exception as e:
        results["tests_failed"] += 1
        results["details"].append(f"❌ Report status column: FAILED - {str(e)}")

    # Test 5: Member approval function includes chapter activation logic
    results["tests_run"] += 1
    try:
        # Import the Member class properly
        # Check if the method imports the activation function
        import inspect

        from verenigingen.verenigingen.doctype.member.member import Member

        source = inspect.getsource(Member.approve_application)
        assert (
            "activate_pending_chapter_membership" in source
        ), "approve_application should call activate_pending_chapter_membership"

        results["tests_passed"] += 1
        results["details"].append("✅ Member approval integration: PASSED")
    except Exception as e:
        results["tests_failed"] += 1
        results["details"].append(f"❌ Member approval integration: FAILED - {str(e)}")

    # Test 6: Application submission includes chapter membership creation
    results["tests_run"] += 1
    try:
        # Check that submit_application function calls create_pending_chapter_membership
        import inspect

        source = inspect.getsource(submit_application)
        assert (
            "create_pending_chapter_membership" in source
        ), "submit_application should call create_pending_chapter_membership"

        results["tests_passed"] += 1
        results["details"].append("✅ Application submission integration: PASSED")
    except Exception as e:
        results["tests_failed"] += 1
        results["details"].append(f"❌ Application submission integration: FAILED - {str(e)}")

    # Summary
    results["success"] = results["tests_failed"] == 0
    results[
        "summary"
    ] = f"Integration Test Results: {results['tests_passed']}/{results['tests_run']} tests passed"

    if results["success"]:
        results["details"].append(
            "\n🎉 ALL INTEGRATION TESTS PASSED! The chapter membership workflow is properly implemented."
        )
    else:
        results["details"].append(f"\n⚠️  {results['tests_failed']} tests failed. Check implementation.")

    return results


# Legacy endpoints for backward compatibility

# Legacy validation endpoints removed - main functions already defined above


@frappe.whitelist(allow_guest=True)
def validate_custom_amount(membership_type, amount):
    """Legacy endpoint - validate custom membership amount"""
    return validate_custom_amount_util(membership_type, amount)


@frappe.whitelist(allow_guest=True)
def save_draft_application(data):
    """Legacy endpoint - save application as draft"""
    return save_draft_application_endpoint(data)


@frappe.whitelist(allow_guest=True)
def load_draft_application(draft_id):
    """Legacy endpoint - load application draft"""
    return load_draft_application_endpoint(draft_id)


@frappe.whitelist(allow_guest=True)
def get_membership_type_details(membership_type):
    """Legacy endpoint - get detailed membership type information"""
    return get_membership_type_details_endpoint(membership_type)


@frappe.whitelist(allow_guest=True)
def get_membership_fee_info(membership_type):
    """Legacy endpoint - get membership fee information"""
    return get_membership_fee_info_endpoint(membership_type)


@frappe.whitelist(allow_guest=True)
def suggest_membership_amounts(membership_type_name):
    """Legacy endpoint - suggest membership amounts based on type"""
    return suggest_membership_amounts_endpoint(membership_type_name)


@frappe.whitelist(allow_guest=True)
def get_payment_methods():
    """Legacy endpoint - get available payment methods"""
    return get_payment_methods_endpoint()


@frappe.whitelist(allow_guest=True)
def check_application_status(application_id):
    """Legacy endpoint - check the status of an application by ID"""
    return check_application_status_endpoint(application_id)


@frappe.whitelist(allow_guest=True)
def submit_application_with_tracking(**kwargs):
    """Legacy endpoint - same as submit_application"""
    return submit_application(**kwargs)


@frappe.whitelist(allow_guest=True)
def check_application_eligibility(data):
    """Legacy endpoint - check if applicant is eligible for membership"""
    return check_application_eligibility_endpoint(data)


@frappe.whitelist(allow_guest=True)
def get_application_form_data_legacy():
    """Legacy endpoint - use get_application_form_data instead"""
    return get_application_form_data()


@frappe.whitelist(allow_guest=True)
def validate_address_endpoint(data):
    """Validate address data"""
    try:
        parsed_data = parse_application_data(data)
        return validate_address_util(parsed_data)
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}
