"""
Account Group Validation Hooks
Integrates the account group project framework with ERPNext transactions.
"""

import frappe
from frappe import _

from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters
from verenigingen.utils.account_group_project_framework import account_group_framework
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


def validate_expense_claim_chapter_access(doc):
    """
    Validate that the user has access to the selected chapter on an Expense Claim.

    Raises:
        frappe.PermissionError: If user doesn't have access to the selected chapter
    """
    user = frappe.session.user
    chapter = doc.custom_chapter  # ast-skip: Custom Field added to Sales Invoice

    if not chapter:
        return

    # Get accessible chapters for current user
    accessible_chapters = get_user_accessible_chapters(user)

    # None means admin access - allow all chapters
    if accessible_chapters is None:
        return

    # Empty list means no chapter access
    if not accessible_chapters:
        frappe.msgprint(
            msg=_(
                "You do not have permission to create expense claims for any chapter. Please contact an administrator."
            ),
            title=_("Chapter Access Required"),
            indicator="red",
            raise_exception=True,
        )

    # Check if selected chapter is in accessible list
    if chapter not in accessible_chapters:
        frappe.msgprint(
            msg=_(
                "You do not have permission to create expense claims for chapter <b>{0}</b>.<br><br>You can only create expense claims for chapters where you are an active board member."
            ).format(chapter),
            title=_("Insufficient Chapter Permissions"),
            indicator="red",
            raise_exception=True,
        )


def validate_journal_entry(doc, method):
    """Validate journal entry accounts against account group mappings"""
    for account in doc.accounts:
        if account.account:
            account_group = get_account_group_for_account(account.account)
            if account_group:
                result = account_group_framework.validate_transaction(
                    account_group, account.project, account.cost_center
                )

                if not result["valid"]:
                    frappe.throw("<br>".join(result["errors"]))

                # Apply defaults if not set
                apply_defaults_to_account_row(account, account_group)


# Roles that make a Staff member more than "plain" Staff: they approve any claim, scoped
# by their own role rather than by the Staff rule below. Treasurer, National Board Member
# and Administrator profiles all carry Verenigingen Staff as well.
_STAFF_APPROVAL_EXEMPT_ROLES = frozenset(
    {
        Roles.TREASURER,
        Roles.NATIONAL_BOARD_MEMBER,
        Roles.VERENIGINGEN_ADMIN,
        Roles.SYSTEM_MANAGER,
        Roles.HR_MANAGER,
    }
)


def validate_expense_claim_approval(doc):
    """Refuse the approval decisions the maintainer ruled out (#1606).

    Runs from the Expense Claim ``validate`` hook, which covers both save and submit
    (``approval_status`` is not allow-on-submit, so no later path can change it; Frappe
    refuses with UpdateAfterSubmitError). Two rules, both on a
    decision (Approved or Rejected) that is new in this save or is carried over to a different
    employee:

    - Nobody decides their own claim, except the Treasurer role. HRMS's
      ``prevent_self_expense_approval`` has no role exemption and is switched off by any
      Expense Claim Workflow, so the exemption cannot be expressed there.
    - Plain Staff may not decide the claim of an employee who is also Staff.
    """
    if doc.approval_status not in ("Approved", "Rejected"):
        return
    # Re-pointing a decided claim at another employee is a decision about that employee's
    # claim: approve a stranger's claim, then change ``employee`` to your own (or to another
    # Staff member's), and a guard keyed on approval_status alone never sees it.
    if not (doc.has_value_changed("approval_status") or doc.has_value_changed("employee")):
        return

    user = frappe.session.user
    user_roles = frappe.get_roles(user)
    claimant = frappe.db.get_value("Employee", doc.employee, "user_id")

    if claimant and claimant == user and Roles.TREASURER not in user_roles:
        frappe.throw(_("You cannot approve or reject your own expense claim."), frappe.PermissionError)

    is_plain_staff = Roles.VERENIGINGEN_STAFF in user_roles and not _STAFF_APPROVAL_EXEMPT_ROLES.intersection(
        user_roles
    )
    if is_plain_staff and claimant and Roles.VERENIGINGEN_STAFF in frappe.get_roles(claimant):
        frappe.throw(
            _("Staff cannot approve or reject the expense claim of another Staff member."),
            frappe.PermissionError,
        )


def validate_expense_claim(doc, method):
    """Validate expense claim against account group mappings and chapter access"""
    validate_expense_claim_approval(doc)

    # Auto-populate department from custom_chapter for ERPNext native filtering
    if doc.custom_chapter and not doc.department:  # ast-skip: Custom Field
        # Try to find a matching department
        department = frappe.db.get_value("Department", doc.custom_chapter, "name")  # ast-skip: Custom Field
        if department:
            doc.department = department
        else:
            # Log if department doesn't exist but don't block
            frappe.logger().info(
                f"No matching Department found for chapter {doc.custom_chapter}. "  # ast-skip: Custom Field
                "Consider creating departments matching chapter names for better ERPNext integration."
            )

    # Validate chapter access if custom_chapter is set
    if doc.custom_chapter:  # ast-skip: Custom Field
        validate_expense_claim_chapter_access(doc)

    # Validate account group mappings
    for expense in doc.expenses:
        if expense.default_account:
            account_group = get_account_group_for_account(expense.default_account)
            if account_group:
                result = account_group_framework.validate_transaction(
                    account_group, expense.project, expense.cost_center
                )

                if not result["valid"]:
                    frappe.throw("<br>".join(result["errors"]))

                # Apply defaults if not set
                apply_defaults_to_expense_row(expense, account_group)


