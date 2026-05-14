"""MijnRoodRelatedRecordsOrchestrator — creates ancillary records after Member creation/update.

Extracted from event_application_service.py as Phase 1, PR #6 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns the "everything that happens after a Member is
created/updated" pipeline:
- Address creation
- Mollie customer linkage
- Membership + Dues Schedule creation/backfill
- User account creation (with per-event dedup)
- MijnRood comment append
- Chapter assignment via division_id

The dedup Set (_acr_queued_members) STAYS on the god-class because it is
per-event state initialized in MijnRoodEventApplicationService.__init__
and cleared at the start of every apply_event call. Methods that touch
the dedup set accept an `orchestrator` parameter and use
`orchestrator._acr_queued_members`.
"""

import logging
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_int

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.related_records")


class MijnRoodRelatedRecordsOrchestrator:
    """Creates ancillary records (address, Mollie, membership, dues, etc.) for a synced Member."""

    _TERMINAL_STATUSES = frozenset(("Quit", "Banned", "Deceased"))

    def __init__(self):
        self.logger = logger

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


_service_instance: Optional[MijnRoodRelatedRecordsOrchestrator] = None


def get_related_records_orchestrator() -> MijnRoodRelatedRecordsOrchestrator:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodRelatedRecordsOrchestrator()
    return _service_instance
