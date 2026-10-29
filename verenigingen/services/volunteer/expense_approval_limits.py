"""Per-chapter expense approval amount limits (#1651).

Maintainer ruling (2026-10-12): the limits mainly restrict what a LOCAL (chapter) treasurer
can approve. A claim above a seat's limit goes up -- Admin/Basic seat -> the chapter's
Financial seat -> the national treasurer (the national board's Financial seat). Double
approval was considered and rejected.

Rules, all keyed on the claim's chapter (``custom_chapter``, else the team's chapter):

- A seat holder of the claim's chapter is limited by their seat's level: a Financial seat
  by ``Chapter.financial_role_approval_limit``, any other seat by
  ``Chapter.board_member_approval_limit``. ``Chapter Role.permissions_level`` decides the
  level, never a role name (#1650).
- A blank/zero limit means NO limit (coordinator decision, preserves today's behaviour; the
  field descriptions say "Leave blank for no limit"). A Currency field cannot tell blank
  from 0, so 0 is also "no limit".
- A regular seat can never approve more than the Financial seat of the same chapter: with
  both limits set the lower one applies, and with only the Financial limit set it applies to
  regular seats too, so a claim never skips a level on its way up.
- Unlimited, and only these (maintainer ruling 2026-10-29, "narrow + fail closed"): the
  Administrator user, holders of the Treasurer role, a System Manager who is not a
  Verenigingen Administrator (that profile bundles System Manager but is ruled bound), and
  anyone holding a Financial seat on the national board chapter. Everyone else is bound by
  their seat on the claim's chapter, and a user with NO seat there (Staff, National Board
  Member, Verenigingen Administrator, HR Manager) is bound like a regular seat: refused above
  the regular limit, so such a claim goes up. Fail-closed applies only where a limit exists:
  a chapter with no limits set stays unlimited for everyone.
- The amount compared is what the claim can actually pay out: the larger of
  ``total_claimed_amount`` and ``total_sanctioned_amount`` plus taxes and charges.

``get_approval_limit`` is the single place that answers "how much may this user approve for
this chapter"; the approval gate, the escalation routing and the portal text all read it.
"""

from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_member_name_for_board_access, get_volunteer_for_member

FINANCIAL = "Financial"


def get_claim_chapter(doc) -> Optional[str]:
    """The chapter a claim is booked against: its own, else its team's. None = national."""
    if doc.get("custom_chapter"):
        return doc.custom_chapter
    if doc.get("custom_team"):
        return frappe.db.get_value("Team", doc.custom_team, "chapter") or None
    return None


def get_chapter_limits(chapter: str) -> tuple:
    """(regular_seat_limit, financial_seat_limit) of a chapter; None = no limit."""
    row = frappe.db.get_value(
        "Chapter", chapter, ["board_member_approval_limit", "financial_role_approval_limit"], as_dict=True
    )
    if not row:
        return None, None
    regular = flt(row.board_member_approval_limit) or None
    financial = flt(row.financial_role_approval_limit) or None
    if financial is not None and (regular is None or regular > financial):
        regular = financial
    return regular, financial


def get_seat_levels(user: str, chapter: str) -> set:
    """Levels of the user's active seats on ``chapter``: Financial or Regular (empty = no seat).

    Identity is Member.user only (#1546): this is an authorization decision. A seat whose
    Chapter Role is missing or inactive still counts as a seat, but never as Financial.
    """
    member = get_member_name_for_board_access(user)
    volunteer = get_volunteer_for_member(member) if member else None
    if not volunteer:
        return set()
    levels = set()
    seats = frappe.get_all(
        "Chapter Board Member",
        filters={"parent": chapter, "volunteer": volunteer, "is_active": 1},
        pluck="chapter_role",
    )
    for role_name in seats:
        role = frappe.db.get_value(
            "Chapter Role", role_name, ["permissions_level", "is_active"], as_dict=True
        )
        financial = bool(role and role.is_active and role.permissions_level == FINANCIAL)
        levels.add(FINANCIAL if financial else "Regular")
    return levels


