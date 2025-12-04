# File: verenigingen/services/approval/termination_approval_service.py
"""
Approval workflow service for membership termination requests.

Handles the multi-stage approval workflow with different rules based on
termination type (voluntary, disciplinary, non-payment, etc.).
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import now

from verenigingen.services.infrastructure.base_service import StatefulService


class TerminationApprovalService(StatefulService):
    """
    Service for managing termination request approval workflows.

    Approval Rules:
    - Voluntary/Non-payment: Direct to approved (no secondary approval)
    - Disciplinary (Policy Violation, Disciplinary Action, Expulsion):
      Requires secondary approval from authorized users
    """

    # Termination types requiring secondary approval
    DISCIPLINARY_TERMINATION_TYPES = ["Policy Violation", "Disciplinary Action", "Expulsion"]

    # Roles authorized to approve termination requests
    APPROVAL_ROLES = [
        "System Manager",
        "Verenigingen Administrator",
        "Chapter Administrator",
        "Board Member",
    ]

    def __init__(self, termination_request: "MembershipTerminationRequest" = None):
        """
        Initialize approval service for a termination request.

        Args:
            termination_request: The MembershipTerminationRequest document
        """
        super().__init__(service_name="TerminationApprovalService")
        self.request = termination_request

    def requires_secondary_approval(self) -> bool:
        """Check if termination type requires secondary approval"""
        return self.request.termination_type in self.DISCIPLINARY_TERMINATION_TYPES

    def set_approval_requirements(self) -> None:
        """Set approval requirements based on termination type"""
        # Only set defaults for new documents
        if not self.request.is_new():
            return

        if self.requires_secondary_approval():
            # Default to requiring secondary approval for disciplinary
            # But Verenigingen Administrators can uncheck this if needed
            self.request.requires_secondary_approval = 1
        else:
            self.request.requires_secondary_approval = 0

    def validate_submission_requirements(self) -> None:
        """Validate that all requirements are met before submission"""
        # Validate required fields
        if not self.request.termination_reason:
            frappe.throw(_("Termination reason is required"))

        # Check disciplinary documentation requirement
        if self.requires_secondary_approval() and not self.request.disciplinary_documentation:
            frappe.throw(_("Documentation is required for disciplinary actions"))

    def submit_for_approval(self) -> Dict[str, str]:
        """
        Submit the termination request for approval.

        Returns:
            Dict with status and message

        Raises:
            frappe.ValidationError: If validation fails
        """
        if self.request.status != "Draft":
            frappe.throw(_("Only draft requests can be submitted for approval"))

        # Validate requirements
        self.validate_submission_requirements()

        # Set approval requirements
        self.set_approval_requirements()

        # Determine next status based on approval requirements
        if self.request.requires_secondary_approval:
            self.request.status = "Pending"
            if not self.request.secondary_approver:
                frappe.throw(_("Secondary approver is required for this termination type"))
        else:
            # For simple terminations, go directly to approved
            self.request.status = "Approved"
            self.request.approved_by = frappe.session.user
            self.request.approval_date = now()

        # Calculate termination date
        self.request.calculate_termination_date()

        # Save the document
        self.request.save()

        # Add audit entry
        self.request.add_audit_entry("Submitted for Approval", f"Status changed to {self.request.status}")

        # Send notifications if needed
        if self.request.status == "Pending" and self.request.secondary_approver:
            self.send_approval_notification()

        frappe.msgprint(_("Termination request submitted for approval"))

        return {"status": self.request.status, "message": "Request submitted successfully"}

    def approve_request(self, decision: str, notes: str = "") -> Dict[str, str]:
        """
        Approve or reject the termination request.

        Args:
            decision: "approved" or "rejected"
            notes: Optional approver notes

        Returns:
            Dict with status and message

        Raises:
            frappe.ValidationError: If validation fails
        """
        if self.request.status not in ["Pending", "Draft"]:
            frappe.throw(_("Only pending or draft requests can be approved/rejected"))

        if decision == "approved":
            self._handle_approval(notes)
            frappe.msgprint(_("Termination request approved"))
            message = "Request approved successfully"

        elif decision == "rejected":
            self._handle_rejection(notes)
            frappe.msgprint(_("Termination request rejected"))
            message = "Request rejected successfully"

        else:
            frappe.throw(_("Invalid decision. Must be 'approved' or 'rejected'"))

        # Save the document
        self.request.save()

        return {"status": self.request.status, "message": message}

    def _handle_approval(self, notes: str) -> None:
        """Handle approval of the request"""
        self.request.status = "Approved"
        self.request.approved_by = frappe.session.user
        self.request.approval_date = now()
        self.request.approver_notes = notes

        # Calculate termination date
        self.request.calculate_termination_date()

        self.request.add_audit_entry("Request Approved", f"Approved by {frappe.session.user}")

    def _handle_rejection(self, notes: str) -> None:
        """Handle rejection of the request"""
        self.request.status = "Rejected"
        self.request.approved_by = frappe.session.user
        self.request.approval_date = now()
        self.request.approver_notes = notes

        self.request.add_audit_entry("Request Rejected", f"Rejected by {frappe.session.user}: {notes}")

    def handle_approved_status(self) -> None:
        """Handle when termination request transitions to approved status"""
        if not self.request.approved_by:
            self.request.approved_by = frappe.session.user
        if not self.request.approval_date:
            self.request.approval_date = now()

        # Calculate termination date using centralized logic
        self.request.calculate_termination_date()

        # Add to expulsion report if disciplinary
        if self.request.requires_secondary_approval:
            self._add_to_expulsion_report()

    def handle_rejected_status(self) -> None:
        """Handle when termination request is rejected"""
        if not self.request.approved_by:
            self.request.approved_by = frappe.session.user
        if not self.request.approval_date:
            self.request.approval_date = now()

    def send_approval_notification(self) -> None:
        """Send notification to approver"""
        try:
            if self.request.secondary_approver:
                # TODO: Implement email notification
                self.logger.info(f"Approval notification should be sent to {self.request.secondary_approver}")
        except Exception as e:
            self.logger.error(f"Failed to send approval notification: {str(e)}")

    def _add_to_expulsion_report(self) -> None:
        """Add disciplinary termination to expulsion report"""
        if self.request.termination_type not in self.DISCIPLINARY_TERMINATION_TYPES:
            return

        try:
            from frappe.utils import today

            # Create expulsion report entry
            expulsion_entry = frappe.new_doc("Expulsion Report Entry")
            expulsion_entry.member_name = self.request.member_name
            expulsion_entry.member_id = self.request.member
            expulsion_entry.expulsion_date = self.request.termination_date or today()
            expulsion_entry.expulsion_type = self.request.termination_type
            expulsion_entry.initiated_by = self.request.requested_by
            expulsion_entry.approved_by = self.request.approved_by
            expulsion_entry.documentation = self.request.disciplinary_documentation
            expulsion_entry.status = "Active"

            # Get member's primary chapter from Chapter Member table
            if frappe.has_permission("Chapter Member", "read"):
                member_chapters = frappe.get_all(
                    "Chapter Member",
                    filters={"member": self.request.member, "enabled": 1},
                    fields=["parent"],
                    order_by="chapter_join_date desc",
                    limit=1,
                )
                if member_chapters:
                    expulsion_entry.chapter_involved = member_chapters[0].parent
            else:
                self.logger.warning(
                    f"User {frappe.session.user} lacks permission to read Chapter Member - "
                    f"chapter information omitted from expulsion report"
                )

            # Use secure document operation
            from verenigingen.utils.secure_operations import secure_document_operation

            expulsion_result = secure_document_operation(
                operation="insert",
                doc=expulsion_entry,
                justification=f"Expulsion report entry creation for member termination {self.request.name}",
                required_permissions=["Expulsion Report:create"],
            )

            if not expulsion_result.success:
                self.logger.error(
                    f"Failed to create expulsion report entry: {'; '.join(expulsion_result.errors)}"
                )

            self.logger.info(f"Added expulsion report entry for {self.request.member_name}")

        except Exception as e:
            self.logger.error(f"Failed to create expulsion report entry: {str(e)}")

    def validate_approver_permissions(self, user: str) -> None:
        """
        Validate that the user has permission to approve termination requests.

        Args:
            user: User ID to validate

        Raises:
            frappe.ValidationError: If user is not authorized
        """
        # Check if user exists and is enabled
        if not frappe.db.exists("User", user):
            frappe.throw(_("Approver {0} does not exist").format(user))

        user_doc = frappe.get_doc("User", user)
        if not user_doc.enabled:
            frappe.throw(_("Approver {0} is disabled").format(user))

        # Check if user has appropriate roles
        user_roles = frappe.get_roles(user)

        if not any(role in user_roles for role in self.APPROVAL_ROLES):
            frappe.throw(_("User {0} does not have permission to approve termination requests").format(user))

    def get_eligible_approvers(
        self,
        doctype: Optional[str] = None,
        txt: Optional[str] = None,
        searchfield: Optional[str] = None,
        start: int = 0,
        page_len: int = 20,
        filters: Optional[Dict] = None,
    ) -> List[Tuple[str, str]]:
        """
        Get list of users eligible to approve termination requests.

        Used as query function for Link field - returns list of tuples.

        Args:
            doctype: DocType name (unused, required by Frappe API)
            txt: Search text
            searchfield: Field to search (unused, required by Frappe API)
            start: Offset for pagination
            page_len: Number of results per page
            filters: Additional filters (unused)

        Returns:
            List of (user_id, full_name) tuples
        """
        try:
            # Build parameterized conditions
            conditions = ["u.enabled = 1"]
            query_params = {
                "roles": self.APPROVAL_ROLES,
                "start": start,
                "page_len": page_len,
            }

            if txt:
                conditions.append("(u.name LIKE %(txt)s OR u.full_name LIKE %(txt)s OR u.email LIKE %(txt)s)")
                query_params["txt"] = f"%{txt}%"

            where_clause = " AND ".join(conditions)

            # Get users with approval roles - fully parameterized query
            users = frappe.db.sql(
                f"""
                SELECT DISTINCT u.name, u.full_name
                FROM `tabUser` u
                INNER JOIN `tabHas Role` hr ON hr.parent = u.name
                WHERE hr.role IN %(roles)s
                AND {where_clause}
                ORDER BY u.full_name
                LIMIT %(start)s, %(page_len)s
                """,
                query_params,
                as_list=True,
            )

            return users

        except Exception as e:
            self.logger.error(f"Error getting eligible approvers: {str(e)}")
            return []
