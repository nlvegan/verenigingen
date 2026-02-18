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
from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.mijnrood_sync.field_mapping import (
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    get_active_status_ids,
    get_role_mapping,
    get_terminated_status_ids,
    get_termination_type_map,
)
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

    # Fields shared between new and changed application handlers.
    # Keys = row_data keys (from _map_mijnrood_to_member_fields),
    # values = Member DocType field names.
    _APPLICATION_FIELDS = {
        "member_id": "member_id",
        "first_name": "first_name",
        "tussenvoegsel": "tussenvoegsel",
        "last_name": "last_name",
        "email": "email",
        "contact_number": "contact_number",
        "birth_date": "birth_date",
        "iban": "iban",
        "dues_rate": "dues_rate",
        "accepts_optional_communications": "accepts_optional_communications",
    }

    def _find_existing_member_or_conflict(self, mijnrood_id, email) -> tuple[Optional[str], Optional[dict]]:
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

    def _set_application_fields(self, member, row_data: dict, is_new: bool = False) -> bool:
        """Apply mapped MijnRood fields to a Member document.

        Handles member_id stringification and payment method inference.

        Args:
            is_new: If True, infer payment_method from IBAN when not already set.

        Returns:
            True if any field was changed.
        """
        changed = False
        for row_key, member_field in self._APPLICATION_FIELDS.items():
            val = row_data.get(row_key)
            if val is None or val == "":
                continue
            if row_key == "member_id":
                val = str(val)
            current = member.get(member_field)
            if str(val).strip() != str(current or "").strip():
                member.set(member_field, val)
                changed = True

        # For new applications, infer payment method from IBAN
        if is_new and member.iban and not member.payment_method:
            member.payment_method = "Bank Transfer"

        # Mollie overrides payment method for both new and changed
        mollie_id = row_data.get("custom_mollie_customer_id")
        if mollie_id and mollie_id != member.mollie_customer_id:
            member.mollie_customer_id = mollie_id
            member.payment_method = "Mollie"
            changed = True

        return changed

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
        division_id = self._safe_int(row_data.get("chapter"))
        if division_id and event:
            chapter_msg = self._assign_chapter_from_division(member_name, division_id, event)
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

    _TERMINAL_STATUSES = frozenset(("Terminated", "Banned", "Deceased"))

    def _ensure_mollie_data(self, member_name: str, row_data: dict) -> Optional[str]:
        """Sync Mollie customer/subscription IDs to Member and Customer records.

        Uses MollieSyncService which handles validation, Customer creation
        if needed, and writing IDs to both Member and Customer records.

        For terminated members, corrects subscription_status after the service
        call (the service hard-codes "active" which is wrong for non-active members).

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

            # MollieSyncService hard-codes subscription_status="active" — correct it
            if subscription_id and is_terminal:
                frappe.db.set_value(
                    "Member",
                    member_name,
                    "subscription_status",
                    "canceled",
                    update_modified=False,
                )

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

    def _assign_chapter_from_division(self, member_name: str, division_id: int, event) -> Optional[str]:
        """Resolve a division_id to a chapter and assign the member.

        Returns a human-readable message, or None if nothing was done.
        """
        chapter_name = self._resolve_division_id(division_id)
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

        new_division_id = self._safe_int(division_change.get("new"))
        if new_division_id is None:
            return None

        return self._assign_chapter_from_division(member_name, new_division_id, event)

    # ─── New ───────────────────────────────────────────────────────────

    def _apply_new(self, event) -> dict:
        """Apply a 'New' event — dispatch to the right table handler."""
        return self._dispatch(event, "new")

    def _apply_new_member(self, event) -> dict:
        """Create a new Member from MijnRood admin_member data."""
        new_data = json.loads(event.new_data) if event.new_data else {}
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = self._map_mijnrood_to_member_fields(new_data)

        # Idempotency — member_id is authoritative, email is fallback
        existing_name, existing_result = self._find_existing_member_or_conflict(
            row_data.get("member_id"), row_data.get("email")
        )
        if existing_result is not None:
            # Check for application→member promotion: MijnRood deletes the
            # application row and creates a new member row with a different ID.
            # _find_existing_member_or_conflict sees this as a conflict (email
            # match, member_id mismatch). If the existing member is a pending
            # application, this is actually a promotion, not a conflict.
            if not existing_result.get("success") and row_data.get("email"):
                promotion_result = self._try_promote_application(event, row_data)
                if promotion_result:
                    return promotion_result

            if existing_name:
                event.linked_member = existing_name
            return existing_result

        # Use MemberImportService for consistent creation logic
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, member_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        if status in ("created", "updated"):
            # Link the event to the member
            event.linked_member = member_name

            # Create related records: address, Mollie IDs, membership + dues
            related_msgs = self._create_related_records(member_name, row_data, event)

            # Process admin roles (ROLE_ADMIN, ROLE_DIVISION_CONTACT)
            role_msgs = self._process_member_roles(member_name, new_data, event=event)
            related_msgs.extend(role_msgs)

            messages = [_("Member {0} {1}").format(member_name, status)]
            messages.extend(related_msgs)
            return {"success": True, "message": "; ".join(messages)}
        else:
            return {"success": False, "message": _("Member creation {0}").format(status)}

    def _try_promote_application(self, event, row_data: dict) -> Optional[dict]:
        """Handle MijnRood application→member promotion.

        When MijnRood approves an application, the admin_membership_application
        row is deleted and a new admin_member row is created with a different ID
        (different table, different auto-increment sequence). The polling service
        detects a "Deleted" event for the application and a "New" event for the
        member. The "New" event hits an email conflict because the Member (created
        from the application event) has the old application's member_id.

        Detection: email match where existing member has application_status=Pending.

        Returns:
            Result dict if promotion was handled, None if not a promotion.
        """
        email = row_data.get("email")
        match = frappe.db.get_value(
            "Member",
            {"email": email},
            ["name", "member_id", "application_status"],
            as_dict=True,
        )
        if not match or match.application_status != "Pending":
            return None

        old_member_id = match.member_id
        new_member_id = row_data.get("member_id")

        self.logger.info(
            "Promoting application %s (member_id %s → %s) via event %s",
            match.name,
            old_member_id,
            new_member_id,
            event.name,
        )

        # Delegate to MemberImportService — it will find the existing member
        # by email (member_id won't match) and update all fields, including
        # overwriting member_id with the new admin_member ID.
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, member_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        if status not in ("created", "updated"):
            return {
                "success": False,
                "message": _("Application promotion failed: {0}").format(status),
            }

        # Clear application-specific fields now that the member is promoted
        frappe.db.set_value(
            "Member",
            member_name,
            {
                "application_status": "Approved",
                "review_notes": (
                    f"Approved via MijnRood (event {event.name}). "
                    f"Application member_id {old_member_id} → member_id {new_member_id}."
                ),
            },
        )

        event.linked_member = member_name

        # Create related records (address, Mollie, membership + dues)
        related_msgs = self._create_related_records(member_name, row_data, event)

        messages = [
            _("Application {0} promoted to member (ID {1} → {2})").format(
                member_name, old_member_id, new_member_id
            )
        ]
        messages.extend(related_msgs)
        return {"success": True, "message": "; ".join(messages)}

    def _apply_new_division(self, event) -> dict:
        """Create or update a Chapter from MijnRood admin_division data."""
        new_data = json.loads(event.new_data) if event.new_data else {}
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        return self._sync_division_to_chapter(new_data, event)

    def _apply_new_membership_application(self, event) -> dict:
        """Create a pending membership application from MijnRood data.

        Creates a Member document with application_status=Pending so it
        enters the normal membership application review workflow.
        """
        new_data = json.loads(event.new_data) if event.new_data else {}
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = self._map_mijnrood_to_member_fields(new_data)

        # Idempotency — member_id is authoritative, email is fallback
        existing_name, existing_result = self._find_existing_member_or_conflict(
            row_data.get("member_id"), row_data.get("email")
        )
        if existing_result is not None:
            if existing_name:
                event.linked_member = existing_name
            return existing_result

        # Create Member document as a pending application
        member = frappe.new_doc("Member")
        member.flags.ignore_workflow = True
        member._system_update = True
        member._csv_import = True
        member.application_id = f"MR-APP-{new_data.get('id', event.name)}"
        member.application_status = "Pending"
        member.status = "Pending"
        member.application_date = new_data.get("registration_time") or today()
        member.review_notes = f"Imported from MijnRood application (event {event.name})"

        self._set_application_fields(member, row_data, is_new=True)

        # Security: System-initiated creation from authoritative MijnRood data
        member.insert(ignore_permissions=True)
        frappe.db.commit()

        # Assign to preferred chapter
        preferred_div_id = self._safe_int(new_data.get("preferred_division_id"))
        if preferred_div_id:
            self._assign_chapter_from_division(member.name, preferred_div_id, event)

        event.linked_member = member.name
        self.logger.info(
            "Created membership application %s from MijnRood row %s",
            member.name,
            new_data.get("id"),
        )
        return {
            "success": True,
            "message": _("Application created as {0} (pending review)").format(member.name),
        }

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

        new_data = json.loads(event.new_data) if event.new_data else {}
        old_data = json.loads(event.old_data) if event.old_data else {}
        changed_fields = json.loads(event.changed_fields) if event.changed_fields else []

        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        # Check for status change to a terminated status
        termination_result = self._check_and_handle_termination(event, old_data, new_data, changed_fields)
        if termination_result is not None:
            return termination_result

        # Apply non-termination field changes to the member
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value("Member", {"member_id": new_data.get("id")}, "name")

        if not member_name:
            return {
                "success": False,
                "message": _("No linked member found for MijnRood ID {0}").format(new_data.get("id")),
            }

        # Handle chapter transfer if division_id changed
        chapter_result = self._handle_division_field_change(
            member_name, changed_fields, event, field_name="division_id"
        )

        row_data = self._map_mijnrood_to_member_fields(new_data)

        messages = []
        if chapter_result:
            messages.append(chapter_result)

        # Role-only events (e.g. synthetic division contact changes from _poll_division_contacts)
        # carry only managed_division_ids / roles — no mappable member fields.  Skip the
        # member create/update path and go straight to role processing.
        if row_data:
            from verenigingen.services.csv_import.member_import_service import get_member_import_service

            service = get_member_import_service()
            status, updated_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name=f"MijnRood Sync: {event.name}",
            )

            if status in ("created", "updated"):
                event.linked_member = updated_name
                member_name = updated_name
                messages.append(_("Member {0} updated").format(updated_name))

                # Create related records: address, Mollie IDs, membership + dues
                messages.extend(self._create_related_records(updated_name, row_data, event))
            else:
                return {"success": False, "message": _("Member update {0}").format(status)}

        # Process admin roles (ROLE_ADMIN, ROLE_DIVISION_CONTACT)
        role_msgs = self._process_member_roles(member_name, new_data, old_data=old_data, event=event)
        messages.extend(role_msgs)

        return {"success": True, "message": "; ".join(messages) if messages else _("No changes applied")}

    def _apply_changed_division(self, event) -> dict:
        """Update Chapter from changed MijnRood admin_division data."""
        new_data = json.loads(event.new_data) if event.new_data else {}
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        return self._sync_division_to_chapter(new_data, event)

    def _apply_changed_membership_application(self, event) -> dict:
        """Update a pending membership application from changed MijnRood data.

        Finds the linked Member (application) and updates fields that changed.
        Handles preferred_division_id changes as chapter reassignment.
        """
        new_data = json.loads(event.new_data) if event.new_data else {}
        changed_fields = json.loads(event.changed_fields) if event.changed_fields else []

        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        # Find the linked member — event link first, then member_id, then email
        member_name = event.linked_member
        if not member_name:
            mijnrood_id = str(new_data.get("id", ""))
            existing_name, existing_result = self._find_existing_member_or_conflict(
                mijnrood_id, new_data.get("email")
            )
            if existing_result and not existing_result.get("success"):
                return existing_result  # Conflict
            member_name = existing_name

        if not member_name:
            return {
                "success": False,
                "message": _("No linked member found for application MijnRood ID {0}").format(
                    new_data.get("id")
                ),
            }

        # Guard: don't overwrite data on already-approved/rejected applications
        app_status = frappe.db.get_value("Member", member_name, "application_status")
        if app_status and app_status not in ("Pending", ""):
            return {
                "success": True,
                "message": _("Application {0} already {1}, skipping update").format(member_name, app_status),
            }

        # Handle preferred_division_id change as chapter reassignment
        chapter_msg = self._handle_division_field_change(
            member_name, changed_fields, event, field_name="preferred_division_id"
        )

        # Update basic fields on the member
        row_data = self._map_mijnrood_to_member_fields(new_data)
        member = frappe.get_doc("Member", member_name)
        member.flags.ignore_workflow = True
        member._system_update = True

        changed_something = self._set_application_fields(member, row_data)

        if changed_something:
            # Security: System-initiated update from authoritative MijnRood data
            member.save(ignore_permissions=True)
            frappe.db.commit()

        messages = []
        if chapter_msg:
            messages.append(chapter_msg)
        messages.append(_("Application {0} updated").format(member_name))

        event.linked_member = member_name
        return {"success": True, "message": "; ".join(messages)}

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

        old_status_id = self._safe_int(status_change.get("old"))
        new_status_id = self._safe_int(status_change.get("new"))

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
            return {
                "success": False,
                "message": _(
                    "Cannot create termination request: no linked member for MijnRood ID {0}"
                ).format(new_data.get("id")),
            }

        member_doc = frappe.get_doc("Member", member_name)

        # Skip if member is already in a terminal state
        if member_doc.status in ("Terminated", "Banned", "Deceased"):
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
                member_name, new_division_ids, old_division_ids, role_config, event
            )
        )

        return messages

    def _handle_admin_role_change(
        self,
        member_name: str,
        current_roles: set,
        old_roles: set,
        role_config: dict,
        event=None,
    ) -> list[str]:
        """Handle ROLE_ADMIN addition or removal."""
        messages = []

        if "ROLE_ADMIN" in current_roles and "ROLE_ADMIN" in role_config:
            config = role_config["ROLE_ADMIN"]
            msgs = self._apply_role_actions(member_name, config, event=event)
            messages.extend(msgs)
        elif "ROLE_ADMIN" in old_roles and "ROLE_ADMIN" not in current_roles:
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
                acr_msg = self._ensure_user_account_for_volunteer(member_name)
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
                self._acr_queued_members.add(member_name)
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
        chapter_name = self._resolve_division_id(division_id)
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

    def _end_chapter_board_membership(
        self,
        member_name: str,
        division_id: int,
        event=None,
    ) -> Optional[str]:
        """End a member's active chapter board membership when their division contact role is revoked.

        Sets is_active to 0 and to_date to today.
        Saving the Chapter triggers BoardManager.handle_board_member_changes(),
        which recalculates the user's role profile and removes Frappe roles.

        Args:
            member_name: Vereinigingen Member name
            division_id: MijnRood division ID to resolve to Chapter
            event: Sync event for logging context

        Returns:
            Human-readable status message, or None if not on the board.
        """
        chapter_name = self._resolve_division_id(division_id)
        if not chapter_name:
            return _("Division ID {0} does not match any Chapter").format(division_id)

        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return None  # No volunteer record — nothing to deactivate

        # Find active board membership
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        target_row = None
        for bm in chapter_doc.board_members or []:
            if bm.volunteer == volunteer_name and bm.is_active:
                target_row = bm
                break

        if not target_row:
            return None  # Not on this chapter's board

        try:
            target_row.is_active = 0
            target_row.to_date = today()
            suffix = "Ended via MijnRood sync — division contact revoked (event {0})".format(
                event.name if event else "N/A"
            )
            target_row.notes = f"{target_row.notes}\n{suffix}" if target_row.notes else suffix

            # Security: System-initiated board removal from authoritative MijnRood division contact revocation
            chapter_doc.save(ignore_permissions=True)

            self.logger.info(
                "Ended board membership for volunteer %s in chapter %s (member %s, event %s)",
                volunteer_name,
                chapter_name,
                member_name,
                event.name if event else "N/A",
            )
            return _("Removed from chapter '{0}' board").format(chapter_name)
        except Exception as e:
            self.logger.error(
                "Failed to end board membership for %s in chapter %s: %s",
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
            ch = self._resolve_division_id(div_id)
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
            contact_email=self._extract_email(division_data.get("email_id")),
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

    def _resolve_division_id(self, division_id: int) -> Optional[str]:
        """Resolve a MijnRood division_id to a Chapter name.

        Checks the Chapter's mijnrood_division_id field first (direct lookup),
        then falls back to Sync State for chapters that predate the ID field.
        """
        # Direct lookup via the ID field on Chapter
        chapter_name = frappe.db.get_value("Chapter", {"mijnrood_division_id": division_id}, "name")
        if chapter_name:
            return chapter_name

        # Fallback: resolve via stored sync state raw data
        state = frappe.db.get_value(
            "MijnRood Sync State",
            {"mijnrood_table": "admin_division", "mijnrood_row_id": division_id},
            "raw_data",
        )
        if state:
            data = json.loads(state)
            return data.get("name")
        return None

    def _map_mijnrood_to_member_fields(self, mijnrood_data: dict) -> dict:
        """Map MijnRood database row to intermediate field names.

        These intermediate names match what MemberImportService.update_member_fields()
        expects (same names as csv_data_validator.py FIELD_MAPPING values).
        """
        from verenigingen.mijnrood_sync.field_mapping import get_status_id_map

        row_data = {}
        for mijnrood_col, member_field in MIJNROOD_TO_MEMBER_FIELD_MAP.items():
            value = mijnrood_data.get(mijnrood_col)
            if value is not None and value != "":
                row_data[member_field] = value

        # Convert status ID to membership type — prefer explicit mapping, fall back to status string
        status_id = self._safe_int(mijnrood_data.get("current_membership_status_id"))
        if status_id:
            from verenigingen.mijnrood_sync.field_mapping import (
                get_verenigingen_membership_type_for_status_id,
            )

            explicit_type = get_verenigingen_membership_type_for_status_id(status_id)
            if explicit_type:
                row_data["membership_type"] = explicit_type
            else:
                status_id_map = get_status_id_map()
                if status_id in status_id_map:
                    row_data["membership_type"] = status_id_map[status_id]
                else:
                    self.logger.warning(
                        "MijnRood status ID %s (member %s) has no mapping configured. "
                        "Configure it in MijnRood Sync Settings → Lidmaatschapstypes.",
                        status_id,
                        mijnrood_data.get("id"),
                    )

        # Convert contribution amount from cents to euros
        cents = self._safe_int(mijnrood_data.get("contribution_per_period_in_cents"))
        if cents:
            row_data["dues_rate"] = cents / 100.0

        # Convert contribution period integer to Dutch string for template resolution
        # MijnRood: 0=Monthly, 1=Quarterly, 2=Annually (see Member.php constants)
        period_int = self._safe_int(mijnrood_data.get("contribution_period"))
        period_map = {0: "Maandelijks", 1: "Per kwartaal", 2: "Jaarlijks"}
        if period_int is not None:
            if period_int in period_map:
                row_data["payment_period"] = period_map[period_int]
            else:
                self.logger.warning(
                    "Unknown contribution_period value %s for MijnRood ID %s",
                    period_int,
                    mijnrood_data.get("id"),
                )

        return row_data

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """Safely convert a value to int, returning None on failure."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_email(value: Any) -> Optional[str]:
        """Return value only if it looks like an email address.

        MijnRood's email_id column may contain a numeric FK rather than
        an actual email string. Passing a bare number to a Frappe Data
        field with options=Email causes a validation error.
        """
        if not value or not isinstance(value, str):
            return None
        return value if "@" in value else None


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


def _batch_approve_and_apply_worker(event_names: list, batch_id: str) -> None:
    """Background worker: approve then apply each event."""
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

    skipped = 0
    for i, name in enumerate(sorted_names):
        try:
            event = frappe.get_doc("MijnRood Sync Event", name)
            if event.status not in ("Pending", "Approved"):
                skipped += 1
                frappe.db.commit()
                frappe.publish_realtime(
                    "batch_approve_apply_progress",
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
            "batch_approve_apply_progress",
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
        "batch_approve_apply_complete",
        {"batch_id": batch_id, "applied": applied, "total": total, "errors": errors},
        user=frappe.session.user,
    )


def _batch_apply_worker(event_names: list, batch_id: str) -> None:
    """Background worker for batch applying sync events."""
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
        result = service.apply_event(name)
        if result.get("success"):
            applied += 1
        else:
            errors.append(f"{name}: {result.get('message', 'Unknown error')}")
        frappe.db.commit()
        frappe.publish_realtime(
            "batch_apply_progress",
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
        "batch_apply_complete",
        {"batch_id": batch_id, "applied": applied, "total": total, "errors": errors},
        user=frappe.session.user,
    )
