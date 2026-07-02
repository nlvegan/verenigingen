"""
Volunteer Expense Portal Page

Main portal for volunteers to submit and track expenses.
Uses centralized utilities from volunteer_expense_portal_utils.py.

URL: /volunteer/expenses
"""

import frappe
from frappe import _

from verenigingen.services.volunteer.expense_submission_service import get_expense_submission_service

# Import centralized utilities
from verenigingen.services.volunteer.volunteer_expense_portal_utils import (
    build_base_expense_context,
    get_approval_thresholds,
    get_expense_categories,
    get_volunteer_expense_statistics,
    get_volunteer_expenses_from_claims,
    get_volunteer_organizations,
    map_erpnext_status_to_volunteer_status,
    validate_expense_data,
)
from verenigingen.utils.member_utils import get_member_name_for_user, get_volunteer_for_current_user
from verenigingen.utils.security.api_security_framework import (
    high_security_api,
    self_service_api,
    standard_api,
)
from verenigingen.utils.security.types import OperationType


def get_context(context):
    """Get context for volunteer expense portal page."""
    context.title = _("Volunteer Expenses")
    return build_base_expense_context(context)


# =============================================================================
# Admin API Endpoints
# =============================================================================


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_volunteer_for_member(member_name: str):
    """Create a volunteer record for an existing member (admin function)."""
    if not frappe.has_permission("Volunteer", "create"):
        frappe.throw(_("Insufficient permissions to create volunteer records"))

    # Get member details
    member = frappe.get_doc("Member", member_name)

    # Check if volunteer already exists
    existing_volunteer = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
    if existing_volunteer:
        frappe.throw(
            _("Volunteer record already exists for member {0}: {1}").format(member_name, existing_volunteer)
        )

    # Create volunteer record
    volunteer = frappe.get_doc(
        {
            "doctype": "Volunteer",
            "volunteer_name": f"{member.first_name} {member.last_name}",
            "email": member.email,
            "member": member.name,
            "status": "Active",
            "start_date": frappe.utils.today(),
        }
    )

    volunteer.insert()

    return {
        "success": True,
        "volunteer_name": volunteer.name,
        "message": _("Volunteer record created successfully for {0}").format(member.full_name),
    }


# =============================================================================
# File Upload API
# =============================================================================


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def upload_expense_receipt():
    """Upload receipt file and return file data for later attachment."""
    try:
        # Enhanced debugging - check all possible file access methods
        debug_info = {
            "request_exists": hasattr(frappe, "request"),
            "files_attr": hasattr(frappe.request, "files") if hasattr(frappe, "request") else False,
            "files_content": (
                dict(frappe.request.files)
                if hasattr(frappe, "request") and hasattr(frappe.request, "files")
                else {}
            ),
            "files_keys": (
                list(frappe.request.files.keys())
                if hasattr(frappe, "request") and hasattr(frappe.request, "files")
                else []
            ),
            "form_dict": dict(frappe.form_dict) if hasattr(frappe, "form_dict") else {},
            "form_dict_keys": list(frappe.form_dict.keys()) if hasattr(frappe, "form_dict") else [],
            "local_files": getattr(frappe.local, "uploaded_files", None),
            "request_method": frappe.request.method if hasattr(frappe, "request") else None,
            "request_content_type": frappe.request.content_type if hasattr(frappe, "request") else None,
            "request_data": (
                len(frappe.request.data)
                if hasattr(frappe, "request") and hasattr(frappe.request, "data")
                else 0
            ),
        }

        # Try multiple methods to access uploaded files
        uploaded_file = None

        # Method 1: Direct from request.files
        if hasattr(frappe, "request") and hasattr(frappe.request, "files") and frappe.request.files:
            if "receipt" in frappe.request.files:
                uploaded_file = frappe.request.files["receipt"]

        # Method 2: From form_dict (common in Frappe)
        if not uploaded_file and hasattr(frappe, "form_dict"):
            for field_name in ["receipt", "file", "_file", "uploaded_file"]:
                if field_name in frappe.form_dict:
                    uploaded_file = frappe.form_dict[field_name]
                    break

        # Method 3: From local.uploaded_files (Frappe's internal storage)
        if not uploaded_file and hasattr(frappe.local, "uploaded_files") and frappe.local.uploaded_files:
            uploaded_file = list(frappe.local.uploaded_files.values())[0]

        if not uploaded_file:
            return {"success": False, "error": "No file uploaded", "debug_info": debug_info}

        # Handle different file object types
        if hasattr(uploaded_file, "filename") and hasattr(uploaded_file, "read"):
            filename = uploaded_file.filename
            if not filename:
                return {"success": False, "error": "No filename provided"}

            file_content = uploaded_file.read()
            content_type = getattr(uploaded_file, "content_type", "application/octet-stream")

        elif isinstance(uploaded_file, dict) and "filename" in uploaded_file:
            filename = uploaded_file["filename"]
            file_content = uploaded_file.get("content", b"")
            content_type = uploaded_file.get("content_type", "application/octet-stream")

        else:
            return {
                "success": False,
                "error": f"Unsupported file object type: {type(uploaded_file)}",
                "debug_info": debug_info,
            }

        if not file_content:
            return {"success": False, "error": "Empty file uploaded"}

        import base64

        return {
            "success": True,
            "file_name": filename,
            "file_content": base64.b64encode(file_content).decode("utf-8"),
            "content_type": content_type,
        }

    except Exception as e:
        import traceback

        frappe.log_error(
            f"Error uploading expense receipt: {str(e)}\n{traceback.format_exc()}",
            "File Upload Error",
        )
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# =============================================================================
# Expense Submission API
# =============================================================================


