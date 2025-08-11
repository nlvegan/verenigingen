"""
Simplified SEPA Direct Debit Batch Workflow Setup
Implements basic approval workflow using existing Frappe states and actions
"""

import frappe


def create_simple_dd_batch_workflow():
    """Create simple SEPA Direct Debit Batch workflow using standard Frappe states"""

    workflow_name = "SEPA Direct Debit Batch Simple Workflow"

    if frappe.db.exists("Workflow", workflow_name):
        print(f"   ✓ Workflow '{workflow_name}' already exists")
        return True

    print(f"   📋 Creating Simple SEPA Direct Debit Batch workflow: {workflow_name}")

    try:
        # First, ensure we have the required workflow states
        required_states = ["Draft", "Pending", "Approved", "Rejected", "Submitted", "Completed"]
        for state in required_states:
            if not frappe.db.exists("Workflow State", state):
                state_doc = frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state})
                state_doc.insert(ignore_permissions=True)
                print(f"      ✓ Created workflow state: {state}")

        # Ensure we have required actions
        required_actions = ["Approve", "Reject", "Submit", "Complete"]
        for action in required_actions:
            if not frappe.db.exists("Workflow Action Master", action):
                action_doc = frappe.get_doc(
                    {"doctype": "Workflow Action Master", "workflow_action_name": action}
                )
                action_doc.insert(ignore_permissions=True)
                print(f"      ✓ Created workflow action: {action}")

        workflow_doc = frappe.new_doc("Workflow")
        workflow_doc.workflow_name = workflow_name
        workflow_doc.document_type = "Direct Debit Batch"
        workflow_doc.is_active = 1
        workflow_doc.workflow_state_field = "approval_status"
        workflow_doc.send_email_alert = 1

        # === SIMPLIFIED WORKFLOW STATES ===

        # State 1: Draft (Initial creation)
        workflow_doc.append(
            "states", {"state": "Draft", "doc_status": "0", "allow_edit": "Verenigingen Manager"}
        )

        # State 2: Pending (Awaiting approval)
        workflow_doc.append(
            "states", {"state": "Pending", "doc_status": "0", "allow_edit": "Finance Manager"}
        )

        # State 3: Approved (Ready for processing)
        workflow_doc.append(
            "states", {"state": "Approved", "doc_status": "1", "allow_edit": "System Manager"}
        )

        # State 4: Rejected (Needs correction)
        workflow_doc.append(
            "states", {"state": "Rejected", "doc_status": "0", "allow_edit": "Verenigingen Manager"}
        )

        # State 5: Submitted (Sent to bank)
        workflow_doc.append(
            "states", {"state": "Submitted", "doc_status": "1", "allow_edit": "System Manager"}
        )

        # State 6: Completed (Successfully processed)
        workflow_doc.append(
            "states", {"state": "Completed", "doc_status": "1", "allow_edit": "System Manager"}
        )

        # === SIMPLIFIED WORKFLOW TRANSITIONS ===

        # Draft → Pending (Submit for approval)
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Submit",
                "next_state": "Pending",
                "allowed": "Verenigingen Manager",
            },
        )

        # Pending → Approved (Approve)
        workflow_doc.append(
            "transitions",
            {"state": "Pending", "action": "Approve", "next_state": "Approved", "allowed": "Finance Manager"},
        )

        # Pending → Rejected (Reject)
        workflow_doc.append(
            "transitions",
            {"state": "Pending", "action": "Reject", "next_state": "Rejected", "allowed": "Finance Manager"},
        )

        # Rejected → Pending (Re-submit)
        workflow_doc.append(
            "transitions",
            {
                "state": "Rejected",
                "action": "Submit",
                "next_state": "Pending",
                "allowed": "Verenigingen Manager",
            },
        )

        # Approved → Submitted (Send to bank)
        workflow_doc.append(
            "transitions",
            {
                "state": "Approved",
                "action": "Submit",
                "next_state": "Submitted",
                "allowed": "Finance Manager",
            },
        )

        # Submitted → Completed (Mark complete)
        workflow_doc.append(
            "transitions",
            {
                "state": "Submitted",
                "action": "Complete",
                "next_state": "Completed",
                "allowed": "System Manager",
            },
        )

        # Save the workflow
        workflow_doc.insert(ignore_permissions=True)

        print(
            f"   ✅ Successfully created workflow with {len(workflow_doc.states)} states and {len(workflow_doc.transitions)} transitions"
        )
        return True

    except Exception as e:
        print(f"   ❌ Failed to create workflow: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def add_workflow_custom_fields():
    """Add custom fields needed for workflow"""

    print("   🏗️ Adding workflow custom fields...")

    # Add approval_status field if it doesn't exist
    if not frappe.db.exists("Custom Field", "SEPA Direct Debit Batch-approval_status"):
        approval_status_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Direct Debit Batch",
                "fieldname": "approval_status",
                "label": "Approval Status",
                "fieldtype": "Data",
                "insert_after": "status",
                "read_only": 1,
                "allow_on_submit": 1,
                "hidden": 1,  # Hidden since workflow will handle display
            }
        )
        approval_status_field.insert(ignore_permissions=True)
        print("      ✓ Added approval_status field")

    # Add workflow_state field for better tracking
    if not frappe.db.exists("Custom Field", "SEPA Direct Debit Batch-workflow_state"):
        workflow_state_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Direct Debit Batch",
                "fieldname": "workflow_state",
                "label": "Workflow State",
                "fieldtype": "Data",
                "insert_after": "approval_status",
                "read_only": 1,
                "allow_on_submit": 1,
            }
        )
        workflow_state_field.insert(ignore_permissions=True)
        print("      ✓ Added workflow_state field")

    # Add risk_level field for approval routing
    if not frappe.db.exists("Custom Field", "SEPA Direct Debit Batch-risk_level"):
        risk_level_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Direct Debit Batch",
                "fieldname": "risk_level",
                "label": "Risk Level",
                "fieldtype": "Select",
                "options": "Low\nMedium\nHigh",
                "insert_after": "workflow_state",
                "read_only": 1,
            }
        )
        risk_level_field.insert(ignore_permissions=True)
        print("      ✓ Added risk_level field")


def setup_simple_dd_workflow():
    """Main function to setup simplified DD batch workflow"""

    print("🔄 Setting up Simple SEPA Direct Debit Batch workflow...")

    success_count = 0

    # Step 1: Add custom fields
    try:
        add_workflow_custom_fields()
        success_count += 1
    except Exception as e:
        print(f"   ⚠️ Warning adding fields: {str(e)}")

    # Step 2: Create workflow
    if create_simple_dd_batch_workflow():
        success_count += 1

    # Step 3: Commit changes
    try:
        frappe.db.commit()
        print("   ✅ Successfully setup Simple DD Batch workflow")
        return True
    except Exception as e:
        print(f"   ❌ Setup failed: {str(e)}")
        frappe.db.rollback()
        return False


@frappe.whitelist()
def setup_production_simple_workflow():
    """API endpoint for Simple DD workflow setup"""
    return setup_simple_dd_workflow()


if __name__ == "__main__":
    setup_simple_dd_workflow()
