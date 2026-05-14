"""MijnRoodVolunteerSyncService — applies MijnRood role events.

Extracted from event_application_service.py as Phase 1, PR #4 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns:
- Role parsing (_parse_mijnrood_roles)
- Volunteer creation (_ensure_volunteer)
- Frappe role assignment (_ensure_user_role)
- Chapter board membership (_ensure_chapter_board_membership,
  _end_chapter_board_membership, _notify_board_membership_change)
- Team membership (_ensure_team_membership, _end_team_membership,
  _prune_orphan_team_members)
- Role-action dispatch (_apply_role_actions)
- Top-level role transition routing (_handle_admin_role_change,
  _handle_division_contact_change)
- Role-processing entry point (_process_member_roles)

It delegates back to the calling event-application orchestrator only
for _ensure_user_account_for_volunteer, which depends on the
orchestrator's _acr_queued_members instance-state and stays in the
god-class. That parameter will go away when the god-class's per-run
dedup state moves to a context object in PR #6.
"""

import json
import logging
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import get_role_mapping
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.volunteer_sync")


class MijnRoodVolunteerSyncService:
    """Applies MijnRood role/team/board events to Verenigingen records."""

    def __init__(self):
        self.logger = logger

    @staticmethod
    def _parse_mijnrood_roles(roles_value) -> set[str]:
        """Parse the MijnRood roles JSON column into a set of role strings.

        The roles column contains a JSON array like '["ROLE_ADMIN"]' or null.
        """
        if not roles_value:
            return set()

        if isinstance(roles_value, str):
            try:
                parsed = json.loads(roles_value)
            except (json.JSONDecodeError, ValueError):
                return set()
        elif isinstance(roles_value, list):
            parsed = roles_value
        else:
            return set()

        return {r for r in parsed if isinstance(r, str) and r.startswith("ROLE_")}

    def _ensure_volunteer(
        self,
        member_name: str,
        config: dict,
        orchestrator,
        event=None,
    ) -> Optional[str]:
        """Create Volunteer record and assign role if configured.

        Uses the existing create_volunteer_from_member() function which
        handles account creation, deduplication, etc.

        Returns:
            Human-readable status message, or None if skipped.
        """
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
            get_volunteer_for_member,
        )

        existing = get_volunteer_for_member(member_name)
        if existing:
            # Volunteer already exists — skip individual role assignment when
            # add_to_team is configured, because the team hook will handle the
            # role profile (which includes all necessary roles). Using add_roles()
            # here is futile: Frappe's populate_role_profile_roles() overwrites
            # individually added roles on every User.save().
            if config.get("add_to_team"):
                self.logger.debug(
                    "Skipping individual role assignment for %s — team hook will set profile",
                    member_name,
                )
                # Ensure User account exists — team hook needs it for profile sync
                acr_msg = orchestrator._ensure_user_account_for_volunteer(member_name)
                return acr_msg  # None if user exists or ACR already queued
            role = config.get("verenigingen_role")
            if role:
                role_msg = self._ensure_user_role(member_name, role)
                if role_msg:
                    return role_msg
            return None

        # Create volunteer — account creation is needed when a role is assigned
        # OR when the member will be added to a team (team hook needs a User
        # account to sync role profiles).
        roles = None
        create_account = False
        role = config.get("verenigingen_role")
        role_profile = config.get("role_profile")
        needs_team = config.get("add_to_team") and config.get("default_team")
        if role:
            create_account = True
            roles = [role]
        elif needs_team:
            create_account = True

        try:
            result = create_volunteer_from_member(
                member_name=member_name,
                create_user_account=create_account,
                roles=roles,
                role_profile=role_profile,
            )
            if result.get("success") is False:
                error = result.get("error", "Unknown error")
                self.logger.warning("Volunteer creation skipped for %s: %s", member_name, error)
                return _("Volunteer creation skipped: {0}").format(error)

            volunteer_name = result.get("volunteer")
            if create_account:
                orchestrator._acr_queued_members.add(member_name)
            self.logger.info(
                "Created volunteer %s for member %s (event %s, role=%s, account=%s)",
                volunteer_name,
                member_name,
                event.name if event else "N/A",
                role,
                create_account,
            )
            msg = _("Volunteer {0} created").format(volunteer_name)
            if role:
                msg += _("; role '{0}' assigned").format(role)
            if create_account and not role:
                msg += _("; account creation queued for team membership")
            return msg

        except Exception as e:
            self.logger.error("Volunteer creation failed for %s: %s", member_name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Volunteer Creation Failed: {member_name}",
            )
            return _("Volunteer creation failed: {0}").format(str(e)[:200])

    def _ensure_user_role(self, member_name: str, role: str) -> Optional[str]:
        """Ensure a member's user account has the specified role.

        Returns:
            Message if role was added, None if already present or no user.
        """
        user = frappe.db.get_value("Member", member_name, "user")
        if not user:
            return None

        if not frappe.db.exists("Role", role):
            self.logger.warning("Role '%s' does not exist, skipping assignment", role)
            return _("Role '{0}' does not exist").format(role)

        try:
            existing_roles = frappe.get_roles(user)
            if role in existing_roles:
                return None

            user_doc = frappe.get_doc("User", user)
            user_doc.add_roles(role)
            self.logger.info("Assigned role '%s' to user %s (member %s)", role, user, member_name)
            return _("Role '{0}' assigned to {1}").format(role, user)
        except Exception as e:
            self.logger.error("Role assignment failed for %s (role %s): %s", user, role, e)
            return _("Role assignment failed: {0}").format(str(e)[:200])

    def _prune_orphan_team_members(self, team_doc, team_name: str) -> int:
        """Remove team_members rows whose volunteer no longer exists.

        Frappe's ``_validate_links()`` validates every child row on parent
        save, so a single orphan reference (left behind by a Volunteer that
        was hard-deleted without ending its team memberships first) blocks
        adding any new row to the team. Prune defensively before save.

        Returns the number of rows pruned.
        """
        referenced = [row.volunteer for row in team_doc.team_members if row.volunteer]
        if not referenced:
            return 0

        existing = set(
            frappe.get_all(
                "Volunteer",
                filters={"name": ["in", list(set(referenced))]},
                pluck="name",
            )
        )
        orphan_rows = [
            row for row in team_doc.team_members if row.volunteer and row.volunteer not in existing
        ]
        for row in orphan_rows:
            self.logger.warning(
                "Pruning orphan Team Member row from team %s: volunteer %s no longer exists",
                team_name,
                row.volunteer,
            )
            team_doc.remove(row)
        return len(orphan_rows)

    def _ensure_chapter_board_membership(
        self,
        member_name: str,
        division_id: int,
        chapter_role: str,
        event=None,
    ) -> Optional[str]:
        """Add member to a chapter's board if not already present.

        Resolves division_id → Chapter, checks for existing board membership,
        and appends to the Chapter's board_members child table.

        Saving the Chapter triggers BoardManager.handle_board_member_additions(),
        which assigns the Frappe role and syncs the user's role profile.

        Returns:
            Human-readable status message, or None if skipped.
        """
        chapter_name = get_mapping_service().resolve_division_id(division_id)
        if not chapter_name:
            return _("Division ID {0} does not match any Chapter").format(division_id)

        if not frappe.db.exists("Chapter", chapter_name):
            return _("Chapter '{0}' does not exist").format(chapter_name)

        # Need a Volunteer record for the board member
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return _("No Volunteer record for {0} — cannot add to chapter board").format(member_name)

        if not frappe.db.exists("Chapter Role", chapter_role):
            self.logger.warning("Chapter Role '%s' does not exist, skipping board assignment", chapter_role)
            return _("Chapter Role '{0}' does not exist").format(chapter_role)

        # Check if already on this chapter's board (active)
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        for bm in chapter_doc.board_members or []:
            if bm.volunteer == volunteer_name and bm.is_active:
                return None  # Already on board

        # Add to board
        try:
            chapter_doc.append(
                "board_members",
                {
                    "volunteer": volunteer_name,
                    "chapter_role": chapter_role,
                    "from_date": today(),
                    "is_active": 1,
                    "notes": "Added via MijnRood sync (event {0})".format(event.name if event else "N/A"),
                },
            )
            # Security: System-initiated board assignment from authoritative MijnRood data
            # Role assignment is handled by Chapter.before_save → BoardManager.handle_board_member_additions
            chapter_doc.save(ignore_permissions=True)

            self.logger.info(
                "Added %s to chapter %s board as %s (event %s)",
                volunteer_name,
                chapter_name,
                chapter_role,
                event.name if event else "N/A",
            )
            return _("Added to chapter '{0}' board as {1}").format(chapter_name, chapter_role)
        except Exception as e:
            self.logger.error(
                "Failed to add %s to chapter %s board: %s",
                volunteer_name,
                chapter_name,
                e,
            )
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Chapter Board Addition Failed: {member_name}",
            )
            return _("Chapter board addition failed: {0}").format(str(e)[:200])

    def _end_chapter_board_membership(
        self,
        member_name: str,
        division_id: int,
        event=None,
    ) -> Optional[str]:
        """Remove a member's active chapter board membership when their division contact role is revoked.

        Uses BoardManager.bulk_remove_board_members() which deletes the child table
        row entirely (volunteer assignment history is preserved on the Volunteer record).
        The save triggers BoardManager.handle_board_member_changes() for role cleanup.

        Args:
            member_name: Vereinigingen Member name
            division_id: MijnRood division ID to resolve to Chapter
            event: Sync event for logging context

        Returns:
            Human-readable status message, or None if not on the board.
        """
        chapter_name = get_mapping_service().resolve_division_id(division_id)
        if not chapter_name:
            return _("Division ID {0} does not match any Chapter").format(division_id)

        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return None  # No volunteer record — nothing to remove

        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Find active board membership(s) for this volunteer
        target_rows = [
            bm for bm in (chapter_doc.board_members or []) if bm.volunteer == volunteer_name and bm.is_active
        ]

        if not target_rows:
            return None  # Not on this chapter's board

        try:
            reason = "MijnRood sync — division contact revoked (event {0})".format(
                event.name if event else "N/A"
            )
            removal_data = [
                {
                    "volunteer": bm.volunteer,
                    "chapter_role": bm.chapter_role,
                    "from_date": str(bm.from_date),
                    "end_date": str(today()),
                    "reason": reason,
                }
                for bm in target_rows
            ]

            result = (
                chapter_doc.board_manager.bulk_remove_board_members(  # ast-skip: dynamic manager property
                    removal_data
                )
            )

            if result.get("success"):
                self.logger.info(
                    "Removed board membership for volunteer %s in chapter %s (member %s, event %s)",
                    volunteer_name,
                    chapter_name,
                    member_name,
                    event.name if event else "N/A",
                )
                return _("Removed from chapter '{0}' board").format(chapter_name)
            else:
                error_msg = result.get("error") or "; ".join(result.get("errors", []))
                self.logger.error(
                    "BoardManager.bulk_remove_board_members failed for %s in %s: %s",
                    volunteer_name,
                    chapter_name,
                    error_msg,
                )
                return _("Chapter board removal failed: {0}").format(str(error_msg)[:200])
        except Exception as e:
            self.logger.error(
                "Failed to remove board membership for %s in chapter %s: %s",
                member_name,
                chapter_name,
                e,
            )
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Chapter Board Removal Failed: {member_name}",
            )
            return _("Chapter board removal failed: {0}").format(str(e)[:200])

    def _notify_board_membership_change(
        self,
        member_name: str,
        removed_division_ids: set,
        event=None,
    ) -> None:
        """Send a notification when board memberships are ended via sync.

        Creates both a transient realtime message and a persistent Notification Log
        entry (via the notification configuration system) so the change is visible
        in the bell icon.
        """
        chapter_names = []
        for div_id in sorted(removed_division_ids):
            ch = get_mapping_service().resolve_division_id(div_id)
            chapter_names.append(ch or f"division {div_id}")

        subject = _("Board membership ended for {0}").format(member_name)
        message = _("MijnRood sync ended board membership for {0} in: {1}").format(
            member_name, ", ".join(chapter_names)
        )
        if event:
            message += _(" (event {0})").format(event.name)

        # Transient realtime notification for the current session
        frappe.publish_realtime(
            "board_membership_ended",
            {"member": member_name, "chapters": chapter_names, "message": message},
            user=frappe.session.user,
        )

        # Persistent notification via the notification configuration system
        from verenigingen.utils.notification_helpers import notify_administrators

        try:
            notify_administrators(
                subject=subject,
                message=f"<p>{message}</p>",
                notification_key="chapter_board_removed",
                category="Chapter",
                document_type="MijnRood Sync Event",
                document_name=event.name if event else None,
            )
        except Exception as e:
            self.logger.warning("Failed to create notification: %s", e)


_service_instance: Optional[MijnRoodVolunteerSyncService] = None


def get_volunteer_sync_service() -> MijnRoodVolunteerSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodVolunteerSyncService()
    return _service_instance
