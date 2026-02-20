import frappe

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def create_termination_workflow_corrected():
    """Create termination workflow with single roles per state/transition"""

    workflow_name = "Membership Termination Workflow"

    if frappe.db.exists("Workflow", workflow_name):
        print(f"   ✓ Workflow '{workflow_name}' already exists")
        return True

    print(f"   📋 Creating workflow with corrected role assignments: {workflow_name}")

    try:
        workflow_doc = frappe.new_doc("Workflow")
        workflow_doc.workflow_name = workflow_name
        workflow_doc.document_type = "Membership Termination Request"
        workflow_doc.is_active = 1
        workflow_doc.workflow_state_field = "status"
        workflow_doc.send_email_alert = 0

        # Add states with SINGLE roles only
        # State 1: Draft
        workflow_doc.append(
            "states",
            {
                "state": "Draft",
                "doc_status": "0",
                "allow_edit": "System Manager",  # Single role only
                "is_optional_state": 1,
            },
        )

        # State 2: Pending
        workflow_doc.append(
            "states",
            {
                "state": "Pending",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # State 3: Approved
        workflow_doc.append(
            "states",
            {
                "state": "Approved",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # State 4: Rejected
        workflow_doc.append(
            "states",
            {
                "state": "Rejected",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # State 5: Executed
        workflow_doc.append(
            "states",
            {"state": "Executed", "doc_status": "1", "allow_edit": "System Manager"},  # Single role only
        )

        # Add transitions with SINGLE roles only
        # We'll create multiple transitions for different roles if needed

        # Draft -> Pending (Submit) - for Verenigingen Administrator
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Submit",
                "next_state": "Pending",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Draft -> Pending (Submit) - for System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Submit",
                "next_state": "Pending",
                "allowed": "System Manager",  # Single role only
            },
        )

        # Pending -> Approved (Approve) - for Association Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Pending -> Approved (Approve) - for System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "System Manager",  # Single role only
            },
        )

        # Pending -> Rejected (Reject) - for Association Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Pending -> Rejected (Reject) - for System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "System Manager",  # Single role only
            },
        )

        # Approved -> Executed (Execute) - for Association Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Approved",
                "action": "Execute",
                "next_state": "Executed",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Approved -> Executed (Execute) - for System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Approved",
                "action": "Execute",
                "next_state": "Executed",
                "allowed": "System Manager",  # Single role only
            },
        )

        # Direct Draft -> Approved for simple cases - Association Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Direct Draft -> Approved for simple cases - System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "System Manager",  # Single role only
            },
        )

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=workflow_doc,
            justification=f"Create {workflow_doc.workflow_name} workflow during system setup - membership termination business process automation",
            required_permissions=["Workflow:create"],
        )

        if not result.success:
            frappe.log_error(
                title="Workflow Creation Failed",
                message=f"Failed to create workflow {workflow_doc.workflow_name}: {'; '.join(result.errors)}",
            )
            return False

        workflow_doc = result.doc

        print(
            f"   ✅ Successfully created workflow with {len(workflow_doc.states)} states and {len(workflow_doc.transitions)} transitions"
        )
        return True

    except Exception as e:
        print(f"   ❌ Failed to create workflow: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def create_appeals_workflow_corrected():
    """Create appeals workflow - SKIP if DocType doesn't exist"""

    # Check if the appeals doctype exists
    if not frappe.db.exists("DocType", "Termination Appeals Process"):
        print("   ℹ️  Skipping appeals workflow - Termination Appeals Process DocType not found")
        return True

    workflow_name = "Termination Appeals Workflow"

    if frappe.db.exists("Workflow", workflow_name):
        print("   ✓ Appeals workflow already exists")
        return True

    print(f"   📋 Creating appeals workflow with corrected roles: {workflow_name}")

    try:
        workflow_doc = frappe.new_doc("Workflow")
        workflow_doc.workflow_name = workflow_name
        workflow_doc.document_type = "Termination Appeals Process"
        workflow_doc.is_active = 1
        workflow_doc.workflow_state_field = "appeal_status"
        workflow_doc.send_email_alert = 0

        # Appeals states with single roles
        workflow_doc.append(
            "states",
            {
                "state": "Draft",
                "doc_status": "0",
                "allow_edit": "System Manager",  # Single role
                "is_optional_state": 1,
            },
        )

        workflow_doc.append(
            "states",
            {
                "state": "Pending",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",  # Corrected role name
            },
        )

        workflow_doc.append(
            "states",
            {
                "state": "Approved",  # Appeal upheld
                "doc_status": "1",
                "allow_edit": "System Manager",  # Single role
            },
        )

        workflow_doc.append(
            "states",
            {
                "state": "Rejected",  # Appeal rejected
                "doc_status": "1",
                "allow_edit": "System Manager",  # Single role
            },
        )

        # Appeals transitions with single roles
        # Multiple transitions for different roles

        # Draft -> Pending (Submit) - System Manager can submit
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Submit",
                "next_state": "Pending",
                "allowed": "System Manager",  # Single role
            },
        )

        # Draft -> Pending (Submit) - Association Manager can submit
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Submit",
                "next_state": "Pending",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Pending -> Approved (Approve) - Association Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Pending -> Approved (Approve) - System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "System Manager",  # Single role
            },
        )

        # Pending -> Rejected (Reject) - Association Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "Verenigingen Administrator",  # Corrected role name
            },
        )

        # Pending -> Rejected (Reject) - System Manager
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "System Manager",  # Single role
            },
        )

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=workflow_doc,
            justification=f"Create {workflow_doc.workflow_name} workflow during system setup - appeals process business automation",
            required_permissions=["Workflow:create"],
        )

        if not result.success:
            frappe.log_error(
                title="Appeals Workflow Creation Failed",
                message=f"Failed to create appeals workflow {workflow_doc.workflow_name}: {'; '.join(result.errors)}",
            )
            return False

        workflow_doc = result.doc

        print(
            f"   ✅ Successfully created appeals workflow with {len(workflow_doc.states)} states and {len(workflow_doc.transitions)} transitions"
        )
        return True

    except Exception as e:
        print(f"   ❌ Failed to create appeals workflow: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def create_workflow_state_masters():
    """Create workflow state masters if they don't exist"""

    print("   🏗️ Creating workflow state masters...")

    # Only create custom states - standard ones should exist
    custom_states = ["Executed"]

    created_count = 0

    for state in custom_states:
        if not frappe.db.exists("Workflow State", state):
            try:
                state_doc = frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state})
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="insert",
                    doc=state_doc,
                    justification=f"Create workflow state {state} for business process automation - workflow setup",
                    required_permissions=["Workflow State:create"],
                )

                if not result.success:
                    frappe.log_error(
                        title="Workflow State Creation Failed",
                        message=f"Failed to create workflow state {state}: {'; '.join(result.errors)}",
                    )
                    continue  # Continue with other states
                created_count += 1
                print(f"      ✓ Created workflow state: {state}")
            except frappe.exceptions.DuplicateEntryError:
                print(f"      ✓ State already exists: {state}")
            except Exception as e:
                print(f"      ⚠️ Could not create state {state}: {str(e)}")
        else:
            print(f"      ✓ State already exists: {state}")

    return created_count


