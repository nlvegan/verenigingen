# File: verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py

from typing import Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now, today

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


class MembershipTerminationRequest(Document):
    def validate(self):
        self.set_defaults()
        self.calculate_termination_date()  # Calculate date so it's visible in all statuses
        self.set_approval_requirements()
        self.validate_permissions()
        self.validate_dates()
        self.validate_termination_request()  # Moved from hooks.py

    def get_grace_period_days(self) -> int:
        """Get grace period days from Verenigingen Settings"""
        settings = frappe.get_cached_doc("Verenigingen Settings")
        return settings.default_grace_period_days or 30  # Fallback to 30 if not set

    def calculate_termination_date(self) -> None:
        """Calculate termination date from member request date or today"""
        if not self.termination_date:
            if self.member_request_date:
                if self.apply_grace_period:
                    grace_days = self.get_grace_period_days()
                    self.termination_date = add_days(self.member_request_date, grace_days)
                else:
                    self.termination_date = self.member_request_date
            else:
                # Disciplinary/Administrative terminations without member request date use today
                self.termination_date = today()

    def set_defaults(self):
        """Set default values"""
        if not self.requested_by:
            self.requested_by = frappe.session.user
        if not self.request_date:
            self.request_date = today()

    def before_save(self):
        """UPDATED: Now uses TerminationAuditService.log_document_update()"""
        from verenigingen.services.termination import TerminationAuditService

        TerminationAuditService.log_document_update(self)

    def after_insert(self):
        """UPDATED: Now uses TerminationAuditService.log_request_created()"""
        from verenigingen.services.termination import TerminationAuditService

        TerminationAuditService.log_request_created(self)

    def on_update_after_submit(self):
        """Handle status changes after document is submitted (workflow changes)"""
        if self.has_value_changed("status"):
            self.handle_status_change()

    def on_submit(self):
        """Called when document is submitted via workflow"""
        if self.status == "Executed":
            self.execute_termination_internal()

    def handle_status_change(self):
        """EXTRACTED: Moved to TerminationAuditService.log_status_change()

        Handle workflow status changes.
        Now delegates to TerminationAuditService for audit trail, then handles transitions.
        """
        from verenigingen.services.termination import TerminationAuditService

        # Log status change to audit trail
        TerminationAuditService.log_status_change(self)

        # Skip if already being executed by the service (prevents recursive execution)
        if getattr(self.flags, "skip_status_change_hook", False):
            return

        # Handle specific status transitions
        old_status = self.get_doc_before_save().status if self.get_doc_before_save() else None
        new_status = self.status

        if new_status == "Executed" and old_status != "Executed":
            frappe.logger().info(f"Executing termination for request {self.name}")
            self.execute_termination_internal()
        elif new_status == "Approved":
            self.handle_approved_status()
        elif new_status == "Rejected":
            self.handle_rejected_status()

    def execute_termination_internal(self) -> bool:
        """EXTRACTED: Moved to TerminationExecutionService.execute()

        Internal method for executing termination using safe integration methods.
        Now delegates to TerminationExecutionService for better testability and reusability.
        """
        from verenigingen.services.termination import TerminationExecutionService

        return TerminationExecutionService.execute(self)

    def execute_system_updates_safely(self) -> Dict:
        """EXTRACTED: Moved to TerminationExecutionService.execute_system_updates()

        Execute system updates using declarative operation pattern.
        Now delegates to TerminationExecutionService for better testability.
        """
        from verenigingen.services.termination import TerminationExecutionService

        return TerminationExecutionService.execute_system_updates(self)

    def add_audit_entry(self, action: str, details: str, is_system: bool = False) -> None:
        """EXTRACTED: Moved to TerminationAuditService.add_entry()

        Add an entry to the audit trail with proper user handling.
        Now delegates to TerminationAuditService for centralized audit management.
        """
        from verenigingen.services.termination import TerminationAuditService

        return TerminationAuditService.add_entry(self, action, details, is_system)

    def set_approval_requirements(self):
        """Set whether secondary approval is required based on termination type"""
        from verenigingen.services.approval import TerminationApprovalService

        approval_service = TerminationApprovalService(self)
        approval_service.set_approval_requirements()

    def handle_approved_status(self):
        """Handle when termination request is approved"""
        from verenigingen.services.approval import TerminationApprovalService

        approval_service = TerminationApprovalService(self)
        approval_service.handle_approved_status()

    def handle_rejected_status(self):
        """Handle when termination request is rejected"""
        from verenigingen.services.approval import TerminationApprovalService

        approval_service = TerminationApprovalService(self)
        approval_service.handle_rejected_status()

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def submit_for_approval(self):
        """Submit the termination request for approval"""
        from verenigingen.services.approval import TerminationApprovalService

        approval_service = TerminationApprovalService(self)
        return approval_service.submit_for_approval()

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def approve_request(self, decision, notes=""):
        """Approve or reject the termination request"""
        from verenigingen.services.approval import TerminationApprovalService

        approval_service = TerminationApprovalService(self)
        return approval_service.approve_request(decision, notes)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def execute_termination(self):
        """EXTRACTED: Moved to TerminationExecutionService.execute_from_api()

        Execute the termination request via API.
        Now delegates to TerminationExecutionService for better testability.
        """
        from verenigingen.services.termination import TerminationExecutionService

        return TerminationExecutionService.execute_from_api(self)

    def validate_permissions(self):
        """Validate user permissions for different termination types"""
        from verenigingen.permissions import can_access_termination_functions, can_terminate_member

        # Check if user can access termination functions in general
        if not can_access_termination_functions():
            frappe.throw(_("You don't have permission to access termination functions"))

        # Check if user can terminate this specific member
        if self.member and not can_terminate_member(self.member):
            frappe.throw(_("You don't have permission to terminate this member"))

    def validate_dates(self):
        """Validate termination and grace period dates"""
        # For voluntary exits, termination date shouldn't be before member request date
        if self.member_request_date and self.termination_date:
            if getdate(self.termination_date) < getdate(self.member_request_date):
                frappe.throw(_("Termination date cannot be before member request date"))

    def validate_termination_request(self):
        """Additional validation logic for termination requests (moved from hooks.py)"""
        # Skip validation if we're executing - member status was just changed by this process
        if self.status == "Executed":
            return

        # Skip validation during error recovery
        if getattr(self.flags, "skip_termination_validation", False):
            return

        # Validate that member exists and is active
        if not frappe.db.exists("Member", self.member):
            frappe.throw(_("Member {0} does not exist").format(self.member))

        member_status = frappe.db.get_value("Member", self.member, "status")
        # Allow termination of Expired members (formal closure), but not already Terminated/Banned/Deceased
        if member_status in ["Terminated", "Banned", "Deceased"]:
            frappe.throw(_("Cannot terminate member with status: {0}").format(member_status))

        # Validate commitment period for voluntary terminations
        # Disciplinary terminations bypass this check
        if self.termination_type == "Voluntary":
            self.validate_commitment_period()

        # Validate disciplinary terminations
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        if self.termination_type in disciplinary_types:
            # Require documentation
            if not self.disciplinary_documentation:
                frappe.throw(_("Documentation is required for disciplinary terminations"))

            # Require secondary approver for pending approval status
            if not self.secondary_approver and self.status == "Pending Approval":
                frappe.throw(_("Secondary approver is required for disciplinary terminations"))

            # Validate approver permissions
            if self.secondary_approver:
                from verenigingen.services.approval import TerminationApprovalService

                TerminationApprovalService.validate_approver_permissions(self.secondary_approver)

    def validate_commitment_period(self):
        """
        Validate that member has completed their commitment period.
        Members who receive welcome gifts must remain for minimum 1 year.
        """
        # Get the member's current active membership
        current_membership = frappe.db.get_value("Member", self.member, "current_membership_plan")

        if not current_membership:
            # No active membership, no commitment to check
            return

        # Get the commitment end date from the membership
        commitment_end_date = frappe.db.get_value("Membership", current_membership, "commitment_end_date")

        if not commitment_end_date:
            # No commitment period set, allow termination
            return

        # Check if termination date is before commitment end date
        if getdate(self.termination_date) < getdate(commitment_end_date):
            frappe.throw(
                _(
                    "Member cannot quit before {0} due to welcome gift commitment period. "
                    "They must remain a member for at least one year from their membership start date."
                ).format(frappe.format(commitment_end_date, {"fieldtype": "Date"})),
                title=_("Commitment Period Not Met"),
            )

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def get_termination_preview(self):
        """Get preview of what will be affected by this termination"""
        from verenigingen.utils.termination_utils import validate_termination_readiness

        return validate_termination_readiness(self.member)

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def simulate_execution(self):
        """Simulate what would happen if this termination were executed"""
        from verenigingen.utils.termination_utils import get_termination_impact_summary

        return get_termination_impact_summary(self.member)


