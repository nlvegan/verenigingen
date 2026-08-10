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
    2. the ``Workflow Action`` rows it generated for Member, and their
       ``Workflow Action Permitted Role`` children.

    Member is the only doctype this workflow governed, and the sole other workflow
    (Periodic Donation Agreement) shares none of its actions, so filtering Workflow
    Action by reference_doctype='Member' cannot touch another workflow's records.

    The children must be deleted explicitly. ``frappe.db.delete`` issues a raw DELETE
    and does NOT cascade -- only ``delete_doc`` does. Measured on veg11, deleting the
    Member Workflow Actions without this step would orphan 7,352 permitted-role rows
    in a table that currently holds zero orphans. ``delete_doc`` per action is not an
    option at this volume, so the children are removed by parent name first.

WHAT THIS DELIBERATELY LEAVES
    ``Workflow State`` and ``Workflow Action Master`` records. Those are a global
    vocabulary in Frappe and are shared -- "Active" is used by the Periodic Donation
    Agreement workflow too. Deleting them would break it.

CACHE
    ``get_workflow_name()`` memoizes the workflow name in Redis
    (``frappe.cache.hset("workflow", doctype, ...)``). The Workflow controller has no
    ``on_trash``, and ``migrate`` calls ``frappe.clear_cache()`` in setUp -- BEFORE
    patches, never after. Without an explicit clear, the next ``Member.save()`` looks
    up a workflow that no longer exists and raises DoesNotExistError, presenting as
    "every Member save is broken after deploy".

NOT A DATA MIGRATION
    ``application_status`` keeps every value it has. It simply becomes an ordinary
    Select field again, written by the approval service and gated by the chapter
    permission check rather than by a global role list.
"""

import frappe

WORKFLOW_NAME = "Membership Application Workflow"


# Selected by subquery rather than an IN list of parent names: veg11 alone has 3,624
# Member Workflow Actions, and that list only grows with the site.
_CHILD_ROWS = """
    FROM `tabWorkflow Action Permitted Role`
    WHERE parenttype = 'Workflow Action'
      AND parent IN (
          SELECT name FROM `tabWorkflow Action` WHERE reference_doctype = 'Member'
      )
"""


def execute():
    deleted_actions = frappe.db.count("Workflow Action", {"reference_doctype": "Member"})
    deleted_roles = 0

    if deleted_actions:
        # frappe.db.delete issues a raw DELETE and does NOT cascade -- the children must
        # go first, or they are orphaned rather than deleted.
        deleted_roles = frappe.db.sql(f"SELECT COUNT(*) {_CHILD_ROWS}")[0][0]
        if deleted_roles:
            frappe.db.sql(f"DELETE {_CHILD_ROWS}")
        frappe.db.delete("Workflow Action", {"reference_doctype": "Member"})

    workflow_removed = False
    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        frappe.delete_doc("Workflow", WORKFLOW_NAME, ignore_permissions=True, force=True)
        workflow_removed = True

    if workflow_removed or deleted_actions:
        # Drop the memoized workflow name; nothing else clears it after patches run.
        frappe.clear_cache(doctype="Member")
        frappe.db.commit()
        frappe.logger().info(
            f"remove_membership_application_workflow: workflow_removed={workflow_removed}, "
            f"workflow_actions_deleted={deleted_actions}, "
            f"permitted_roles_deleted={deleted_roles}"
        )