def get_claim_amount(doc) -> float:
    """What the claim can pay out: tax rows add to the sanctioned amount, so the claimed
    amount alone would let 500 at a 500 limit plus 400 tax through."""
    payable = flt(doc.get("total_sanctioned_amount")) + flt(doc.get("total_taxes_and_charges"))
    return max(flt(doc.get("total_claimed_amount")), payable)


def _is_unlimited(user: str) -> bool:
    roles = frappe.get_roles(user)
    if user == "Administrator" or Roles.TREASURER in roles:
        return True
    if Roles.SYSTEM_MANAGER in roles and Roles.VERENIGINGEN_ADMIN not in roles:
        return True
    national = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
    return bool(national) and FINANCIAL in get_seat_levels(user, national)


def get_approval_limit(user: str, chapter: Optional[str]) -> Optional[float]:
    """How much ``user`` may approve for a claim of ``chapter``. None = unlimited."""
    if not chapter or _is_unlimited(user):
        return None
    levels = get_seat_levels(user, chapter)
    regular, financial = get_chapter_limits(chapter)
    # no seat at all is bound like a regular seat (fail closed)
    return financial if FINANCIAL in levels else regular


def validate_amount_within_approval_limit(doc, user: str) -> None:
    """Refuse an approval of ``doc`` that is above what ``user`` may approve for its chapter."""
    chapter = get_claim_chapter(doc)
    limit = get_approval_limit(user, chapter)
    amount = get_claim_amount(doc)
    if limit is None or amount <= limit:
        return
    next_level = (
        _("the national treasurer")
        if FINANCIAL in get_seat_levels(user, chapter)
        else _("the financial board member of the chapter or the national treasurer")
    )
    frappe.throw(
        _(
            "This claim of {0} is above your approval limit of {1} for chapter {2}. "
            "It has to be approved by {3}."
        ).format(
            fmt_money(amount, currency=doc.get("currency")),
            fmt_money(limit, currency=doc.get("currency")),
            chapter,
            next_level,
        ),
        frappe.PermissionError,
    )


def route_claim_above_limit(doc) -> None:
    """Point an undecided claim at the next approver up when its amount exceeds the limit of
    the approver it is currently assigned to (the claim's, else the employee's).

    Escalates only: no approver found leaves the assignment alone (the approval gate still
    refuses an approver who is over their limit).
    """
    chapter = get_claim_chapter(doc)
    amount = get_claim_amount(doc)
    current = doc.get("expense_approver") or frappe.db.get_value("Employee", doc.employee, "expense_approver")
    if not (chapter and current):
        return
    limit = get_approval_limit(current, chapter)
    if limit is None or amount <= limit:
        return
    approver = _next_approver_up(doc, chapter, amount, current)
    if approver:
        doc.expense_approver = approver


def _next_approver_up(doc, chapter: str, amount: float, current: str) -> Optional[str]:
    from verenigingen.services.volunteer.expense_approver_service import VolunteerExpenseApproverService

    claimant = frappe.db.get_value("Volunteer", {"employee_id": doc.employee}, "name")
    service = VolunteerExpenseApproverService(claimant or "")
    boards = []
    if FINANCIAL not in get_seat_levels(current, chapter):
        boards.append(chapter)
    national = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
    if national and national not in boards:
        boards.append(national)
    for board in boards:
        candidate = service.get_board_financial_approver(board, exclude_volunteer=claimant or None)
        if not candidate or candidate == current:
            continue
        candidate_limit = get_approval_limit(candidate, chapter)
        if candidate_limit is None or amount <= candidate_limit:
            return candidate
    return None


def get_chapter_thresholds() -> dict:
    """{chapter: {"regular_limit": float|None, "financial_limit": float|None}} for every chapter
    that sets a limit; a chapter missing from the result has none. Read by the portal."""
    chapters = frappe.get_all(
        "Chapter",
        or_filters={"board_member_approval_limit": [">", 0], "financial_role_approval_limit": [">", 0]},
        pluck="name",
    )
    thresholds = {}
    for chapter in chapters:
        regular, financial = get_chapter_limits(chapter)
        thresholds[chapter] = {"regular_limit": regular, "financial_limit": financial}
    return thresholds
