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
from verenigingen.utils.constants import Roles
from verenigingen.utils.service_logger import get_service_logger
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

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
    ) -> tuple[Optional[str], Optional[str]]:
        """Remove a member's active chapter board membership when their division contact role is revoked.

        Uses BoardManager.bulk_remove_board_members() which deletes the child table
        row entirely (volunteer assignment history is preserved on the Volunteer record).

        Args:
            member_name: Vereinigingen Member name
            division_id: MijnRood division ID to resolve to Chapter
            event: Sync event for logging context

        Returns:
            ``(vacated_chapter, message)``. ``vacated_chapter`` is the Chapter whose
            seat was removed *and verified withdrawn*, or None when there was nothing
            to remove. It is the only trustworthy input to
            _notify_board_membership_change: a message alone is also produced for a
            division that resolves to no Chapter at all, and notifying on that told
            administrators access was ended in "division {id}".

        Raises:
            frappe.ValidationError when the removal cannot be persisted, and when the
            recalculation that follows it did not withdraw the access (see
            _assert_board_access_withdrawn) — plus anything the Chapter save raises.
            This is a privilege *revocation*: every caller between here and
            MijnRoodEventApplicationService.apply_event passes messages through as
            success, so a status string here marks the event Applied with the seat,
            the Frappe role and the role profile all still in place.
        """
        chapter_name = get_mapping_service().resolve_division_id(division_id)
        if not chapter_name:
            return None, _("Division ID {0} does not match any Chapter").format(division_id)

        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return None, None  # No volunteer record — nothing to remove

        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Find active board membership(s) for this volunteer
        target_rows = [
            bm for bm in (chapter_doc.board_members or []) if bm.volunteer == volunteer_name and bm.is_active
        ]

        if not target_rows:
            return None, None  # Not on this chapter's board

        reason = "MijnRood sync — division contact revoked (event {0})".format(event.name if event else "N/A")
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
        target_roles = [bm.chapter_role for bm in target_rows]

        try:
            result = (
                chapter_doc.board_manager.bulk_remove_board_members(  # ast-skip: dynamic manager property
                    removal_data
                )
            )
        except NON_RESUMABLE_DB_ERRORS:
            # The transaction is already discarded, so the log_error() below would be
            # a write on it and every later statement in this sync run would be issued
            # against state the server threw away. Let it reach the transaction owner
            # (same clause and reasoning as _ensure_chapter_board_membership, which
            # was the only path in this file that had one).
            raise
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
            raise

        self._raise_on_failed_board_removal(result, member_name, chapter_name)
        self._assert_board_access_withdrawn(member_name, chapter_name, target_roles)

        self.logger.info(
            "Removed board membership for volunteer %s in chapter %s (member %s, event %s)",
            volunteer_name,
            chapter_name,
            member_name,
            event.name if event else "N/A",
        )
        return chapter_name, _("Removed from chapter '{0}' board").format(chapter_name)

    def _raise_on_failed_board_removal(self, result: dict, member_name: str, chapter_name: str) -> None:
        """Raise unless bulk_remove_board_members really persisted the removal.

        ``success`` alone does not mean it did. bulk_remove_board_members() returns
        ``{"success": True, "errors": [...]}`` when ``_save_chapter_with_board_changes()``
        returned False — the Chapter save failure is only *appended* to ``errors``, so
        the seat is untouched while the caller is told it was vacated. A per-row
        mismatch lands in the same list. Both are the same outcome and both must raise.

        No frappe.log_error() here on purpose. _save_chapter_with_board_changes() has
        already written one, and if the underlying failure was a lost deadlock (which
        secure_document_operation flattens into success=False) that write already went
        to a transaction the server discarded; adding a second is not free of that
        problem either.
        """
        errors = [str(e) for e in (result.get("errors") or [])]
        if not result.get("success"):
            errors.append(str(result.get("error") or _("unknown error")))
        if not errors:
            return

        detail = "; ".join(errors)
        self.logger.error(
            "BoardManager.bulk_remove_board_members did not remove %s from chapter %s: %s",
            member_name,
            chapter_name,
            detail,
        )
        raise frappe.ValidationError(
            _("Chapter '{0}' board removal for {1} failed: {2}").format(
                chapter_name, member_name, detail[:400]
            )
        )

    def _assert_board_access_withdrawn(
        self,
        member_name: str,
        chapter_name: str,
        chapter_roles: list,
    ) -> None:
        """Raise unless the access the seat conferred is really off the user.

        Deleting the Chapter Board Member row is bookkeeping. The access is the
        ``Verenigingen Chapter Board Member`` role and the board-derived role profile,
        and what withdraws them is BoardManager.handle_board_member_deletions() — which
        cannot report failure, and in the ordinary case does not even succeed:

        - It runs from ``Chapter.validate()`` (via _handle_document_changes), i.e.
          *before* the child rows are written. get_board_member_profiles() reads
          ``Chapter Board Member`` from the database, so it still sees the seat as
          active, calculate_user_role_profile() still returns the board profile and
          sync_user_role_profile() reports ``changed: False``. The *additions* path was
          given a deferred flush from ``on_update`` for exactly this reason
          (flush_pending_board_profile_syncs); the deletions path never was.
        - Both ``remove_board_member_role()`` and ``_sync_role_profile_for_volunteer()``
          go through BoardManager._log_or_reraise, which logs and continues for
          everything that is not a broken transaction.
        - ``auto_sync_on_role_change`` is explicitly fire-and-forget: it logs and
          returns, and turns a non-exception failure (``success: False``) into a
          logged warning.

        So re-running sync_user_role_profile() here is not a belt-and-braces retry —
        after the save it is the first recalculation that can see the seat is gone, and
        this frame is the only one where its result is observable. Only when it refuses
        to run (a disabled User, a calculate_user_role_profile() returning None, a
        TimestampMismatchError on User.save()) *and* the access is still held is this a
        failed revocation; access that survives a successful recalculation is granted by
        something else — another board seat, a team, an administrator profile — and was
        never this seat's to withdraw.
        """
        user = frappe.db.get_value("Member", member_name, "user")
        if not user:
            return  # No account — no access to withdraw.

        if not self._outstanding_board_access(user, member_name, chapter_name, chapter_roles):
            return

        from verenigingen.services.member.account.user_role_profile_calculator import (
            sync_user_role_profile,
        )

        result = sync_user_role_profile(user) or {}
        outstanding = self._outstanding_board_access(user, member_name, chapter_name, chapter_roles)
        if not outstanding:
            return

        if result.get("success") and not result.get("skipped"):
            self.logger.info(
                "Board access %s survives the chapter %s revocation for %s — granted elsewhere",
                ", ".join(outstanding),
                chapter_name,
                user,
            )
            return

        reason = result.get("skipped") or result.get("error") or _("unknown")
        self.logger.error(
            "Chapter %s board revocation did not withdraw %s from %s (member %s): %s",
            chapter_name,
            ", ".join(outstanding),
            user,
            member_name,
            reason,
        )
        raise frappe.ValidationError(
            _(
                "Chapter '{0}' board membership ended but {1} is still attached to {2} "
                "({3}) — the access was not withdrawn."
            ).format(chapter_name, ", ".join(outstanding), user, reason)
        )

    def _outstanding_board_access(
        self,
        user: str,
        member_name: str,
        chapter_name: str,
        chapter_roles: list,
    ) -> list[str]:
        """Name the board access the user is still observed to hold, if any."""
        from verenigingen.services.member.account.user_role_profile_calculator import (
            get_user_role_profiles,
            is_active_board_member,
        )

        # frappe.get_roles() memoises per user; the Chapter save rewrote User.roles.
        frappe.clear_cache(user=user)

        outstanding = []
        profile = self._board_seat_profile(chapter_name, chapter_roles)
        if profile and profile in get_user_role_profiles(user):
            outstanding.append(_("role profile '{0}'").format(profile))

        # Only a leak once there is no seat left to justify it — a member sitting on
        # another chapter's board holds the role legitimately.
        if Roles.CHAPTER_BOARD_MEMBER in frappe.get_roles(user) and not is_active_board_member(
            user, member_name
        ):
            outstanding.append(_("role '{0}'").format(Roles.CHAPTER_BOARD_MEMBER))

        return outstanding

    def _board_seat_profile(self, chapter_name: str, chapter_roles: list) -> Optional[str]:
        """The role profile the removed seat conferred.

        Resolved from the same cached config get_board_member_profiles() reads, rather
        than re-deriving it, so this cannot claim a different profile than the one that
        actually granted the access — including when both are looking at a config the
        5-minute cache has not refreshed yet.
        """
        from verenigingen.services.member.account.user_role_profile_calculator import (
            PROFILE_BOARD_MEMBER,
            _get_cached_chapter_profile_config,
        )

        config = _get_cached_chapter_profile_config(chapter_name)
        if config.get("enable_specific"):
            for chapter_role in chapter_roles:
                specific = (config.get("specific_profiles") or {}).get(chapter_role)
                if specific and frappe.db.exists("Role Profile", specific):
                    return specific

        default_profile = config.get("default_profile")
        if default_profile and frappe.db.exists("Role Profile", default_profile):
            return default_profile

        if frappe.db.exists("Role Profile", PROFILE_BOARD_MEMBER):
            return PROFILE_BOARD_MEMBER
        return None

    def _notify_board_membership_change(
        self,
        member_name: str,
        vacated_chapters: list,
        event=None,
    ) -> None:
        """Send a notification when board memberships are ended via sync.

        Creates both a transient realtime message and a persistent Notification Log
        entry (via the notification configuration system) so the change is visible
        in the bell icon.

        Takes the Chapters actually vacated, not the division IDs the sync was asked
        to revoke. Re-resolving the requested set here meant administrators were told
        access had been withdrawn in chapters where the removal failed, and an id that
        matched no Chapter at all was announced as "division {id}".
        """
        chapter_names = list(vacated_chapters)

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
        division_contact_active: bool = False,
        event=None,
    ) -> list[str]:
        """Handle ROLE_ADMIN addition or removal.

        Only fires on the *transition* (added or removed). For unchanged-admin
        events (e.g. a fee change for an existing admin) we skip role actions
        entirely — re-running them on every member update produces no useful
        delta and can break legitimate non-role updates when team data is
        corrupt or role config has drifted.

        On removal, withdraws both the team membership configured by
        ``add_to_team`` + ``default_team`` (via _end_team_membership, which
        verifies the recalculation) and the ``verenigingen_role`` /
        ``role_profile`` this config granted directly (via
        _revoke_direct_grants — #208). ``division_contact_active`` names the one
        case #208 flagged as unsafe to strip blindly: the member currently still
        holds ROLE_DIVISION_CONTACT, whose own config may name the identical
        role / role_profile, in which case _revoke_direct_grants leaves it alone.

        The "ROLE_ADMIN removed" message is appended *after* _end_team_membership(),
        which raises both when the row edit cannot be persisted and when the
        resulting recalculation did not actually drop the team's role profile —
        so it is never emitted while a **team** revocation is outstanding.
        _revoke_direct_grants raises the same way for the direct grants, so the
        message is likewise never emitted while one of those is outstanding.
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

            other_config = role_config.get("ROLE_DIVISION_CONTACT") if division_contact_active else None
            messages.extend(
                self._revoke_direct_grants(member_name, config, other_config, "ROLE_ADMIN revocation")
            )

            messages.append(_("ROLE_ADMIN removed from member {0}").format(member_name))
            self.logger.info(
                "ROLE_ADMIN removed from member %s (event %s)",
                member_name,
                event.name if event else "N/A",
            )

        return messages

    def _revoke_direct_grants(
        self,
        member_name: str,
        config: dict,
        other_active_config: Optional[dict],
        context: str,
    ) -> list[str]:
        """Withdraw the ``verenigingen_role`` / ``role_profile`` ``config`` granted directly.

        ``_ensure_volunteer`` grants these whenever ``create_volunteer`` is
        configured without ``add_to_team``: ``User.add_roles()`` (:190) for
        ``verenigingen_role``, and ``create_volunteer_from_member(role_profile=...)``
        for ``role_profile``. That combination had no revocation counterpart at all
        (#208) — the team-membership path already recalculates and verifies
        (_assert_team_profile_withdrawn / _assert_board_access_withdrawn); this
        direct grant withdrew nothing.

        Skips a value also named by ``other_active_config`` — the one cross-mapping
        case #208 identified as unsafe to strip blindly, since ROLE_ADMIN and
        ROLE_DIVISION_CONTACT may configure the identical role / role_profile.
        Callers must already condition ``other_active_config`` on the member
        currently holding that *other* MijnRood role, read from live MijnRood state
        rather than the event being processed (see ``_live_admin_active`` /
        ``_live_division_contact_active``); pass None when it does not apply.

        ``role_profile`` is withdrawn via ``sync_user_role_profile`` — the same
        ground-truth recalculation ``_assert_team_profile_withdrawn`` /
        ``_assert_board_access_withdrawn`` already use — not a direct
        child-table edit. A direct edit that merely detaches the profile link does
        not withdraw the *access*: ``User.populate_role_profile_roles()`` re-derives
        ``roles`` from ``role_profiles`` on every save, but returns immediately when
        ``role_profiles`` is empty, so every role the profile granted (measured:
        9 roles for "Verenigingen Staff") stays attached while the profile link is
        gone and the caller is told it was withdrawn. ``sync_user_role_profile``
        always sets *some* ground-truth profile (never an empty ``role_profiles``),
        so the role recompute always runs, and it is the same call that correctly
        preserves a profile the user independently holds via a team or board seat.

        Removes ``role_profile`` before ``verenigingen_role`` for the same reason:
        while a profile granting ``role`` is still attached, removing the role
        directly would be undone by ``populate_role_profile_roles()`` within that
        same save.

        A role held under the identical name for some other, unrecorded reason
        (granted by hand) is not distinguishable from this config's own grant and
        is withdrawn the same way _assert_board_access_withdrawn already withdraws
        an identical board-derived role once no seat justifies it. #208's own
        analysis names this as the residual risk that recording grant provenance
        would remove; nothing here claims to have solved that.

        Raises frappe.ValidationError if a removal does not verifiably take —
        matching _assert_board_access_withdrawn / _assert_team_profile_withdrawn:
        a revocation must never silently report success while access remains.
        """
        user = frappe.db.get_value("Member", member_name, "user")
        if not user:
            return []

        other_active_config = other_active_config or {}
        messages = []

        role_profile = config.get("role_profile")
        if role_profile:
            if other_active_config.get("role_profile") == role_profile:
                self.logger.info(
                    "%s: role profile '%s' retained for %s — also granted by the "
                    "other active MijnRood role",
                    context,
                    role_profile,
                    user,
                )
            else:
                from verenigingen.services.member.account.user_role_profile_calculator import (
                    get_user_role_profiles,
                    sync_user_role_profile,
                )

                if role_profile in get_user_role_profiles(user):
                    result = sync_user_role_profile(user) or {}
                    if role_profile in get_user_role_profiles(user):
                        if result.get("success") and not result.get("skipped"):
                            self.logger.info(
                                "%s: role profile '%s' survives recalculation for %s — " "granted elsewhere",
                                context,
                                role_profile,
                                user,
                            )
                        else:
                            reason = result.get("skipped") or result.get("error") or _("unknown")
                            raise frappe.ValidationError(
                                _("{0}: role profile '{1}' could not be withdrawn from {2} ({3}).").format(
                                    context, role_profile, user, reason
                                )
                            )
                    else:
                        self.logger.info(
                            "%s: withdrew role profile '%s' from %s", context, role_profile, user
                        )
                        messages.append(_("Role profile '{0}' withdrawn from {1}").format(role_profile, user))

        role = config.get("verenigingen_role")
        if role:
            if other_active_config.get("verenigingen_role") == role:
                self.logger.info(
                    "%s: role '%s' retained for %s — also granted by the other active MijnRood role",
                    context,
                    role,
                    user,
                )
            elif role in frappe.get_roles(user):
                user_doc = frappe.get_doc("User", user)
                user_doc.remove_roles(role)
                frappe.clear_cache(user=user)
                if role in frappe.get_roles(user):
                    if self._role_granted_by_attached_profile(user, role):
                        # User.populate_role_profile_roles() re-derives roles from
                        # role_profiles on every save, so a role inside the user's
                        # surviving, independently-justified profile is re-added
                        # within the same save that just removed it — that profile,
                        # not this config, is what grants it. Same reasoning
                        # _outstanding_board_access already applies by gating the
                        # CHAPTER_BOARD_MEMBER check on is_active_board_member().
                        self.logger.info(
                            "%s: role '%s' survives for %s — granted by an attached role profile",
                            context,
                            role,
                            user,
                        )
                    else:
                        raise frappe.ValidationError(
                            _("{0}: role '{1}' could not be withdrawn from {2}.").format(context, role, user)
                        )
                else:
                    self.logger.info("%s: withdrew role '%s' from %s", context, role, user)
                    messages.append(_("Role '{0}' withdrawn from {1}").format(role, user))

        return messages

    def _role_granted_by_attached_profile(self, user: str, role: str) -> bool:
        """Whether ``role`` is granted by one of the user's currently-attached role profiles.

        ``User.populate_role_profile_roles()`` re-derives ``roles`` from
        ``role_profiles`` on every save, so a role inside the user's ground-truth
        profile cannot be removed individually by ``user_doc.remove_roles()`` — it
        is re-added within that same save. That is not a failed revocation: the
        profile, not this config, is what grants it.
        """
        from verenigingen.services.member.account.user_role_profile_calculator import (
            get_user_role_profiles,
        )

        for profile in get_user_role_profiles(user):
            profile_roles = {r.role for r in frappe.get_cached_doc("Role Profile", profile).roles}
            if role in profile_roles:
                return True
        return False

    def _handle_division_contact_change(
        self,
        member_name: str,
        new_division_ids,
        old_division_ids,
        role_config: dict,
        admin_active: bool = False,
        event=None,
    ) -> list[str]:
        """Handle ROLE_DIVISION_CONTACT addition or removal.

        The removal branch no longer catches. It used to wrap
        _end_chapter_board_membership in a bare ``except Exception`` that appended
        "Failed to end board membership for division {0}" to the message list —
        which apply_event joins into a hardcoded ``{"success": True}`` and marks the
        event Applied, leaving the seat, the Frappe role and the role profile exactly
        where they were. _process_member_roles collects handler failures into one
        aggregate, so letting this propagate reports the failure *and* still attempts
        the ROLE_ADMIN handler, which withdraws different access.

        Once the member is no longer a division contact anywhere (``new_set`` empty),
        also withdraws the ``verenigingen_role`` / ``role_profile`` this config
        granted directly through _ensure_volunteer (via _revoke_direct_grants —
        #208), the same gap ROLE_ADMIN's handler closes. ``admin_active`` names the
        one case #208 flagged as unsafe to strip blindly: the member currently
        still holds ROLE_ADMIN, whose own config may name the identical role /
        role_profile, in which case _revoke_direct_grants leaves it alone. While the
        member still holds another division it is legitimately theirs, and the
        ``if not new_set`` guard below leaves it untouched either way.
        """
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
            vacated_chapters = []
            for div_id in sorted(removed_divs):
                chapter_name, message = self._end_chapter_board_membership(member_name, div_id, event=event)
                if message:
                    messages.append(message)
                if chapter_name:
                    vacated_chapters.append(chapter_name)

            # Only for seats actually vacated. Notifying on the requested set told
            # administrators access was withdrawn where the removal failed, and
            # announced an unresolvable id as "division {id}".
            if vacated_chapters:
                self._notify_board_membership_change(member_name, vacated_chapters, event)

            if not new_set:
                config = role_config.get("ROLE_DIVISION_CONTACT", {})
                other_config = role_config.get("ROLE_ADMIN") if admin_active else None
                messages.extend(
                    self._revoke_direct_grants(
                        member_name, config, other_config, "ROLE_DIVISION_CONTACT revocation"
                    )
                )

        return messages

    def _live_division_contact_active(self, member_name: str, role_config: dict) -> bool:
        """Whether ROLE_DIVISION_CONTACT is currently active for this member.

        Read from live MijnRood-mirrored state, never from the event being
        processed: a ROLE_ADMIN-change event's payload never carries
        ``managed_division_ids`` at all — that field comes from a separate poll of
        the ``division_member`` junction table (``_poll_division_contacts``), not
        the ``admin_member`` row a ROLE_ADMIN event is about — so deriving it from
        ``mijnrood_data``/``old_data`` made the cross-mapping exemption in
        ``_revoke_direct_grants`` permanently ``False`` on the one path it exists
        for (#208 review).

        ``MijnRood Sync Settings.last_division_contacts_hash`` is updated on every
        poll of that junction table (``{member_id: [division_id, ...]}``),
        independent of which event is currently being applied. The MijnRood
        numeric ``member_id`` it is keyed by is the same id recorded on this
        member's ``admin_member`` ``MijnRood Sync State`` row.

        Known gap: ``_poll_table`` only (re-)resolves ``linked_member`` for a
        new/changed/deleted row — an unchanged row's ``last_seen`` is bumped
        without touching ``linked_member``. A row that was never linkable at
        first poll and has not changed since therefore returns ``False`` here
        (fail-open on this exemption, i.e. towards revoking), not a false
        positive. #208's own analysis already accepts an equivalent residual gap
        (a role held for an unrecorded reason); this is the same class.
        """
        if "ROLE_DIVISION_CONTACT" not in role_config:
            return False

        mijnrood_row_id = frappe.db.get_value(
            "MijnRood Sync State",
            {"mijnrood_table": "admin_member", "linked_member": member_name},
            "mijnrood_row_id",
        )
        if not mijnrood_row_id:
            return False

        settings = frappe.get_single("MijnRood Sync Settings")
        if not settings.last_division_contacts_hash:
            return False
        try:
            current_divisions = json.loads(settings.last_division_contacts_hash)
        except (json.JSONDecodeError, ValueError):
            return False

        return bool(current_divisions.get(str(mijnrood_row_id)))

    def _live_admin_active(self, member_name: str, role_config: dict) -> bool:
        """Whether ROLE_ADMIN is currently active for this member.

        Read from live MijnRood-mirrored state, never from the event being
        processed: a division-contact synthetic event's payload never carries
        ``"roles"`` at all — it is built purely from the ``division_member`` diff
        (``_poll_division_contacts``), not the ``admin_member`` row — so deriving
        it from ``mijnrood_data``/``old_data`` made the cross-mapping exemption in
        ``_revoke_direct_grants`` permanently ``False`` on the other path it exists
        for (#208 review).

        ``MijnRood Sync State.raw_data`` for this member's ``admin_member`` row is
        updated on every poll of that table, independent of which event is
        currently being applied.
        """
        if "ROLE_ADMIN" not in role_config:
            return False

        raw_data = frappe.db.get_value(
            "MijnRood Sync State",
            {"mijnrood_table": "admin_member", "linked_member": member_name},
            "raw_data",
        )
        if not raw_data:
            return False
        try:
            row = json.loads(raw_data)
        except (json.JSONDecodeError, ValueError):
            return False

        return "ROLE_ADMIN" in self._parse_mijnrood_roles(row.get("roles"))

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

        # 2. managed_division_ids drives ROLE_DIVISION_CONTACT
        new_division_ids = mijnrood_data.get("managed_division_ids")
        old_division_ids = old_data.get("managed_division_ids") if old_data else None

        # Whether the *other* MijnRood role mapping is currently active for this
        # member — the one case #208 flagged as unsafe for _revoke_direct_grants to
        # strip blindly, since both mappings may name the identical
        # verenigingen_role / role_profile. Read from live MijnRood-mirrored state,
        # not this event's own payload — see the two helpers' docstrings for why.
        division_contact_active = self._live_division_contact_active(member_name, role_config)
        admin_active = self._live_admin_active(member_name, role_config)

        try:
            messages.extend(
                self._handle_admin_role_change(
                    member_name,
                    current_roles,
                    old_roles,
                    role_config,
                    division_contact_active,
                    event,
                )
            )
        except NON_RESUMABLE_DB_ERRORS:
            # No point attempting the second handler: every statement it issues would
            # be on a transaction the server has already discarded.
            raise
        except Exception as e:
            self.logger.error("ROLE_ADMIN handling failed for member %s: %s", member_name, e)
            failures.append(e)

        try:
            messages.extend(
                self._handle_division_contact_change(
                    member_name,
                    new_division_ids,
                    old_division_ids,
                    role_config,
                    admin_active,
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