def validate_purchase_invoice(doc, method):
    """Validate purchase invoice against account group mappings"""
    for item in doc.items:
        if item.expense_account:
            account_group = get_account_group_for_account(item.expense_account)
            if account_group:
                result = account_group_framework.validate_transaction(
                    account_group, item.project, item.cost_center
                )

                if not result["valid"]:
                    frappe.throw("<br>".join(result["errors"]))

                # Apply defaults if not set
                apply_defaults_to_item_row(item, account_group)


def apply_defaults_to_account_row(account_row, account_group):
    """Apply default project and cost center to journal entry account row"""
    defaults = account_group_framework.get_defaults_for_transaction(account_group)

    if not account_row.project and defaults.get("project"):
        account_row.project = defaults["project"]

    if not account_row.cost_center and defaults.get("cost_center"):
        account_row.cost_center = defaults["cost_center"]


def apply_defaults_to_expense_row(expense_row, account_group):
    """Apply default project and cost center to expense claim row"""
    defaults = account_group_framework.get_defaults_for_transaction(account_group)

    if not expense_row.project and defaults.get("project"):
        expense_row.project = defaults["project"]

    if not expense_row.cost_center and defaults.get("cost_center"):
        expense_row.cost_center = defaults["cost_center"]


def apply_defaults_to_item_row(item_row, account_group):
    """Apply default project and cost center to purchase invoice item row"""
    defaults = account_group_framework.get_defaults_for_transaction(account_group)

    if not item_row.project and defaults.get("project"):
        item_row.project = defaults["project"]

    if not item_row.cost_center and defaults.get("cost_center"):
        item_row.cost_center = defaults["cost_center"]


def get_account_group_for_account(account):
    """Get the account group for a given account"""
    if not account:
        return None

    # Check if account is a group itself
    account_doc = frappe.get_cached_doc("Account", account)
    if account_doc.is_group:
        return account

    # Walk up the parent chain to find the group
    current_account = account_doc
    while current_account.parent_account:
        parent = frappe.get_cached_doc("Account", current_account.parent_account)
        if parent.is_group and parent.root_type in ["Income", "Expense"]:
            # Check if this parent has a mapping
            if frappe.db.exists("Account Group Project Mapping", parent.name):
                return parent.name
        current_account = parent

    return None


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_account_group_info_for_account(account):
    """Get account group info for frontend use"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return {}

    mapping = account_group_framework.get_mapping(account_group)
    if not mapping:
        return {}

    return {
        "account_group": account_group,
        "account_group_type": mapping.get("account_group_type"),
        "tracking_mode": mapping.get("tracking_mode"),
        "requires_project": mapping.get("requires_project"),
        "requires_cost_center": mapping.get("requires_cost_center"),
        "default_project": mapping.get("default_project"),
        "default_cost_center": mapping.get("default_cost_center"),
        "description": mapping.get("description"),
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_filtered_projects_for_account(account):
    """Get filtered projects for an account based on account group mapping"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return frappe.get_all("Project", filters={"status": "Open"}, fields=["name", "project_name"])

    return account_group_framework.get_valid_projects(account_group)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_filtered_cost_centers_for_account(account):
    """Get filtered cost centers for an account based on account group mapping"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return frappe.get_all("Cost Center", filters={"is_disabled": 0}, fields=["name", "cost_center_name"])

    return account_group_framework.get_valid_cost_centers(account_group)


def setup_validation_hooks():
    """Setup validation hooks in the system"""

    # This would typically be called from hooks.py
    hooks = {
        "Journal Entry": {
            "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry"
        },
        "Expense Claim": {
            "validate": "verenigingen.utils.account_group_validation_hooks.validate_expense_claim"
        },
        "Purchase Invoice": {
            "validate": "verenigingen.utils.account_group_validation_hooks.validate_purchase_invoice"
        },
    }

    return hooks


# Client-side integration functions
@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_account_defaults_for_form(account):
    """Get account defaults for form auto-population"""
    info = get_account_group_info_for_account(account)
    if not info:
        return {}

    return {
        "project": info.get("default_project"),
        "cost_center": info.get("default_cost_center"),
        "requires_project": info.get("requires_project"),
        "requires_cost_center": info.get("requires_cost_center"),
        "tracking_mode": info.get("tracking_mode"),
        "description": info.get("description"),
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_form_selection(account, project=None, cost_center=None):
    """Validate form selection before save"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return {"valid": True}

    return account_group_framework.validate_transaction(account_group, project, cost_center)
