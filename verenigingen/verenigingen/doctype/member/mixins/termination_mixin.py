import frappe


class TerminationMixin:
    """Mixin for termination-related functionality"""

    def get_termination_readiness_check(self):
        """Check if member is ready for termination and what would be affected"""
        from verenigingen.utils.termination_utils import get_termination_impact_preview

        readiness = {"can_terminate": True, "warnings": [], "blockers": [], "impact": {}}

        impact = get_termination_impact_preview(self.name)
        readiness["impact"] = impact

        if impact["board_positions"] > 0:
            readiness["warnings"].append(f"Member holds {impact['board_positions']} board position(s)")

        if impact["outstanding_invoices"] > 5:
            readiness["warnings"].append(f"Member has {impact['outstanding_invoices']} outstanding invoices")

        pending = frappe.get_all(
            "Membership Termination Request",
            filters={"member": self.name, "status": ["in", ["Draft", "Pending", "Approved"]]},
        )

        if pending:
            readiness["can_terminate"] = False
            readiness["blockers"].append("Member already has pending termination request")

        return readiness

    def terminate_membership(self, termination_type, termination_date, termination_request=None):
        """Terminate membership method for Member doctype"""
        status_mapping = {
            "Voluntary": "Expired",
            "Non-payment": "Suspended",
            "Deceased": "Deceased",
            "Policy Violation": "Suspended",
            "Disciplinary Action": "Suspended",
            "Expulsion": "Banned",
        }

        self.status = status_mapping.get(termination_type, "Suspended")

        termination_note = f"Membership terminated on {termination_date} - Type: {termination_type}"
        if termination_request:
            termination_note += f" - Request: {termination_request}"

        if self.notes:
            self.notes += f"\n\n{termination_note}"
        else:
            self.notes = termination_note

        self.flags.ignore_permissions = True
        self.save()

        frappe.logger().info(f"Terminated membership for member {self.name} - Status: {self.status}")

    def update_termination_status_display(self):
        """Update member fields to display current termination status"""
        executed_termination = frappe.get_all(
            "Membership Termination Request",
            filters={"member": self.name, "status": "Executed"},
            fields=["name", "termination_type", "execution_date", "termination_date"],
            order_by="execution_date desc",
            limit=1,
        )

        pending_termination = frappe.get_all(
            "Membership Termination Request",
            filters={"member": self.name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
            fields=["name", "status", "termination_type", "request_date"],
            order_by="request_date desc",
            limit=1,
        )

        if executed_termination:
            term_data = executed_termination[0]

            if hasattr(self, "termination_status"):
                self.termination_status = "Terminated"

            if hasattr(self, "termination_date"):
                self.termination_date = term_data.execution_date or term_data.termination_date

            if hasattr(self, "termination_type"):
                self.termination_type = term_data.termination_type

            if hasattr(self, "termination_request"):
                self.termination_request = term_data.name

            if hasattr(self, "status") and self.status != "Terminated":
                self.status = "Terminated"

            if hasattr(self, "termination_notes"):
                self.termination_notes = (
                    f"Terminated on {term_data.execution_date} - Type: {term_data.termination_type}"
                )

        elif pending_termination:
            pend_data = pending_termination[0]

            if hasattr(self, "termination_status"):
                status_map = {
                    "Draft": "Termination Draft",
                    "Pending Approval": "Termination Pending Approval",
                    "Approved": "Termination Approved",
                }
                self.termination_status = status_map.get(pend_data.status, "Termination Pending")

            if hasattr(self, "pending_termination_type"):
                self.pending_termination_type = pend_data.termination_type

            if hasattr(self, "pending_termination_request"):
                self.pending_termination_request = pend_data.name

        else:
            if hasattr(self, "termination_status"):
                self.termination_status = "Active"

            if hasattr(self, "termination_date"):
                self.termination_date = None

            if hasattr(self, "termination_type"):
                self.termination_type = None

            if hasattr(self, "termination_request"):
                self.termination_request = None

            if hasattr(self, "pending_termination_type"):
                self.pending_termination_type = None

            if hasattr(self, "pending_termination_request"):
                self.pending_termination_request = None

        # Update color/badge field for visual indication
        if hasattr(self, "membership_badge_color"):
            if executed_termination:
                self.membership_badge_color = "#dc3545"  # Red for terminated
            elif pending_termination:
                self.membership_badge_color = "#ffc107"  # Yellow for pending
            elif self.status == "Suspended":
                self.membership_badge_color = "#fd7e14"  # Orange for suspended
            else:
                active_membership = frappe.db.exists(
                    "Membership", {"member": self.name, "status": "Active", "docstatus": 1}
                )
                if active_membership:
                    self.membership_badge_color = "#28a745"  # Green for active
                else:
                    self.membership_badge_color = "#6c757d"  # Gray for inactive

    def get_suspension_summary(self):
        """Get summary of suspension status and impact"""
        from verenigingen.utils.termination_integration import get_member_suspension_status

        return get_member_suspension_status(self.name)

    def suspend_member(self, reason, suspend_user=True, suspend_teams=True):
        """Suspend this member with given reason"""
        from verenigingen.utils.termination_integration import suspend_member_safe

        return suspend_member_safe(
            member_name=self.name,
            suspension_reason=reason,
            suspend_user=suspend_user,
            suspend_teams=suspend_teams,
        )

    def unsuspend_member(self, reason):
        """Unsuspend this member with given reason"""
        from verenigingen.utils.termination_integration import unsuspend_member_safe

        return unsuspend_member_safe(member_name=self.name, unsuspension_reason=reason)
