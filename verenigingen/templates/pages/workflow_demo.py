"""
Workflow Demo Page
Demonstrates the membership application workflow in action
"""
import frappe
from frappe import _


def get_context(context):
    """Get context for workflow demo page"""

    context.title = _("Membership Application Workflow Demo")

    # Check if user has permission to view workflows
    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("You don't have permission to view this page"))

    # Get workflow information
    try:
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")
        context.workflow = workflow
        context.workflow_exists = True

        # Get workflow states and transitions for display
        context.workflow_states = [
            {
                "name": state.state,
                "doc_status": state.doc_status,
                "allow_edit": state.allow_edit,
                "message": getattr(state, "message", ""),
            }
            for state in workflow.states
        ]

        context.workflow_transitions = [
            {
                "from_state": transition.state,
                "action": transition.action,
                "to_state": transition.next_state,
                "allowed_role": transition.allowed,
            }
            for transition in workflow.transitions
        ]

    except frappe.DoesNotExistError:
        context.workflow_exists = False
        context.error_message = _("Membership Application Workflow not found. Please contact administrator.")

    # Get sample members with different workflow states for demo
    try:
        context.sample_members = frappe.get_all(
            "Member",
            fields=["name", "full_name", "application_status", "application_date", "email"],
            filters={
                "application_status": [
                    "in",
                    ["Pending", "Under Review", "Approved", "Payment Pending", "Active", "Rejected"],
                ]
            },
            order_by="application_date desc",
            limit=10,
        )
    except Exception:
        context.sample_members = []

    # Get workflow statistics
    if context.workflow_exists:
        try:
            context.workflow_stats = {}
            for state in ["Pending", "Under Review", "Approved", "Payment Pending", "Active", "Rejected"]:
                count = frappe.db.count("Member", {"application_status": state})
                context.workflow_stats[state] = count
        except Exception:
            context.workflow_stats = {}

    return context


@frappe.whitelist()
def get_workflow_actions(member_name):
    """Get available workflow actions for a member"""

    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("You don't have permission to modify members"))

    try:
        member = frappe.get_doc("Member", member_name)
        current_state = member.application_status

        # Get workflow transitions available from current state
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")

        available_actions = []
        user_roles = frappe.get_roles(frappe.session.user)

        for transition in workflow.transitions:
            if transition.state == current_state and transition.allowed in user_roles:
                available_actions.append(
                    {
                        "action": transition.action,
                        "next_state": transition.next_state,
                        "current_state": current_state,
                    }
                )

        return {"success": True, "current_state": current_state, "available_actions": available_actions}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def execute_workflow_action(member_name, action, next_state):
    """Execute a workflow action on a member"""

    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("You don't have permission to modify members"))

    try:
        member = frappe.get_doc("Member", member_name)
        old_state = member.application_status

        # Update the application status
        member.application_status = next_state
        member.add_comment(
            "Workflow",
            f"Workflow action '{action}' executed by {frappe.session.user}. State changed from '{old_state}' to '{next_state}'.",
        )
        member.save()

        # Log the workflow action
        frappe.logger().info(
            f"Workflow action executed: {action} on member {member_name} by {frappe.session.user}"
        )

        return {
            "success": True,
            "message": f"Successfully executed '{action}'. Member status changed to '{next_state}'.",
            "old_state": old_state,
            "new_state": next_state,
        }

    except Exception as e:
        frappe.log_error(f"Workflow action failed: {str(e)}", "Workflow Demo Error")
        return {"success": False, "error": str(e)}
