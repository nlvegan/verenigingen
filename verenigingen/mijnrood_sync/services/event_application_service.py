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
    get_terminated_status_ids,
    get_termination_type_map,
)
from verenigingen.services.infrastructure.base_service import StatefulService


class MijnRoodEventApplicationService(StatefulService):
    """Applies approved MijnRood Sync Events to Verenigingen data."""

    def __init__(self):
        super().__init__(service_name="MijnRoodEventApplicationService")

    def apply_event(self, event_name: str) -> dict:
        """Apply a single approved sync event.

        Args:
            event_name: Name of the MijnRood Sync Event document

        Returns:
            Dict with success status and message
        """
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
            return {"success": True, "message": _("Member {0} {1}").format(member_name, status)}
        else:
            return {"success": False, "message": _("Member creation {0}").format(status)}

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

        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, updated_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        messages = []
        if chapter_result:
            messages.append(chapter_result)

        if status in ("created", "updated"):
            event.linked_member = updated_name
            messages.append(_("Member {0} updated").format(updated_name))
            return {"success": True, "message": "; ".join(messages)}
        else:
            return {"success": False, "message": _("Member update {0}").format(status)}

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

        # Security: System-initiated termination from authoritative MijnRood data
        termination_doc.insert(ignore_permissions=True)
        self.logger.info(
            "Created termination request %s for member %s (type=%s)",
            termination_doc.name,
            member_name,
            termination_type,
        )

        return {
            "success": True,
            "message": _("Termination request {0} created for member {1} (type: {2})").format(
                termination_doc.name, member_name, termination_type
            ),
        }

    # ─── Division → Chapter sync ─────────────────────────────────────

    def _sync_division_to_chapter(self, division_data: dict, event) -> dict:
        """Sync a MijnRood admin_division row to a Verenigingen Chapter.

        Matches by name (string). Creates the Chapter if it doesn't exist,
        updates `published` if it does.

        Field mapping:
            admin_division.name → Chapter name (match key)
            admin_division.can_be_selected_on_application → Chapter.published
        """
        division_name = division_data.get("name")
        if not division_name:
            return {"success": False, "message": _("Division has no name")}

        published = 1 if division_data.get("can_be_selected_on_application") else 0

        if frappe.db.exists("Chapter", division_name):
            chapter = frappe.get_doc("Chapter", division_name)
            if chapter.published != published:
                chapter.published = published
                # Security: System-initiated sync from authoritative MijnRood data
                chapter.save(ignore_permissions=True)
                self.logger.info(
                    "Updated Chapter %s: published=%s",
                    division_name,
                    published,
                )
                return {
                    "success": True,
                    "message": _("Chapter '{0}' updated (published={1})").format(division_name, published),
                }
            return {
                "success": True,
                "message": _("Chapter '{0}' already up to date").format(division_name),
            }

        # Chapter doesn't exist — flag for manual creation since Chapter
        # requires fields (region, introduction) that MijnRood doesn't have
        return {
            "success": True,
            "message": _("Chapter '{0}' does not exist. Create it manually and re-apply.").format(
                division_name
            ),
        }

    def _resolve_division_id(self, division_id: int) -> Optional[str]:
        """Resolve a MijnRood division_id to a Chapter name.

        Looks up the division name from stored sync state, which holds
        the raw admin_division data including the 'name' field.
        """
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

        # Convert status ID to membership type string
        status_id = self._safe_int(mijnrood_data.get("current_membership_status_id"))
        status_id_map = get_status_id_map()
        if status_id and status_id in status_id_map:
            row_data["membership_type"] = status_id_map[status_id]

        # Convert contribution amount from cents to euros
        cents = self._safe_int(mijnrood_data.get("contribution_per_period_in_cents"))
        if cents:
            row_data["dues_rate"] = cents / 100.0

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


@frappe.whitelist()
def batch_apply(event_names: str | list) -> dict:
    """Apply multiple approved sync events.

    Args:
        event_names: JSON string or list of event names
    """
    if isinstance(event_names, str):
        event_names = json.loads(event_names)

    service = get_event_application_service()
    applied = 0
    errors = []
    for name in event_names:
        result = service.apply_event(name)
        if result.get("success"):
            applied += 1
        else:
            errors.append(f"{name}: {result.get('message', 'Unknown error')}")

    return {"applied": applied, "errors": errors}