@frappe.whitelist()
@standard_api(
    operation_type=OperationType.REPORTING,
    self_service_only=True,
    self_service_implicit_allowed=True,
)
def submit_expense(expense_data=None, additional_expenses=None):
    """Submit a new expense from the portal.

    Args:
        expense_data: Primary expense data (required fields for the claim)
        additional_expenses: Optional list of additional expense lines

    Returns:
        dict: Result with success status and expense claim details
    """
    # Handle JSON request body
    if expense_data is None:
        import json

        request_data = json.loads(frappe.request.data.decode("utf-8"))
        expense_data = request_data.get("expense_data")
        additional_expenses = request_data.get("additional_expenses")

    # Parse JSON string if needed (fallback for form submissions)
    if isinstance(expense_data, str):
        import html
        import json

        decoded_data = html.unescape(expense_data)
        expense_data = json.loads(decoded_data)

    # Delegate to service
    service = get_expense_submission_service()
    result = service.submit_expense(expense_data, additional_expenses)

    # Convert OperationResult to dict for API response
    if result.success:
        return {
            "success": True,
            "message": result.metadata.get("message", "Expense claim saved successfully"),
            "expense_claim_name": result.metadata.get("expense_claim_name"),
            "employee_created": result.metadata.get("employee_created", False),
        }
    else:
        return {
            "success": False,
            "message": result.error_message,
            "errors": result.errors,
        }


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def submit_multiple_expenses(expenses):
    """Submit multiple expenses from the portal at once.

    Groups expenses by organization for efficient processing.
    """
    try:
        if frappe.session.user == "Guest":
            return {"success": False, "message": _("Please log in to submit expenses")}

        # Parse JSON string if needed
        if isinstance(expenses, str):
            import json

            expenses = json.loads(expenses)

        # Use service for grouped submission
        service = get_expense_submission_service()
        result = service.submit_multiple_expenses_grouped(expenses)

        # Convert OperationResult to dict
        if result.success:
            return {
                "success": True,
                "message": result.metadata.get("message"),
                "created_count": result.metadata.get("created_count", 0),
                "claim_count": result.metadata.get("claim_count", 0),
                "created_claims": result.metadata.get("created_claims", []),
                "partial": result.metadata.get("partial", False),
                "errors": result.metadata.get("errors", []),
            }
        else:
            return {
                "success": False,
                "message": result.error_message,
                "errors": result.errors,
            }

    except Exception as e:
        import traceback

        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}


