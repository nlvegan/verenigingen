"""
SEPA Direct Debit Batch Workflow Setup
Implements risk-based approval workflows for SEPA batch processing
"""

import frappe

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def create_dd_batch_workflow():
    """Create comprehensive SEPA Direct Debit Batch workflow"""

    workflow_name = "SEPA Direct Debit Batch Approval Workflow"

    if frappe.db.exists("Workflow", workflow_name):
        print(f"   ✓ Workflow '{workflow_name}' already exists")
        return True

    print(f"   📋 Creating SEPA Direct Debit Batch workflow: {workflow_name}")

    try:
        workflow_doc = frappe.new_doc("Workflow")
        workflow_doc.workflow_name = workflow_name
        workflow_doc.document_type = "Direct Debit Batch"
        workflow_doc.is_active = 1
        workflow_doc.workflow_state_field = "approval_status"  # New field needed
        workflow_doc.send_email_alert = 1

        # === WORKFLOW STATES ===

        # State 1: Draft (Initial creation)
        workflow_doc.append("states", {"state": "Draft", "doc_status": "0", "allow_edit": "System Manager"})

        # State 2: Pending Validation (Automated checks)
        workflow_doc.append(
            "states", {"state": "Pending Validation", "doc_status": "0", "allow_edit": "System Manager"}
        )

        # State 3: Validation Failed (Issues need resolution)
        workflow_doc.append(
            "states", {"state": "Validation Failed", "doc_status": "0", "allow_edit": "Verenigingen Staff"}
        )

        # State 4: Pending Approval (Manager review needed)
        workflow_doc.append(
            "states", {"state": "Pending Approval", "doc_status": "0", "allow_edit": "Verenigingen Staff"}
        )

        # State 5: Pending Senior Approval (High-value batches)
        workflow_doc.append(
            "states",
            {
                "state": "Pending Senior Approval",
                "doc_status": "0",
                "allow_edit": Roles.FINANCIAL_MANAGER,
            },
        )

        # State 6: Approved (Ready for SEPA generation)
        workflow_doc.append(
            "states", {"state": "Approved", "doc_status": "0", "allow_edit": "System Manager"}
        )

        # State 7: SEPA Generated (File created)
        workflow_doc.append(
            "states", {"state": "SEPA Generated", "doc_status": "1", "allow_edit": "System Manager"}
        )

        # State 8: Pending Bank Submission (Ready to send)
        workflow_doc.append(
            "states",
            {
                "state": "Pending Bank Submission",
                "doc_status": "1",
                "allow_edit": Roles.FINANCIAL_MANAGER,
            },
        )

        # State 9: Submitted to Bank (Processing)
        workflow_doc.append(
            "states", {"state": "Submitted to Bank", "doc_status": "1", "allow_edit": "System Manager"}
        )

        # State 10: Processed (Successfully completed)
        workflow_doc.append(
            "states", {"state": "Processed", "doc_status": "1", "allow_edit": "System Manager"}
        )

        # State 11: Failed (Requires investigation)
        workflow_doc.append(
            "states", {"state": "Failed", "doc_status": "1", "allow_edit": Roles.FINANCIAL_MANAGER}
        )

        # === WORKFLOW TRANSITIONS ===

        # Draft → Pending Validation (Validate)
        workflow_doc.append(
            "transitions",
            {
                "state": "Draft",
                "action": "Validate",
                "next_state": "Pending Validation",
                "allowed": "Verenigingen Staff",
            },
        )

        # Pending Validation → Validation Failed (Fail Validation)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending Validation",
                "action": "Fail Validation",
                "next_state": "Validation Failed",
                "allowed": "System Manager",
            },
        )

        # Pending Validation → Pending Approval (Pass Validation)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending Validation",
                "action": "Pass Validation",
                "next_state": "Pending Approval",
                "allowed": "System Manager",
            },
        )

        # Pending Validation → Pending Senior Approval (High Value)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending Validation",
                "action": "Require Senior Approval",
                "next_state": "Pending Senior Approval",
                "allowed": "System Manager",
            },
        )

        # Validation Failed → Pending Validation (Re-validate)
        workflow_doc.append(
            "transitions",
            {
                "state": "Validation Failed",
                "action": "Re-validate",
                "next_state": "Pending Validation",
                "allowed": "Verenigingen Staff",
            },
        )

        # Pending Approval → Approved (Approve)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending Approval",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Verenigingen Staff",
            },
        )

        # Pending Senior Approval → Approved (Senior Approve)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending Senior Approval",
                "action": "Senior Approve",
                "next_state": "Approved",
                "allowed": Roles.FINANCIAL_MANAGER,
            },
        )

        # Approved → SEPA Generated (Generate SEPA)
        workflow_doc.append(
            "transitions",
            {
                "state": "Approved",
                "action": "Generate SEPA",
                "next_state": "SEPA Generated",
                "allowed": "System Manager",
            },
        )

        # SEPA Generated → Pending Bank Submission (Submit to Bank)
        workflow_doc.append(
            "transitions",
            {
                "state": "SEPA Generated",
                "action": "Submit to Bank",
                "next_state": "Pending Bank Submission",
                "allowed": Roles.FINANCIAL_MANAGER,
            },
        )

        # Pending Bank Submission → Submitted to Bank (Confirm Submission)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending Bank Submission",
                "action": "Confirm Submission",
                "next_state": "Submitted to Bank",
                "allowed": Roles.FINANCIAL_MANAGER,
            },
        )

        # Submitted to Bank → Processed (Mark Processed)
        workflow_doc.append(
            "transitions",
            {
                "state": "Submitted to Bank",
                "action": "Mark Processed",
                "next_state": "Processed",
                "allowed": "System Manager",
            },
        )

        # Submitted to Bank → Failed (Mark Failed)
        workflow_doc.append(
            "transitions",
            {
                "state": "Submitted to Bank",
                "action": "Mark Failed",
                "next_state": "Failed",
                "allowed": Roles.FINANCIAL_MANAGER,
            },
        )

        # Failed → Pending Validation (Retry)
        workflow_doc.append(
            "transitions",
            {
                "state": "Failed",
                "action": "Retry",
                "next_state": "Pending Validation",
                "allowed": Roles.FINANCIAL_MANAGER,
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


def create_workflow_conditions():
    """Create workflow conditions for risk-based routing"""

    print("   🔍 Creating workflow conditions...")

    # Condition 1: High-value batch (>€5000)
    high_value_condition = {
        "condition_name": "High Value Batch",
        "document_type": "Direct Debit Batch",
        "condition": "doc.total_amount > 5000",
    }

    # Condition 2: Large batch (>50 invoices)
    large_batch_condition = {
        "condition_name": "Large Batch",
        "document_type": "Direct Debit Batch",
        "condition": "doc.entry_count > 50",
    }

    # Condition 3: First-time SEPA batch
    first_time_condition = {
        "condition_name": "First Time Batch",
        "document_type": "Direct Debit Batch",
        "condition": "doc.sequence_type == 'FRST'",
    }

    return [high_value_condition, large_batch_condition, first_time_condition]


def add_custom_fields_for_workflow():
    """Add custom fields needed for workflow"""

    print("   🏗️ Adding custom fields for workflow...")

    # Add approval_status field to SEPA Direct Debit Batch
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
            }
        )
        approval_status_field.insert(ignore_permissions=True)
        print("      ✓ Added approval_status field")

    # Add risk_level field
    if not frappe.db.exists("Custom Field", "SEPA Direct Debit Batch-risk_level"):
        risk_level_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Direct Debit Batch",
                "fieldname": "risk_level",
                "label": "Risk Level",
                "fieldtype": "Select",
                "options": "Low\nMedium\nHigh",
                "insert_after": "approval_status",
                "read_only": 1,
            }
        )
        risk_level_field.insert(ignore_permissions=True)
        print("      ✓ Added risk_level field")

    # Add approval_notes field
    if not frappe.db.exists("Custom Field", "SEPA Direct Debit Batch-approval_notes"):
        approval_notes_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Direct Debit Batch",
                "fieldname": "approval_notes",
                "label": "Approval Notes",
                "fieldtype": "Text",
                "insert_after": "risk_level",
            }
        )
        approval_notes_field.insert(ignore_permissions=True)
        print("      ✓ Added approval_notes field")