def create_workflow_action_masters():
    """Create workflow action masters if they don't exist"""

    print("   ⚡ Creating workflow action masters...")

    # Only create custom actions - standard ones should exist
    custom_actions = ["Execute"]

    created_count = 0

    for action in custom_actions:
        if not frappe.db.exists("Workflow Action Master", action):
            try:
                action_doc = frappe.get_doc(
                    {"doctype": "Workflow Action Master", "workflow_action_name": action}
                )
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="insert",
                    doc=action_doc,
                    justification=f"Create workflow action {action} for business process automation - workflow setup",
                    required_permissions=["Workflow Action:create"],
                )

                if not result.success:
                    frappe.log_error(
                        title="Workflow Action Creation Failed",
                        message=f"Failed to create workflow action {action}: {'; '.join(result.errors)}",
                    )
                    continue  # Continue with other actions
                created_count += 1
                print(f"      ✓ Created workflow action: {action}")
            except frappe.exceptions.DuplicateEntryError:
                print(f"      ✓ Action already exists: {action}")
            except Exception as e:
                print(f"      ⚠️ Could not create action {action}: {str(e)}")
        else:
            print(f"      ✓ Action already exists: {action}")

    return created_count


def validate_prerequisites():
    """Validate prerequisites for workflow creation"""

    print("   🔍 Validating prerequisites...")

    issues = []

    # Check target doctypes - only require termination request, appeals is optional
    required_doctypes = ["Membership Termination Request"]

    for doctype in required_doctypes:
        if not frappe.db.exists("DocType", doctype):
            issues.append(f"Missing DocType: {doctype}")

    # Check required roles exist - use correct role names
    required_roles = list(Roles.ADMIN_PAIR)
    for role in required_roles:
        if not frappe.db.exists("Role", role):
            issues.append(f"Missing Role: {role}")

    if issues:
        print("   ❌ Prerequisites validation failed:")
        for issue in issues:
            print(f"      - {issue}")
        return False

    print("   ✅ All prerequisites validated")
    return True


def setup_workflows_corrected():
    """Main function to setup workflows with corrected role assignments"""

    print("🔄 Setting up workflows with corrected single-role assignments...")

    # Step 1: Validate prerequisites
    if not validate_prerequisites():
        return False

    success_count = 0

    # Step 2: Create workflow masters if needed
    try:
        states_created = create_workflow_state_masters()
        actions_created = create_workflow_action_masters()

        if states_created > 0 or actions_created > 0:
            frappe.db.commit()
            print(f"   ✅ Created {states_created} states and {actions_created} actions")
    except Exception as e:
        print(f"   ⚠️ Warning creating masters: {str(e)}")

    # Step 3: Create termination workflow
    if create_termination_workflow_corrected():
        success_count += 1

    # Step 4: Create appeals workflow
    if create_appeals_workflow_corrected():
        success_count += 1

    # Step 5: Commit all changes
    try:
        frappe.db.commit()
        print(f"   ✅ Successfully committed {success_count} workflows")
        return success_count > 0
    except Exception as e:
        print(f"   ❌ Commit failed: {str(e)}")
        frappe.db.rollback()
        return False


# API endpoint
@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_production_workflows_corrected():
    """API endpoint for corrected workflow setup"""
    return setup_workflows_corrected()


# Main execution
if __name__ == "__main__":
    setup_workflows_corrected()
