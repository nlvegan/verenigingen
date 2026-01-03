# File: verenigingen/services/approval/contribution_amendment_approval_service.py
"""
Approval workflow service for contribution amendment requests.

Handles the approval, rejection, and application of fee changes, billing changes,
and membership type changes. Follows the same delegation pattern as
TerminationApprovalService for consistency.

Key Responsibilities:
- Auto-approval logic for fee changes that respect minimums
- Manual approval/rejection workflows
- Amendment application to memberships and dues schedules
- Conflicting amendment cancellation
- Approval/rejection notifications
"""

from typing import TYPE_CHECKING, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.validation_utilities import DateRangeValidator

if TYPE_CHECKING:
    from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
        ContributionAmendmentRequest,
    )

# Configuration Constants
MINIMUM_FEE_PERCENTAGE = 0.3  # 30% of base amount
STUDENT_MINIMUM_FEE_PERCENTAGE = 0.5  # 50% of base amount for students
ABSOLUTE_MINIMUM_FEE = 5.0  # EUR 5 absolute minimum


class ContributionAmendmentApprovalService(StatefulService):
    """
    Service for managing contribution amendment approval workflows.

    Handles:
    - Auto-approval decision logic (minimum fee validation)
    - Manual approval/rejection workflows
    - Amendment application to memberships and dues schedules
    - Conflicting amendment cancellation
    - Approval/rejection notifications

    Approval Rules:
    - Fee changes respecting minimums: Auto-approved
    - Fee changes below minimums: Manual approval required
    - Membership type changes: Always manual approval required
    """

    def __init__(self, amendment_request: "ContributionAmendmentRequest" = None):
        """
        Initialize approval service for a contribution amendment request.

        Args:
            amendment_request: The ContributionAmendmentRequest document
        """
        super().__init__(service_name="ContributionAmendmentApprovalService")
        self.request = amendment_request

    # ====== Auto-Approval Logic ======

    def check_respects_minimum_fee(self) -> bool:
        """
        Check if requested amount respects minimum fee requirements.

        Returns:
            bool: True if requested amount meets minimum fee requirements, False otherwise
        """
        if not self.request.requested_amount or not self.request.membership:
            return False

        try:
            membership = frappe.get_doc("Membership", self.request.membership)
            if not membership.membership_type:
                return True  # No membership type means no minimum to enforce

            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            if not membership_type.dues_schedule_template:
                return True  # No template means no minimum to enforce

            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
            if not template.suggested_amount:
                return True  # No suggested amount means no minimum to enforce

            base_amount = template.suggested_amount

            # Calculate minimum fee (configurable percentage of base or absolute minimum)
            minimum_fee = max(base_amount * MINIMUM_FEE_PERCENTAGE, ABSOLUTE_MINIMUM_FEE)

            # Check if member is a student (gets higher minimum percentage)
            if self.request.member:
                member = frappe.get_doc("Member", self.request.member)
                if getattr(member, "student_status", 0):
                    minimum_fee = max(base_amount * STUDENT_MINIMUM_FEE_PERCENTAGE, ABSOLUTE_MINIMUM_FEE)

            # CRITICAL: Ensure minimum respects template's minimum_amount and membership type minimum
            template_minimum = float(template.minimum_amount or 0)
            membership_type_minimum = float(membership_type.minimum_amount or 0)
            minimum_fee = max(minimum_fee, template_minimum, membership_type_minimum)

            # Return True if requested amount meets or exceeds minimum
            return self.request.requested_amount >= minimum_fee

        except Exception as e:
            self.logger.warning(f"Error checking minimum fee for amendment {self.request.name}: {str(e)}")
            return False  # If we can't determine minimum, require manual approval

    def set_auto_approval_status(self) -> None:
        """
        Determine and set approval status during creation.

        Business Rules:
        - Fee changes respecting minimums: Auto-approved
        - Fee changes below minimums: Pending approval
        - Membership type changes: Always pending approval
        """
        # Enhanced auto-approval logic - only after all validations pass
        if (
            self.request.amendment_type == "Fee Change"
            and self.request.requested_amount
            and self.request.current_amount
        ):
            # Check if requested amount respects minimum fee requirements
            respects_minimum = self.check_respects_minimum_fee()

            # AUTO-APPROVE ALL DUES RATE CHANGES that respect minimums
            if respects_minimum:
                self.request.status = "Approved"
                self.request.approved_by = frappe.session.user
                self.request.approved_date = now_datetime()
                self.request.internal_notes = "Auto-approved: Dues rate change respects minimum requirements"
            else:
                # Require manual approval
                self.request.status = "Pending Approval"
                self.request.internal_notes = "Requires approval: requested amount below minimum fee"

        # MEMBERSHIP TYPE CHANGES always require approval
        elif self.request.amendment_type == "Membership Type Change":
            self.request.status = "Pending Approval"
            self.request.internal_notes = "Requires approval: Membership type changes require manual review"

    # ====== Manual Approval Methods ======

    def approve_amendment(self, approval_notes: Optional[str] = None) -> None:
        """
        Approve the amendment request.

        Args:
            approval_notes: Optional notes to add to the approval for audit trail

        Raises:
            frappe.ValidationError: If amendment is not in "Pending Approval" status
        """
        if self.request.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be approved"))

        # Cancel any other pending or approved amendments for the same member
        self.cancel_conflicting_amendments()

        self.request.status = "Approved"
        self.request.approved_by = frappe.session.user
        self.request.approved_date = now_datetime()

        if approval_notes:
            self.request.internal_notes = (
                self.request.internal_notes or ""
            ) + f"\nApproval Notes: {approval_notes}"

        self.request.save()

        # Notify the requester
        self.send_approval_notification(approval_notes)
        frappe.msgprint(_("Amendment approved successfully"))

    def reject_amendment(self, rejection_reason: str) -> None:
        """
        Reject the amendment request.

        Args:
            rejection_reason: Required reason for rejection (stored for audit trail)

        Raises:
            frappe.ValidationError: If amendment is not in "Pending Approval" status
        """
        if self.request.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be rejected"))

        self.request.status = "Rejected"
        self.request.rejection_reason = rejection_reason
        self.request.save()

        # Notify the requester
        self.send_rejection_notification()
        frappe.msgprint(_("Amendment rejected"))

    # ====== Application Methods ======

    def apply_amendment(self) -> Dict[str, str]:
        """
        Apply the approved amendment to the membership and dues schedule.

        Returns:
            dict: Operation result with status ("success", "error", "warning") and message

        Raises:
            frappe.ValidationError: If amendment is not approved or other validation fails
        """
        if self.request.status != "Approved":
            frappe.msgprint(_("Only approved amendments can be applied"), indicator="red")
            return {"status": "error", "message": "Amendment not approved"}

        # For future-dated amendments, only apply if explicitly requested
        if DateRangeValidator.is_date_in_future(self.request.effective_date):
            if not getattr(self.request, "_force_apply", False):
                effective_date_formatted = frappe.utils.formatdate(self.request.effective_date)
                frappe.msgprint(
                    _(
                        "This amendment is scheduled to be applied automatically on {0}. "
                        "You cannot apply it manually before the effective date."
                    ).format(effective_date_formatted),
                    title=_("Amendment Not Ready"),
                    indicator="orange",
                )
                return {"status": "warning", "message": "Amendment scheduled for future date"}

        try:
            membership = frappe.get_doc("Membership", self.request.membership)

            if self.request.amendment_type == "Fee Change":
                self.apply_fee_change(membership)
            elif self.request.amendment_type == "Billing Interval Change":
                self.apply_billing_change(membership)
            elif self.request.amendment_type == "Membership Type Change":
                self.apply_membership_type_change(membership)

            self.request.status = "Applied"
            self.request.applied_date = now_datetime()
            self.request.applied_by = frappe.session.user
            self.request.save()

            frappe.msgprint(_("Amendment applied successfully"), indicator="green")
            return {"status": "success", "message": "Amendment applied successfully"}

        except Exception as e:
            self.logger.error(f"Error applying amendment {self.request.name}: {str(e)}")
            frappe.msgprint(_("Error applying amendment: {0}").format(str(e)), indicator="red")
            return {"status": "error", "message": f"Error applying amendment: {str(e)}"}

    def apply_fee_change(self, membership) -> None:
        """Apply fee change to membership."""
        try:
            # IDEMPOTENCY CHECK: Skip if member's current dues_rate already matches
            member_doc = frappe.get_doc("Member", self.request.member)
            current_rate = getattr(member_doc, "dues_rate", 0) or 0

            if current_rate == self.request.requested_amount:
                self.logger.info(
                    f"Amendment {self.request.name} already applied - member {self.request.member} "
                    f"dues_rate already matches requested amount EUR{self.request.requested_amount}"
                )
                self.request.processing_notes = (
                    f"Skipped: Member dues_rate already set to EUR{self.request.requested_amount} "
                    f"(amendment appears to have been applied previously)"
                )
                return

            # Check if this is a pure fee change (no membership type change)
            is_pure_fee_change = self.request.amendment_type == "Fee Change" and (
                not self.request.requested_membership_type
                or self.request.requested_membership_type == self.request.current_membership_type
            )

            if is_pure_fee_change:
                # For pure fee changes, just update the existing dues schedule
                if self.request.current_dues_schedule:
                    self._update_existing_schedule()
                else:
                    # Member has no dues schedule - error
                    frappe.throw(
                        _(
                            "Cannot apply fee change: Member {0} has no active dues schedule. "
                            "Please create a dues schedule first."
                        ).format(self.request.member)
                    )
            else:
                # For membership type changes or other complex changes, create new schedule
                dues_schedule_name = self.create_dues_schedule_for_amendment()
                self.request.new_dues_schedule = dues_schedule_name
                self.request.processing_notes = f"Dues schedule {dues_schedule_name} created for amendment."

            # Update member record
            self._update_member_fee_fields(member_doc, current_rate)

        except Exception as e:
            frappe.throw(_("Error applying fee change: {0}").format(str(e)))

    def _update_existing_schedule(self) -> None:
        """Update the existing dues schedule with new fee amount."""
        schedule_doc = frappe.get_doc("Membership Dues Schedule", self.request.current_dues_schedule)
        schedule_doc.dues_rate = self.request.requested_amount
        schedule_doc.contribution_mode = "Custom"
        schedule_doc.uses_custom_amount = 1
        schedule_doc.custom_amount_approved = 1
        schedule_doc.custom_amount_reason = f"Amendment Request: {self.request.reason}"
        schedule_doc.custom_amount_approved_by = frappe.session.user
        schedule_doc.custom_amount_approved_date = today()

        # Add amendment note
        schedule_doc.notes = (
            schedule_doc.notes or ""
        ) + f"\nAmended via {self.request.name} on {today()}: EUR{self.request.requested_amount:.2f}"

        # Set flag to bypass duplicate schedule validation
        schedule_doc.flags.from_amendment = True

        schedule_result = secure_document_operation(
            operation="save",
            doc=schedule_doc,
            justification=f"Apply fee change amendment {self.request.name} to dues schedule",
            required_permissions=["Membership Dues Schedule:write"],
        )

        if not schedule_result.success:
            frappe.throw(
                _("Failed to apply fee change to schedule: {0}").format("; ".join(schedule_result.errors))
            )

        # Add comment
        schedule_doc.add_comment(
            text=f"Fee adjusted via amendment {self.request.name}. New amount: EUR{self.request.requested_amount:.2f}"
        )

        self.request.new_dues_schedule = self.request.current_dues_schedule
        self.request.processing_notes = (
            f"Updated existing dues schedule {self.request.current_dues_schedule} with new fee amount."
        )

    def _update_member_fee_fields(self, member_doc, actual_current_rate: float) -> None:
        """Update member record with new fee override fields."""
        member_doc.reload()

        # Record fee change in history
        dues_schedule_ref = self.request.new_dues_schedule or ""
        member_doc.record_fee_change(
            {
                "change_date": now_datetime(),
                "old_amount": actual_current_rate,
                "new_amount": self.request.requested_amount,
                "reason": f"Amendment {self.request.name}: {self.request.reason}",
                "changed_by": frappe.session.user,
                "dues_schedule_name": dues_schedule_ref,
                "dues_schedule_action": f"Applied via {dues_schedule_ref}",
                "amendment_request_name": self.request.name,
            }
        )

        member_doc.dues_rate = self.request.requested_amount
        member_doc.fee_override_reason = f"Amendment: {self.request.reason}"
        member_doc.fee_override_date = today()
        member_doc.fee_override_by = frappe.session.user
        member_doc._system_update = True

        member_result = secure_document_operation(
            operation="save",
            doc=member_doc,
            justification=f"Apply fee override from amendment {self.request.name}",
            required_permissions=["Member:write"],
        )

        if not member_result.success:
            frappe.throw(
                _("Failed to apply fee override to member: {0}").format("; ".join(member_result.errors))
            )

    def apply_billing_change(self, membership) -> None:
        """Apply billing interval change."""
        frappe.throw(_("Billing interval changes are not yet implemented"))

    def apply_membership_type_change(self, membership) -> None:
        """Apply membership type change with optional fee change."""
        try:
            old_membership_type = membership.membership_type

            # Update the membership type on the membership record
            membership.membership_type = self.request.requested_membership_type
            membership.save()

            # Get new membership type details for billing info
            new_type_doc = frappe.get_doc("Membership Type", self.request.requested_membership_type)
            new_billing_frequency = getattr(new_type_doc, "billing_period", None)
            new_dues_rate = self.request.requested_amount or new_type_doc.minimum_amount

            # Update existing dues schedule instead of cancel/recreate
            repo = DuesScheduleRepository()
            existing_schedule_info = repo.get_active_or_paused_schedule(
                self.request.member, fields=["name", "dues_rate", "billing_frequency", "membership_type"]
            )

            if existing_schedule_info:
                update_result = repo.update_schedule_for_type_change(
                    schedule_name=existing_schedule_info.name,
                    new_membership_type=self.request.requested_membership_type,
                    new_dues_rate=new_dues_rate,
                    new_billing_frequency=new_billing_frequency,
                    reason=f"Amendment {self.request.name}: {self.request.reason}",
                )
                if not update_result.success:
                    frappe.throw(
                        _("Failed to update dues schedule: {0}").format("; ".join(update_result.errors))
                    )
                self.request.new_dues_schedule = existing_schedule_info.name
            else:
                # No existing schedule - create new one
                dues_schedule_name = self.create_dues_schedule_for_amendment()
                self.request.new_dues_schedule = dues_schedule_name

            # Update member record
            member_doc = frappe.get_doc("Member", self.request.member)
            member_doc.reload()

            # Handle fee change if applicable
            if self.request.requested_amount:
                actual_current_rate = getattr(member_doc, "dues_rate", 0) or 0

                # Record fee change in history
                member_doc.record_fee_change(
                    {
                        "change_date": now_datetime(),
                        "old_amount": actual_current_rate,
                        "new_amount": self.request.requested_amount,
                        "reason": f"Membership type change amendment {self.request.name}: {self.request.reason}",
                        "changed_by": frappe.session.user,
                        "dues_schedule_action": f"Updated schedule {self.request.new_dues_schedule}",
                        "amendment_request_name": self.request.name,
                    }
                )

                member_doc.reload()
                member_doc.dues_rate = self.request.requested_amount
                member_doc.fee_override_reason = f"Amendment: {self.request.reason}"
                member_doc.fee_override_date = today()
                member_doc.fee_override_by = frappe.session.user

            # Record membership type change in history
            self._record_membership_type_history(
                member_doc=member_doc,
                old_type=old_membership_type,
                new_type=self.request.requested_membership_type,
            )

            # Update current_membership_type on member
            member_doc.current_membership_type = self.request.requested_membership_type

            member_doc._system_update = True
            member_result = secure_document_operation(
                operation="save",
                doc=member_doc,
                justification=f"Update member for membership type change amendment {self.request.name}",
                required_permissions=["Member:write"],
            )
            if not member_result.success:
                frappe.throw(_("Failed to update member: {0}").format("; ".join(member_result.errors)))

            # Update role profile for the user
            self._update_member_role_profile(
                member_doc, old_membership_type, self.request.requested_membership_type
            )

            self.request.processing_notes = (
                f"Membership type changed from {old_membership_type} to "
                f"{self.request.requested_membership_type}. "
                f"Dues schedule {self.request.new_dues_schedule} updated."
            )

        except Exception as e:
            frappe.throw(_("Error applying membership type change: {0}").format(str(e)))

    def create_dues_schedule_for_amendment(self) -> str:
        """Create a new dues schedule for this amendment."""
        try:
            # Get current active membership
            membership = frappe.db.get_value(
                "Membership",
                {"member": self.request.member, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )

            if not membership:
                frappe.throw(_("No active membership found for creating dues schedule"))

            # Deactivate existing active or paused dues schedule
            repo = DuesScheduleRepository()
            existing_schedule_info = repo.get_active_or_paused_schedule(self.request.member, fields=["name"])

            if existing_schedule_info:
                cancel_result = repo.cancel_schedule(
                    existing_schedule_info.name,
                    f"Cancelled and replaced by amendment {self.request.name}: EUR{self.request.requested_amount:.2f}",
                )
                if not cancel_result.success:
                    frappe.throw(
                        _("Failed to cancel dues schedule {0}: {1}").format(
                            existing_schedule_info.name, "; ".join(cancel_result.errors)
                        )
                    )

            # Create new dues schedule
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.flags.from_amendment = True
            dues_schedule.schedule_name = f"Amendment {self.request.name} - {frappe.utils.random_string(6)}"
            dues_schedule.member = self.request.member
            dues_schedule.membership = membership.name

            # Use requested membership type if this is a membership type change
            if (
                self.request.amendment_type == "Membership Type Change"
                and self.request.requested_membership_type
            ):
                dues_schedule.membership_type = self.request.requested_membership_type
            else:
                dues_schedule.membership_type = membership.membership_type

            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = self.request.requested_amount
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_approved = 1
            dues_schedule.custom_amount_reason = f"Amendment Request: {self.request.reason}"

            if not self.request.requested_amount:
                dues_schedule.custom_amount_reason = f"Free membership via amendment: {self.request.reason}"

            # Get billing frequency from membership type's template
            membership_type_to_use = (
                self.request.requested_membership_type
                if self.request.amendment_type == "Membership Type Change"
                and self.request.requested_membership_type
                else membership.membership_type
            )

            dues_schedule.billing_frequency = self._get_billing_frequency(membership_type_to_use)
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 1
            dues_schedule.test_mode = 0
            dues_schedule.effective_date = self.request.effective_date or today()
            dues_schedule.next_invoice_date = self.request.effective_date or today()

            dues_schedule.notes = (
                f"Created from amendment request {self.request.name} by {frappe.session.user} on {today()}"
            )

            create_result = secure_document_operation(
                operation="save",
                doc=dues_schedule,
                justification=f"Create new dues schedule for amendment {self.request.name}",
                required_permissions=["Membership Dues Schedule:create"],
            )
            if not create_result.success:
                frappe.throw(_("Failed to create dues schedule: {0}").format("; ".join(create_result.errors)))

            dues_schedule.add_comment(
                text=f"Created from amendment request {self.request.name}. "
                f"Amount: EUR{self.request.requested_amount:.2f}. Reason: {self.request.reason}"
            )

            return dues_schedule.name

        except Exception as e:
            frappe.log_error(
                f"Error creating dues schedule for amendment: {str(e)}", "Amendment Dues Schedule Error"
            )
            frappe.throw(_("Error creating dues schedule: {0}").format(str(e)))

    def _get_billing_frequency(self, membership_type_name: str) -> str:
        """Get billing frequency for a membership type."""
        if not membership_type_name:
            return "Monthly"

        try:
            membership_type_doc = frappe.get_doc("Membership Type", membership_type_name)
            if membership_type_doc.dues_schedule_template:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                return template.billing_frequency or "Monthly"
            else:
                billing_period_map = {
                    "Daily": "Daily",
                    "Monthly": "Monthly",
                    "Quarterly": "Quarterly",
                    "Biannual": "Semi-Annual",
                    "Annual": "Annual",
                    "Custom": "Custom",
                }
                billing_period = getattr(membership_type_doc, "billing_period", None)
                return billing_period_map.get(billing_period, "Monthly") if billing_period else "Monthly"
        except Exception:
            return "Monthly"

    # ====== Conflict Handling ======

    def cancel_conflicting_amendments(self) -> None:
        """Cancel conflicting amendments - only those that haven't taken effect yet."""
        if not self.request.member:
            return

        conflicting_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": self.request.member,
                "name": ["!=", self.request.name],
                "status": ["in", ["Pending Approval", "Approved"]],
            },
            fields=["name", "status", "requested_amount", "effective_date"],
        )

        cancelled_count = 0
        for amendment_data in conflicting_amendments:
            try:
                should_cancel = False

                if amendment_data.status == "Pending Approval":
                    should_cancel = True
                elif amendment_data.status == "Approved":
                    if amendment_data.effective_date and DateRangeValidator.is_date_in_future(
                        amendment_data.effective_date
                    ):
                        should_cancel = True
                    elif not amendment_data.effective_date:
                        self.logger.warning(f"Approved amendment {amendment_data.name} has no effective date")

                if should_cancel:
                    amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)
                    amendment.internal_notes = (
                        amendment.internal_notes or ""
                    ) + f"\nCancelled due to approval of newer amendment {self.request.name}"
                    amendment.status = "Cancelled"
                    amendment.flags.ignore_validate_update_after_submit = True
                    amendment.save()
                    cancelled_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Error cancelling conflicting amendment {amendment_data.name}: {str(e)}",
                    "Amendment Cancellation Error",
                )

        if cancelled_count > 0:
            self.request.internal_notes = (
                self.request.internal_notes or ""
            ) + f"\nCancelled {cancelled_count} conflicting amendment(s) upon approval"
            self.logger.info(
                f"Cancelled {cancelled_count} conflicting amendments for member {self.request.member}"
            )

    # ====== Notifications ======

    def send_approval_notification(self, approval_notes: Optional[str] = None) -> None:
        """Send notification to requester about approval using EmailService template."""
        if not self.request.requested_by:
            return

        try:
            from verenigingen.services.communication.email_service import get_email_service

            membership = frappe.get_doc("Membership", self.request.membership)
            member = frappe.get_doc("Member", membership.member)

            email_service = get_email_service()
            result = email_service.send_templated_email(
                template_name="amendment_approved",
                recipients=[self.request.requested_by],
                context={
                    "member_name": member.full_name,
                    "amendment_id": self.request.name,
                    "amendment_type": self.request.amendment_type or "N/A",
                    "new_amount": (
                        frappe.format_value(self.request.requested_amount, "Currency")
                        if self.request.requested_amount
                        else None
                    ),
                    "effective_date": (
                        frappe.utils.formatdate(self.request.effective_date)
                        if self.request.effective_date
                        else None
                    ),
                    "approval_notes": approval_notes,
                    "portal_link": frappe.utils.get_url()
                    + "/app/contribution-amendment-request/"
                    + self.request.name,
                    "current_year": frappe.utils.now_datetime().year,
                },
                reference_doctype="Contribution Amendment Request",
                reference_name=self.request.name,
                notification_key="dues_amendment_approved",
            )

            if not result.get("success"):
                frappe.log_error(
                    f"Failed to send approval notification: {result.get('message')}",
                    "Amendment Approval Email Error",
                )
        except Exception as e:
            frappe.log_error(f"Error sending approval notification: {str(e)}")

    def send_rejection_notification(self) -> None:
        """Send notification to requester about rejection using EmailService template."""
        if not self.request.requested_by:
            return

        try:
            from verenigingen.services.communication.email_service import get_email_service

            membership = frappe.get_doc("Membership", self.request.membership)
            member = frappe.get_doc("Member", membership.member)

            email_service = get_email_service()
            result = email_service.send_templated_email(
                template_name="amendment_rejected",
                recipients=[self.request.requested_by],
                context={
                    "member_name": member.full_name,
                    "amendment_id": self.request.name,
                    "amendment_type": self.request.amendment_type or "N/A",
                    "requested_amount": (
                        frappe.format_value(self.request.requested_amount, "Currency")
                        if self.request.requested_amount
                        else None
                    ),
                    "rejection_reason": self.request.rejection_reason or "No reason provided",
                    "portal_link": frappe.utils.get_url()
                    + "/app/contribution-amendment-request/"
                    + self.request.name,
                    "current_year": frappe.utils.now_datetime().year,
                },
                reference_doctype="Contribution Amendment Request",
                reference_name=self.request.name,
                notification_key="dues_amendment_rejected",
            )

            if not result.get("success"):
                frappe.log_error(
                    f"Failed to send rejection notification: {result.get('message')}",
                    "Amendment Rejection Email Error",
                )
        except Exception as e:
            frappe.log_error(f"Error sending rejection notification: {str(e)}")

    # ====== Helper Methods ======

    def _record_membership_type_history(self, member_doc, old_type: str, new_type: str) -> None:
        """Record membership type change in member's history table."""
        try:
            # Close the previous entry by setting to_date
            for entry in member_doc.get("membership_type_history", []):
                if not entry.to_date and entry.membership_type == old_type:
                    entry.to_date = today()

            # Add new entry for the new membership type
            member_doc.append(
                "membership_type_history",
                {
                    "membership_type": new_type,
                    "from_date": today(),
                    "to_date": None,
                    "changed_by": frappe.session.user,
                    "reason": self.request.reason,
                    "amendment_request": self.request.name,
                },
            )
        except Exception as e:
            frappe.log_error(
                f"Error recording membership type history: {str(e)}", "Membership Type History Error"
            )

    def _update_member_role_profile(self, member_doc, old_type: str, new_type: str) -> None:
        """Update the member's role profile based on new membership type."""
        if not member_doc.user:
            self.logger.info(
                f"[Amendment {self.request.name}] Member {self.request.member} has no user account - "
                "skipping role profile update"
            )
            return

        try:
            from verenigingen.utils.membership_type_role_profile import update_membership_type_role_profile

            result = update_membership_type_role_profile(
                user=member_doc.user,
                old_membership_type=old_type,
                new_membership_type=new_type,
            )

            if result.get("success"):
                self.logger.info(
                    f"[Amendment {self.request.name}] Role profile updated for user {member_doc.user}: "
                    f"{result.get('old_profile')} -> {result.get('new_profile')}"
                )
            elif result.get("no_change"):
                self.logger.info(
                    f"[Amendment {self.request.name}] No role profile change needed for user {member_doc.user}"
                )
            else:
                self.logger.warning(
                    f"[Amendment {self.request.name}] Failed to update role profile: {result.get('message')}"
                )
        except Exception as e:
            frappe.log_error(
                f"Error updating role profile for amendment {self.request.name}: {str(e)}",
                "Membership Role Profile Error",
            )


def get_contribution_amendment_approval_service(
    amendment_request: "ContributionAmendmentRequest",
) -> ContributionAmendmentApprovalService:
    """Get instance of ContributionAmendmentApprovalService."""
    return ContributionAmendmentApprovalService(amendment_request)
