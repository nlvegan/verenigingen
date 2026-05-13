"""MijnRoodMemberSyncService — applies MijnRood member events to Member rows.

Extracted from event_application_service.py as Phase 1, PR #2 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns the New-Member and Changed-Member event paths plus the
existing-member-or-conflict lookup. It delegates back to the calling
event-application orchestrator for cross-cutting helpers
(create_related_records, process_member_roles, try_promote_application,
check_and_handle_termination, handle_division_field_change) that have
not yet been extracted into their own services. The `orchestrator`
parameter on the public methods will be removed once all of those are
moved to their own services in later PRs.
"""

import logging
from typing import Optional

import frappe
from frappe import _

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.member_sync")


class MijnRoodMemberSyncService:
    """Applies MijnRood member events to Member rows.

    Stateful only insofar as it is a singleton — no per-instance state.
    """

    def find_existing_member_or_conflict(self, mijnrood_id, email) -> tuple[Optional[str], Optional[dict]]:
        """Look up existing member by member_id (authoritative) then email.

        Returns:
            (member_name, result_dict) — found or conflict
            (None, None) — no match
        """
        if mijnrood_id:
            existing = frappe.db.get_value("Member", {"member_id": str(mijnrood_id)}, "name")
            if existing:
                return existing, {
                    "success": True,
                    "message": _("Member {0} already exists (member_id={1})").format(existing, mijnrood_id),
                }
        if email:
            match = frappe.db.get_value("Member", {"email": email}, ["name", "member_id"], as_dict=True)
            if match:
                if match.member_id and mijnrood_id and str(match.member_id) != str(mijnrood_id):
                    return None, {
                        "success": False,
                        "message": _(
                            "Email {0} already used by {1} (member_id={2}), " "conflicts with MijnRood ID {3}"
                        ).format(email, match.name, match.member_id, mijnrood_id),
                    }
                return match.name, {
                    "success": True,
                    "message": _("Member {0} already exists (email={1})").format(match.name, email),
                }
        return None, None


_service_instance: Optional[MijnRoodMemberSyncService] = None


def get_member_sync_service() -> MijnRoodMemberSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMemberSyncService()
    return _service_instance