# Module-level function for workflow integration
def on_workflow_action(doc, action):
    """Called by workflow when action is taken"""
    frappe.logger().info(f"Workflow action '{action}' taken on {doc.name}")

    if action == "Execute" and doc.status == "Executed":
        frappe.logger().info(f"Executing termination via workflow for {doc.name}")
        doc.execute_termination_internal()


# Module-level function for document hooks
def handle_status_change(doc, method=None):
    """Handle status changes for termination requests"""
    if hasattr(doc, "handle_status_change"):
        doc.handle_status_change()


# Public API methods that can be called from outside
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_termination_impact_preview(member):
    """Public API to get termination impact preview"""
    from verenigingen.utils.termination_utils import validate_termination_readiness

    readiness_data = validate_termination_readiness(member)

    # Return the impact data in the format expected by the frontend
    if readiness_data and "impact" in readiness_data:
        impact = readiness_data["impact"]

        # Add customer linkage info
        member_doc = frappe.get_doc("Member", member)
        impact["customer_linked"] = bool(member_doc.customer)

        return impact
    else:
        # Fallback - return empty impact data
        return {
            "active_memberships": 0,
            "sepa_mandates": 0,
            "mollie_mandates": 0,
            "board_positions": 0,
            "outstanding_invoices": 0,
            "active_dues_schedules": 0,
            "volunteer_records": 0,
            "pending_volunteer_expenses": 0,
            "employee_records": 0,
            "user_account": False,
            "customer_linked": False,
        }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def execute_safe_member_termination(member, termination_type, termination_date=None):
    """Public API to execute termination using safe methods"""
    from verenigingen.api.termination_api import execute_safe_termination

    return execute_safe_termination(member, termination_type, termination_date)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_member_termination_status(member):
    """Get termination status for a member - redirect to member_utils"""
    from verenigingen.verenigingen.doctype.member.member_utils import get_member_termination_status

    return get_member_termination_status(member)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_member_termination_history(member):
    """Get termination history for a member"""
    try:
        # Get all termination requests for this member
        termination_requests = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member},
            fields=[
                "name",
                "termination_type",
                "termination_reason",
                "status",
                "request_date",
                "termination_date",
                "execution_date",
                "requested_by",
                "approved_by",
                "executed_by",
            ],
            order_by="request_date desc",
        )

        # Get audit trail for each request
        for request in termination_requests:
            audit_trail = frappe.get_all(
                "Termination Audit Entry",
                filters={"parent": request.name},
                fields=["timestamp", "action", "user", "details", "system_action"],
                order_by="timestamp desc",
            )
            request["audit_trail"] = audit_trail

        return {
            "success": True,
            "termination_requests": termination_requests,
            "total_requests": len(termination_requests),
        }

    except Exception as e:
        frappe.log_error(f"Error getting termination history for {member}: {str(e)}")
        return {"success": False, "error": str(e), "termination_requests": []}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_termination_statistics():
    """Get termination statistics for dashboard display"""
    try:
        # Get statistics for different termination types and statuses
        stats = {}

        # Total termination requests
        stats["total_requests"] = frappe.db.count("Membership Termination Request")

        # By status
        status_counts = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabMembership Termination Request`
            GROUP BY status
        """,
            as_dict=True,
        )

        stats["by_status"] = {item.status: item.count for item in status_counts}

        # By termination type
        type_counts = frappe.db.sql(
            """
            SELECT termination_type, COUNT(*) as count
            FROM `tabMembership Termination Request`
            GROUP BY termination_type
        """,
            as_dict=True,
        )

        stats["by_type"] = {item.termination_type: item.count for item in type_counts}

        # Recent requests (last 30 days)
        recent_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMembership Termination Request`
            WHERE request_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """,
            as_dict=True,
        )

        stats["recent_requests"] = recent_count[0].count if recent_count else 0

        # Pending approvals
        pending_count = frappe.db.count(
            "Membership Termination Request", filters={"status": ["in", ["Pending Approval", "Under Review"]]}
        )

        stats["pending_approvals"] = pending_count

        return {"success": True, "statistics": stats}

    except Exception as e:
        frappe.log_error(f"Error getting termination statistics: {str(e)}")
        return {"success": False, "error": str(e), "statistics": {}}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_eligible_approvers(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
    """Get list of users eligible to approve termination requests

    Used as query function for Link field - returns list of tuples
    """
    from verenigingen.services.approval import TerminationApprovalService

    return TerminationApprovalService.get_eligible_approvers(
        doctype=doctype, txt=txt, searchfield=searchfield, start=start, page_len=page_len, filters=filters
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.REPORTING)
def generate_expulsion_report(filters=None):
    """Generate expulsion report based on filters"""
    try:
        if not filters:
            filters = {}

        # Build query conditions
        conditions = ["1=1"]
        values = []

        if filters.get("from_date"):
            conditions.append("ter.termination_date >= %s")
            values.append(filters["from_date"])

        if filters.get("to_date"):
            conditions.append("ter.termination_date <= %s")
            values.append(filters["to_date"])

        if filters.get("termination_type"):
            conditions.append("ter.termination_type = %s")
            values.append(filters["termination_type"])

        if filters.get("chapter"):
            conditions.append("mem.current_chapter_display = %s")
            values.append(filters["chapter"])

        # Add disciplinary/expulsion filter using parameterized query
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        # Build IN clause with proper number of placeholders
        in_placeholders = ", ".join(["%s"] * len(disciplinary_types))
        conditions.append(f"ter.termination_type IN ({in_placeholders})")
        values.extend(disciplinary_types)  # Add each type individually to values list

        # Get expulsion data - safe from SQL injection via parameterized WHERE clause
        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                ter.name as termination_request,
                ter.member,
                mem.full_name as member_name,
                mem.email as member_email,
                mem.current_chapter_display,
                ter.termination_type,
                ter.termination_reason,
                ter.termination_date,
                ter.execution_date,
                ter.executed_by,
                ter.status
            FROM `tabMembership Termination Request` ter
            LEFT JOIN `tabMember` mem ON ter.member = mem.name
            WHERE {where_clause}
            ORDER BY ter.termination_date DESC
        """

        expulsions = frappe.db.sql(query, tuple(values), as_dict=True)

        # Get summary statistics
        summary = {
            "total_expulsions": len(expulsions),
            "by_type": {},
            "by_chapter": {},
            "date_range": {"from": filters.get("from_date"), "to": filters.get("to_date")},
        }

        for exp in expulsions:
            # Count by type
            exp_type = exp.termination_type
            summary["by_type"][exp_type] = summary["by_type"].get(exp_type, 0) + 1

            # Count by chapter
            chapter = exp.current_chapter_display or "Unknown"
            summary["by_chapter"][chapter] = summary["by_chapter"].get(chapter, 0) + 1

        return {"success": True, "expulsions": expulsions, "summary": summary}

    except Exception as e:
        frappe.log_error(f"Error generating expulsion report: {str(e)}")
        return {"success": False, "error": str(e), "expulsions": [], "summary": {}}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def initiate_disciplinary_termination(member, reason, evidence=None, reporter=None):
    """Initiate disciplinary termination procedure for a member"""
    try:
        # Validate input
        if not member:
            frappe.throw(_("Member is required"))

        if not reason:
            frappe.throw(_("Reason is required for disciplinary termination"))

        # Check if member exists and is active
        member_doc = frappe.get_doc("Member", member)
        if member_doc.membership_status in ["Terminated", "Suspended"]:
            frappe.throw(_("Member is already terminated or suspended"))

        # Check if there's already a pending disciplinary request
        existing_request = frappe.db.exists(
            "Membership Termination Request",
            {
                "member": member,
                "termination_type": "Disciplinary",
                "status": ["in", ["Draft", "Pending Approval", "Under Review"]],
            },
        )

        if existing_request:
            frappe.throw(_("There is already a pending disciplinary termination request for this member"))

        # Create disciplinary termination request
        termination_request = frappe.new_doc("Membership Termination Request")
        termination_request.member = member
        termination_request.termination_type = "Disciplinary"
        termination_request.termination_reason = reason
        termination_request.requested_by = reporter or frappe.session.user
        termination_request.request_date = today()
        termination_request.status = "Draft"
        termination_request.requires_board_approval = 1
        termination_request.requires_governance_review = 1

        # Add evidence if provided
        if evidence:
            termination_request.supporting_documentation = evidence

        # Set disciplinary-specific fields
        termination_request.disciplinary_procedure = 1
        termination_request.investigation_required = 1

        # Save the request
        termination_request.insert()
        termination_request.add_audit_entry(
            "Disciplinary Procedure Initiated",
            f"Disciplinary termination initiated by {frappe.session.user}. Reason: {reason}",
        )

        # Submit for approval workflow
        termination_request.submit_for_approval()

        # Send notifications to relevant parties
        termination_request.send_approval_notification()

        # Notify the member if required by policy
        # TODO: Add notify_member_of_disciplinary_action field to Verenigingen Settings doctype
        # Future enhancement: send_disciplinary_notification(member, termination_request.name)

        return {
            "success": True,
            "termination_request": termination_request.name,
            "message": _("Disciplinary termination procedure has been initiated for {0}").format(
                member_doc.full_name
            ),
        }

    except Exception as e:
        frappe.log_error(f"Error initiating disciplinary termination for {member}: {str(e)}")
        return {"success": False, "error": str(e)}


def send_disciplinary_notification(member, termination_request):
    """Send notification to member about disciplinary action"""
    try:
        member_doc = frappe.get_doc("Member", member)

        # MIGRATED: Use unified EmailService for disciplinary notifications
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Prepare context for template
        context = {
            "member": member_doc,
            "member_name": member_doc.full_name,
            "reference": termination_request,
            "termination_request": termination_request,
        }

        # Send email if member has email
        if member_doc.email:
            result = email_service.send_notification(
                notification_type="member_suspension",  # Use existing notification type
                recipients=[member_doc.email],
                data=context,
                reference_doctype="Membership Termination Request",
                reference_name=termination_request,
            )

            return result.get("success", False)

        return False

    except Exception as e:
        frappe.log_error(f"Error sending disciplinary notification to {member}: {str(e)}")
        return False