# =============================================================================
# Data Retrieval API
# =============================================================================


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_organization_options(organization_type: str, volunteer_name: str | None = None):
    """Get organization options for the current volunteer."""
    if not volunteer_name:
        volunteer_name = get_volunteer_for_current_user()
        if not volunteer_name:
            return {"success": False, "message": _("No volunteer record found")}
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer:
            return []
        volunteer_name = volunteer.name

    organizations = get_volunteer_organizations(volunteer_name)

    if organization_type == "Chapter":
        return [{"value": ch["name"], "label": ch["chapter_name"]} for ch in organizations["chapters"]]
    elif organization_type == "Team":
        return [{"value": t["name"], "label": t["team_name"]} for t in organizations["teams"]]

    return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_expense_details(expense_name: str):
    """Get details for a specific expense from ERPNext or legacy records."""
    volunteer_name = get_volunteer_for_current_user()
    if not volunteer_name:
        return {"success": False, "message": _("No volunteer record found")}
    volunteer = frappe.get_doc("Volunteer", volunteer_name)
    if not volunteer:
        frappe.throw(_("Access denied"))

    try:
        # Check if this is an ERPNext Expense Claim reference
        if "-" in expense_name:
            claim_name = expense_name.split("-")[0]

            # Verify this is an ERPNext Expense Claim for this volunteer
            volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)
            if volunteer_doc.employee_id:
                expense_claim = frappe.get_doc("Expense Claim", claim_name)
                if expense_claim.employee != volunteer_doc.employee_id:
                    frappe.throw(_("Access denied"))

                # Get expense details from ERPNext
                expense_details = frappe.get_all(
                    "Expense Claim Detail",
                    filters={"parent": claim_name},
                    fields=["expense_type", "description", "amount", "expense_date"],
                    order_by="idx",
                )

                # Get linked Volunteer Expense record for organization info.
                # Volunteer Expense was archived; the DocType + table are dropped
                # by patches/v2_2/drop_volunteer_expense_archived_doctype.py on
                # migrated sites. Guard the query so post-migration sites don't
                # hit "Unknown table" SQL errors.
                volunteer_expense = None
                if frappe.db.exists("DocType", "Volunteer Expense"):
                    volunteer_expense = frappe.db.get_value(
                        "Volunteer Expense",
                        {"expense_claim_id": claim_name},
                        ["organization_type", "chapter", "team", "category"],
                        as_dict=True,
                    )

                if expense_details:
                    detail = expense_details[0]
                    expense_dict = {
                        "name": expense_name,
                        "expense_claim_id": claim_name,
                        "description": detail.description,
                        "amount": detail.amount,
                        "expense_date": detail.expense_date,
                        "status": map_erpnext_status_to_volunteer_status(
                            expense_claim.status, expense_claim.approval_status
                        ),
                        "organization_type": (
                            volunteer_expense.organization_type if volunteer_expense else "Unknown"
                        ),
                        "chapter": volunteer_expense.chapter if volunteer_expense else None,
                        "team": volunteer_expense.team if volunteer_expense else None,
                        "category": volunteer_expense.category if volunteer_expense else detail.expense_type,
                    }

                    # Add category name
                    if expense_dict.get("category"):
                        expense_dict["category_name"] = (
                            frappe.db.get_value("Expense Category", expense_dict["category"], "category_name")
                            or frappe.db.get_value(
                                "Expense Claim Type", expense_dict["category"], "expense_type"
                            )
                            or expense_dict["category"]
                        )

                    # Add organization name
                    organization_name = expense_dict.get("chapter")
                    if not organization_name:
                        organization_name = expense_dict.get("team")
                    if not organization_name:
                        organization_name = "Unknown"
                    expense_dict["organization_name"] = organization_name

                    # Add attachment count
                    expense_dict["attachment_count"] = frappe.db.count(
                        "File", {"attached_to_name": claim_name, "attached_to_doctype": "Expense Claim"}
                    )

                    return expense_dict
                else:
                    frappe.throw(_("Expense details not found"))
            else:
                frappe.throw(_("Access denied - no employee record"))
        else:
            # Legacy Volunteer Expense branch was always unreachable: the routing
            # condition above tests for "-" in the name, and Volunteer Expense
            # records used autoname `VE-{YYYY}-{MM}-{#####}` (see archived JSON),
            # so they always contain hyphens. Both reviewers of PR #86 flagged
            # this branch as dead code. Replaced with a clean "not found" since
            # the legacy code path cannot be reached.
            frappe.throw(_("Expense not found"))

    except Exception as e:
        frappe.log_error(f"Error getting expense details: {str(e)}", "Expense Details Error")
        frappe.throw(_("Error retrieving expense details"))


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
def get_volunteer_expense_context():
    """Get context data for the expense claim form (API endpoint)."""
    try:
        if frappe.session.user == "Guest":
            return {"success": False, "message": _("Please log in to access this feature")}

        volunteer_name = get_volunteer_for_current_user()
        if not volunteer_name:
            return {"success": False, "message": _("No volunteer record found")}
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer:
            return {"success": False, "message": _("No volunteer record found for your account")}

        organizations = get_volunteer_organizations(volunteer.name)
        categories = get_expense_categories()
        thresholds = get_approval_thresholds()

        return {
            "success": True,
            "volunteer": volunteer.name,
            "user_chapters": [ch["name"] for ch in organizations.get("chapters", [])],
            "user_teams": [tm["name"] for tm in organizations.get("teams", [])],
            "expense_categories": [cat["name"] for cat in categories],
            "approval_thresholds": thresholds,
        }

    except Exception as e:
        import traceback

        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}
