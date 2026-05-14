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
from frappe.utils import now_datetime, today

from verenigingen.mijnrood_sync.field_mapping import (
    get_active_status_ids,
    get_terminated_status_ids,
    get_termination_type_map,
)
from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
    get_mapping_service,
)
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    MijnRoodVolunteerSyncService,
    get_volunteer_sync_service,
)
from verenigingen.mijnrood_sync.utils import safe_int, safe_json_load
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
        messages = []

        # Chapter assignment from division_id
        # Use membership start date as chapter join date (best proxy for historical data)
        division_id = safe_int(row_data.get("chapter"))
        if division_id and event:
            chapter_msg = self._assign_chapter_from_division(
                member_name, division_id, event, join_date=row_data.get("member_since")
            )
            if chapter_msg:
                messages.append(chapter_msg)

        address_msg = self._ensure_address(member_name, row_data)
        if address_msg:
            messages.append(address_msg)

        mollie_msg = self._ensure_mollie_data(member_name, row_data)
        if mollie_msg:
            messages.append(mollie_msg)

        membership_msg = self._ensure_membership_and_dues(member_name, row_data)
        if membership_msg:
            messages.append(membership_msg)

        account_msg = self._ensure_user_account(member_name)
        if account_msg:
            messages.append(account_msg)

        notes_msg = self._apply_mijnrood_comments(member_name, row_data)
        if notes_msg:
            messages.append(notes_msg)

        return messages

    def _apply_mijnrood_comments(self, member_name: str, row_data: dict) -> Optional[str]:
        """Append MijnRood comments to the Member's notes field.

        Skips if the comment text is already present in notes (idempotent).

        Returns:
            Human-readable status message, or None if skipped.
        """
        comment = (row_data.get("mijnrood_comments") or "").strip()
        if not comment:
            return None

        current_notes = frappe.db.get_value("Member", member_name, "notes") or ""
        if comment in current_notes:
            return None

        prefix = "MijnRood notitie"
        new_notes = f"{current_notes}<br>{prefix}: {comment}" if current_notes else f"{prefix}: {comment}"
        frappe.db.set_value("Member", member_name, "notes", new_notes, update_modified=False)
        return _("MijnRood comments added to notes")

    def _ensure_address(self, member_name: str, row_data: dict) -> Optional[str]:
        """Create or update Address document for a synced member.

        Uses AddressImportService which handles duplicate detection,
        link management, and stale-link cleanup.

        Returns:
            Human-readable status message, or None if skipped.
        """
        address_line1 = (row_data.get("address_line1") or "").strip()
        city = (row_data.get("city") or "").strip()
        if not address_line1 or not city:
            return None

        from verenigingen.services.csv_import.address_import_service import (
            get_address_import_service,
        )

        try:
            member_doc = frappe.get_doc("Member", member_name)
            address_name = get_address_import_service().create_or_update_address(member_doc, row_data)
            if address_name:
                # Persist the primary_address link (set by the service on member_doc)
                frappe.db.set_value(
                    "Member",
                    member_name,
                    "primary_address",
                    address_name,
                    update_modified=False,
                )
                self.logger.info("Address %s linked to member %s", address_name, member_name)
                return _("Address {0} linked").format(address_name)
        except Exception as e:
            self.logger.error("Address creation failed for %s: %s", member_name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Address Creation Failed: {member_name}",
            )
            return _("Address creation failed: {0}").format(str(e)[:200])

        return None

    _TERMINAL_STATUSES = frozenset(("Quit", "Banned", "Deceased"))

    def _ensure_mollie_data(self, member_name: str, row_data: dict) -> Optional[str]:
        """Sync Mollie customer/subscription IDs to Member and Customer records.

        Uses MollieSyncService which handles validation, Customer creation
        if needed, and writing IDs to both Member and Customer records.

        Returns:
            Human-readable status message, or None if skipped.
        """
        customer_id = row_data.get("custom_mollie_customer_id")
        subscription_id = row_data.get("custom_mollie_subscription_id")
        if not customer_id and not subscription_id:
            return None

        from verenigingen.services.csv_import.mollie_sync_service import (
            get_mollie_sync_service,
        )

        try:
            member_doc = frappe.get_doc("Member", member_name)
            is_terminal = member_doc.status in self._TERMINAL_STATUSES
            sub_status = ("canceled" if is_terminal else "active") if subscription_id else None
            mollie_data = {
                "custom_mollie_customer_id": customer_id,
                "custom_mollie_subscription_id": subscription_id,
                "custom_subscription_status": sub_status,
            }
            get_mollie_sync_service().sync_mollie_data(member_doc, mollie_data)

            self.logger.info("Mollie data synced for member %s (terminal=%s)", member_name, is_terminal)
            return _("Mollie data synced")
        except Exception as e:
            self.logger.error("Mollie sync failed for %s: %s", member_name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Mollie Sync Failed: {member_name}",
            )
            return _("Mollie sync failed: {0}").format(str(e)[:200])

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
        # Require both dues_rate and payment_period from MijnRood data.
        # No defaults — if the data is missing, skip and let the operator investigate.
        if "dues_rate" not in row_data:
            return None
        if "payment_period" not in row_data:
            self.logger.warning(
                "Skipping membership creation for %s: no payment_period in sync data", member_name
            )
            return None

        member_doc = frappe.get_doc("Member", member_name)

        if member_doc.status != "Active":
            return None

        existing_membership = frappe.db.get_value(
            "Membership",
            {"member": member_name, "status": "Active", "docstatus": 1},
            "name",
        )

        if existing_membership:
            # Membership exists — but does it have a dues schedule?
            has_schedule = frappe.db.exists(
                "Membership Dues Schedule",
                {"member": member_name, "is_template": 0},
            )
            if has_schedule:
                # Check if dues rate changed — update existing schedule if so
                new_rate = row_data.get("dues_rate")
                if new_rate is not None:
                    return self._update_existing_dues_schedule(member_name, new_rate)
                return None
            # Membership exists without a dues schedule — backfill it
            return self._backfill_dues_schedule(member_doc, existing_membership, row_data)

        from verenigingen.services.csv_import.membership_import_service import (
            get_membership_import_service,
        )

        try:
            membership_name = get_membership_import_service().create_membership_from_csv(member_doc, row_data)
            if membership_name:
                self.logger.info("Created membership %s for synced member %s", membership_name, member_name)
                return _("Membership {0} created").format(membership_name)
        except Exception as e:
            self.logger.error("Membership creation failed for %s: %s", member_name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Membership Creation Failed: {member_name}",
            )
            return _("Membership creation failed: {0}").format(str(e)[:200])

        return None

    def _backfill_dues_schedule(self, member_doc, membership_name: str, row_data: dict) -> Optional[str]:
        """Create a missing dues schedule for an existing membership.

        Resolves the template from payment_period via Verenigingen Settings
        (same logic as the CSV import), then calls create_from_template.

        Returns:
            Human-readable status message, or None if skipped.
        """
        from verenigingen.utils.csv.data_transformers import (
            get_dues_schedule_template_from_payment_period,
        )

        try:
            template_name = get_dues_schedule_template_from_payment_period(row_data)
        except Exception as e:
            self.logger.warning(
                "Cannot resolve dues template for %s (payment_period=%s): %s",
                member_doc.name,
                row_data.get("payment_period"),
                e,
            )
            return _("Dues schedule backfill skipped: {0}").format(str(e)[:200])

        if not template_name:
            return None

        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        try:
            membership_type = frappe.db.get_value("Membership", membership_name, "membership_type")
            schedule_name = MembershipDuesSchedule.create_from_template(
                member_doc.name,
                template_name=template_name,
                membership_type=membership_type,
                membership_name=membership_name,
                custom_amount=row_data.get("dues_rate"),
                custom_amount_reason="Backfilled from MijnRood sync data",
            )
            self.logger.info(
                "Backfilled dues schedule %s for member %s (membership %s)",
                schedule_name,
                member_doc.name,
                membership_name,
            )
            return _("Dues schedule {0} created for existing membership").format(schedule_name)
        except Exception as e:
            self.logger.error("Dues schedule backfill failed for %s: %s", member_doc.name, e)
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Sync - Dues Schedule Backfill Failed: {member_doc.name}",
            )
            return _("Dues schedule backfill failed: {0}").format(str(e)[:200])

    def _update_existing_dues_schedule(self, member_name: str, new_rate: float) -> Optional[str]:
        """Update an existing dues schedule's rate if it differs from the incoming MijnRood rate.

        Delegates to DuesScheduleRepository.update_schedule_rate() for the
        actual update logic (idempotent — no-ops when rates match).

        Returns:
            Human-readable status message, or None if no update needed.
        """
        from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository

        repo = DuesScheduleRepository()
        schedule = repo.get_active_or_paused_schedule(member_name)
        if not schedule:
            return None

        result = repo.update_schedule_rate(
            schedule_name=schedule.name,
            new_rate=new_rate,
            reason="MijnRood sync",
        )

        if not result.success:
            self.logger.error("Dues schedule update failed for %s: %s", member_name, result.message)
            frappe.log_error(
                "; ".join(result.errors or [result.message]),
                f"MijnRood Sync - Dues Schedule Update Failed: {member_name}",
            )
            return _("Dues schedule update failed: {0}").format(result.message[:200])

        if result.method_used == "no_change_needed":
            return None

        self.logger.info("Updated dues schedule %s for member %s", schedule.name, member_name)
        return _("Dues schedule {0} updated: {1}").format(schedule.name, result.message)

    def _ensure_user_account(self, member_name: str) -> Optional[str]:
        """Queue an Account Creation Request for a synced member if enabled.

        Checks the 'create_member_accounts' setting. If disabled or the member
        already has a user account, returns None. Otherwise delegates to the
        standard ACR pipeline which handles deduplication (existing user,
        pending request) automatically.

        Returns:
            Human-readable status message, or None if skipped.
        """
        if not frappe.db.get_single_value("MijnRood Sync Settings", "create_member_accounts"):
            return None

        user = frappe.db.get_value("Member", member_name, "user")
        if user:
            return None

        # Skip if ACR was already queued for this member in the current event
        # (e.g. via _ensure_volunteer → create_volunteer_from_member)
        if member_name in self._acr_queued_members:
            return None

        from verenigingen.utils.account_creation_manager import (
            queue_account_creation_for_member,
        )

        try:
            result = queue_account_creation_for_member(
                member_name,
                roles=["Verenigingen Member"],
                role_profile="Verenigingen Member",
                priority="Low",
            )
            if result.success:
                self._acr_queued_members.add(member_name)
                request_name = result.data.get("request_name", "") if result.data else ""
                self.logger.info(
                    "Queued account creation for member %s (request=%s)",
                    member_name,
                    request_name,
                )
                return _("Account creation queued ({0})").format(request_name)
            else:
                # Expected skips (no email, duplicate request) — debug only
                self.logger.debug(
                    "Account creation skipped for %s: %s",
                    member_name,
                    result.error_message,
                )
                return None
        except Exception as e:
            self.logger.warning("Account creation failed for %s: %s", member_name, e)
            return _("Account creation failed: {0}").format(str(e)[:200])

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
        user = frappe.db.get_value("Member", member_name, "user")
        if user:
            return None

        if member_name in self._acr_queued_members:
            return None

        from verenigingen.utils.account_creation_manager import (
            queue_account_creation_for_member,
        )

        try:
            result = queue_account_creation_for_member(
                member_name,
                roles=["Verenigingen Volunteer"],
                role_profile="Verenigingen Volunteer",
                priority="Medium",
            )
            if result.success:
                self._acr_queued_members.add(member_name)
                request_name = result.data.get("request_name", "") if result.data else ""
                self.logger.info(
                    "Queued account creation for volunteer %s (request=%s)",
                    member_name,
                    request_name,
                )
                return _("Account creation queued for volunteer ({0})").format(request_name)
            else:
                self.logger.debug(
                    "Account creation skipped for volunteer %s: %s",
                    member_name,
                    result.error_message,
                )
                return None
        except Exception as e:
            self.logger.warning("Account creation failed for volunteer %s: %s", member_name, e)
            return _("Account creation failed: {0}").format(str(e)[:200])

    def _assign_chapter_from_division(
        self, member_name: str, division_id: int, event, join_date: str = None
    ) -> Optional[str]:
        """Resolve a division_id to a chapter and assign the member.

        Args:
            join_date: Optional chapter join date (e.g. member_since from MijnRood).
                       Defaults to today() if not provided or invalid.

        Returns a human-readable message, or None if nothing was done.
        """
        # Validate join_date — fall back to today() for unparseable or future dates
        if join_date:
            from frappe.utils import getdate

            try:
                if getdate(join_date) > getdate(today()):
                    self.logger.warning(
                        "Join date %s is in the future for member %s, using today", join_date, member_name
                    )
                    join_date = None
            except Exception:
                self.logger.warning(
                    "Invalid join_date '%s' for member %s, using today", join_date, member_name
                )
                join_date = None

        chapter_name = get_mapping_service().resolve_division_id(division_id)
        if not chapter_name:
            return _("Division ID {0} does not match any Chapter").format(division_id)

        if not frappe.db.exists("Chapter", chapter_name):
            return _("Chapter '{0}' does not exist in Frappe").format(chapter_name)

        from verenigingen.services.chapter.chapter_assignment_service import (
            ChapterAssignmentService,
        )

        try:
            result = ChapterAssignmentService().assign_with_cleanup(
                member=member_name,
                chapter=chapter_name,
                note=f"MijnRood sync: chapter assignment (event {event.name})",
                join_date=join_date,
            )
        except frappe.ValidationError as e:
            self.logger.info("Chapter assignment skipped for %s: %s", member_name, e)
            return None
        except Exception as e:
            self.logger.error("Chapter assignment failed for %s: %s", member_name, e)
            frappe.log_error(frappe.get_traceback(), f"MijnRood Chapter Assignment Failed: {member_name}")
            return _("Chapter assignment error: {0}").format(str(e))

        if result.get("success"):
            self.logger.info("Assigned member %s to chapter %s", member_name, chapter_name)
            return _("Assigned to chapter '{0}'").format(chapter_name)
        return _("Chapter assignment failed: {0}").format(result.get("message", "unknown"))

    def _handle_division_field_change(
        self, member_name: str, changed_fields: list, event, field_name: str = "division_id"
    ) -> Optional[str]:
        """Handle division_id or preferred_division_id changes as chapter reassignment.

        Scans changed_fields for the given field_name, resolves the new
        division to a chapter, and reassigns the member.
        """
        division_change = None
        for change in changed_fields:
            if change.get("field") == field_name:
                division_change = change
                break

        if not division_change:
            return None

        new_division_id = safe_int(division_change.get("new"))
        if new_division_id is None:
            return None

        return self._assign_chapter_from_division(member_name, new_division_id, event)

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
        # Find the status field change
        status_change = None
        for change in changed_fields:
            if change.get("field") == "current_membership_status_id":
                status_change = change
                break

        if not status_change:
            return None

        old_status_id = safe_int(status_change.get("old"))
        new_status_id = safe_int(status_change.get("new"))

        # Only handle transitions FROM active TO terminated
        if new_status_id not in get_terminated_status_ids():
            return None
        if old_status_id not in get_active_status_ids():
            # Already in a non-active state, just update the status field
            return None

        # Find the linked member
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value("Member", {"member_id": new_data.get("id")}, "name")
        if not member_name:
            old_email = (old_data or {}).get("email")
            if old_email:
                member_name = frappe.db.get_value("Member", {"email": old_email}, "name")

        if not member_name:
            return {
                "success": False,
                "message": _(
                    "Cannot create termination request: no linked member for MijnRood ID {0}"
                ).format(new_data.get("id")),
            }

        member_doc = frappe.get_doc("Member", member_name)

        # Skip if member is already in a terminal state
        if member_doc.status in ("Quit", "Banned", "Deceased"):
            return {
                "success": True,
                "message": _("Member {0} already has status {1}, skipping termination").format(
                    member_name, member_doc.status
                ),
            }

        # Create Membership Termination Request
        termination_type = get_termination_type_map().get(new_status_id, "Administrative")

        termination_doc = frappe.new_doc("Membership Termination Request")
        termination_doc.member = member_name
        termination_doc.termination_type = termination_type
        termination_doc.termination_reason = (
            f"Detected via MijnRood sync (event {event.name}): " f"status changed to {new_status_id}"
        )
        termination_doc.request_date = today()
        termination_doc.termination_date = today()
        termination_doc.notes = (
            f"Auto-created from MijnRood sync event {event.name}. "
            f"MijnRood status changed from {old_status_id} to {new_status_id}."
        )

        # For Voluntary and Deceased, set member_request_date
        if termination_type in ("Voluntary", "Deceased"):
            termination_doc.member_request_date = today()

        # Pre-approve since this is a sync from the authoritative system
        termination_doc.status = "Approved"
        termination_doc._csv_import = True  # Bypass workflow validation
        termination_doc.flags.skip_termination_validation = (
            True  # System-initiated, skip commitment/doc checks
        )

        # Security: System-initiated termination from authoritative MijnRood data
        termination_doc.insert(ignore_permissions=True)
        self.logger.info(
            "Created termination request %s for member %s (type=%s)",
            termination_doc.name,
            member_name,
            termination_type,
        )

        # Auto-execute: MijnRood is authoritative, termination already happened there
        from verenigingen.services.termination import TerminationExecutionService

        try:
            TerminationExecutionService().execute(termination_doc)
            self.logger.info(
                "Executed termination %s for member %s",
                termination_doc.name,
                member_name,
            )
        except Exception as e:
            self.logger.error(
                "Termination request %s created but execution failed: %s",
                termination_doc.name,
                e,
            )
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Termination Execution Failed: {termination_doc.name}",
            )
            return {
                "success": False,
                "message": _("Termination request {0} created but execution failed: {1}").format(
                    termination_doc.name, str(e)
                ),
            }

        return {
            "success": True,
            "message": _("Termination request {0} executed for member {1} (type: {2})").format(
                termination_doc.name, member_name, termination_type
            ),
        }

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
