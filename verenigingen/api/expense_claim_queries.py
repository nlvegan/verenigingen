#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Expense Claim Query Filters for Chapter Board Members

Provides custom query functions for filtering expense approvers based on
chapter and team organizational structures. Ensures expense claims are
approved by appropriate chapter board members with financial authority.

Business Rules:
- Expense approvers must be board members of the relevant chapter
- Approvers must have financial roles (Treasurer, Financial Officer, etc.)
- Approvers must have the "Expense Approver" role enabled
- Team expenses use the team's parent chapter for approver selection

Integration Points:
- VolunteerExpenseApproverService: Automatic approver determination logic
- Chapter Board Member: Board position tracking
- Chapter Role: Permission level definitions
- Expense Claim: ERPNext expense management
"""

from typing import Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, standard_api

# Financial roles that can approve expenses (matches VolunteerExpenseApproverService)
FINANCIAL_ROLES = [
    "Treasurer",
    "Financial Officer",
    "Secretary-Treasurer",
    "Board Chair",
    "Secretary",
]


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_user_accessible_chapters_for_expenses(
    doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: Optional[dict] = None
):
    """
    Get chapters accessible to the current user for expense claim assignment.

    Returns:
    - Admins/Staff: All active chapters
    - National board members: All active chapters
    - Chapter board members: Only their chapters

    Args:
        doctype: Target doctype (Chapter)
        txt: Search text for filtering
        searchfield: Field to search in (name)
        start: Pagination start
        page_len: Page length
        filters: Additional filters (not used)

    Returns:
        List of tuples: [(chapter_name,), ...]
    """
    from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

    if filters is None:
        filters = {}

    user = frappe.session.user

    # Get accessible chapters using existing utility
    accessible_chapters = get_user_accessible_chapters(user)

    # None means admin access - return all active chapters
    if accessible_chapters is None:
        query = """
            SELECT name
            FROM `tabChapter`
            WHERE status = 'Active'
                AND name LIKE %(txt)s
            ORDER BY name
            LIMIT %(start)s, %(page_len)s
        """
        return frappe.db.sql(
            query,
            {"txt": f"%{txt}%", "start": start, "page_len": page_len},
            as_list=True,
        )

    # Empty list means no access
    if not accessible_chapters:
        return []

    # Build search condition
    search_condition = ""
    if txt:
        search_condition = "AND name LIKE %(txt)s"

    # Return only accessible chapters
    chapter_names = [frappe.db.escape(ch) for ch in accessible_chapters]
    query = f"""
        SELECT name
        FROM `tabChapter`
        WHERE status = 'Active'
            AND name IN ({','.join(chapter_names)})
            {search_condition}
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """  # nosec B608  # Safe: chapter_names escaped, search_condition static, user input parameterized

    return frappe.db.sql(
        query,
        {"txt": f"%{txt}%", "start": start, "page_len": page_len},
        as_list=True,
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_chapter_expense_approvers(
    doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: Optional[dict] = None
):
    """
    Get expense approvers for a specific chapter.

    Returns users who are:
    - Board members of the specified chapter
    - Have Admin or Financial permission level roles
    - Have the "Expense Approver" role
    - Are enabled users

    Args:
        doctype: Target doctype (User)
        txt: Search text for filtering
        searchfield: Field to search in (email or full_name)
        start: Pagination start
        page_len: Page length
        filters: Dict with 'chapter' key

    Returns:
        List of tuples: [(user_email, user_full_name), ...]
    """
    if filters is None:
        filters = {}

    chapter = filters.get("chapter")
    if not chapter:
        return []

    # Build search condition
    search_condition = ""
    if txt:
        search_condition = """
            AND (u.email LIKE %(txt)s OR u.full_name LIKE %(txt)s)
        """

    # Query for chapter board members with Admin or Financial permission levels and Expense Approver role
    query = f"""
        SELECT DISTINCT
            u.email,
            u.full_name,
            cr.name as role_name
        FROM `tabUser` u
        JOIN `tabHas Role` hr ON hr.parent = u.name
        JOIN `tabVolunteer` v ON v.user = u.email
        JOIN `tabChapter Board Member` cbm ON cbm.volunteer = v.name
        JOIN `tabChapter Role` cr ON cr.name = cbm.chapter_role
        WHERE u.enabled = 1
            AND u.name != 'Administrator'
            AND hr.role = 'Expense Approver'
            AND cbm.parent = %(chapter)s
            AND cbm.is_active = 1
            AND cr.permissions_level IN ('Admin', 'Financial')
            {search_condition}
        ORDER BY u.full_name
        LIMIT %(start)s, %(page_len)s
    """  # nosec B608  # Safe: search_condition is static string, all user input parameterized

    return frappe.db.sql(
        query,
        {
            "chapter": chapter,
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
        as_list=True,
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_team_expense_approvers(
    doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: Optional[dict] = None
):
    """
    Get expense approvers for a team (uses team's chapter).

    Returns users who are:
    - Board members of the team's parent chapter
    - Have financial roles
    - Have the "Expense Approver" role
    - Are enabled users

    Args:
        doctype: Target doctype (User)
        txt: Search text for filtering
        searchfield: Field to search in (email or full_name)
        start: Pagination start
        page_len: Page length
        filters: Dict with 'team' key

    Returns:
        List of tuples: [(user_email, user_full_name), ...]
    """
    if filters is None:
        filters = {}

    team = filters.get("team")
    if not team:
        return []

    # Get the team's chapter
    team_chapter = frappe.db.get_value("Team", team, "chapter")
    if not team_chapter:
        frappe.log_error(
            message=f"Team {team} has no chapter assigned",
            title="Team Expense Approver Query Error",
        )
        return []

    # Reuse chapter query with team's chapter
    return get_chapter_expense_approvers(
        doctype=doctype,
        txt=txt,
        searchfield=searchfield,
        start=start,
        page_len=page_len,
        filters={"chapter": team_chapter},
    )
