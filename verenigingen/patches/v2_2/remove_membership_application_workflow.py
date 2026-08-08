# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the native Frappe Workflow "Membership Application Workflow".

WHY
    The workflow made ``Member.application_status`` a workflow state field, so every
    ``doc.save()`` on Member was validated against its transition table. That gate was
    a duplicate of the app's own authorization -- ``approve_membership_application``
    already calls ``validate_chapter_permission_or_throw`` -- and the two disagreed:
    patch v2_2.add_staff_to_membership_workflow exists solely because a Verenigingen
    Staff user cleared the chapter check and was then blocked by the workflow.

    More decisively, the workflow's ``allowed`` field is a plain GLOBAL role. It cannot
    express "board member of THIS chapter", which is the actual rule: a member with a
    volunteer profile, seated on that chapter's board, may approve that chapter's
    applicants. No role added to the transition table can encode that, so the workflow
    could not be corrected -- only removed.

    Its creator (``setup.membership_application_workflow_setup``) was already disabled
    in hooks/lifecycle.py, commented "Workflow not in use, has bugs in action master
    creation". The row it had created previously stayed live and kept validating.

WHAT THIS DELETES
    1. the Workflow document, and with it its child Workflow Document State and
       Workflow Transition rows;
    2. the ``Workflow Action`` rows it generated for Member.

    Member is the only doctype this workflow governed, and the sole other workflow
    (Periodic Donation Agreement) shares none of its actions, so filtering Workflow
    Action by reference_doctype='Member' cannot touch another workflow's records.

WHAT THIS DELIBERATELY LEAVES
    ``Workflow State`` and ``Workflow Action Master`` records. Those are a global
    vocabulary in Frappe and are shared -- "Active" is used by the Periodic Donation
    Agreement workflow too. Deleting them would break it.

NOT A DATA MIGRATION
    ``application_status`` keeps every value it has. It simply becomes an ordinary
    Select field again, written by the approval service and gated by the chapter
    permission check rather than by a global role list.
"""

import frappe

WORKFLOW_NAME = "Membership Application Workflow"


def execute():
    deleted_actions = frappe.db.count("Workflow Action", {"reference_doctype": "Member"})
    if deleted_actions:
        # Child rows (Workflow Action Permitted Role) go with the parent.
        frappe.db.delete("Workflow Action", {"reference_doctype": "Member"})

    workflow_removed = False
    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        frappe.delete_doc("Workflow", WORKFLOW_NAME, ignore_permissions=True, force=True)
        workflow_removed = True

    if workflow_removed or deleted_actions:
        frappe.db.commit()
        frappe.logger().info(
            f"remove_membership_application_workflow: workflow_removed={workflow_removed}, "
            f"workflow_actions_deleted={deleted_actions}"
        )
