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
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="event_application.volunteer_sync")

# Doc-flag on the MijnRood Sync Event carrying "this apply succeeded but left access
# behind" text up to apply_event, which persists it on the row. A service log file is
# not reachable by the operator who would act on it.
RETAINED_ACCESS_FLAG = "mijnrood_retained_access"


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
        except NON_RESUMABLE_DB_ERRORS:
            # Turning this into a per-member "failed" status would let the sync run march
            # on to the next member inside a transaction the server has already discarded,
            # and frappe.log_error() below would be a write on it. Let it reach whoever
            # owns the transaction boundary so the whole sync run is retried instead.
            raise
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

        Sets status to 'Completed' (the Team Member Select has no 'Ended' option),
        is_active to 0, and to_date to today. Saving the Team triggers the
        on_team_members_change hook which recalculates the user's role profile —
        that recalculation, not the row edit, is what actually withdraws the
        team-derived access.

        Args:
            member_name: Vereinigingen Member name
            team_name: Team document name
            event: Sync event for logging context

        Returns:
            Human-readable status message, or None if not a team member.

        Raises:
            Anything the Team save raises (after orphan rows are pruned — see
            below), and ValidationError when the recalculation did not actually
            withdraw the team's role profile (see _assert_team_profile_withdrawn).
            This is a privilege *revocation*: a failure here leaves the member's
            role profile intact, so it must never be downgraded to a status
            string. Every caller between here and
            MijnRoodEventApplicationService.apply_event passes messages through as
            success, so apply_event's except block — which records error_message
            and leaves the event un-Applied — is the only layer that can turn this
            into a visible failure.
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
            # Same defence as the addition path (_ensure_team_membership): one dangling
            # volunteer reference makes _validate_links() reject the whole parent save.
            # Without it the grant path self-heals corrupt team data while the revocation
            # path — which now raises rather than swallowing — fails permanently, i.e. a
            # member who can join the team but never leave it.
            self._prune_orphan_team_members(team_doc, team_name)
            for row in team_doc.team_members:
                if row.name == tm_name:
                    row.status = "Completed"
                    row.is_active = 0
                    row.to_date = today()
                    suffix = "Ended via MijnRood sync — role revoked (event {0})".format(
                        event.name if event else "N/A"
                    )
                    row.notes = f"{row.notes}\n{suffix}" if row.notes else suffix
                    break
            # Security: System-initiated team removal from authoritative MijnRood role revocation
            team_doc.save(ignore_permissions=True)

            # The save fires on_team_members_change → auto_sync_on_role_change(),
            # but neither can report failure. Verify the post-condition instead.
            self._assert_team_profile_withdrawn(member_name, team_name)

            self.logger.info(
                "Ended team membership for volunteer %s in team %s (member %s, event %s)",
                volunteer_name,
                team_name,
                member_name,
                event.name if event else "N/A",
            )
            return _("Removed from team '{0}'").format(team_name)
        except NON_RESUMABLE_DB_ERRORS:
            # The transaction is already discarded — log_error() below would be a
            # write on it. Let it reach the transaction owner (same clause and
            # reasoning as _ensure_chapter_board_membership; the team *addition*
            # path has no such clause).
            raise
        except Exception as e:
            self.logger.error("Failed to end team membership for %s in %s: %s", member_name, team_name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Team Removal Failed: {member_name}",
            )
            raise

    def _assert_team_profile_withdrawn(self, member_name: str, team_name: str) -> None:
        """Raise unless the team's ``default_role_profile`` is really off the user.

        Ending the Team Member row is bookkeeping; the recalculation triggered by
        ``on_team_members_change`` is what withdraws the access. That recalculation
        cannot fail loudly — it is swallowed twice:

        - ``team_role_profile_hooks.on_team_members_change`` catches every
          exception per volunteer and ``continue``s.
        - ``user_role_profile_calculator.auto_sync_on_role_change`` is explicitly
          fire-and-forget: it logs and returns, and turns a non-exception failure
          (``success: False``) into a logged warning.

        So a disabled User (``sync_user_role_profile`` refuses to touch one — it
        would re-enable the account via the Employee/User status lockstep), a
        ``calculate_user_role_profile`` that returns None, or a
        ``TimestampMismatchError`` on ``User.save()`` all leave the profile
        attached while the caller returns "Removed from team 'X'" and apply_event
        marks the event Applied. Trust the post-condition, not the hook.

        Re-running ``sync_user_role_profile`` here — where its result is
        observable — is deliberate and cheap: if the hook already did the work it
        is a no-op, and if it did not this is the retry. Only when the
        authoritative recalculation refuses to run *and* the profile is still
        attached is this a failed revocation; a profile that survives a successful
        recalculation is granted by some other source (another team, a chapter
        board) and was never this team's to withdraw.
        """
        profile = frappe.db.get_value("Team", team_name, "default_role_profile")
        if not profile:
            return

        user = frappe.db.get_value("Member", member_name, "user")
        if not user:
            return  # No account — no profile to withdraw.

        from verenigingen.services.member.account.user_role_profile_calculator import (
            get_user_role_profiles,
            sync_user_role_profile,
        )

        if profile not in get_user_role_profiles(user):
            return

        result = sync_user_role_profile(user) or {}
        if profile not in get_user_role_profiles(user):
            return

        if result.get("success") and not result.get("skipped"):
            self.logger.info(
                "Role profile '%s' survives the team revocation for %s — granted elsewhere",
                profile,
                user,
            )
            return

        reason = result.get("skipped") or result.get("error") or _("unknown")
        self.logger.error(
            "Team revocation did not withdraw role profile '%s' from %s (member %s): %s",
            profile,
            user,
            member_name,
            reason,
        )
        raise frappe.ValidationError(
            _(
                "Team '{0}' membership ended but role profile '{1}' is still attached to {2} "
                "({3}) — the access was not withdrawn."
            ).format(team_name, profile, user, reason)
        )

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

        Revocation here is *partial by design*, and the messages say so.

        The only access this branch withdraws is the team membership configured by
        ``add_to_team`` + ``default_team``. The "ROLE_ADMIN removed" message is
        appended *after* _end_team_membership(), which raises both when the row
        edit cannot be persisted and when the resulting recalculation did not
        actually drop the team's role profile — so it is never emitted while a
        **team** revocation is outstanding.

        It guarantees nothing about ``verenigingen_role`` and ``role_profile``,
        which the addition path grants directly (_ensure_user_role() →
        User.add_roles(), and the ``role_profile`` handed to
        create_volunteer_from_member()) and which nothing here removes. Undoing
        those correctly needs provenance the system does not record: both role
        mappings can name the same role or profile, and a role may equally have
        been granted by hand, so a blind remove_roles() would over-revoke. Until
        that is designed, the retained access is *reported* rather than left
        implied by a bare "removed" on an event apply_event then marks Applied —
        but only the access the user is *observed* to still hold (see
        _retained_access_messages), because telling an operator to hand-revoke a
        role that was never granted is over-revocation by proxy.
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

            retained = self._retained_access_messages(member_name, config)
            if retained:
                retained_text = ", ".join(retained)
                warning = _("NOT withdrawn by sync, revoke manually: {0}").format(retained_text)
                self.logger.warning(
                    "ROLE_ADMIN revocation for member %s does NOT withdraw %s (event %s)",
                    member_name,
                    retained_text,
                    event.name if event else "N/A",
                )
                messages.append(warning)
                if event is not None:
                    # Carried to apply_event, which persists it on the event row.
                    event.flags.setdefault(RETAINED_ACCESS_FLAG, []).append(warning)

        return messages

    def _retained_access_messages(self, member_name: str, config: dict) -> list[str]:
        """Name only the configured access the user is *observed* to still hold.

        Deriving this from the config alone over-reports. With ``add_to_team`` on
        the team hook does withdraw ``role_profile``, and ``_ensure_volunteer``
        never granted ``verenigingen_role`` in that config at all — it returns
        early because ``populate_role_profile_roles()`` overwrites individually
        added roles on every User.save(). An operator acting on a config-derived
        list would strip access the user legitimately holds from another team or a
        chapter board: over-revocation by human, on a security path, which is the
        very failure the deferral rationale exists to avoid.
        """
        user = frappe.db.get_value("Member", member_name, "user")
        if not user:
            return []

        retained = []
        role = config.get("verenigingen_role")
        if role and role in frappe.get_roles(user):
            retained.append(_("role '{0}'").format(role))

        role_profile = config.get("role_profile")
        if role_profile:
            from verenigingen.services.member.account.user_role_profile_calculator import (
                get_user_role_profiles,
            )

            if role_profile in get_user_role_profiles(user):
                retained.append(_("role profile '{0}'").format(role_profile))

        return retained

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
                except NON_RESUMABLE_DB_ERRORS:
                    # Without this the bare except below flattens a deadlock into a
                    # status string, the loop marches on issuing statements on a
                    # transaction the server has already discarded, and
                    # _notify_board_membership_change mails administrators that
                    # board access was withdrawn when it was not. It also makes
                    # _process_member_roles' own NON_RESUMABLE clause unreachable
                    # for this path.
                    raise
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
        failures = []

        # 1. Parse ROLE_ADMIN from the roles JSON column
        current_roles = self._parse_mijnrood_roles(mijnrood_data.get("roles"))
        old_roles = self._parse_mijnrood_roles(old_data.get("roles")) if old_data else set()

        try:
            messages.extend(
                self._handle_admin_role_change(member_name, current_roles, old_roles, role_config, event)
            )
        except NON_RESUMABLE_DB_ERRORS:
            # No point attempting the second handler: every statement it issues would
            # be on a transaction the server has already discarded.
            raise
        except Exception as e:
            self.logger.error("ROLE_ADMIN handling failed for member %s: %s", member_name, e)
            failures.append(e)

        # 2. Process ROLE_DIVISION_CONTACT from managed_division_ids
        new_division_ids = mijnrood_data.get("managed_division_ids")
        old_division_ids = old_data.get("managed_division_ids") if old_data else None

        try:
            messages.extend(
                self._handle_division_contact_change(
                    member_name,
                    new_division_ids,
                    old_division_ids,
                    role_config,
                    event,
                )
            )
        except NON_RESUMABLE_DB_ERRORS:
            raise
        except Exception as e:
            self.logger.error("ROLE_DIVISION_CONTACT handling failed for member %s: %s", member_name, e)
            failures.append(e)

        # The two handlers withdraw *different* access, so a raise from the first
        # must not cancel the second. The durable outcome is "neither applied"
        # either way — apply_event rolls back — so the benefit is diagnostic, not
        # transactional: attempting both means *both* failures are reported and
        # neither revocation is silently skipped, which is what an operator needs
        # before re-running. The aggregate then reaches apply_event, which records
        # it and leaves the event un-Applied.
        #
        # The handler output below is neutral context, not a claim about what
        # survived: it is whatever the handlers emitted this attempt, including
        # strings they produced *for* the failures, and the rollback discards all
        # of it.
        if failures:
            handler_output = "; ".join(messages) if messages else _("none")
            raise frappe.ValidationError(
                _("Role processing failed for member {0}: {1} (handler output: {2})").format(
                    member_name,
                    " | ".join(str(f)[:200] for f in failures),
                    handler_output,
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
