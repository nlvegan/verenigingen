import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation


class TerminationMixin:
    """Mixin for termination-related functionality"""

    def get_termination_readiness_check(self):
        """Check if member is ready for termination and what would be affected"""
        # get_termination_impact_preview lives on the Membership Termination Request
        # module, not in termination_utils — importing it from termination_utils
        # raised ImportError and broke this whole method whenever it was called.
        from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
            get_termination_impact_preview,
        )

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

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        member_result = secure_document_operation(
            operation="save",
            doc=self,
            justification=f"Execute membership termination for member {self.name} with status {self.status}",
            required_permissions=["Member:write"],
        )

        if not member_result.success:
            frappe.log_error(
                f"Failed to save member termination: {'; '.join(member_result.errors)}",
                "Member Termination Security",
            )
            frappe.throw(
                _("Failed to execute member termination: {0}").format("; ".join(member_result.errors))
            )

        frappe.logger().info(f"Terminated membership for member {self.name} - Status: {self.status}")

    def get_suspension_summary(self):
        """Get summary of suspension status and impact"""
        from verenigingen.utils.termination_integration import get_member_suspension_status

        return get_member_suspension_status(self.name)

    def suspend_member(self, reason, suspend_user=True, suspend_teams=True):
        """Suspend this member with given reason"""
        from verenigingen.utils.termination_integration import suspend_member_safe

        results = suspend_member_safe(
            member_name=self.name,
            suspension_reason=reason,
            suspend_user=suspend_user,
            suspend_teams=suspend_teams,
        )
        return _flag_partial_result(results, _("Member suspended, but NOT everything was done"))

    def unsuspend_member(self, reason):
        """Unsuspend this member with given reason"""
        from verenigingen.utils.termination_integration import unsuspend_member_safe

        results = unsuspend_member_safe(member_name=self.name, unsuspension_reason=reason)
        return _flag_partial_result(results, _("Member unsuspended, but NOT everything was done"))


def _flag_partial_result(results, title):
    """Mark a success that left steps undone and tell the desk user (#2597).

    success stays True (the member did change); `partial` plus the warning name what a
    staff user would otherwise only find in the Error Log, e.g. a team row still active.
    """
    from verenigingen.utils.termination_integration import partial_failure_errors

    not_done = partial_failure_errors(results)
    if not_done:
        results["partial"] = True
        frappe.msgprint(
            "<br>".join([title] + [frappe.utils.escape_html(e) for e in not_done]),
            indicator="orange",
            title=_("Partial result"),
        )
    return results
