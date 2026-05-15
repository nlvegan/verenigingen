"""
MijnRood Event Application Service

Applies approved sync events to Verenigingen data. Handles:
- New members: creates Member documents
- Changed members: updates existing Member fields
- Status changes to terminated: creates Membership Termination Requests
  (uses the existing termination workflow rather than directly setting status)
- Deleted rows: flagged for review, never auto-applied

Reuses existing patterns from:
- MemberImportService for field mapping and member creation
- MemberLookupService for member matching
- Membership Termination Request workflow for termination handling
"""

import json
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
)
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    MijnRoodVolunteerSyncService,
    get_volunteer_sync_service,
)
from verenigingen.mijnrood_sync.utils import safe_json_load
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class MijnRoodEventApplicationService(StatefulService):
    """Applies approved MijnRood Sync Events to Verenigingen data."""

    def __init__(self):
        super().__init__(service_name="MijnRoodEventApplicationService")
        self._acr_queued_members: set[str] = set()

    def apply_event(self, event_name: str) -> dict:
        """Apply a single approved sync event.

        Args:
            event_name: Name of the MijnRood Sync Event document

        Returns:
            Dict with success status and message
        """
        self._acr_queued_members.clear()
        event = frappe.get_doc("MijnRood Sync Event", event_name)

        if event.status != "Approved":
            return {"success": False, "message": _("Only Approved events can be applied")}

        try:
            if event.event_type == "New":
                result = self._apply_new(event)
            elif event.event_type == "Changed":
                result = self._apply_changed(event)
            elif event.event_type == "Deleted":
                result = self._apply_deleted(event)
            elif event.event_type == "Approved":
                result = self._apply_approved(event)
            else:
                result = {"success": False, "message": _("Unknown event type: {0}").format(event.event_type)}

            if result["success"]:
                event.status = "Applied"
                event.applied_at = now_datetime()
                event.error_message = None
            else:
                event.error_message = result.get("message", "")[:500]

            # Security: System-internal sync event status update, not user-facing
            event.save(ignore_permissions=True)
            frappe.db.commit()
            return result

        except Exception as e:
            error_msg = str(e)[:500]
            self.logger.error("Failed to apply event %s: %s", event_name, error_msg)
            frappe.log_error(frappe.get_traceback(), f"MijnRood Event Application Failed: {event_name}")

            event.reload()
            event.error_message = error_msg
            # Security: System-internal error recording on sync event
            event.save(ignore_permissions=True)
            frappe.db.commit()

            return {"success": False, "message": error_msg}

    # ─── Table dispatch ───────────────────────────────────────────────

    _TABLE_HANDLERS = {
        "admin_member": "member",
        "admin_division": "division",
        "admin_membership_application": "membership_application",
    }

    def _dispatch(self, event, action: str) -> dict:
        """Route event to the right table handler, or return a reference-only result."""
        table_key = self._TABLE_HANDLERS.get(event.mijnrood_table)
        if table_key is None:
            return {
                "success": True,
                "message": _("Table '{0}' — recorded for reference only").format(event.mijnrood_table),
            }
        handler = getattr(self, f"_apply_{action}_{table_key}")
        return handler(event)

    # ─── Shared helpers ────────────────────────────────────────────────

    def _find_existing_member_or_conflict(self, mijnrood_id, email) -> tuple[Optional[str], Optional[dict]]:
        """Look up existing member by member_id (authoritative) then email.

        Returns:
            (member_name, result_dict) — found or conflict
            (None, None) — no match
        """
        return get_member_sync_service().find_existing_member_or_conflict(mijnrood_id, email)

    def _create_related_records(self, member_name: str, row_data: dict, event=None) -> list[str]:
        """Create related records (chapter, address, Mollie, membership, notes) for a synced member.

        Mirrors the CSV import's _create_related_records_via_services() but
        adapted for the sync event path. Each operation is independent —
        a failure in one does not block the others.

        Returns:
            List of human-readable status messages (empty if all skipped).
        """
        return get_related_records_orchestrator()._create_related_records(
            member_name, row_data, event=event, orchestrator=self
        )

    def _apply_mijnrood_comments(self, member_name: str, row_data: dict) -> Optional[str]:
        """Append MijnRood comments to the Member's notes field.

        Skips if the comment text is already present in notes (idempotent).

        Returns:
            Human-readable status message, or None if skipped.
        """
        return get_related_records_orchestrator()._apply_mijnrood_comments(member_name, row_data)

    def _ensure_address(self, member_name: str, row_data: dict) -> Optional[str]:
        """Create or update Address document for a synced member.

        Uses AddressImportService which handles duplicate detection,
        link management, and stale-link cleanup.

        Returns:
            Human-readable status message, or None if skipped.
        """
        return get_related_records_orchestrator()._ensure_address(member_name, row_data)

    def _ensure_mollie_data(self, member_name: str, row_data: dict) -> Optional[str]:
        """Sync Mollie customer/subscription IDs to Member and Customer records.

        Uses MollieSyncService which handles validation, Customer creation
        if needed, and writing IDs to both Member and Customer records.

        Returns:
            Human-readable status message, or None if skipped.
        """
        return get_related_records_orchestrator()._ensure_mollie_data(member_name, row_data)

    def _ensure_membership_and_dues(self, member_name: str, row_data: dict) -> Optional[str]:
        """Create Membership + Dues Schedule for a synced member if eligible.

        Eligibility mirrors the CSV import's _should_create_membership():
        - row_data must contain dues_rate
        - Member status must be Active
        - No existing active submitted Membership

        Uses MembershipImportService.create_membership_from_csv() which handles
        membership type determination, dues schedule template resolution, and
        start_date from row_data["member_since"].

        Returns:
            Human-readable status message, or None if skipped.
        """
        return get_related_records_orchestrator()._ensure_membership_and_dues(member_name, row_data)

    def _backfill_dues_schedule(self, member_doc, membership_name: str, row_data: dict) -> Optional[str]:
        """Create a missing dues schedule for an existing membership.

        Resolves the template from payment_period via Verenigingen Settings
        (same logic as the CSV import), then calls create_from_template.

        Returns:
            Human-readable status message, or None if skipped.
        """
        return get_related_records_orchestrator()._backfill_dues_schedule(
            member_doc, membership_name, row_data
        )

    def _update_existing_dues_schedule(self, member_name: str, new_rate: float) -> Optional[str]:
        """Update an existing dues schedule's rate if it differs from the incoming MijnRood rate.

        Delegates to DuesScheduleRepository.update_schedule_rate() for the
        actual update logic (idempotent — no-ops when rates match).

        Returns:
            Human-readable status message, or None if no update needed.
        """
        return get_related_records_orchestrator()._update_existing_dues_schedule(member_name, new_rate)

    def _ensure_user_account(self, member_name: str) -> Optional[str]:
        """Queue an Account Creation Request for a synced member if enabled.

        Checks the 'create_member_accounts' setting. If disabled or the member
        already has a user account, returns None. Otherwise delegates to the
        standard ACR pipeline which handles deduplication (existing user,
        pending request) automatically.

        Returns:
            Human-readable status message, or None if skipped.
        """
        return get_related_records_orchestrator()._ensure_user_account(member_name, self)

    def _ensure_user_account_for_volunteer(self, member_name: str) -> Optional[str]:
        """Queue an ACR for a volunteer/staff member who needs a User account.

        Unlike ``_ensure_user_account()`` (which respects the global
        ``create_member_accounts`` toggle), this is unconditional — volunteers
        being assigned to teams or boards always need a User account for
        the role profile system to work.

        The ACR pipeline handles all idempotency checks (existing user,
        pending request, missing email).

        Returns:
            Human-readable status message, or None if user exists / ACR already queued.
        """
        return get_related_records_orchestrator()._ensure_user_account_for_volunteer(member_name, self)

    def _assign_chapter_from_division(
        self, member_name: str, division_id: int, event, join_date: str = None
    ) -> Optional[str]:
        """Resolve a division_id to a chapter and assign the member.

        Args:
            join_date: Optional chapter join date (e.g. member_since from MijnRood).
                       Defaults to today() if not provided or invalid.

        Returns a human-readable message, or None if nothing was done.
        """
        return get_related_records_orchestrator()._assign_chapter_from_division(
            member_name, division_id, event, join_date=join_date
        )

    def _handle_division_field_change(
        self, member_name: str, changed_fields: list, event, field_name: str = "division_id"
    ) -> Optional[str]:
        """Handle division_id or preferred_division_id changes as chapter reassignment.

        Scans changed_fields for the given field_name, resolves the new
        division to a chapter, and reassigns the member.
        """
        return get_related_records_orchestrator()._handle_division_field_change(
            member_name, changed_fields, event, field_name=field_name
        )

    # ─── New ───────────────────────────────────────────────────────────

    def _apply_new(self, event) -> dict:
        """Apply a 'New' event — dispatch to the right table handler."""
        return self._dispatch(event, "new")

    def _apply_new_member(self, event) -> dict:
        """Create a new Member from MijnRood admin_member data."""
        return get_member_sync_service().apply_new_member(event, self)

    def _promote_application_member(
        self,
        old_data: dict,
        new_data: dict,
        row_data: dict,
        event,
    ) -> dict:
        """Promote a local Pending Member to Approved/Active using MijnRood data.

        Shared by:
        - _apply_approved (correlator-driven path, preferred)
        - _try_promote_application (apply-time cross-run safety net)

        Handles:
        1. Field sync via MemberImportService.create_or_update_member
        2. Flipping application_status to Approved AND member.status to Active
           (the latter was missing in the original _try_promote_application and
           prevented Membership + Dues Schedule creation downstream)
        3. Running the standard related-records side effects (chapter, address,
           Mollie, Membership + Dues Schedule, user account, notes)
        """
        return get_application_sync_service().promote_application_member(
            old_data, new_data, row_data, event, self
        )

    def _try_promote_application(self, event, row_data: dict) -> Optional[dict]:
        """Handle MijnRood application→member promotion (apply-time safety net).

        This runs when the correlator didn't pair events at poll time (rare:
        cross-run split or low-confidence match). Detection: email match where
        the existing member has application_status=Pending. Promotion itself
        is delegated to _promote_application_member.

        Returns:
            Result dict if promotion was handled, None if not a promotion.
        """
        return get_application_sync_service().try_promote_application(event, row_data, self)

    def _apply_new_division(self, event) -> dict:
        """Create or update a Chapter from MijnRood admin_division data."""
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        return self._sync_division_to_chapter(new_data, event)

    def _apply_new_membership_application(self, event) -> dict:
        """Create a pending membership application from MijnRood data.

        Creates a Member document with application_status=Pending so it
        enters the normal membership application review workflow.
        """
        return get_application_sync_service().apply_new_membership_application(event, self)

    # ─── Changed ────────────────────────────────────────────────────────

    def _apply_changed(self, event) -> dict:
        """Apply a 'Changed' event — dispatch to the right table handler."""
        return self._dispatch(event, "changed")

    def _apply_changed_member(self, event) -> dict:
        """Update existing Member fields from MijnRood admin_member data.

        For status changes to terminated statuses, creates a Membership
        Termination Request rather than directly modifying the member,
        since termination involves multiple documents (membership, mandates,
        user accounts, etc.) managed by the termination workflow.
        """
        return get_member_sync_service().apply_changed_member(event, self)

    def _apply_changed_division(self, event) -> dict:
        """Update Chapter from changed MijnRood admin_division data."""
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        return self._sync_division_to_chapter(new_data, event)

    def _apply_changed_membership_application(self, event) -> dict:
        """Update a pending membership application from changed MijnRood data.

        Finds the linked Member (application) and updates fields that changed.
        Handles preferred_division_id changes as chapter reassignment.
        """
        return get_application_sync_service().apply_changed_membership_application(event, self)

    # ─── Deleted ──────────────────────────────────────────────────────

    def _apply_deleted(self, event) -> dict:
        """Handle a 'Deleted' event.

        Deleted rows are never auto-applied — they are recorded for
        reference. The user must manually handle member deletion/archiving.
        """
        return {
            "success": True,
            "message": _("Deleted event recorded. Member deletion requires manual review."),
        }

    # ─── Approved (correlator-synthesized) ─────────────────────────────

    def _apply_approved(self, event) -> dict:
        """Apply an Approved event synthesized by the approval correlator.

        The event's old_data is the deleted application row; new_data is the
        newly-created admin_member row. We locate the local Pending Member
        that was created when the application first synced, then delegate to
        _promote_application_member for the actual promotion.
        """
        return get_application_sync_service().apply_approved(event, self)

    def _check_and_handle_termination(
        self,
        event,
        old_data: dict,
        new_data: dict,
        changed_fields: list,
    ) -> Optional[dict]:
        """Check if this change involves a status transition to terminated.

        If so, creates a Membership Termination Request using the existing
        workflow instead of directly setting the member status.

        Returns:
            Result dict if termination was handled, None otherwise
        """
        return get_termination_sync_service()._check_and_handle_termination(
            event, old_data, new_data, changed_fields
        )

    # ─── Role processing (ROLE_ADMIN, ROLE_DIVISION_CONTACT) ─────────

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
        return get_volunteer_sync_service()._process_member_roles(
            member_name, mijnrood_data, old_data=old_data, event=event, orchestrator=self
        )

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
        return get_volunteer_sync_service()._handle_admin_role_change(
            member_name, current_roles, old_roles, role_config, event=event, orchestrator=self
        )

    def _handle_division_contact_change(
        self,
        member_name: str,
        new_division_ids,
        old_division_ids,
        role_config: dict,
        event=None,
    ) -> list[str]:
        """Handle ROLE_DIVISION_CONTACT addition or removal."""
        return get_volunteer_sync_service()._handle_division_contact_change(
            member_name, new_division_ids, old_division_ids, role_config, event=event, orchestrator=self
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
        return get_volunteer_sync_service()._apply_role_actions(
            member_name, config, division_ids=division_ids, event=event, orchestrator=self
        )

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
        return get_volunteer_sync_service()._ensure_volunteer(member_name, config, self, event=event)

    def _ensure_user_role(self, member_name: str, role: str) -> Optional[str]:
        """Ensure a member's user account has the specified role.

        Returns:
            Message if role was added, None if already present or no user.
        """
        return get_volunteer_sync_service()._ensure_user_role(member_name, role)

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
        return get_volunteer_sync_service()._ensure_chapter_board_membership(
            member_name, division_id, chapter_role, event=event
        )

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
        return get_volunteer_sync_service()._ensure_team_membership(member_name, team_name, event=event)

    def _prune_orphan_team_members(self, team_doc, team_name: str) -> int:
        """Remove team_members rows whose volunteer no longer exists.

        Frappe's ``_validate_links()`` validates every child row on parent
        save, so a single orphan reference (left behind by a Volunteer that
        was hard-deleted without ending its team memberships first) blocks
        adding any new row to the team. Prune defensively before save.

        Returns the number of rows pruned.
        """
        return get_volunteer_sync_service()._prune_orphan_team_members(team_doc, team_name)

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
        return get_volunteer_sync_service()._end_team_membership(member_name, team_name, event=event)

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
        return get_volunteer_sync_service()._end_chapter_board_membership(
            member_name, division_id, event=event
        )

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
        return get_volunteer_sync_service()._notify_board_membership_change(
            member_name, removed_division_ids, event=event
        )

    @staticmethod
    def _parse_mijnrood_roles(roles_value) -> set[str]:
        """Parse the MijnRood roles JSON column into a set of role strings.

        The roles column contains a JSON array like '["ROLE_ADMIN"]' or null.
        """
        return MijnRoodVolunteerSyncService._parse_mijnrood_roles(roles_value)

    # ─── Division → Chapter sync ─────────────────────────────────────

    def _sync_division_to_chapter(self, division_data: dict, event) -> dict:
        """Sync a MijnRood admin_division row to a Verenigingen Chapter.

        Matches by mijnrood_division_id first (rename-safe), then falls back
        to name matching for chapters that predate the ID field.

        Field mapping:
            admin_division.id → Chapter.mijnrood_division_id (match key)
            admin_division.name → Chapter name (fallback match / rename detection)
            admin_division.can_be_selected_on_application → Chapter.published
        """
        division_name = division_data.get("name")
        division_id = division_data.get("id")
        if not division_name:
            return {"success": False, "message": _("Division has no name")}

        published = 1 if division_data.get("can_be_selected_on_application") else 0

        # Try to find chapter by MijnRood ID first (rename-safe)
        chapter_name = None
        if division_id:
            chapter_name = frappe.db.get_value("Chapter", {"mijnrood_division_id": division_id}, "name")

        # Fall back to name matching for chapters without the ID set
        if not chapter_name and frappe.db.exists("Chapter", division_name):
            chapter_name = division_name

        if chapter_name:
            chapter = frappe.get_doc("Chapter", chapter_name)
            changed = False

            if division_id and chapter.mijnrood_division_id:
                if chapter.mijnrood_division_id != division_id:
                    # ID conflict — chapter is linked to a different MijnRood division
                    self.logger.error(
                        "MijnRood division ID conflict: Chapter %s has ID %s but sync received ID %s",
                        chapter_name,
                        chapter.mijnrood_division_id,
                        division_id,
                    )
                    return {
                        "success": False,
                        "message": _(
                            "Division ID conflict on Chapter '{0}': existing={1}, received={2}. "
                            "Resolve manually."
                        ).format(chapter_name, chapter.mijnrood_division_id, division_id),
                    }
            elif division_id and not chapter.mijnrood_division_id:
                # First-time linking — store the MijnRood ID
                chapter.mijnrood_division_id = division_id
                changed = True

            if chapter.published != published:
                chapter.published = published
                changed = True

            if changed:
                try:
                    # Security: System-initiated sync from authoritative MijnRood data
                    chapter.save(ignore_permissions=True)
                except frappe.UniqueValidationError:
                    # Another worker already linked this division_id to a different chapter
                    self.logger.error(
                        "MijnRood division ID %s already assigned to another chapter "
                        "(race condition during sync of Chapter %s)",
                        division_id,
                        chapter_name,
                    )
                    return {
                        "success": False,
                        "message": _(
                            "Division ID {0} is already linked to another chapter. " "Resolve manually."
                        ).format(division_id),
                    }
                self.logger.info(
                    "Updated Chapter %s: published=%s, mijnrood_division_id=%s",
                    chapter_name,
                    published,
                    division_id,
                )
                return {
                    "success": True,
                    "message": _("Chapter '{0}' updated (published={1})").format(chapter_name, published),
                }
            return {
                "success": True,
                "message": _("Chapter '{0}' already up to date").format(chapter_name),
            }

        # Chapter doesn't exist — auto-create with defaults
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_chapter

        created = ensure_chapter(
            chapter_name=division_name,
            published=published,
            mijnrood_division_id=division_id,
            contact_email=extract_email(division_data.get("email_id")),
        )
        if created:
            self.logger.info("Auto-created Chapter '%s' from division sync", division_name)
            return {
                "success": True,
                "message": _("Chapter '{0}' created from MijnRood division").format(division_name),
            }
        return {
            "success": False,
            "message": _("Failed to auto-create Chapter '{0}'. Check error logs.").format(division_name),
        }


# Module-level singleton accessor
_service_instance: Optional[MijnRoodEventApplicationService] = None


def get_event_application_service() -> MijnRoodEventApplicationService:
    """Get singleton instance of MijnRoodEventApplicationService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodEventApplicationService()
    return _service_instance


# ─────────────────────────────────────────────────────────────────────
# Whitelisted API methods for batch operations from list view
# ─────────────────────────────────────────────────────────────────────


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def batch_approve(event_names: str | list) -> dict:
    """Approve multiple sync events at once.

    Args:
        event_names: JSON string or list of event names
    """
    if isinstance(event_names, str):
        event_names = json.loads(event_names)

    approved = 0
    errors = []
    for name in event_names:
        try:
            event = frappe.get_doc("MijnRood Sync Event", name)
            if event.status == "Pending":
                event.approve()
                approved += 1
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")

    frappe.db.commit()
    return {"approved": approved, "errors": errors}


# Table processing priority: divisions (chapters) must exist before
# members or applications that reference them.
_TABLE_PRIORITY = {
    "admin_division": 0,
    "admin_member": 1,
    "admin_membership_application": 2,
}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def batch_approve_and_apply(event_names: str | list) -> dict:
    """Approve and apply multiple Pending sync events in one background job.

    Args:
        event_names: JSON string or list of event names
    """
    if isinstance(event_names, str):
        event_names = json.loads(event_names)

    batch_id = frappe.generate_hash(length=10)
    frappe.enqueue(
        _batch_approve_and_apply_worker,
        queue="long",
        timeout=600,
        job_id=batch_id,
        event_names=event_names,
        batch_id=batch_id,
        job_name=f"batch_approve_apply_sync_events_{batch_id}",
    )
    return {"batch_id": batch_id, "total": len(event_names)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def batch_apply(event_names: str | list) -> dict:
    """Enqueue batch application of approved sync events as a background job.

    Events are sorted by table dependency order so that division/chapter
    events are processed before member events that may reference them.

    Args:
        event_names: JSON string or list of event names
    """
    if isinstance(event_names, str):
        event_names = json.loads(event_names)

    batch_id = frappe.generate_hash(length=10)
    frappe.enqueue(
        _batch_apply_worker,
        queue="long",
        timeout=600,
        job_id=batch_id,
        event_names=event_names,
        batch_id=batch_id,
        job_name=f"batch_apply_sync_events_{batch_id}",
    )
    return {"batch_id": batch_id, "total": len(event_names)}


def _batch_event_worker(
    event_names: list,
    batch_id: str,
    approve_first: bool = False,
    progress_event: str = "batch_apply_progress",
    complete_event: str = "batch_apply_complete",
) -> None:
    """Background worker for batch applying (and optionally approving) sync events.

    Args:
        event_names: List of MijnRood Sync Event names to process.
        batch_id: Unique identifier for progress tracking.
        approve_first: If True, approve Pending events before applying.
        progress_event: Realtime event name for per-item progress.
        complete_event: Realtime event name for completion.
    """
    events_with_table = frappe.get_all(
        "MijnRood Sync Event",
        filters={"name": ["in", event_names]},
        fields=["name", "mijnrood_table"],
    )
    events_with_table.sort(key=lambda e: _TABLE_PRIORITY.get(e.mijnrood_table, 99))
    sorted_names = [e.name for e in events_with_table]

    total = len(sorted_names)
    service = get_event_application_service()
    applied = 0
    errors = []

    for i, name in enumerate(sorted_names):
        try:
            if approve_first:
                event = frappe.get_doc("MijnRood Sync Event", name)
                if event.status not in ("Pending", "Approved"):
                    frappe.db.commit()
                    frappe.publish_realtime(
                        progress_event,
                        {
                            "batch_id": batch_id,
                            "current": i + 1,
                            "total": total,
                            "applied": applied,
                            "errors": len(errors),
                        },
                        user=frappe.session.user,
                    )
                    continue
                if event.status == "Pending":
                    event.approve()
                    frappe.db.commit()

            result = service.apply_event(name)
            if result.get("success"):
                applied += 1
            else:
                errors.append(f"{name}: {result.get('message', 'Unknown error')}")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")
        frappe.db.commit()
        frappe.publish_realtime(
            progress_event,
            {
                "batch_id": batch_id,
                "current": i + 1,
                "total": total,
                "applied": applied,
                "errors": len(errors),
            },
            user=frappe.session.user,
        )

    frappe.publish_realtime(
        complete_event,
        {"batch_id": batch_id, "applied": applied, "total": total, "errors": errors},
        user=frappe.session.user,
    )


def _batch_approve_and_apply_worker(event_names: list, batch_id: str) -> None:
    """Background worker: approve then apply each event."""
    _batch_event_worker(
        event_names,
        batch_id,
        approve_first=True,
        progress_event="batch_approve_apply_progress",
        complete_event="batch_approve_apply_complete",
    )


def _batch_apply_worker(event_names: list, batch_id: str) -> None:
    """Background worker for batch applying sync events."""
    _batch_event_worker(event_names, batch_id)
