"""
Volunteer Expense Submission Service

Consolidated service for volunteer expense claim creation and submission.
Handles validation, employee creation, organization access checks, and
expense claim document creation.

This service consolidates logic previously duplicated between:
- templates/pages/volunteer/expenses.py
- templates/pages/volunteer-portal/expense_claim_new.py

Author: Verenigingen Development Team
License: MIT
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document
from frappe import _
from frappe.utils import flt

from verenigingen.utils.employee_user_link import create_employee_for_approved_volunteer
from verenigingen.utils.member_utils import get_volunteer_for_current_user
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.audit_logging import AuditLogger
from verenigingen.utils.security.types import AuditEventType, AuditSeverity
from verenigingen.utils.volunteer_expense_setup import get_or_create_expense_type


@dataclass
class ExpenseSubmissionRequest:
    """Request data for expense submission"""

    description: str
    amount: float
    expense_date: str
    organization_type: str  # 'Chapter', 'Team', or 'National'
    category: str
    chapter: Optional[str] = None
    team: Optional[str] = None
    notes: Optional[str] = None
    receipt_attachment: Optional[dict] = None
    volunteer: Optional[str] = None  # For tampering detection
    additional_expenses: list = field(default_factory=list)


class VolunteerExpenseSubmissionService:
    """Service for managing volunteer expense submissions"""

    REQUIRED_FIELDS = ["description", "amount", "expense_date", "organization_type", "category"]

    def __init__(self, volunteer_name: Optional[str] = None):
        """Initialize service

        Args:
            volunteer_name: Volunteer record name. If None, uses current user's volunteer.
        """
        self._volunteer_name = volunteer_name
        self._volunteer_doc = None
        self._settings = None
        self._company = None

    @property
    def volunteer_name(self) -> str:
        """Get volunteer name, resolving from current user if needed"""
        if not self._volunteer_name:
            self._volunteer_name = get_volunteer_for_current_user()
            if not self._volunteer_name:
                frappe.throw(
                    _(
                        "No volunteer record found for your account. Please contact your chapter administrator."
                    ),
                    frappe.DoesNotExistError,
                )
        return self._volunteer_name

    @property
    def volunteer_doc(self) -> "Document":
        """Lazy load volunteer document."""
        if not self._volunteer_doc:
            self._volunteer_doc = frappe.get_doc("Volunteer", self.volunteer_name)
        return self._volunteer_doc

    @property
    def settings(self) -> "Document":
        """Lazy load Verenigingen Settings."""
        if not self._settings:
            self._settings = frappe.get_single("Verenigingen Settings")
        return self._settings

    @property
    def company(self) -> str:
        """Get default company from settings."""
        if not self._company:
            self._company = self.settings.company
            if not self._company:
                frappe.throw(_("Company not configured in Verenigingen Settings"))
        return self._company

    def submit_expense(
        self,
        expense_data: dict,
        additional_expenses: Optional[list] = None,
    ) -> OperationResult:
        """Submit a volunteer expense claim.

        Creates an Expense Claim document for the current volunteer with proper
        cost center assignment, organization validation, and optional receipt attachment.

        Args:
            expense_data: Primary expense data dictionary containing:
                - description (str): Expense description (required)
                - amount (float): Expense amount (required)
                - expense_date (str): Date of expense (required)
                - organization_type (str): 'Chapter', 'Team', or 'National' (required)
                - category (str): Expense category name (required)
                - chapter (str, optional): Chapter name if organization_type='Chapter'
                - team (str, optional): Team name if organization_type='Team'
                - notes (str, optional): Additional notes/remarks
                - receipt_attachment (dict, optional): Receipt file data with either:
                    - file_url + frappe_file_name (Frappe upload format), or
                    - file_content + file_name (base64 format)
                - volunteer (str, optional): Volunteer name for tampering detection

            additional_expenses: Optional list of additional expense lines, each containing:
                - description (str): Line description (required)
                - amount (float): Line amount (required, > 0)
                - category (str): Expense category (required)
                - expense_date (str, optional): Defaults to primary expense_date

        Returns:
            OperationResult with:
                - data: Expense Claim document on success
                - metadata.message: User-facing success/error message
                - metadata.expense_claim_name: Created document name
                - metadata.employee_created: True if employee record was auto-created
                - metadata.receipt_attached: True if receipt was successfully attached

        Raises:
            frappe.PermissionError: If volunteer parameter tampering is detected

        Note:
            The wrapper API functions (expenses.py, expense_claim_new.py) manually
            convert this result to dict format rather than using OperationResult.to_dict()
            because the API requires 'message' for errors (not 'error') and excludes
            the full document data to keep responses lightweight.
        """
        try:
            # Build request from dict
            request = self._build_request(expense_data, additional_expenses)

            # Validate request
            validation_errors = self._validate_request(request)
            if validation_errors:
                return OperationResult.fail(validation_errors[0], errors=validation_errors)

            # Check for volunteer parameter tampering
            if request.volunteer and request.volunteer != self.volunteer_name:
                self._log_tampering_attempt(request.volunteer)
                frappe.throw(
                    _("Security violation: volunteer parameter tampering detected"),
                    frappe.PermissionError,
                )

            # Validate organization access
            access_error = self._validate_organization_access(request)
            if access_error:
                return OperationResult.fail(access_error)

            # Ensure employee record exists
            employee_created = self._ensure_employee_exists()

            # Resolve organization (chapter/team)
            chapter, team = self._resolve_organization(request)

            # Get cost center
            cost_center = self._get_cost_center(request)

            # Create expense claim
            expense_claim = self._create_expense_claim(request, chapter, team, cost_center, employee_created)

            # Attach receipt if provided
            receipt_result = {"success": True}
            if request.receipt_attachment:
                receipt_result = self._attach_receipt(expense_claim.name, request.receipt_attachment)

            # Build success message
            success_message = _("Expense claim saved successfully and awaiting approval")
            if employee_created:
                success_message += _(" (Employee record created for your account)")
            if not receipt_result["success"]:
                success_message += _(" (Warning: Receipt attachment failed - please upload manually)")

            return OperationResult.ok(
                expense_claim,
                message=success_message,
                expense_claim_name=expense_claim.name,
                employee_created=employee_created,
                receipt_attached=receipt_result["success"],
            )

        except frappe.PermissionError:
            raise
        except Exception as e:
            frappe.log_error(f"Error submitting expense: {str(e)}", "Volunteer Expense Submission Error")
            return OperationResult.fail(str(e))

    def _build_request(
        self, expense_data: dict, additional_expenses: Optional[list]
    ) -> ExpenseSubmissionRequest:
        """Build ExpenseSubmissionRequest from raw dict data"""
        return ExpenseSubmissionRequest(
            description=expense_data.get("description", ""),
            amount=flt(expense_data.get("amount", 0)),
            expense_date=expense_data.get("expense_date", ""),
            organization_type=expense_data.get("organization_type", ""),
            category=expense_data.get("category", ""),
            chapter=expense_data.get("chapter"),
            team=expense_data.get("team"),
            notes=expense_data.get("notes"),
            receipt_attachment=expense_data.get("receipt_attachment"),
            volunteer=expense_data.get("volunteer"),
            additional_expenses=additional_expenses or [],
        )

    def _validate_request(self, request: ExpenseSubmissionRequest) -> list:
        """Validate expense submission request

        Returns:
            List of validation error messages
        """
        errors = []

        # Check required fields
        for field_name in self.REQUIRED_FIELDS:
            if not getattr(request, field_name, None):
                errors.append(_("Field {0} is required").format(field_name))

        # Validate organization selection
        if request.organization_type == "Chapter" and not request.chapter:
            errors.append(_("Please select a chapter"))
        elif request.organization_type == "Team" and not request.team:
            errors.append(_("Please select a team"))

        # Validate additional expense lines
        for i, add_expense in enumerate(request.additional_expenses, start=2):
            line_error = self._validate_expense_line(add_expense, i)
            if line_error:
                errors.append(line_error)

        return errors

    def _validate_expense_line(self, expense_dict: dict, line_number: int) -> Optional[str]:
        """Validate a single expense line.

        Args:
            expense_dict: Expense line data
            line_number: Line number for error messages (1-indexed)

        Returns:
            Error message if invalid, None otherwise
        """
        if not expense_dict.get("description"):
            return _("Line {0}: Description is required").format(line_number)

        amount = flt(expense_dict.get("amount", 0))
        if amount <= 0:
            return _("Line {0}: Amount must be greater than zero").format(line_number)

        if not expense_dict.get("category"):
            return _("Line {0}: Category is required").format(line_number)

        # Check expense account exists for category
        expense_account = frappe.db.get_value(
            "Expense Category", expense_dict.get("category"), "expense_account"
        )
        if not expense_account:
            return _("Line {0}: Category '{1}' does not have an expense account configured").format(
                line_number, expense_dict.get("category")
            )

        return None

    def _validate_organization_access(self, request: ExpenseSubmissionRequest) -> Optional[str]:
        """Validate volunteer has access to the organization

        Returns:
            Error message if validation fails, None otherwise
        """
        if request.organization_type == "Chapter":
            return self._validate_chapter_access(request.chapter)
        elif request.organization_type == "Team":
            return self._validate_team_access(request.team)
        elif request.organization_type == "National":
            return self._validate_national_access(request.category)
        return None

    def _validate_chapter_access(self, chapter_name: str) -> Optional[str]:
        """Validate volunteer has chapter membership"""
        if not self.volunteer_doc.member:
            return _("Chapter membership required for {0}").format(chapter_name)

        direct_membership = frappe.db.exists(
            "Chapter Member", {"parent": chapter_name, "member": self.volunteer_doc.member}
        )

        if not direct_membership:
            return _("Chapter membership required for {0}").format(chapter_name)
        return None

    def _validate_team_access(self, team_name: str) -> Optional[str]:
        """Validate volunteer has team membership"""
        team_membership = frappe.db.exists(
            "Team Member", {"parent": team_name, "volunteer": self.volunteer_name}
        )
        if not team_membership:
            return _("Team membership required for {0}").format(team_name)
        return None

    def _validate_national_access(self, category: str) -> Optional[str]:
        """Validate volunteer can submit national expenses"""
        # Policy-covered expenses allowed for all volunteers
        if category and self._is_policy_covered_expense(category):
            frappe.logger().info(
                f"Policy-covered national expense allowed for volunteer {self.volunteer_name}: {category}"
            )
            return None

        # Other national expenses require board membership
        if not self.settings.national_board_chapter:
            return None

        if not self.volunteer_doc.member:
            return _("National board membership required for non-policy national expenses")

        board_membership = frappe.db.exists(
            "Chapter Member",
            {"parent": self.settings.national_board_chapter, "member": self.volunteer_doc.member},
        )
        if not board_membership:
            return _("National board membership required for non-policy national expenses")
        return None

    def _is_policy_covered_expense(self, category: str) -> bool:
        """Check if expense category is covered by organizational policy.

        Policy-covered expenses can be claimed by any volunteer without board
        membership. The check uses two sources:

        1. Primary: Expense Category.policy_covered field (database configuration)
        2. Fallback: Keyword matching for common policy-covered types

        Common policy-covered categories include:
        - Travel/Transportation (commute reimbursements)
        - Materials/Supplies (event and office supplies)
        - Communication (phone, internet for volunteer work)

        Returns:
            True if category is covered by policy
        """
        if not category:
            return False

        # Primary check: database field (authoritative)
        expense_category = frappe.db.get_value("Expense Category", category, ["policy_covered"], as_dict=True)
        if expense_category and expense_category.get("policy_covered"):
            return True

        # Fallback: keyword matching for backward compatibility
        # These are common policy-covered expense types
        policy_keywords = [
            "travel",
            "transport",
            "materials",
            "supplies",
            "office",
            "promotional",
            "event",
            "communication",
            "phone",
            "internet",
        ]

        category_lower = category.lower()
        return any(keyword in category_lower for keyword in policy_keywords)

    def _ensure_employee_exists(self) -> bool:
        """Ensure volunteer has an employee record

        Returns:
            True if employee was created, False if already existed
        """
        if self.volunteer_doc.employee_id:
            return False

        frappe.logger().info(
            f"Creating employee record for volunteer {self.volunteer_doc.name} during expense submission"
        )

        employee_id = create_employee_for_approved_volunteer(self.volunteer_doc)
        if not employee_id:
            frappe.throw(
                _(
                    "Unable to create employee record automatically. "
                    "Please contact your administrator to set up your employee profile before submitting expenses."
                )
            )

        frappe.logger().info(
            f"Successfully created employee {employee_id} for volunteer {self.volunteer_doc.name}"
        )

        # Reload volunteer document to get updated employee_id
        self._volunteer_doc = None
        return True

    def _resolve_organization(self, request: ExpenseSubmissionRequest) -> tuple:
        """Resolve chapter and team from request

        Returns:
            Tuple of (chapter, team)
        """
        chapter = None
        team = None

        if request.organization_type == "Chapter":
            chapter = request.chapter
        elif request.organization_type == "Team":
            team = request.team
        elif request.organization_type == "National":
            if self.settings.national_board_chapter:
                chapter = self.settings.national_board_chapter
            else:
                frappe.throw(_("National chapter not configured in settings"))

        return chapter, team

    def _get_cost_center(self, request: ExpenseSubmissionRequest) -> str:
        """Get cost center for the expense"""
        from verenigingen.utils.cost_center_resolver import get_organization_cost_center

        return get_organization_cost_center(
            organization_type=request.organization_type,
            chapter=request.chapter,
            team=request.team,
        )

    def _create_expense_claim(
        self,
        request: ExpenseSubmissionRequest,
        chapter: Optional[str],
        team: Optional[str],
        cost_center: str,
        employee_created: bool,
    ):
        """Create the expense claim document"""
        # Get expense type and account
        expense_type = get_or_create_expense_type(request.category)
        expense_account = frappe.db.get_value("Expense Category", request.category, "expense_account")
        if not expense_account:
            frappe.throw(
                _(
                    "Expense Category '{0}' does not have an expense account configured. "
                    "Please contact your administrator."
                ).format(request.category)
            )

        # Get payable account
        payable_account = frappe.db.get_value("Company", self.company, "default_payable_account")
        if not payable_account:
            frappe.throw(
                _(
                    "No payable account configured for company {0}. "
                    "Please set default_payable_account in Company settings."
                ).format(self.company)
            )

        # Create expense claim
        expense_claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": self.volunteer_doc.employee_id,
                "posting_date": request.expense_date,
                "company": self.company,
                "cost_center": cost_center,
                "payable_account": payable_account,
                "approval_status": "Draft",
                "remark": request.notes,
                "status": "Draft",
                # Custom volunteer fields
                "custom_volunteer": self.volunteer_name,
                "custom_organization_type": request.organization_type,
                "custom_chapter": chapter,
                "custom_team": team,
                "custom_expense_category": request.category,
            }
        )

        # Add primary expense line
        expense_claim.append(
            "expenses",
            {
                "expense_date": request.expense_date,
                "expense_type": expense_type,
                "description": request.description,
                "amount": request.amount,
                "sanctioned_amount": request.amount,
                "cost_center": cost_center,
                "default_account": expense_account,
            },
        )

        # Add additional expense lines
        for add_expense in request.additional_expenses:
            add_expense_type = get_or_create_expense_type(add_expense.get("category"))
            add_expense_account = frappe.db.get_value(
                "Expense Category", add_expense.get("category"), "expense_account"
            )

            expense_claim.append(
                "expenses",
                {
                    "expense_date": add_expense.get("expense_date", request.expense_date),
                    "expense_type": add_expense_type,
                    "description": add_expense.get("description", ""),
                    "amount": flt(add_expense.get("amount", 0)),
                    "sanctioned_amount": flt(add_expense.get("amount", 0)),
                    "cost_center": cost_center,
                    "default_account": add_expense_account,
                },
            )

        # Insert with secure operation
        expense_result = secure_document_operation(
            operation="insert",
            doc=expense_claim,
            justification=f"Create volunteer expense claim for {self.volunteer_name} - Amount: {request.amount}",
            required_permissions=["Expense Claim:create"],
        )

        if not expense_result.success:
            frappe.log_error(
                f"Failed to create expense claim: {'; '.join(expense_result.errors)}",
                "Expense Claim Security",
            )
            frappe.throw(_("Failed to create expense claim: {0}").format("; ".join(expense_result.errors)))

        return frappe.get_doc("Expense Claim", expense_result.doc_name)

    def _attach_receipt(self, expense_claim_name: str, receipt_data: dict) -> dict:
        """Attach receipt to expense claim.

        Args:
            expense_claim_name: Expense claim document name
            receipt_data: Receipt file data

        Returns:
            dict: {"success": bool, "error": Optional[str]}
        """
        if not receipt_data or not isinstance(receipt_data, dict):
            return {"success": True}  # No receipt to attach is not an error

        try:
            if receipt_data.get("file_url") and receipt_data.get("frappe_file_name"):
                # Handle Frappe's built-in upload format
                self._attach_frappe_file(expense_claim_name, receipt_data)
            elif receipt_data.get("file_content"):
                # Handle custom base64 format
                self._attach_base64_file(expense_claim_name, receipt_data)
            else:
                frappe.logger().warning(
                    f"Receipt data provided but no valid file format found: {receipt_data}"
                )
                return {"success": False, "error": "Invalid file format"}

            return {"success": True}

        except Exception as attachment_error:
            # Log error but don't fail the entire expense submission
            frappe.log_error(
                f"Failed to attach receipt to expense claim {expense_claim_name}: {str(attachment_error)}",
                "Expense Receipt Attachment Error",
            )
            frappe.logger().warning(f"Receipt attachment failed for {expense_claim_name}: {attachment_error}")
            return {"success": False, "error": str(attachment_error)}

    def _attach_frappe_file(self, expense_claim_name: str, receipt_data: dict) -> None:
        """Attach a Frappe file to expense claim"""
        frappe.logger().info(f"Using Frappe built-in file: {receipt_data.get('frappe_file_name')}")

        file_doc = frappe.get_doc("File", receipt_data.get("frappe_file_name"))
        file_doc.attached_to_doctype = "Expense Claim"
        file_doc.attached_to_name = expense_claim_name
        file_doc.folder = "Home/Attachments"
        file_doc.is_private = 0

        file_result = secure_document_operation(
            operation="save",
            doc=file_doc,
            justification=f"Attach receipt file {file_doc.name} to expense claim {expense_claim_name} for volunteer {self.volunteer_name}",
            required_permissions=["File:write"],
        )

        if not file_result.success:
            raise frappe.ValidationError(
                f"File attachment failed: {file_result.errors[0] if file_result.errors else 'Unknown error'}"
            )

        frappe.logger().info(
            f"Successfully re-attached Frappe file {file_doc.name} to expense claim {expense_claim_name}"
        )

    def _attach_base64_file(self, expense_claim_name: str, receipt_data: dict) -> None:
        """Attach a base64-encoded file to expense claim"""
        import base64

        frappe.logger().info(f"Using custom base64 file: {receipt_data.get('file_name')}")

        file_content = base64.b64decode(receipt_data.get("file_content", ""))

        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": receipt_data.get("file_name"),
                "content": file_content,
                "attached_to_doctype": "Expense Claim",
                "attached_to_name": expense_claim_name,
                "folder": "Home/Attachments",
                "is_private": 0,
            }
        )

        file_result = secure_document_operation(
            operation="insert",
            doc=file_doc,
            justification=f"Create receipt file {receipt_data.get('file_name')} for expense claim {expense_claim_name} - volunteer {self.volunteer_name}",
            required_permissions=["File:create"],
        )

        if not file_result.success:
            raise frappe.ValidationError(
                f"Receipt upload failed: {file_result.errors[0] if file_result.errors else 'Unknown error'}"
            )

        frappe.logger().info(
            f"Successfully attached custom receipt {receipt_data.get('file_name')} to expense claim {expense_claim_name}"
        )

    def _log_tampering_attempt(self, submitted_volunteer: str) -> None:
        """Log parameter tampering attempt"""
        audit_logger = AuditLogger()
        audit_logger.log_security_event(
            event_type=AuditEventType.PARAMETER_TAMPERING,
            severity=AuditSeverity.ERROR,
            details={
                "submitted_volunteer": submitted_volunteer,
                "actual_volunteer": self.volunteer_name,
                "endpoint": "submit_expense",
                "user": frappe.session.user,
            },
        )


def get_expense_submission_service(volunteer_name: Optional[str] = None) -> VolunteerExpenseSubmissionService:
    """Factory function for expense submission service

    Args:
        volunteer_name: Optional volunteer name. If None, uses current user's volunteer.

    Returns:
        VolunteerExpenseSubmissionService instance
    """
    return VolunteerExpenseSubmissionService(volunteer_name)