def create_required_roles():
    """Create required roles if they don't exist"""

    print("   👥 Creating required roles...")

    required_roles = ["Verenigingen Staff", Roles.FINANCIAL_MANAGER]

    for role_name in required_roles:
        if not frappe.db.exists("Role", role_name):
            role_doc = frappe.get_doc({"doctype": "Role", "role_name": role_name})
            role_doc.insert(ignore_permissions=True)
            print(f"      ✓ Created role: {role_name}")
        else:
            print(f"      ✓ Role already exists: {role_name}")


def setup_dd_batch_workflow():
    """Main function to setup SEPA Direct Debit Batch workflow"""

    print("🔄 Setting up SEPA Direct Debit Batch workflow...")

    success_count = 0

    # Step 1: Create required roles
    try:
        create_required_roles()
        success_count += 1
    except Exception as e:
        print(f"   ⚠️ Warning creating roles: {str(e)}")

    # Step 2: Add custom fields
    try:
        add_custom_fields_for_workflow()
        success_count += 1
    except Exception as e:
        print(f"   ⚠️ Warning adding fields: {str(e)}")

    # Step 3: Create workflow
    if create_dd_batch_workflow():
        success_count += 1

    # Step 4: Commit changes
    try:
        frappe.db.commit()
        print("   ✅ Successfully setup SEPA Direct Debit Batch workflow")
        return True
    except Exception as e:
        print(f"   ❌ Setup failed: {str(e)}")
        frappe.db.rollback()
        return False


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_production_dd_workflow():
    """API endpoint for SEPA Direct Debit workflow setup"""
    return setup_dd_batch_workflow()


if __name__ == "__main__":
    setup_dd_batch_workflow()
