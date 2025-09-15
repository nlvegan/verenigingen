import frappe
from frappe import _
from frappe.utils import flt, formatdate, today

from verenigingen.utils.member_utils import get_current_user_member_name, get_volunteer_for_current_user
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.validation_utilities import DocumentExistenceValidator
from verenigingen.utils.volunteer_expense_setup import (
    create_default_cost_center,
    get_fallback_cost_center,
    get_or_create_expense_type,
    setup_expense_claim_types,
)


def _get_empty_statistics():
    """Return empty statistics dictionary for error cases or permission denied scenarios"""
    return {
        "total_submitted": 0,
        "total_approved": 0,
        "pending_amount": 0,
        "pending_count": 0,
        "approved_count": 0,
        "total_count": 0,
    }


def get_context(context):
    """Get context for volunteer expense portal page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the volunteer expense portal"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Volunteer Expenses")

    # Get current user's volunteer record using standardized utility
    volunteer_name = get_volunteer_for_current_user()
    if not volunteer_name:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator."
        )
        # Set default values to prevent template errors
        context.volunteer = None
        context.organizations = {"chapters": [], "teams": []}
        context.expense_categories = []
        context.recent_expenses = []
        context.expense_stats = {
            "total_submitted": 0,
            "total_approved": 0,
            "pending_amount": 0,
            "pending_count": 0,
            "approved_count": 0,
            "total_count": 0,
        }
        context.approval_thresholds = get_approval_thresholds()
        context.national_chapter = None
        return context

    # Get the full volunteer document
    volunteer = frappe.get_doc("Volunteer", volunteer_name)
    context.volunteer = volunteer

    # Get volunteer's organizations (chapters and teams)
    context.organizations = get_volunteer_organizations(volunteer.name)

    # Get expense categories
    context.expense_categories = get_expense_categories()

    # Get volunteer's recent expenses from HRMS Expense Claims
    context.recent_expenses = get_volunteer_expenses_from_claims(volunteer.name, limit=10)

    # Get expense statistics with optimized single query
    try:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)
        if not volunteer_doc.employee_id:
            context.stats_debug = "No employee_id found for volunteer"
            context.expense_stats = _get_empty_statistics()
        else:
            # Single optimized query for statistics
            stats_result = frappe.db.sql(
                """
                SELECT
                    COUNT(*) as total_count,
                    COALESCE(SUM(total_claimed_amount), 0) as total_submitted,
                    COALESCE(SUM(CASE
                        WHEN status IN ('Paid', 'Reimbursed') OR approval_status = 'Approved'
                        THEN COALESCE(total_sanctioned_amount, total_claimed_amount)
                        ELSE 0
                    END), 0) as total_approved,
                    COUNT(CASE
                        WHEN status IN ('Paid', 'Reimbursed') OR approval_status = 'Approved'
                        THEN 1
                    END) as approved_count
                FROM `tabExpense Claim`
                WHERE employee = %s AND docstatus != 2
            """,
                [volunteer_doc.employee_id],
                as_dict=True,
            )[0]

            total_submitted = flt(stats_result.total_submitted)
            total_approved = flt(stats_result.total_approved)
            approved_count = int(stats_result.approved_count or 0)
            total_count = int(stats_result.total_count or 0)
            pending_count = total_count - approved_count

            context.stats_debug = f"Optimized query for employee {volunteer_doc.employee_id}: {total_count} claims, €{total_submitted} submitted, €{total_approved} approved"
            context.expense_stats = {
                "total_submitted": total_submitted,
                "total_approved": total_approved,
                "pending_amount": total_submitted - total_approved,
                "pending_count": pending_count,
                "approved_count": approved_count,
                "total_count": total_count,
            }

    except frappe.DoesNotExistError:
        context.stats_debug = f"Volunteer {volunteer.name} not found"
        context.expense_stats = _get_empty_statistics()
    except frappe.PermissionError as e:
        context.stats_debug = f"Permission denied accessing expense data: {str(e)}"
        context.expense_stats = _get_empty_statistics()
    except Exception as e:
        frappe.log_error(
            f"Error calculating expense statistics for {volunteer.name}: {str(e)}", "Expense Statistics Error"
        )
        context.stats_debug = f"Error calculating statistics: {str(e)}"
        context.expense_stats = _get_empty_statistics()

    # Get maximum amounts for each approval level (for UI guidance)
    context.approval_thresholds = get_approval_thresholds()

    # Get national chapter info from settings
    context.national_chapter = get_national_chapter()

    return context


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_volunteer_for_member(member_name):
    """Create a volunteer record for an existing member (admin function)"""
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


def get_volunteer_organizations(volunteer_name):
    """Get chapters and teams the volunteer belongs to"""
    organizations = {"chapters": [], "teams": []}

    # Check if volunteer exists
    if not DocumentExistenceValidator.check_document_exists("Volunteer", volunteer_name):
        return organizations

    # Get chapters through member relationship
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        # Get chapters where this member is active
        chapter_members = frappe.get_all(
            "Chapter Member", filters={"member": volunteer_doc.member, "enabled": 1}, fields=["parent"]
        )

        for cm in chapter_members:
            chapter_data = frappe.db.get_value("Chapter", cm.parent, ["name"], as_dict=True)
            if chapter_data:
                # Standardize chapter data structure (consistent with dashboard.py)
                chapter_info = {
                    "name": chapter_data["name"],
                    "chapter_name": chapter_data["name"],  # Chapter name is stored in the 'name' field
                    "city": "",  # Chapters don't have city in this system
                }
                organizations["chapters"].append(chapter_info)
                frappe.logger().debug(f"Added chapter to organizations: {chapter_info}")

    # Get teams where volunteer is active
    team_members = frappe.get_all(
        "Team Member", filters={"volunteer": volunteer_name, "status": "Active"}, fields=["parent"]
    )

    for tm in team_members:
        team_info = frappe.db.get_value("Team", tm.parent, ["name"], as_dict=True)
        if team_info:
            # Add team_name field with same value as name for consistency
            team_info["team_name"] = team_info["name"]
            organizations["teams"].append(team_info)

    return organizations


def get_expense_categories():
    """Get available expense categories"""
    return frappe.get_all(
        "Expense Category",
        filters={"is_active": 1},
        fields=["name", "category_name", "description"],
        order_by="category_name",
    )


def get_volunteer_expenses_from_claims(volunteer_name, limit=None):
    """Get volunteer's expenses directly from HRMS Expense Claims (simplified)"""
    try:
        # Get volunteer's employee_id
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer_doc.employee_id:
            return []

        # Get expense claims for this employee
        expense_claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": volunteer_doc.employee_id, "docstatus": ["!=", 2]},  # Exclude cancelled
            fields=[
                "name",
                "total_claimed_amount",
                "total_sanctioned_amount",
                "status",
                "approval_status",
                "posting_date",
                "remark",
                "custom_organization_type",
                "custom_chapter",
                "custom_team",
                "custom_expense_category",
            ],
            order_by="posting_date desc",
            limit=limit,
        )

        expenses = []
        for claim in expense_claims:
            # Get first expense detail for description
            expense_details = frappe.get_all(
                "Expense Claim Detail",
                filters={"parent": claim.name},
                fields=["description", "expense_type", "amount"],
                order_by="idx",
                limit=1,
            )

            description = expense_details[0].description if expense_details else f"Expense Claim {claim.name}"

            # Get organization name
            org_name = claim.custom_chapter or claim.custom_team or "National"
            org_type = claim.custom_organization_type or "Unknown"

            # Map HRMS status to volunteer portal status
            if claim.status == "Paid":
                status = "Reimbursed"
            elif claim.approval_status == "Approved":
                status = "Approved"
            elif claim.status == "Submitted":
                status = "Submitted"
            else:
                status = "Draft"

            expense = {
                "name": claim.name,
                "expense_claim_id": claim.name,
                "description": description,
                "amount": claim.total_claimed_amount,
                "currency": "EUR",
                "expense_date": claim.posting_date,
                "status": status,
                "organization_type": org_type,
                "organization_name": org_name,
                "category": claim.custom_expense_category,
                "category_name": frappe.db.get_value(
                    "Expense Category", claim.custom_expense_category, "category_name"
                )
                if claim.custom_expense_category
                else "Uncategorized",
                "formatted_date": formatdate(claim.posting_date),
                "status_class": get_status_class(status),
            }
            expenses.append(expense)

        return expenses

    except frappe.DoesNotExistError:
        frappe.log_error(f"Volunteer {volunteer_name} not found", "Volunteer Not Found")
        return []
    except frappe.PermissionError as e:
        frappe.log_error(
            f"Permission denied accessing expenses for {volunteer_name}: {str(e)}", "Expense Access Denied"
        )
        return []
    except Exception as e:
        frappe.log_error(
            f"Error getting volunteer expenses from claims for {volunteer_name}: {str(e)}",
            "Volunteer Expenses from Claims Error",
        )
        return []


