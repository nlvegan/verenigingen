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

It calls the related_records service directly via
``get_related_records_orchestrator()`` for user-account creation.
"""

import json
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import get_role_mapping
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.utils.service_logger import get_service_logger

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="event_application.volunteer_sync")


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
                acr_msg = get_related_records_orchestrator()._ensure_user_account_for_volunteer(member_name)
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

            volunteer_name = result.get("volunteer_name")
            if create_account:
                get_related_records_orchestrator().mark_acr_queued(member_name)
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

    def _ensure_team_membership(
        self,
        member_name: str,
        team_name: str,
        event=None,
    ) -> Optional[str]:
        """Add member's volunteer to a team if not already an active member.

        Saving the Team triggers the ``on_team_members_change`` hook which calls
        ``auto_sync_on_role_change()`` — this recalculates the user's role profile
        via the calculator (which now respects ``is_association_wide`` priority).

        Args:
            member_name: Vereinigingen Member name
            team_name: Team document name
            event: Sync event for logging context

        Returns:
            Human-readable status message, or None if already a team member.
        """
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return _("No Volunteer record for {0} — cannot add to team").format(member_name)

        team_status = frappe.db.get_value("Team", team_name, "status")
        if not team_status:
            return _("Team '{0}' does not exist").format(team_name)
        if team_status != "Active":
            return _("Team '{0}' is not active (status: {1})").format(team_name, team_status)

        # Check if already an active team member
        existing = frappe.db.exists(
            "Team Member",
            {"parent": team_name, "volunteer": volunteer_name, "status": "Active"},
        )
        if existing:
            return None  # Already on team

        default_team_role = "Team Member"
        try:
            team_doc = frappe.get_doc("Team", team_name)
            # Defensive: Frappe's _validate_links() validates *every* child row on
            # parent save, so a single dangling volunteer reference (from a prior
            # hard-delete that skipped link checks) blocks every subsequent add.
            self._prune_orphan_team_members(team_doc, team_name)
            team_doc.append(
                "team_members",
                {
                    "volunteer": volunteer_name,
                    "team_role": default_team_role,
                    "from_date": today(),
                    "status": "Active",
                    "is_active": 1,
                    "notes": "Added via MijnRood sync (event {0})".format(event.name if event else "N/A"),
                },
            )
            # Security: System-initiated team assignment from authoritative MijnRood data
            # Saving triggers on_team_members_change → auto_sync_on_role_change()
            team_doc.save(ignore_permissions=True)

            self.logger.info(
                "Added volunteer %s to team %s (member %s, event %s)",
                volunteer_name,
                team_name,
                member_name,
                event.name if event else "N/A",
            )
            return _("Added to team '{0}'").format(team_name)
        except Exception as e:
            self.logger.error(
                "Failed to add %s to team %s: %s",
                volunteer_name,
                team_name,
                e,
            )
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Team Addition Failed: {member_name}",
            )
            return _("Team addition failed: {0}").format(str(e)[:200])

    def _end_team_membership(
        self,
        member_name: str,
        team_name: str,
        event=None,
    ) -> Optional[str]:
        """End a member's active team membership when their MijnRood role is revoked.

        Sets status to 'Ended', is_active to 0, and to_date to today.
        Saving the Team triggers the on_team_members_change hook which
        recalculates the user's role profile.

        Args:
            member_name: Vereinigingen Member name
            team_name: Team document name
            event: Sync event for logging context

        Returns:
            Human-readable status message, or None if not a team member.
        """
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return None

        # Find active team membership
        tm_name = frappe.db.get_value(
            "Team Member",
            {"parent": team_name, "volunteer": volunteer_name, "status": "Active"},
            "name",
        )
        if not tm_name:
            return None  # Not on team

        try:
            team_doc = frappe.get_doc("Team", team_name)
            for row in team_doc.team_members:
                if row.name == tm_name:
                    row.status = "Ended"
                    row.is_active = 0
                    row.to_date = today()
                    suffix = "Ended via MijnRood sync — role revoked (event {0})".format(
                        event.name if event else "N/A"
                    )
                    row.notes = f"{row.notes}\n{suffix}" if row.notes else suffix
                    break
            # Security: System-initiated team removal from authoritative MijnRood role revocation
            team_doc.save(ignore_permissions=True)

            self.logger.info(
                "Ended team membership for volunteer %s in team %s (member %s, event %s)",
                volunteer_name,
                team_name,
                member_name,
                event.name if event else "N/A",
            )
            return _("Removed from team '{0}'").format(team_name)
        except Exception as e:
            self.logger.error("Failed to end team membership for %s in %s: %s", member_name, team_name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Team Removal Failed: {member_name}",
            )
            return _("Team removal failed: {0}").format(str(e)[:200])

    def _apply_role_actions(
        self,
        member_name: str,
        config: dict,
        division_ids: Optional[list[int]] = None,
        event=None,
    ) -> list[str]:
        """Apply the configured actions for a single role mapping entry.

        Args:
            member_name: Verenigingen Member name
            config: Role mapping config dict from get_role_mapping()
            division_ids: Division IDs for ROLE_DIVISION_CONTACT (None for ROLE_ADMIN)
            event: Sync event for logging context

        Returns:
            List of human-readable status messages.
        """
        messages = []

        # Create Volunteer if configured
        if config.get("create_volunteer"):
            vol_msg = self._ensure_volunteer(member_name, config, event=event)
            if vol_msg:
                messages.append(vol_msg)

        # Add to chapter board if configured (only meaningful with division_ids)
        chapter_role = config.get("chapter_role")
        if config.get("add_to_chapter_board") and division_ids:
            if not chapter_role:
                messages.append(_("add_to_chapter_board enabled but no chapter_role configured"))
            else:
                for div_id in division_ids:
                    board_msg = self._ensure_chapter_board_membership(
                        member_name, div_id, chapter_role, event=event
                    )
                    if board_msg:
                        messages.append(board_msg)

        # Add to team if configured (team hook handles role profile sync)
        if config.get("add_to_team") and config.get("default_team"):
            team_msg = self._ensure_team_membership(member_name, config["default_team"], event=event)
            if team_msg:
                messages.append(team_msg)

        return messages

    def _handle_admin_role_change(
        self,
        member_name: str,
        current_roles: set,
        old_roles: set,
        role_config: dict,
        event=None,
    ) -> list[str]:
        """Handle ROLE_ADMIN addition or removal.

        Only fires on the *transition* (added or removed). For unchanged-admin
        events (e.g. a fee change for an existing admin) we skip role actions
        entirely — re-running them on every member update produces no useful
        delta and can break legitimate non-role updates when team data is
        corrupt or role config has drifted.
        """
        messages = []

        admin_added = "ROLE_ADMIN" in current_roles and "ROLE_ADMIN" not in old_roles
        admin_removed = "ROLE_ADMIN" in old_roles and "ROLE_ADMIN" not in current_roles

        if admin_added and "ROLE_ADMIN" in role_config:
            config = role_config["ROLE_ADMIN"]
            msgs = self._apply_role_actions(member_name, config, event=event)
            messages.extend(msgs)
        elif admin_removed:
            config = role_config.get("ROLE_ADMIN", {})
            if config.get("add_to_team") and config.get("default_team"):
                team_msg = self._end_team_membership(member_name, config["default_team"], event=event)
                if team_msg:
                    messages.append(team_msg)
            messages.append(_("ROLE_ADMIN removed from member {0}").format(member_name))
            self.logger.info(
                "ROLE_ADMIN removed from member %s (event %s)",
                member_name,
                event.name if event else "N/A",
            )

        return messages

    def _handle_division_contact_change(
        self,
        member_name: str,
        new_division_ids,
        old_division_ids,
        role_config: dict,
        event=None,
    ) -> list[str]:
        """Handle ROLE_DIVISION_CONTACT addition or removal."""
        messages = []

        if new_division_ids and "ROLE_DIVISION_CONTACT" in role_config:
            config = role_config["ROLE_DIVISION_CONTACT"]
            msgs = self._apply_role_actions(member_name, config, division_ids=new_division_ids, event=event)
            messages.extend(msgs)

        # Detect division contact removal (normalize [] and None to empty set)
        old_set = set(old_division_ids) if old_division_ids else set()
        new_set = set(new_division_ids) if new_division_ids else set()
        removed_divs = old_set - new_set

        if removed_divs:
            for div_id in sorted(removed_divs):
                try:
                    result = self._end_chapter_board_membership(member_name, div_id, event=event)
                    if result:
                        messages.append(result)
                except Exception as e:
                    self.logger.error(
                        "Failed to end board membership for member %s, division %s: %s",
                        member_name,
                        div_id,
                        e,
                    )
                    messages.append(
                        _("Failed to end board membership for division {0}: {1}").format(div_id, str(e)[:200])
                    )

            # Notify the session user about board membership changes
            self._notify_board_membership_change(member_name, removed_divs, event)

        return messages

    def _process_member_roles(
        self,
        member_name: str,
        mijnrood_data: dict,
        old_data: Optional[dict] = None,
        event=None,
    ) -> list[str]:
        """Process MijnRood admin roles for a member.

        Reads the roles JSON column and managed_division_ids to determine
        which roles the member holds, then applies configured actions
        (volunteer creation, Frappe role assignment, chapter board membership).

        Division contact removals automatically end the corresponding chapter
        board membership. Other role removals are flagged for review.

        Args:
            member_name: Vereinigingen Member name
            mijnrood_data: Current MijnRood row data (new_data from event)
            old_data: Previous MijnRood row data (for removal detection)
            event: The sync event (for logging context)

        Returns:
            List of human-readable status messages.
        """
        role_config = get_role_mapping()
        if not role_config:
            return []

        messages = []

        # 1. Parse ROLE_ADMIN from the roles JSON column
        current_roles = self._parse_mijnrood_roles(mijnrood_data.get("roles"))
        old_roles = self._parse_mijnrood_roles(old_data.get("roles")) if old_data else set()

        messages.extend(
            self._handle_admin_role_change(member_name, current_roles, old_roles, role_config, event)
        )

        # 2. Process ROLE_DIVISION_CONTACT from managed_division_ids
        new_division_ids = mijnrood_data.get("managed_division_ids")
        old_division_ids = old_data.get("managed_division_ids") if old_data else None

        messages.extend(
            self._handle_division_contact_change(
                member_name,
                new_division_ids,
                old_division_ids,
                role_config,
                event,
            )
        )

        return messages


_service_instance: Optional[MijnRoodVolunteerSyncService] = None


def get_volunteer_sync_service() -> MijnRoodVolunteerSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodVolunteerSyncService()
    return _service_instance
