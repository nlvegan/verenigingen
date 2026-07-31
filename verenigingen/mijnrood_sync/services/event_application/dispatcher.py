"""
MijnRood Event Application Service — Dispatcher

The dispatcher module housing MijnRoodEventApplicationService, its
singleton accessor, and the batch_approve/batch_apply whitelist
endpoints. MijnRoodEventApplicationService is the external entry
point: ``apply_event`` resets the per-event ACR dedup state and
routes via the ``_dispatch`` table to the per-table ``_apply_*``
handlers, plus ``_sync_division_to_chapter`` for division events.
All per-concern logic lives in the sibling service modules
(mapping_service, member_sync_service, application_sync_service,
volunteer_sync_service, termination_sync_service,
related_records_orchestrator), called via their ``get_xxx_service()``
accessors.

Originally defined in event_application_service.py — that module is
now a re-export shim importing from this file.
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
from verenigingen.mijnrood_sync.utils import safe_json_load
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


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
        get_related_records_orchestrator().reset_acr_dedup()
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

        except NON_RESUMABLE_DB_ERRORS:
            # Every NON_RESUMABLE_DB_ERRORS clause below this frame (e.g.
            # _end_team_membership, _ensure_chapter_board_membership) re-raises so the
            # unit of work is abandoned rather than resumed. Catching them here and
            # writing an Error Log + event row on the discarded transaction is exactly
            # what would neutralise all of them, so this frame only rolls back and
            # propagates: whoever owns the transaction boundary restarts the run.
            frappe.db.rollback()
            self.logger.error("Non-resumable DB error applying event %s", event_name)
            raise

        except Exception as e:
            # Roll back BEFORE recording the failure. The handlers write as they go and
            # _create_related_records (address, membership, dues schedule, ACR, notes)
            # never commits, so without this the event.save() + commit() below makes
            # those partial writes durable while the event still says un-Applied — and
            # the operator's re-run then replays them onto half-applied state.
            # (create_or_update_member is the exception: member_import_service commits
            # the Member save itself, so that one write survives regardless. Separate
            # pre-existing issue — this frame cannot reach it.)
            frappe.db.rollback()

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

    # ─── New ───────────────────────────────────────────────────────────

    def _apply_new(self, event) -> dict:
        """Apply a 'New' event — dispatch to the right table handler."""
        return self._dispatch(event, "new")

    def _apply_new_member(self, event) -> dict:
        """Create a new Member from MijnRood admin_member data."""
        return get_member_sync_service().apply_new_member(event)

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
        return get_application_sync_service().apply_new_membership_application(event)

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
        return get_member_sync_service().apply_changed_member(event)

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
        return get_application_sync_service().apply_changed_membership_application(event)

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
        return get_application_sync_service().apply_approved(event)

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
