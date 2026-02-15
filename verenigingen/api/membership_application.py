"""
Refactored membership application API with improved organization and error handling
"""

import json
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.api.membership_application_review import send_rejection_notification
from verenigingen.utils.application_helpers import (
    check_application_status as check_application_status_util,
    create_address_from_application,
    create_member_from_application,
    create_pending_chapter_membership,
    create_volunteer_record,
    determine_chapter_from_application,
    generate_application_id,
    get_form_data,
    get_member_field_info,
    get_membership_fee_info as get_membership_fee_info_util,
    get_membership_type_details as get_membership_type_details_util,
    load_draft_application as load_draft_application_util,
    parse_application_data,
    save_draft_application as save_draft_application_util,
    suggest_membership_amounts as suggest_membership_amounts_util,
    update_member_from_reapplication,
)
from verenigingen.utils.application_notifications import check_overdue_applications
from verenigingen.utils.application_payments import (
    get_payment_methods as get_payment_methods_util,
    process_application_payment,
)
from verenigingen.utils.config_manager import ConfigManager

# Import enhanced utilities
from verenigingen.utils.error_handling import PermissionError, ValidationError, handle_api_error, log_error
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.performance_utils import QueryOptimizer, performance_monitor

# Import security decorators
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    public_api,
    standard_api,
)
from verenigingen.utils.validation.api_validators import (
    APIValidator,
    rate_limit,
    require_roles,
    validate_api_input,
)

# Import our utility modules
from verenigingen.utils.validation.application_validators import (
    check_application_eligibility as check_application_eligibility_util,
    validate_address as validate_address_util,
    validate_birth_date as validate_birth_date_util,
    validate_custom_amount as validate_custom_amount_util,
    validate_email as validate_email_util,
    validate_membership_amount_selection,
    validate_name as validate_name_util,
    validate_phone_number as validate_phone_number_util,
    validate_postal_code as validate_postal_code_util,
    validate_required_fields,
)

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


def _wrap_validation(fn, field_name="field", operation=""):
    """Generic wrapper for validation endpoints returning {"valid": True/False}.

    Eliminates repeated try/except/OperationResult boilerplate across validation
    endpoints. The fn callable should return a dict with at least a "valid" key.
    """
    try:
        result = fn()
        if result.get("valid"):
            return OperationResult.ok(result, message=_(f"{field_name} is valid"))
        return OperationResult.fail(
            _(result.get("message", f"{field_name} validation failed")),
            errors=[result.get("type", "validation_error")],
            context=result,
        )
    except Exception as e:
        frappe.log_error(
            f"{field_name} validation error: {str(e)}\n{traceback.format_exc()}",
            f"{field_name} Validation Error",
        )
        return OperationResult.fail(
            _(f"{field_name} validation failed"),
            errors=[str(e)],
            context={"operation": operation or f"validate_{field_name.lower()}"},
        )


def _wrap_data_fetch(
    fn, success_message="Data retrieved", error_message="Error retrieving data", operation=""
):
    """Generic wrapper for data-fetch endpoints that always return ok unless exception.

    Eliminates repeated try/except/OperationResult boilerplate across
    endpoints that call a utility function and wrap its result in OperationResult.ok().
    """
    try:
        result = fn()
        return OperationResult.ok(result, message=_(success_message))
    except Exception as e:
        frappe.log_error(
            f"{operation} error: {str(e)}\n{traceback.format_exc()}",
            f"{operation} Error",
        )
        return OperationResult.fail(
            _(error_message),
            errors=[str(e)],
            context={"operation": operation},
        )


def _wrap_success_check(fn, success_message="", fail_message="", fail_error="failed", operation=""):
    """Generic wrapper for endpoints returning {"success": True/False}.

    Eliminates repeated try/except/OperationResult boilerplate across
    endpoints that delegate to utility functions returning success dicts.
    """
    try:
        result = fn()
        if result.get("success"):
            return OperationResult.ok(result, message=_(success_message))
        return OperationResult.fail(
            _(result.get("message", fail_message)),
            errors=[result.get("error", fail_error)],
            context=result,
        )
    except Exception as e:
        frappe.log_error(
            f"{operation} error: {str(e)}\n{traceback.format_exc()}",
            f"{operation} Error",
        )
        return OperationResult.fail(
            _(f"Error: {fail_message.lower()}" if fail_message else "Operation failed"),
            errors=[str(e)],
            context={"operation": operation},
        )


