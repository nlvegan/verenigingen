"""Grant Verenigingen Staff the membership approval-path workflow transitions.

Background:
  Membership approval is authorised at the API layer by
  ``chapter_security.get_user_manageable_chapters``, which returns 'all' for
  Verenigingen Staff (Staff is in ``Roles.ADMIN_ROLES``).
  ``approve_membership_application`` runs ``validate_chapter_permission_or_throw``
  and then drives the member from ``Pending`` to ``Approved``.

  Because ``application_status`` is the "Membership Application Workflow"
  state field, that save is also validated against the workflow's role gate —
  which only allowed Verenigingen Administrator and System Manager. So a
  Verenigingen Staff user, already past the chapter-permission check, was
  blocked at the workflow with "Workflow State transition not allowed from
  Pending to Approved". The two permission layers disagreed.

  This patch aligns the workflow with the API model by adding Verenigingen
  Staff to the review/approval-path transitions (Start Review, Approve). The
  workflow setup function (membership_application_workflow_setup.py) seeds
  these for fresh installs; this patch backfills existing workflows. Idempotent.

  Post-approval financial transitions (Request Payment, Activate, Confirm
  Payment) and rejection deliberately remain with Administrators / System
  Manager — Staff drives application triage, not activation or payment.
"""

import frappe

from verenigingen.utils.constants import Roles

WORKFLOW_NAME = "Membership Application Workflow"

# (state, action, next_state) transitions Verenigingen Staff should be able to drive.
STAFF_TRANSITIONS = (
    ("Pending", "Start Review", "Under Review"),
    ("Pending", "Approve", "Approved"),
    ("Under Review", "Approve", "Approved"),
)


def execute():
    if not frappe.db.exists("Workflow", WORKFLOW_NAME):
        return

    workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)

    existing = {(t.state, t.action, t.next_state, t.allowed) for t in workflow.transitions}

    added = 0
    for state, action, next_state in STAFF_TRANSITIONS:
        if (state, action, next_state, Roles.VERENIGINGEN_STAFF) in existing:
            continue
        workflow.append(
            "transitions",
            {
                "state": state,
                "action": action,
                "next_state": next_state,
                "allowed": Roles.VERENIGINGEN_STAFF,
            },
        )
        added += 1

    if added:
        workflow.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.logger().info(
            f"add_staff_to_membership_workflow: added {added} Verenigingen Staff transition(s)"
        )