# Legacy functions removed - using get_volunteer_expenses_from_claims() as primary method


def get_approval_thresholds():
    """Get approval thresholds for UI guidance"""
    return {"basic_limit": 100.0, "financial_limit": 500.0, "admin_limit": 999999.0}


def get_national_chapter():
    """Get national chapter info from settings"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and getattr(settings, "national_board_chapter", None):
            chapter_info = frappe.db.get_value(
                "Chapter", settings.national_board_chapter, ["name"], as_dict=True
            )
            if chapter_info:
                return {
                    "name": chapter_info.name,
                    "chapter_name": chapter_info.name,  # Use name as chapter_name since that field doesn't exist
                }
    except Exception as e:
        frappe.log_error(f"Error getting national chapter: {str(e)}")
        # Log more details for debugging
        frappe.logger().error(f"National chapter error details: {str(e)}")
        import traceback

        frappe.logger().error(f"National chapter traceback: {traceback.format_exc()}")

    return None


def get_status_class(status):
    """Get CSS class for expense status"""
    status_classes = {
        "Draft": "badge-secondary",
        "Submitted": "badge-warning",
        "Approved": "badge-success",
        "Rejected": "badge-danger",
        "Reimbursed": "badge-primary",
    }
    return status_classes.get(status, "badge-secondary")


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def upload_expense_receipt():
    """Upload receipt file and return file data for later attachment"""
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
            # Check for various possible field names
            for field_name in ["receipt", "file", "_file", "uploaded_file"]:
                if field_name in frappe.form_dict:
                    uploaded_file = frappe.form_dict[field_name]
                    break

        # Method 3: From local.uploaded_files (Frappe's internal storage)
        if not uploaded_file and hasattr(frappe.local, "uploaded_files") and frappe.local.uploaded_files:
            # Take the first uploaded file if available
            uploaded_file = list(frappe.local.uploaded_files.values())[0]

        if not uploaded_file:
            return {"success": False, "error": "No file uploaded", "debug_info": debug_info}

        # Handle different file object types
        if hasattr(uploaded_file, "filename") and hasattr(uploaded_file, "read"):
            # Standard file upload object
            filename = uploaded_file.filename
            if not filename:
                return {"success": False, "error": "No filename provided"}

            file_content = uploaded_file.read()
            content_type = getattr(uploaded_file, "content_type", "application/octet-stream")

        elif isinstance(uploaded_file, dict) and "filename" in uploaded_file:
            # Frappe's processed file format
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

        # Return file data for processing during expense submission
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
            f"Error uploading expense receipt: {str(e)}\n{traceback.format_exc()}", "File Upload Error"
        )
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING, self_service_only=True)
def submit_expense(expense_data=None):
    """Submit a new expense from the portal"""
    try:
        # Handle JSON request body
        if expense_data is None:
            import json

            request_data = json.loads(frappe.request.data.decode("utf-8"))
            expense_data = request_data.get("expense_data")

        # Parse JSON string if needed (fallback for form submissions)
        if isinstance(expense_data, str):
            import html
            import json

            # Decode HTML entities (handles cases where JSON gets HTML encoded)
            decoded_data = html.unescape(expense_data)
            expense_data = json.loads(decoded_data)
        # Get current user's volunteer record
        volunteer_name = get_volunteer_for_current_user()
        if not volunteer_name:
            return {"success": False, "message": _("No volunteer record found")}
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer:
            # Provide more helpful error message using member_utils
            from verenigingen.utils.member_utils import get_member_name_for_user

            user_email = frappe.session.user
            member = get_member_name_for_user(user_email)

            if member:
                error_msg = _(
                    "No volunteer record found for your account. You have a member record ({0}) but no linked volunteer record. Please contact your chapter administrator to create a volunteer profile."
                ).format(member)
            else:
                error_msg = _(
                    "No volunteer record found for your account. Your email ({0}) is not associated with any member or volunteer record. Please contact your chapter administrator."
                ).format(user_email)

            frappe.throw(error_msg)

        # Validate required fields
        required_fields = ["description", "amount", "expense_date", "organization_type", "category"]
        for field in required_fields:
            if not expense_data.get(field):
                frappe.throw(_(f"Field {field} is required"))

        # Validate organization selection
        if expense_data.get("organization_type") == "Chapter" and not expense_data.get("chapter"):
            frappe.throw(_("Please select a chapter"))
        elif expense_data.get("organization_type") == "Team" and not expense_data.get("team"):
            frappe.throw(_("Please select a team"))
        # National expenses don't require specific organization selection

        # Enhanced access validation with policy-based national expenses
        if expense_data.get("organization_type") == "Chapter":
            organization_name = expense_data.get("chapter")
            # For chapter expenses, check chapter membership through member record
            if volunteer.member:
                direct_membership = frappe.db.exists(
                    "Chapter Member", {"parent": organization_name, "member": volunteer.member}
                )
            else:
                direct_membership = None

            if not direct_membership:
                frappe.throw(_("Chapter membership required for {0}").format(organization_name))

        elif expense_data.get("organization_type") == "Team":
            organization_name = expense_data.get("team")
            # For team expenses, only check team membership (no chapter validation needed)
            team_membership = frappe.db.exists(
                "Team Member", {"parent": organization_name, "volunteer": volunteer.name}
            )
            if not team_membership:
                frappe.throw(_("Team membership required for {0}").format(organization_name))

        elif expense_data.get("organization_type") == "National":
            # Check if this is a policy-covered expense type
            category = expense_data.get("category")
            if category and is_policy_covered_expense(category):
                # Policy-covered expenses (materials, travel) are allowed for all volunteers
                frappe.logger().info(
                    f"Policy-covered national expense allowed for volunteer {volunteer.name}: {category}"
                )
            else:
                # Other national expenses require board membership
                settings = frappe.get_single("Verenigingen Settings")
                if settings.national_board_chapter:
                    board_membership = frappe.db.exists(
                        "Chapter Member",
                        {"parent": settings.national_board_chapter, "volunteer": volunteer.name},
                    )
                    if not board_membership:
                        frappe.throw(_("National board membership required for non-policy national expenses"))

        # Determine chapter/team based on organization type
        chapter = None
        team = None

        if expense_data.get("organization_type") == "Chapter":
            chapter = expense_data.get("chapter")
        elif expense_data.get("organization_type") == "Team":
            team = expense_data.get("team")
        elif expense_data.get("organization_type") == "National":
            # Set to national chapter from settings
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                chapter = settings.national_board_chapter
            else:
                frappe.throw(_("National chapter not configured in settings"))

        # Get company from Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")
        default_company = settings.company
        if not default_company:
            frappe.throw(_("Company not configured in Verenigingen Settings"))

        if not default_company:
            frappe.throw(_("No company configured in the system. Please contact the administrator."))

        # Get volunteer document for employee_id
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)

        # Ensure volunteer has employee_id - create if missing
        employee_created = False
        if not volunteer_doc.employee_id:
            try:
                frappe.logger().info(
                    f"Creating employee record for volunteer {volunteer_doc.name} during expense submission"
                )
                employee_id = volunteer_doc.create_minimal_employee()
                if employee_id:
                    frappe.logger().info(
                        f"Successfully created employee {employee_id} for volunteer {volunteer_doc.name}"
                    )
                    # Reload volunteer document to get the updated employee_id
                    volunteer_doc.reload()
                    employee_created = True
                else:
                    frappe.log_error(
                        f"Employee creation returned None for volunteer {volunteer_doc.name}",
                        "Employee Creation Warning",
                    )
                    frappe.throw(
                        _(
                            "Unable to create employee record automatically. Please contact your administrator to set up your employee profile before submitting expenses."
                        )
                    )
            except Exception as e:
                error_msg = str(e)[:50]  # Short error message for logging
                frappe.log_error(f"Employee creation failed: {error_msg}", "Employee Creation")
                frappe.throw(
                    _(
                        "Unable to create employee record automatically. Please contact your administrator to set up your employee profile before submitting expenses."
                    )
                )

        # Get cost center based on organization
        cost_center = get_organization_cost_center(expense_data)

        # Get expense type from category
        expense_type = get_or_create_expense_type(expense_data.get("category"))

        # Get payable account from company settings
        payable_account = frappe.db.get_value("Company", default_company, "default_payable_account")
        if not payable_account:
            # Fallback to default payable account
            payable_account = frappe.db.get_value("Company", default_company, "default_payable_account")

        if not payable_account:
            frappe.throw(
                _(
                    "No payable account configured for company {0}. Please set default_payable_account in Company settings."
                ).format(default_company)
            )

        # Create ERPNext Expense Claim with custom volunteer fields
        expense_claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": volunteer_doc.employee_id,
                "posting_date": expense_data.get("expense_date"),
                "company": default_company,
                "cost_center": cost_center,
                "payable_account": payable_account,
                "approval_status": "Draft",  # Leave approval to appropriate user roles
                "remark": expense_data.get("notes"),
                "status": "Draft",
                # Custom volunteer fields
                "custom_volunteer": volunteer.name,
                "custom_organization_type": expense_data.get("organization_type"),
                "custom_chapter": chapter,
                "custom_team": team,
                "custom_expense_category": expense_data.get("category"),
            }
        )

        # Add expense detail
        expense_claim.append(
            "expenses",
            {
                "expense_date": expense_data.get("expense_date"),
                "expense_type": expense_type,
                "description": expense_data.get("description"),
                "amount": flt(expense_data.get("amount")),
                "sanctioned_amount": flt(expense_data.get("amount")),
                "cost_center": cost_center,
            },
        )

        # Insert the expense claim as draft (don't submit automatically)
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        expense_result = secure_document_operation(
            operation="insert",
            doc=expense_claim,
            justification=f"Create volunteer expense claim for {volunteer.name} - Amount: {flt(expense_data.get('amount'))}",
            required_permissions=["Expense Claim:create"],
        )

        if not expense_result.success:
            frappe.log_error(
                f"Failed to create expense claim: {'; '.join(expense_result.errors)}",
                "Expense Claim Security",
            )
            return {
                "success": False,
                "error": f"Failed to create expense claim: {'; '.join(expense_result.errors)}",
            }

        expense_claim = frappe.get_doc("Expense Claim", expense_result.doc_name)
        frappe.logger().info(f"Successfully created expense claim draft: {expense_claim.name}")

        # Add receipt attachment if provided - attach to the ERPNext Expense Claim
        receipt_data = expense_data.get("receipt_attachment")
        if receipt_data and isinstance(receipt_data, dict):
            try:
                if receipt_data.get("file_url") and receipt_data.get("frappe_file_name"):
                    # Handle Frappe's built-in upload format
                    frappe.logger().info(
                        f"Using Frappe built-in file: {receipt_data.get('frappe_file_name')}"
                    )

                    # Get the existing file document and re-attach it to the expense claim
                    file_doc = frappe.get_doc("File", receipt_data.get("frappe_file_name"))
                    file_doc.attached_to_doctype = expense_claim.doctype
                    file_doc.attached_to_name = expense_claim.name
                    file_doc.folder = "Home/Attachments"
                    file_doc.is_private = 0

                    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                    file_result = secure_document_operation(
                        operation="save",
                        doc=file_doc,
                        justification=f"Attach receipt file {file_doc.name} to expense claim {expense_claim.name} for volunteer {volunteer.name}",
                        required_permissions=["File:write"],
                    )

                    if not file_result.success:
                        frappe.logger().error(
                            f"Failed to attach Frappe file to expense claim: {'; '.join(file_result.errors)}"
                        )
                        raise frappe.ValidationError(
                            f"File attachment failed: {file_result.errors[0] if file_result.errors else 'Unknown error'}"
                        )

                    frappe.logger().info(
                        f"Successfully re-attached Frappe file {file_doc.name} to expense claim {expense_claim.name}"
                    )

                elif receipt_data.get("file_content"):
                    # Handle our custom base64 format
                    frappe.logger().info(f"Using custom base64 file: {receipt_data.get('file_name')}")

                    # Decode file content
                    import base64

                    file_content = base64.b64decode(receipt_data.get("file_content", ""))

                    # Create file with proper attachment using official Frappe API
                    file_doc = frappe.get_doc(
                        {
                            "doctype": "File",
                            "file_name": receipt_data.get("file_name"),
                            "content": file_content,
                            "attached_to_doctype": expense_claim.doctype,
                            "attached_to_name": expense_claim.name,
                            "folder": "Home/Attachments",
                            "is_private": 0,
                        }
                    )

                    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                    file_result = secure_document_operation(
                        operation="insert",
                        doc=file_doc,
                        justification=f"Create receipt file {receipt_data.get('file_name')} for expense claim {expense_claim.name} - volunteer {volunteer.name}",
                        required_permissions=["File:create"],
                    )

                    if not file_result.success:
                        frappe.logger().error(
                            f"Failed to create custom receipt file: {'; '.join(file_result.errors)}"
                        )
                        raise frappe.ValidationError(
                            f"Receipt upload failed: {file_result.errors[0] if file_result.errors else 'Unknown error'}"
                        )

                    frappe.logger().info(
                        f"Successfully attached custom receipt {receipt_data.get('file_name')} to expense claim {expense_claim.name}"
                    )
                else:
                    frappe.logger().warning(
                        f"Receipt data provided but no valid file format found: {receipt_data}"
                    )

            except Exception as attachment_error:
                # Log error but don't fail the entire expense submission
                frappe.log_error(
                    f"Failed to attach receipt to expense claim {expense_claim.name}: {str(attachment_error)}",
                    "Expense Receipt Attachment Error",
                )
                frappe.logger().warning(
                    f"Receipt attachment failed for {expense_claim.name}: {attachment_error}"
                )

        # Don't submit automatically - leave for approval workflow
        # The expense claim will remain in Draft status until approved and submitted by authorized users

        # No longer creating redundant Volunteer Expense record - all data is stored in Expense Claim custom fields

        # Prepare success message
        success_message = _("Expense claim saved successfully and awaiting approval")
        if employee_created:
            success_message += _(" (Employee record created for your account)")

        return {
            "success": True,
            "message": success_message,
            "expense_claim_name": expense_claim.name,
            "employee_created": employee_created,
        }

    except Exception as e:
        frappe.log_error(f"Error submitting expense: {str(e)}", "Volunteer Expense Submission Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_organization_options(organization_type, volunteer_name=None):
    """Get organization options for the current volunteer"""
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
def get_expense_details(expense_name):
    """Get details for a specific expense from ERPNext or legacy records"""
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

                # Get linked Volunteer Expense record for organization info
                volunteer_expense = frappe.db.get_value(
                    "Volunteer Expense",
                    {"expense_claim_id": claim_name},
                    ["organization_type", "chapter", "team", "category"],
                    as_dict=True,
                )

                # Build response from ERPNext data
                if expense_details:
                    detail = expense_details[0]  # First detail for now
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

                    # Add organization name with explicit fallback logic
                    organization_name = expense_dict.get("chapter")
                    if not organization_name:
                        organization_name = expense_dict.get("team")
                    if not organization_name:
                        organization_name = "Unknown"
                    expense_dict["organization_name"] = organization_name

                    # Add attachment count from ERPNext
                    expense_dict["attachment_count"] = frappe.db.count(
                        "File", {"attached_to_name": claim_name, "attached_to_doctype": "Expense Claim"}
                    )

                    return expense_dict
                else:
                    frappe.throw(_("Expense details not found"))
            else:
                frappe.throw(_("Access denied - no employee record"))
        else:
            # Legacy Volunteer Expense record
            expense = frappe.get_doc("Volunteer Expense", expense_name)
            if expense.volunteer != volunteer.name:
                frappe.throw(_("Access denied"))

            # Get enhanced expense details
            expense_dict = expense.as_dict()

            # Add category name
            if expense.category:
                expense_dict["category_name"] = frappe.db.get_value(
                    "Expense Category", expense.category, "category_name"
                )

            # Add organization name
            expense_dict["organization_name"] = expense.chapter or expense.team

            # Add attachment count
            expense_dict["attachment_count"] = frappe.db.count(
                "File", {"attached_to_name": expense.name, "attached_to_doctype": "Volunteer Expense"}
            )

            return expense_dict

    except Exception as e:
        frappe.log_error(f"Error getting expense details: {str(e)}", "Expense Details Error")
        frappe.throw(_("Error retrieving expense details"))


# setup_expense_claim_types function moved to verenigingen.utils.volunteer_expense_setup


def get_organization_cost_center(expense_data):
    """Get cost center based on organization with enhanced fallback logic"""
    try:
        cost_center = None

        if expense_data.get("organization_type") == "Chapter" and expense_data.get("chapter"):
            chapter_doc = frappe.get_doc("Chapter", expense_data.get("chapter"))
            cost_center = getattr(chapter_doc, "cost_center", None)

        elif expense_data.get("organization_type") == "Team" and expense_data.get("team"):
            team_doc = frappe.get_doc("Team", expense_data.get("team"))
            cost_center = getattr(team_doc, "cost_center", None)

            # If team doesn't have cost center, try to get from chapter
            if not cost_center and hasattr(team_doc, "chapter") and team_doc.chapter:
                try:
                    chapter_doc = frappe.get_doc("Chapter", team_doc.chapter)
                    cost_center = getattr(chapter_doc, "cost_center", None)
                    frappe.logger().info(f"Using chapter cost center for team {team_doc.name}: {cost_center}")
                except Exception as e:
                    frappe.logger().error(f"Error getting chapter cost center: {str(e)}")

        elif expense_data.get("organization_type") == "National":
            # Get national cost center from settings
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "national_cost_center") and settings.national_cost_center:
                cost_center = settings.national_cost_center

        # Enhanced fallback logic
        if not cost_center:
            frappe.logger().warning(
                f"No cost center found for organization type: {expense_data.get('organization_type')}"
            )

            # Try to get company cost center from settings
            settings = frappe.get_single("Verenigingen Settings")
            default_company = settings.company
            if not default_company:
                frappe.throw(_("Company not configured in Verenigingen Settings"))

            if default_company:
                # Get main cost center for the company
                main_cost_centers = frappe.get_all(
                    "Cost Center",
                    filters={"company": default_company, "is_group": 0},
                    fields=["name"],
                    limit=1,
                )

                if main_cost_centers:
                    cost_center = main_cost_centers[0].name
                    frappe.logger().info(f"Using fallback cost center: {cost_center}")
                else:
                    # Create a default cost center if none exists
                    cost_center = create_default_cost_center(default_company)

        return cost_center

    except Exception as e:
        frappe.log_error(f"Error getting cost center: {str(e)}", "Cost Center Error")
        # Return a default cost center as last resort
        return get_fallback_cost_center()


# create_default_cost_center function moved to verenigingen.utils.volunteer_expense_setup


# get_fallback_cost_center function moved to verenigingen.utils.volunteer_expense_setup


def validate_volunteer_organization_access(volunteer_name, organization_type, organization_name):
    """
    Enhanced validation for volunteer access to organizations.
    Supports direct chapter membership AND indirect access via team membership.
    """
    try:
        frappe.get_doc("Volunteer", volunteer_name)

        if organization_type == "Chapter":
            # Direct chapter membership check
            direct_membership = frappe.db.exists(
                "Chapter Member", {"parent": organization_name, "volunteer": volunteer_name}
            )

            if direct_membership:
                return True

            # Indirect access via team membership
            # Get teams where volunteer is a member and team's chapter matches
            team_memberships = frappe.get_all(
                "Team Member", filters={"volunteer": volunteer_name}, fields=["parent"]
            )

            for membership in team_memberships:
                team_doc = frappe.get_doc("Team", membership.parent)
                if hasattr(team_doc, "chapter") and team_doc.chapter == organization_name:
                    frappe.logger().info(
                        f"Volunteer {volunteer_name} has access to chapter {organization_name} via team {team_doc.name}"
                    )
                    return True

            return False

        elif organization_type == "Team":
            # Direct team membership check
            team_membership = frappe.db.exists(
                "Team Member", {"parent": organization_name, "volunteer": volunteer_name}
            )
            return bool(team_membership)

        elif organization_type == "National":
            # All volunteers have access to national expenses
            return True

        return False

    except Exception as e:
        frappe.log_error(
            f"Error validating volunteer organization access: {str(e)}", "Access Validation Error"
        )
        # In case of error, allow access to prevent blocking legitimate requests
        return True


def is_policy_covered_expense(category):
    """Check if expense category is covered by organizational policy for all volunteers"""
    try:
        # Get expense category details
        category_doc = frappe.get_doc("Expense Category", category)

        # Policy-covered categories (configurable via category settings)
        if hasattr(category_doc, "policy_covered") and category_doc.policy_covered:
            return True

        # Fallback: Check by category name for common policy-covered expenses
        policy_covered_categories = [
            "Travel",  # Travel expenses
            "Materials",  # Materials for campaigns/events
            "Office Supplies",  # Basic office supplies
            "events",  # Event materials
        ]

        category_name = getattr(category_doc, "category_name", category).lower()
        return any(policy_cat.lower() in category_name for policy_cat in policy_covered_categories)

    except Exception as e:
        frappe.log_error(
            f"Error checking policy coverage for category {category}: {str(e)}", "Policy Coverage Check"
        )
        # Default to requiring permission if we can't determine policy coverage
        return False


# get_or_create_expense_type function moved to verenigingen.utils.volunteer_expense_setup


@frappe.whitelist(allow_guest=False)
def submit_multiple_expenses(expenses):
    """Submit multiple expenses from the portal at once"""
    try:
        # Ensure user is logged in
        if frappe.session.user == "Guest":
            return {"success": False, "message": _("Please log in to submit expenses")}
        # Parse JSON string if needed
        if isinstance(expenses, str):
            import json

            expenses = json.loads(expenses)

        # Validate input
        if not expenses or not isinstance(expenses, list):
            return {"success": False, "message": _("Invalid expense data provided")}

        if len(expenses) > 50:  # Reasonable limit
            return {
                "success": False,
                "message": _("Too many expenses in one submission. Maximum allowed: 50"),
            }

        # Get current user's volunteer record once
        volunteer_name = get_volunteer_for_current_user()
        if not volunteer_name:
            return {"success": False, "message": _("No volunteer record found")}
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer:
            # Use member_utils for consistent member lookup
            from verenigingen.utils.member_utils import get_member_name_for_user

            user_email = frappe.session.user
            member = get_member_name_for_user(user_email)
            if member:
                error_msg = _(
                    "No volunteer record found for your account. You have a member record ({0}) but no linked volunteer record. Please contact your chapter administrator to create a volunteer profile."
                ).format(member)
            else:
                error_msg = _(
                    "No volunteer record found for your account. Your email ({0}) is not associated with any member or volunteer record. Please contact your chapter administrator."
                ).format(user_email)
            return {"success": False, "message": error_msg}

        created_expenses = []
        errors = []
        total_amount = 0

        # Validate each expense before processing
        for idx, expense_data in enumerate(expenses):
            # Basic validation
            validation_errors = validate_expense_data(expense_data, idx + 1)
            if validation_errors:
                errors.extend(validation_errors)
                continue

            total_amount += float(expense_data.get("amount", 0))

        # Check total amount limit (reasonable safety limit)
        if total_amount > 10000:  # €10,000 limit per submission
            return {
                "success": False,
                "message": _(
                    "Total expense amount (€{0}) exceeds the maximum allowed per submission (€10,000)"
                ).format(total_amount),
            }

        # If we have validation errors, return them immediately
        if errors:
            return {
                "success": False,
                "message": _("Validation errors found in expense data"),
                "errors": errors,
            }

        # Process each expense
        for idx, expense_data in enumerate(expenses):
            try:
                # Submit individual expense
                result = submit_expense(expense_data)

                if result.get("success"):
                    created_expenses.append(
                        {
                            "expense_claim_name": result.get("expense_claim_name"),
                            "expense_name": result.get("expense_name"),
                            "description": expense_data.get("description"),
                            "amount": expense_data.get("amount"),
                        }
                    )
                else:
                    errors.append(
                        {
                            "index": idx,
                            "description": expense_data.get("description"),
                            "error": result.get("message", "Unknown error"),
                        }
                    )

            except Exception as e:
                errors.append(
                    {
                        "index": idx,
                        "description": expense_data.get("description", f"Expense {idx + 1}"),
                        "error": str(e),
                    }
                )

        # Prepare response
        if created_expenses and not errors:
            # All expenses created successfully
            return {
                "success": True,
                "message": _("Successfully submitted {0} expense(s)").format(len(created_expenses)),
                "created_count": len(created_expenses),
                "created_expenses": created_expenses,
            }
        elif created_expenses and errors:
            # Partial success
            return {
                "success": True,
                "partial": True,
                "message": _("Submitted {0} expense(s) successfully, {1} failed").format(
                    len(created_expenses), len(errors)
                ),
                "created_count": len(created_expenses),
                "created_expenses": created_expenses,
                "errors": errors,
            }
        else:
            # All failed
            return {"success": False, "message": _("Failed to submit any expenses"), "errors": errors}

    except Exception as e:
        import traceback

        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist(allow_guest=False)
def get_volunteer_expense_context():
    """Get context data for the expense claim form"""
    try:
        # Ensure user is logged in
        if frappe.session.user == "Guest":
            return {"success": False, "message": _("Please log in to access this feature")}

        # Get current user's volunteer record
        volunteer_name = get_volunteer_for_current_user()
        if not volunteer_name:
            return {"success": False, "message": _("No volunteer record found")}
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer:
            return {"success": False, "message": _("No volunteer record found for your account")}

        # Get organizations
        organizations = get_volunteer_organizations(volunteer.name)

        # Get expense categories
        categories = get_expense_categories()

        # Get approval thresholds for UI guidance
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


def validate_expense_data(expense_data, line_number):
    """Validate individual expense data"""
    errors = []

    # Required fields validation
    required_fields = {
        "description": _("Description"),
        "amount": _("Amount"),
        "expense_date": _("Expense Date"),
        "organization_type": _("Organization Type"),
        "category": _("Category"),
    }

    for field, label in required_fields.items():
        if not expense_data.get(field):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": field,
                    "error": _("Line {0}: {1} is required").format(line_number, label),
                }
            )

    # Amount validation
    try:
        amount = float(expense_data.get("amount", 0))
        if amount <= 0:
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "amount",
                    "error": _("Line {0}: Amount must be greater than 0").format(line_number),
                }
            )
        if amount > 5000:  # Individual expense limit
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "amount",
                    "error": _("Line {0}: Amount cannot exceed €5,000 per expense").format(line_number),
                }
            )
    except (ValueError, TypeError):
        errors.append(
            {
                "index": line_number - 1,
                "field": "amount",
                "error": _("Line {0}: Invalid amount format").format(line_number),
            }
        )

    # Date validation
    if expense_data.get("expense_date"):
        try:
            from frappe.utils import getdate

            expense_date = getdate(expense_data.get("expense_date"))
            today_date = getdate(today())

            if expense_date > today_date:
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "expense_date",
                        "error": _("Line {0}: Expense date cannot be in the future").format(line_number),
                    }
                )

            # Check if date is too old (e.g., older than 1 year)
            days_old = (today_date - expense_date).days
            if days_old > 365:
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "expense_date",
                        "error": _("Line {0}: Expense date is too old (older than 1 year)").format(
                            line_number
                        ),
                    }
                )
        except (ValueError, TypeError):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "expense_date",
                    "error": _("Line {0}: Invalid date format").format(line_number),
                }
            )

    # Description validation
    description = expense_data.get("description", "").strip()
    if description and len(description) > 200:
        errors.append(
            {
                "index": line_number - 1,
                "field": "description",
                "error": _("Line {0}: Description is too long (maximum 200 characters)").format(line_number),
            }
        )

    # Organization validation
    org_type = expense_data.get("organization_type")
    if org_type == "Chapter" and not expense_data.get("chapter"):
        errors.append(
            {
                "index": line_number - 1,
                "field": "chapter",
                "error": _("Line {0}: Chapter selection is required for chapter expenses").format(
                    line_number
                ),
            }
        )
    elif org_type == "Team" and not expense_data.get("team"):
        errors.append(
            {
                "index": line_number - 1,
                "field": "team",
                "error": _("Line {0}: Team selection is required for team expenses").format(line_number),
            }
        )

    # Category validation
    category = expense_data.get("category")
    if category:
        if not frappe.db.exists("Expense Category", category):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "category",
                    "error": _("Line {0}: Invalid expense category").format(line_number),
                }
            )

    # File validation (if receipt provided)
    receipt = expense_data.get("receipt_attachment")
    if receipt and isinstance(receipt, dict):
        file_name = receipt.get("file_name", "")
        if file_name:
            # Check file extension
            allowed_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"]
            if not any(file_name.lower().endswith(ext) for ext in allowed_extensions):
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "receipt_attachment",
                        "error": _("Line {0}: Invalid file type. Allowed: PDF, JPG, PNG, GIF, BMP").format(
                            line_number
                        ),
                    }
                )

            # Check file content size (base64 encoded, so roughly file_size * 1.33)
            file_content = receipt.get("file_content", "")
            if file_content and len(file_content) > 10 * 1024 * 1024:  # ~7.5MB actual file size
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "receipt_attachment",
                        "error": _("Line {0}: File size too large (maximum 7.5MB)").format(line_number),
                    }
                )

    return errors


def get_user_volunteer_record():
    """Get the volunteer record for the current user"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access volunteer information"), frappe.PermissionError)

    # Use the existing optimized utility function
    from verenigingen.utils.performance_utils import get_user_volunteer_record_optimized

    return get_user_volunteer_record_optimized(frappe.session.user)


def map_erpnext_status_to_volunteer_status(status, approval_status=None):
    """Map ERPNext Expense Claim status to volunteer expense status"""
    # This function was referenced but not defined - adding implementation
    if status == "Draft":
        return "Draft"
    elif status == "Submitted":
        if approval_status == "Approved":
            return "Approved"
        elif approval_status == "Rejected":
            return "Rejected"
        else:
            return "Submitted"
    elif status == "Paid":
        return "Reimbursed"
    elif status == "Cancelled":
        return "Rejected"
    else:
        return status  # Fallback to original status