# API Endpoints


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def test_connection() -> OperationResult[Dict[str, Any]]:
    """Simple test method to verify the API is working"""
    return OperationResult.ok(
        {
            "message": _("Backend connection working"),
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
        },
        message=_("API connection successful"),
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def test_all_endpoints() -> OperationResult[Dict[str, Any]]:
    """Test that all critical endpoints are accessible"""
    endpoints_tested = []
    try:
        # Test form data
        form_data = get_form_data()
        endpoints_tested.append({"get_form_data": "✓" if form_data.get("success") else "✗"})

        # Test email validation
        email_test = validate_email_util("test@example.com")
        endpoints_tested.append({"validate_email": "✓" if email_test.get("valid") else "✗"})

        return OperationResult.ok({"tested": endpoints_tested}, message=_("All endpoints accessible"))
    except Exception as e:
        frappe.log_error(f"Endpoint test error: {str(e)}\n{traceback.format_exc()}", "Endpoint Test Error")
        return OperationResult.fail(
            _("Some endpoints failed testing"),
            errors=[str(e)],
            context={"operation": "test_all_endpoints", "tested": endpoints_tested},
        )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_application_form_data() -> OperationResult[Dict[str, Any]]:
    """Get data needed for application form"""
    try:
        result = get_form_data()
        # Ensure consistent success format
        if not result.get("success"):
            result["success"] = True
        return OperationResult.ok(result, message=_("Form data retrieved successfully"))
    except Exception as e:
        # Enhanced error logging and fallback
        frappe.log_error(
            f"Error in get_form_data: {str(e)}\n{traceback.format_exc()}", "Application Form Data Error"
        )
        # Return fallback data with OperationResult
        fallback_data = {
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
        return OperationResult.ok(fallback_data, message=_("Form data retrieved with fallback defaults"))


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
@performance_monitor(threshold_ms=200)
def validate_email(email) -> OperationResult[Dict[str, Any]]:
    """Validate email format and check if it already exists"""

    if not email:
        return OperationResult.fail(
            _("Email is required"),
            errors=["email_required"],
            context={"type": "required", "valid": False},
        )

    # Use enhanced API validator
    try:
        validated_email = APIValidator.validate_email(email)
        result = validate_email_util(validated_email)

        # Ensure consistent response format
        if not isinstance(result, dict):
            return OperationResult.fail(
                _("Invalid validation response"),
                errors=["invalid_response"],
                context={"type": "server_error", "valid": False},
            )

        # Wrap validation result in OperationResult
        if result.get("valid"):
            return OperationResult.ok(result, message=_("Email is valid"))
        else:
            return OperationResult.fail(
                _(result.get("message", "Email validation failed")),
                errors=[result.get("type", "validation_error")],
                context=result,
            )

    except ValidationError as e:
        return OperationResult.fail(
            str(e), errors=["validation_error"], context={"type": "validation_error", "valid": False}
        )
    except Exception as e:
        log_error(f"Email validation error: {str(e)}\n{traceback.format_exc()}", "Email Validation Error")
        return OperationResult.fail(
            _("Validation service error"),
            errors=[str(e)],
            context={"type": "server_error", "valid": False},
        )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_email_endpoint(email) -> OperationResult[Dict[str, Any]]:
    """Validate email format and check if it already exists (legacy endpoint)"""
    return validate_email(email)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_postal_code(postal_code, country="Netherlands") -> OperationResult[Dict[str, Any]]:
    """Validate postal code format and suggest chapters"""
    try:
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
                frappe.log_error(
                    f"Error finding chapters for postal code {postal_code}: {str(e)}\n{traceback.format_exc()}",
                    "Chapter Lookup Error",
                )

            result["suggested_chapters"] = suggested_chapters
            return OperationResult.ok(result, message=_("Postal code is valid"))
        else:
            return OperationResult.fail(
                _(result.get("message", "Postal code validation failed")),
                errors=[result.get("type", "validation_error")],
                context=result,
            )
    except Exception as e:
        frappe.log_error(
            f"Postal code validation error: {str(e)}\n{traceback.format_exc()}",
            "Postal Code Validation Error",
        )
        return OperationResult.fail(
            _("Postal code validation failed"),
            errors=[str(e)],
            context={"operation": "validate_postal_code"},
        )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_postal_code_endpoint(postal_code, country="Netherlands") -> OperationResult[Dict[str, Any]]:
    """Validate postal code format and suggest chapters (legacy endpoint)"""
    return validate_postal_code(postal_code, country)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_phone_number(phone, country="Netherlands") -> OperationResult[Dict[str, Any]]:
    """Validate phone number format"""
    return _wrap_validation(
        lambda: validate_phone_number_util(phone, country),
        field_name="Phone number",
        operation="validate_phone_number",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_phone_number_endpoint(phone, country="Netherlands") -> OperationResult[Dict[str, Any]]:
    """Validate phone number format (legacy endpoint)"""
    return validate_phone_number(phone, country)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_birth_date(birth_date) -> OperationResult[Dict[str, Any]]:
    """Validate birth date"""
    return _wrap_validation(
        lambda: validate_birth_date_util(birth_date),
        field_name="Birth date",
        operation="validate_birth_date",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_birth_date_endpoint(birth_date) -> OperationResult[Dict[str, Any]]:
    """Validate birth date (legacy endpoint)"""
    return validate_birth_date(birth_date)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_name(name, field_name="Name") -> OperationResult[Dict[str, Any]]:
    """Validate name fields"""
    return _wrap_validation(
        lambda: validate_name_util(name, field_name),
        field_name=field_name,
        operation="validate_name",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_name_endpoint(name, field_name="Name") -> OperationResult[Dict[str, Any]]:
    """Validate name fields (legacy endpoint)"""
    return validate_name(name, field_name)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def check_application_eligibility_endpoint(data) -> OperationResult[Dict[str, Any]]:
    """Check if applicant is eligible for membership"""
    try:
        parsed_data = parse_application_data(data)
        result = check_application_eligibility_util(parsed_data)
        if result.get("eligible"):
            return OperationResult.ok(result, message=_("Applicant is eligible for membership"))
        else:
            return OperationResult.fail(
                _("Applicant is not eligible for membership"),
                errors=result.get("issues", []),
                context={"warnings": result.get("warnings", [])},
            )
    except Exception as e:
        frappe.log_error(
            f"Eligibility check error: {str(e)}\n{traceback.format_exc()}", "Eligibility Check Error"
        )
        return OperationResult.fail(
            _("Eligibility check failed"),
            errors=[str(e)],
            context={"operation": "check_application_eligibility"},
        )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
@handle_api_error
@performance_monitor(threshold_ms=3000)
def submit_application(**kwargs) -> OperationResult[Dict[str, Any]]:
    """Process membership application submission - Main entry point

    Delegates to private helpers:
    - _handle_existing_member: reapplication scenario routing
    - _validate_membership_amount: custom amount validation
    - _save_suggested_chapter: chapter save with timestamp retry
    """
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
            return OperationResult.fail(
                _("Missing required fields: {0}").format(", ".join(validation_result["missing_fields"])),
                errors=validation_result["missing_fields"],
                context={"operation": "submit_application", "type": "validation_error"},
            )

        # Check eligibility
        eligibility = check_application_eligibility_util(data)
        if not eligibility["eligible"]:
            # Log detailed validation failure for debugging
            frappe.log_error(
                title="Application Eligibility Failed",
                message=f"Email: {data.get('email')}\nIssues: {'; '.join(eligibility['issues'])}",
            )
            return OperationResult.fail(
                _("Validation failed: {0}").format("; ".join(eligibility["issues"])),
                errors=eligibility["issues"],
                context={
                    "warnings": eligibility.get("warnings", []),
                    "operation": "submit_application",
                },
            )

        # Check if member with email already exists and handle reapplication scenarios
        existing_member = frappe.db.get_value(
            "Member",
            {"email": data.get("email")},
            ["name", "status", "application_status"],
            as_dict=True,
        )

        if existing_member:
            action, error = _handle_existing_member(existing_member, data)
            if error:
                return error

        # Validate membership amount if custom amount is provided
        amount_error = _validate_membership_amount(data)
        if amount_error:
            return amount_error

        # Generate application ID
        application_id = generate_application_id()

        # Create address
        address = None
        try:
            address = create_address_from_application(data)
        except Exception as e:
            frappe.log_error(
                f"Failed to create address for application {application_id}: {str(e)}\n{traceback.format_exc()}",
                "Address Creation Error",
            )
            # Continue without address - not critical for member creation

        # Create or update member
        try:
            # If we're reapplicating (existing_member set from earlier check), update existing record
            if existing_member:
                member = update_member_from_reapplication(existing_member.name, data, application_id, address)
            else:
                # New application - create fresh member record
                member = create_member_from_application(data, application_id, address)
        except Exception as e:
            frappe.log_error(
                f"Failed to create/update member record for application {application_id}: {str(e)}\n{traceback.format_exc()}\nData: {json.dumps(data, default=str)}",
                "Member Creation Error",
            )
            raise  # Re-raise since this is critical

        # Determine suggested chapter
        suggested_chapter = determine_chapter_from_application(data)
        if suggested_chapter:
            _save_suggested_chapter(member, suggested_chapter, application_id)

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

        # Notifications are now handled via Frappe's native Notification system:
        # - "New Membership Application Submitted" notifies administrators
        # - "Member Application Approved/Rejected" notifies applicant on status change

        return OperationResult.ok(
            {
                "application_id": application_id,
                "applicant_id": getattr(member, "application_id", None),
                "member_record": member.name,
                "status": "pending_review",
            },
            message=_(
                "Application submitted successfully! You will receive an email with your application ID."
            ),
        )

    except Exception as e:
        frappe.db.rollback()

        # Get full error details
        error_msg = str(e)
        full_traceback = traceback.format_exc()

        frappe.log_error(
            f"Error in submit_application: {error_msg}\n\nFull traceback:\n{full_traceback}",
            "Application Submission Error",
        )

        return OperationResult.fail(
            _("Application submission failed: {0}").format(error_msg),
            errors=[error_msg],
            context={
                "type": "server_error",
                "timestamp": frappe.utils.now(),
                "operation": "submit_application",
            },
        )


def _handle_existing_member(existing_member, data):
    """Handle all existing-member reapplication scenarios.

    Returns (action, error_result) where:
    - action is "update" if reapplication is allowed, None if blocked
    - error_result is None if allowed, or an OperationResult to return immediately
    """
    member_name = existing_member.name
    status = existing_member.status
    app_status = existing_member.application_status

    # Scenario 1: Rejected application - allow reapplication
    if app_status == "Rejected":
        frappe.logger().info(f"Reapplication detected for rejected member {member_name}")
        return "update", None

    # Scenario 2: Pending application - update existing pending application
    if app_status == "Pending":
        frappe.logger().info(f"Update to pending application {member_name}")
        return "update", None

    # Scenario 3: Terminated member - check termination type
    if status == "Terminated":
        termination_result = frappe.db.get_value(
            "Membership Termination Request",
            {"member": member_name, "status": "Executed"},
            ["termination_type"],
            order_by="execution_date desc",
        )

        if not termination_result:
            frappe.log_error(
                f"Member {member_name} has Terminated status but no executed termination request found",
                "Termination Data Integrity",
            )
            return None, OperationResult.fail(
                _("Please contact us to clarify your membership status before reapplying."),
                errors=["termination_status_unclear"],
                context={"requires_contact": True, "operation": "submit_application"},
            )

        if termination_result == "Voluntary":
            frappe.logger().info(f"Voluntary termination reapplication for {member_name}")
            return "update", None

        frappe.logger().warning(
            f"Reapplication blocked for {member_name} - involuntary termination: {termination_result}"
        )
        return None, OperationResult.fail(
            _(
                "Your previous membership was terminated for reasons that require direct contact with our organization. "
                "Please email us to discuss rejoining."
            ),
            errors=["involuntary_termination"],
            context={
                "requires_contact": True,
                "termination_type": termination_result,
                "operation": "submit_application",
            },
        )

    # Scenario 4: Active member - cannot reapply
    if status == "Active":
        return None, OperationResult.fail(
            _("You are already an active member. Please login to manage your membership."),
            errors=["already_active_member"],
            context={"member_exists": True, "operation": "submit_application"},
        )

    # Unknown status - block with contact message
    return None, OperationResult.fail(
        _("A membership record with this email already exists. Please contact us for assistance."),
        errors=["membership_record_exists"],
        context={"operation": "submit_application"},
    )


def _validate_membership_amount(data):
    """Validate membership amount if custom amount is provided.

    Returns None if valid (or not applicable), or an OperationResult.fail() if invalid.
    """
    if not (data.get("membership_amount") or data.get("uses_custom_amount")):
        return None

    membership_type = data.get("selected_membership_type")
    custom_contribution_fee = data.get("custom_contribution_fee")
    uses_custom = data.get("uses_custom_amount", False)

    if not (membership_type and custom_contribution_fee):
        return None

    amount_validation = validate_custom_amount_util(membership_type, custom_contribution_fee)
    if not amount_validation["valid"]:
        frappe.log_error(
            f"Custom amount validation failed for application: {amount_validation['message']}",
            "Custom Amount Validation Failed",
        )
        return OperationResult.fail(
            _(amount_validation["message"]),
            errors=["invalid_custom_amount"],
            context={"type": "validation_error", "operation": "submit_application"},
        )

    selection_validation = validate_membership_amount_selection(
        membership_type, custom_contribution_fee, uses_custom
    )
    if not selection_validation["valid"]:
        frappe.log_error(
            f"Membership amount selection validation failed for application: {selection_validation['message']}",
            "Amount Selection Validation Failed",
        )
        return OperationResult.fail(
            _(selection_validation["message"]),
            errors=["invalid_amount_selection"],
            context={"type": "validation_error", "operation": "submit_application"},
        )

    return None


def _save_suggested_chapter(member, suggested_chapter, application_id):
    """Set suggested chapter on member and save with retry on timestamp mismatch.

    Fire-and-forget: logs errors but does not raise.
    """
    if hasattr(member, "suggested_chapter"):
        member.suggested_chapter = suggested_chapter
    else:
        member.current_chapter_display = suggested_chapter

    from verenigingen.utils.secure_operations import (
        get_system_user_for_operation,
        secure_user_context,
    )

    system_user = get_system_user_for_operation("member_update_during_application")
    with secure_user_context(system_user, f"Update suggested chapter for application {application_id}"):
        try:
            member.save()
        except frappe.TimestampMismatchError:
            member.reload()
            if hasattr(member, "suggested_chapter"):
                member.suggested_chapter = suggested_chapter
            else:
                member.current_chapter_display = suggested_chapter
            member.save()


@frappe.whitelist()
@high_security_api()  # Member application approval
@handle_api_error
@performance_monitor(threshold_ms=2000)
@require_roles(["System Manager", "Verenigingen Administrator", "Verenigingen Staff"])
def approve_membership_application(member_name, notes=None) -> OperationResult[Dict[str, Any]]:
    """
    DEPRECATED: Use verenigingen.api.membership_application_review.approve_membership_application instead.

    This function redirects to the canonical implementation for backward compatibility.
    Will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "verenigingen.api.membership_application.approve_membership_application is deprecated. "
        "Use verenigingen.api.membership_application_review.approve_membership_application instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Redirect to canonical implementation
    from verenigingen.api.membership_application_review import (
        approve_membership_application as canonical_approve,
    )

    # Call canonical function with compatible parameters
    # Note: This doesn't pass membership_type or chapter, assuming defaults
    result = canonical_approve(member_name=member_name, notes=notes, create_invoice=True)

    # If result is already OperationResult, return it directly
    # If it's a dict (legacy format), wrap it
    if isinstance(result, OperationResult):
        return result
    elif isinstance(result, dict):
        if result.get("success"):
            return OperationResult.ok(
                result, message=_(result.get("message", "Application approved successfully"))
            )
        else:
            return OperationResult.fail(
                _(result.get("message", "Application approval failed")),
                errors=[result.get("error", "approval_failed")],
                context=result,
            )
    else:
        return OperationResult.fail(
            _("Unexpected response from approval function"),
            errors=["unexpected_response"],
            context={"operation": "approve_membership_application"},
        )


@frappe.whitelist()
@high_security_api()  # Member application rejection
def reject_membership_application(member_name, reason) -> OperationResult[Dict[str, Any]]:
    """Reject a membership application"""
    try:
        member = frappe.get_doc("Member", member_name)

        if member.application_status not in ["Pending", "Under Review"]:
            return OperationResult.fail(
                _("This application cannot be rejected in its current state"),
                errors=["invalid_application_status"],
                context={
                    "current_status": member.application_status,
                    "operation": "reject_membership_application",
                },
            )

        # Use the new reject_application method which handles chapter membership cleanup
        member.reject_application(reason)

        # Send rejection notification using modern EmailService
        send_rejection_notification(member, reason)

        return OperationResult.ok(
            {
                "member_id": member_name,
                "status": "Rejected",
            },
            message=_("Application rejected, pending chapter membership removed, and notification sent"),
        )

    except Exception as e:
        frappe.log_error(
            f"Error rejecting application: {str(e)}\n{traceback.format_exc()}",
            "Application Rejection Error",
        )
        return OperationResult.fail(
            _("Error rejecting application"),
            errors=[str(e)],
            context={"operation": "reject_membership_application"},
        )


@frappe.whitelist()
@high_security_api()  # Payment processing
def process_application_payment_endpoint(
    member_name, payment_method, payment_reference=None
) -> OperationResult[Dict[str, Any]]:
    """Process payment for approved application"""
    try:
        payment_entry = process_application_payment(member_name, payment_method, payment_reference)

        # Send payment confirmation notification (failure must not affect payment result)
        member = frappe.get_doc("Member", member_name)

        try:
            if member.email:
                from verenigingen.services.communication.email_service import get_email_service

                email_service = get_email_service()
                membership_type = getattr(member, "selected_membership_type", "") or ""
                portal_url = frappe.utils.get_url("/member-dashboard")

                email_service.send_templated_email(
                    template_name="member_lifecycle_notification",
                    recipients=[member.email],
                    context={
                        "member_name": member.full_name,
                        "old_status": None,
                        "new_status": "Active",
                        "membership_number": member.name,
                        "additional_message": _(
                            "Thank you for your payment! Your {0} membership is now active. "
                            "Visit {1} to access the member portal."
                        ).format(membership_type, portal_url),
                        "company": frappe.defaults.get_global_default("company"),
                    },
                    subject_override=_("Welcome! Your membership is active"),
                    reference_doctype="Member",
                    reference_name=member.name,
                    notification_key="member_activated",
                )
        except Exception as e:
            frappe.log_error(
                f"Error sending payment confirmation email for {member_name}: {str(e)}",
                "Payment Confirmation Email Error",
            )

        return OperationResult.ok(
            {
                "payment_entry": payment_entry.name,
                "member_id": member_name,
            },
            message=_("Payment processed successfully"),
        )

    except Exception as e:
        frappe.log_error(
            f"Error processing payment: {str(e)}\n{traceback.format_exc()}",
            "Payment Processing Error",
        )
        return OperationResult.fail(
            _("Error processing payment"),
            errors=[str(e)],
            context={"operation": "process_application_payment"},
        )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_membership_fee_info_endpoint(membership_type) -> OperationResult[Dict[str, Any]]:
    """Get membership fee information"""
    return _wrap_data_fetch(
        lambda: get_membership_fee_info_util(membership_type),
        success_message="Membership fee information retrieved",
        error_message="Error retrieving membership fee information",
        operation="get_membership_fee_info",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def get_membership_type_details_endpoint(membership_type) -> OperationResult[Dict[str, Any]]:
    """Get detailed membership type information"""
    return _wrap_data_fetch(
        lambda: get_membership_type_details_util(membership_type),
        success_message="Membership type details retrieved",
        error_message="Error retrieving membership type details",
        operation="get_membership_type_details",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def suggest_membership_amounts_endpoint(membership_type_name) -> OperationResult[Dict[str, Any]]:
    """Suggest membership amounts based on type"""
    return _wrap_data_fetch(
        lambda: suggest_membership_amounts_util(membership_type_name),
        success_message="Membership amount suggestions retrieved",
        error_message="Error suggesting membership amounts",
        operation="suggest_membership_amounts",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_membership_amount_selection_endpoint(
    membership_type, amount, uses_custom
) -> OperationResult[Dict[str, Any]]:
    """Validate membership amount selection"""
    return _wrap_validation(
        lambda: validate_membership_amount_selection(membership_type, amount, uses_custom),
        field_name="Membership amount selection",
        operation="validate_membership_amount_selection",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_custom_amount_endpoint(membership_type, amount) -> OperationResult[Dict[str, Any]]:
    """Validate custom membership amount"""
    return _wrap_validation(
        lambda: validate_custom_amount_util(membership_type, amount),
        field_name="Custom amount",
        operation="validate_custom_amount",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_payment_methods_endpoint() -> OperationResult[Dict[str, Any]]:
    """Get available payment methods"""
    return _wrap_data_fetch(
        get_payment_methods_util,
        success_message="Payment methods retrieved",
        error_message="Error retrieving payment methods",
        operation="get_payment_methods",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def save_draft_application_endpoint(data) -> OperationResult[Dict[str, Any]]:
    """Save application as draft"""
    return _wrap_success_check(
        lambda: save_draft_application_util(parse_application_data(data)),
        success_message="Draft application saved successfully",
        fail_message="Failed to save draft application",
        fail_error="save_failed",
        operation="save_draft_application",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def load_draft_application_endpoint(draft_id) -> OperationResult[Dict[str, Any]]:
    """Load application draft"""
    return _wrap_success_check(
        lambda: load_draft_application_util(draft_id),
        success_message="Draft application loaded successfully",
        fail_message="Failed to load draft application",
        fail_error="load_failed",
        operation="load_draft_application",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def get_member_field_info_endpoint() -> OperationResult[Dict[str, Any]]:
    """Get information about member fields for form generation"""
    return _wrap_data_fetch(
        get_member_field_info,
        success_message="Member field information retrieved",
        error_message="Error retrieving member field information",
        operation="get_member_field_info",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def check_application_status_endpoint(application_id) -> OperationResult[Dict[str, Any]]:
    """Check the status of an application by ID"""
    return _wrap_success_check(
        lambda: check_application_status_util(application_id),
        success_message="Application status retrieved",
        fail_message="Failed to retrieve application status",
        fail_error="status_check_failed",
        operation="check_application_status",
    )


# Scheduled tasks


def check_overdue_applications_task():
    """Scheduled task to check for overdue applications"""
    check_overdue_applications()


# Test endpoints


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def test_submit() -> OperationResult[Dict[str, Any]]:
    """Simple test submission function"""
    return OperationResult.ok(
        {"timestamp": frappe.utils.now()},
        message=_("Test submission working"),
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def debug_member_issue(member_name="Assoc-Member-2025-06-0091") -> OperationResult[Dict[str, Any]]:
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

        return OperationResult.ok(result, message=_("Member debug information retrieved"))

    except Exception as e:
        frappe.log_error(
            f"Error debugging member issue: {str(e)}\n{traceback.format_exc()}",
            "Member Debug Error",
        )
        return OperationResult.fail(
            _("Error debugging member issue"),
            errors=[str(e)],
            context={"operation": "debug_member_issue"},
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def fix_specific_member(member_name, chapter_name=None, dry_run=True) -> OperationResult[Dict[str, Any]]:
    """
    Fix chapter membership for a specific member

    Args:
        member_name (str): Member ID to fix
        chapter_name (str): Chapter to assign (optional, will try to determine if not provided)
        dry_run (bool): If True, only analyze without fixing

    Returns:
        OperationResult: Results of the operation
    """
    results = {"member": member_name, "fixed": False, "dry_run": dry_run}

    try:
        # Get member
        if not frappe.db.exists("Member", member_name):
            return OperationResult.fail(
                _("Member {0} does not exist").format(member_name),
                errors=["member_not_found"],
                context={"operation": "fix_specific_member"},
            )

        member = frappe.get_doc("Member", member_name)

        # Check if member already has chapter memberships
        existing_chapters = frappe.get_all(
            "Chapter Member", filters={"member": member_name}, fields=["parent", "status"]
        )

        if existing_chapters:
            return OperationResult.fail(
                _("Member {0} already has chapter memberships: {1}").format(
                    member_name, [ch["parent"] for ch in existing_chapters]
                ),
                errors=["chapter_membership_exists"],
                context={"existing_chapters": existing_chapters, "operation": "fix_specific_member"},
            )

        # Determine chapter if not provided
        if not chapter_name:
            # Note: suggested_chapter field was planned but never implemented
            # Use current_chapter_display which shows current chapter membership
            if hasattr(member, "current_chapter_display") and member.current_chapter_display:
                chapter_name = member.current_chapter_display
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
            return OperationResult.fail(
                _("No chapter could be determined for member {0}").format(member_name),
                errors=["chapter_not_determined"],
                context={"operation": "fix_specific_member"},
            )

        # Verify chapter exists
        if not frappe.db.exists("Chapter", chapter_name):
            return OperationResult.fail(
                _("Chapter '{0}' does not exist").format(chapter_name),
                errors=["chapter_not_found"],
                context={"operation": "fix_specific_member"},
            )

        results["proposed_chapter"] = chapter_name

        if not dry_run:
            # Create the chapter membership
            from verenigingen.utils.application_helpers import create_active_chapter_membership

            chapter_member = create_active_chapter_membership(member, chapter_name)

            if chapter_member:
                results["fixed"] = True
                results["action"] = f"Created active chapter membership for {member_name} in {chapter_name}"
                return OperationResult.ok(results, message=_("Chapter membership created successfully"))
            else:
                return OperationResult.fail(
                    _("Failed to create chapter membership for {0} in {1}").format(member_name, chapter_name),
                    errors=["chapter_membership_creation_failed"],
                    context=results,
                )
        else:
            results["action"] = f"Would create active chapter membership for {member_name} in {chapter_name}"
            return OperationResult.ok(results, message=_("Dry run completed - no changes made"))

    except Exception as e:
        frappe.log_error(
            f"Error fixing specific member: {str(e)}\n{traceback.format_exc()}",
            "Fix Member Error",
        )
        return OperationResult.fail(
            _("Error fixing member chapter membership"),
            errors=[str(e)],
            context={"operation": "fix_specific_member"},
        )


# Legacy endpoints for backward compatibility


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def validate_custom_amount(membership_type, amount) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - validate custom membership amount"""
    return validate_custom_amount_endpoint(membership_type, amount)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def save_draft_application(data) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - save application as draft"""
    return save_draft_application_endpoint(data)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def load_draft_application(draft_id) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - load application draft"""
    return load_draft_application_endpoint(draft_id)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def get_membership_type_details(membership_type) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - get detailed membership type information"""
    return get_membership_type_details_endpoint(membership_type)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def get_membership_fee_info(membership_type) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - get membership fee information"""
    return get_membership_fee_info_endpoint(membership_type)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def suggest_membership_amounts(membership_type_name) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - suggest membership amounts based on type"""
    return suggest_membership_amounts_endpoint(membership_type_name)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def get_payment_methods() -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - get available payment methods"""
    return get_payment_methods_endpoint()


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def check_application_status(application_id) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - check the status of an application by ID"""
    return check_application_status_endpoint(application_id)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def submit_application_with_tracking(**kwargs) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - same as submit_application"""
    return submit_application(**kwargs)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def check_application_eligibility(data) -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - check if applicant is eligible for membership"""
    return check_application_eligibility_endpoint(data)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def get_application_form_data_legacy() -> OperationResult[Dict[str, Any]]:
    """Legacy endpoint - use get_application_form_data instead"""
    return get_application_form_data()


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_address_endpoint(data) -> OperationResult[Dict[str, Any]]:
    """Validate address data"""
    return _wrap_validation(
        lambda: validate_address_util(parse_application_data(data)),
        field_name="Address",
        operation="validate_address",
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def suggest_chapters_for_postal_code(postal_code) -> OperationResult[Dict[str, Any]]:
    """Suggest chapters based on postal code.

    Delegates to private helpers:
    - _match_chapter_postal_codes: postal range matching
    - _match_chapter_region_heuristic: regional fallback matching

    Args:
        postal_code (str): Postal code to search for

    Returns:
        OperationResult: List of suggested chapters with relevance scores
    """
    # Validate input
    if not postal_code:
        return OperationResult.fail(
            _("Postal code is required"),
            errors=["postal_code_required"],
            context={"operation": "suggest_chapters_for_postal_code"},
        )

    # Clean and normalize postal code
    postal_code = str(postal_code).strip().upper()

    # Basic Dutch postal code validation (NNNNAA format)
    import re

    if not re.match(r"^\d{4}[A-Z]{2}$", postal_code):
        return OperationResult.fail(
            _("Invalid postal code format. Expected format: 1234AB"),
            errors=["invalid_postal_code_format"],
            context={"postal_code": postal_code, "operation": "suggest_chapters_for_postal_code"},
        )

    try:
        postal_numeric = int(postal_code[:4])

        chapters = frappe.get_all(
            "Chapter",
            filters={"published": 1},
            fields=["name", "region", "postal_codes", "introduction", "address"],
        )

        suggestions = []

        for chapter in chapters:
            score, match_type = 0, None

            if chapter.postal_codes:
                score, match_type = _match_chapter_postal_codes(
                    chapter.postal_codes, postal_numeric, postal_code
                )

            if score == 0:
                score, match_type = _match_chapter_region_heuristic(
                    chapter.name, chapter.region, postal_numeric
                )

            if score > 0:
                suggestions.append(
                    {
                        "name": chapter.name,
                        "chapter_name": chapter.name,
                        "region": chapter.region,
                        "address": chapter.address,
                        "introduction": chapter.introduction,
                        "relevance_score": score,
                        "match_type": match_type,
                        "postal_code_ranges": chapter.postal_codes,
                    }
                )

        suggestions.sort(key=lambda x: x["relevance_score"], reverse=True)
        suggestions = suggestions[:5]

        return OperationResult.ok(
            {
                "postal_code": postal_code,
                "suggestions": suggestions,
                "total_suggestions": len(suggestions),
            },
            message=_("Found {0} chapter suggestions").format(len(suggestions)),
        )

    except Exception as e:
        frappe.log_error(
            f"Error suggesting chapters for postal code {postal_code}: {str(e)}\n{traceback.format_exc()}",
            "Chapter Suggestion Error",
        )
        return OperationResult.fail(
            _("Error processing postal code"),
            errors=[str(e)],
            context={"postal_code": postal_code, "operation": "suggest_chapters_for_postal_code"},
        )


def _match_chapter_postal_codes(chapter_postal_codes, postal_numeric, postal_code):
    """Parse postal_codes field (comma-separated ranges) and check for match.

    Pure function — no database access, no side effects.

    Returns (relevance_score, match_type).
    """
    postal_ranges = chapter_postal_codes.replace(" ", "").split(",")

    for range_str in postal_ranges:
        if "-" in range_str:
            try:
                start, end = range_str.split("-")
                start_num = int(start)
                end_num = int(end)
                if start_num <= postal_numeric <= end_num:
                    return 100, "postal_range"
            except ValueError:
                continue
        else:
            try:
                if range_str == postal_code[:4]:
                    return 90, "postal_prefix"
                if range_str == postal_code:
                    return 100, "postal_exact"
            except ValueError:
                continue

    return 0, None


def _match_chapter_region_heuristic(chapter_name, region, postal_numeric):
    """Fallback regional guessing based on postal numeric ranges and chapter/region names.

    Pure function — no database access, no side effects.

    Returns (relevance_score, match_type).
    """
    chapter_name_lower = chapter_name.lower() if chapter_name else ""
    region_lower = region.lower() if region else ""

    if postal_numeric < 2000:
        if "amsterdam" in chapter_name_lower or "noord-holland" in region_lower:
            return 30, "region_guess"
    elif postal_numeric < 3000:
        if "den haag" in chapter_name_lower or "zuid-holland" in region_lower:
            return 30, "region_guess"
    elif postal_numeric < 4000:
        if "rotterdam" in chapter_name_lower or "zuid-holland" in region_lower:
            return 30, "region_guess"

    return 0, None
