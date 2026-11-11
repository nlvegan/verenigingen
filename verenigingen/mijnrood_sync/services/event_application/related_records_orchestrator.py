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

The per-event ACR dedup Set (_acr_queued_members) lives on this service.
The dispatcher resets it at the start of every apply_event call via
reset_acr_dedup(); peer services call each other via their
``get_xxx_service()`` accessors.
"""

import hashlib
from typing import Callable, Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application import config_fault_alerts
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_int
from verenigingen.utils.service_logger import get_service_logger

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="event_application.related_records")

MOVE_FAILED_ALERT_KEY = "mijnrood_chapter_move_failed"
ALERT_REALERT_SECONDS = 24 * 3600


def move_failed_alert_claim_key(member_name: str, chapter_name: str, reason: str) -> str:
    """The Redis key that holds the once-a-day claim for one member's failed move to one chapter, for one reason."""
    reason_hash = hashlib.sha1((reason or "").encode()).hexdigest()[:10]
    return frappe.cache.make_key(f"{MOVE_FAILED_ALERT_KEY}:{member_name}:{chapter_name}:{reason_hash}")


class MijnRoodRelatedRecordsOrchestrator:
    """Creates ancillary records (address, Mollie, membership, dues, etc.) for a synced Member."""

    _TERMINAL_STATUSES = frozenset(("Quit", "Banned", "Deceased"))

    def __init__(self):
        self.logger = logger
        # Per-event ACR dedup: tracks which members have already had an
        # Account Creation Request queued during the current apply_event
        # invocation. Reset by the dispatcher via reset_acr_dedup() at the
        # start of each event. Previously lived on the dispatcher god-class
        # as _acr_queued_members.
        self._acr_queued_members: set[str] = set()
        # (member, blocking ACR) pairs already reported as blocked in this event (#1825), so the
        # member and volunteer entry points log one Error Log row between them. Not "queued":
        # nothing was queued, and is_acr_queued() must stay False.
        self._acr_blocked_reported: set[tuple[str, str]] = set()
        # Staff alerts raised during the current event (a failed chapter move #2199, configuration faults
        # #2309), sent by flush_pending_alerts() once the event is committed: an alert's rows and its
        # once-a-day claim must not be taken inside a transaction the event may still roll back.
        # Entries: (claim key, sender returning True when delivered, Error Log title if the send raises).
        self._pending_alerts: list[tuple[str, Callable[[], bool], str]] = []

    def reset_acr_dedup(self) -> None:
        """Clear the per-event ACR dedup set.

        Called by the dispatcher at the start of every apply_event
        invocation so dedup state never leaks between events.
        """
        self._acr_queued_members.clear()
        self._acr_blocked_reported.clear()
        self.discard_pending_alerts()

    def is_acr_queued(self, member_name: str) -> bool:
        """True if an ACR has already been queued for this member in the
        current event."""
        return member_name in self._acr_queued_members

    def mark_acr_queued(self, member_name: str) -> None:
        """Record that an ACR has been queued for this member."""
        self._acr_queued_members.add(member_name)

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
                title=f"MijnRood Sync - Address Creation Failed: {member_name}",
                message=frappe.get_traceback(),
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
                title=f"MijnRood Sync - Mollie Sync Failed: {member_name}",
                message=frappe.get_traceback(),
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
            self.alert_division_unmapped(
                division_id, "unmapped", "no Chapter has that division id", member_name, event
            )
            return _("Division ID {0} does not match any Chapter").format(division_id)

        if not frappe.db.exists("Chapter", chapter_name):
            self.alert_division_unmapped(
                division_id,
                "chapter missing",
                f"its mapped Chapter '{chapter_name}' does not exist",
                member_name,
                event,
            )
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
            frappe.log_error(
                title=f"MijnRood Chapter Assignment Failed: {member_name}",
                message=frappe.get_traceback(),
            )
            self._alert_chapter_move_failed(member_name, chapter_name, str(e), event)
            return _("Chapter assignment error: {0}").format(str(e))

        if result.get("success"):
            self.logger.info("Assigned member %s to chapter %s", member_name, chapter_name)
            return _("Assigned to chapter '{0}'").format(chapter_name)
        reason = result.get("message", "unknown")
        self._alert_chapter_move_failed(member_name, chapter_name, reason, event)
        return _("Chapter assignment failed: {0}").format(reason)

    def discard_pending_alerts(self) -> None:
        """Forget the alerts of an event that was rolled back: its re-apply will raise them again."""
        self._pending_alerts.clear()

    def queue_alert(self, claim: str, send: Callable[[], bool], failure_title: str) -> None:
        """Queue a staff alert to be sent after the event's commit, at most once per 24h per ``claim`` (rolling TTL, not a calendar day)."""
        self._pending_alerts.append((claim, send, failure_title))

    def flush_pending_alerts(self) -> None:
        """Send the alerts queued during the event. Call only AFTER the event's commit (#2199).

        Sent inside the event, the Notification Log rows were undone by the savepoint that backs out a
        failed member update and by the full rollback, while the once-a-day claim in Redis survived and
        suppressed every retry. Here a rollback can no longer take them back, and a rolled-back event
        never reaches this method, so its re-apply alerts instead of finding a stale claim.
        """
        pending, self._pending_alerts = self._pending_alerts, []
        for claim, send, failure_title in pending:
            self._send_alert_once_a_day(claim, send, failure_title)

    def _send_alert_once_a_day(self, claim: str, send: Callable[[], bool], failure_title: str) -> None:
        """Tell staff once per 24h. The alert must never undo the sync, so a failure here is logged and swallowed."""
        try:
            # SETNX with an expiry, not the key's per-recipient cooldown: that is admin-editable (0 = off).
            if not frappe.cache.set(claim, "1", ex=ALERT_REALERT_SECONDS, nx=True):
                return
            delivered = send()
        except Exception:
            frappe.cache.delete(claim)  # so the next failure tries again
            frappe.log_error(title=failure_title, message=frappe.get_traceback())
            return
        if not delivered:
            frappe.cache.delete(claim)  # key off or nobody to tell: do not hold the alert back for a day

    def _alert_chapter_move_failed(self, member_name: str, chapter_name: str, reason: str, event) -> None:
        """Queue the staff alert for a chapter move that did not happen (#2199), sent after the commit.

        The event is consumed either way and MijnRood does not resend, so without this the only trace is
        the applied message.
        """
        event_name = getattr(event, "name", "") or ""
        self.queue_alert(
            move_failed_alert_claim_key(member_name, chapter_name, reason),
            lambda: self._send_chapter_move_failed_alert(member_name, chapter_name, reason, event_name),
            "MijnRood chapter-move alert failed",
        )

    def alert_division_unmapped(self, division_id, reason: str, detail: str, member_name: str, event) -> None:
        """Queue the configuration-fault alert for a division id no Chapter answers (#2309)."""
        event_name = getattr(event, "name", "") or ""
        self.queue_alert(
            config_fault_alerts.division_unmapped_claim(division_id, reason),
            lambda: config_fault_alerts.send_division_unmapped_alert(
                division_id, reason, detail, member_name, event_name
            ),
            "MijnRood division alert failed",
        )

    def alert_role_mapping_invalid(
        self, object_type: str, name: str, reason: str, member_name: str, event
    ) -> None:
        """Queue the configuration-fault alert for a role-mapping target that is missing or inactive (#2309)."""
        event_name = getattr(event, "name", "") or ""
        self.queue_alert(
            config_fault_alerts.role_mapping_claim(object_type, name, reason),
            lambda: config_fault_alerts.send_role_mapping_alert(
                object_type, name, reason, member_name, event_name
            ),
            "MijnRood role-mapping alert failed",
        )

    def alert_dues_template_unresolved(
        self, payment_period, detail: str, member_name: str, event=None
    ) -> None:
        """Queue the configuration-fault alert for a payment period with no dues template (#2309)."""
        event_name = getattr(event, "name", "") or ""
        self.queue_alert(
            config_fault_alerts.dues_template_claim(payment_period),
            lambda: config_fault_alerts.send_dues_template_alert(
                payment_period, detail, member_name, event_name
            ),
            "MijnRood dues-template alert failed",
        )

    def _send_chapter_move_failed_alert(
        self, member_name: str, chapter_name: str, reason: str, event_name: str
    ) -> bool:
        """Raise the staff alert; True when at least one notification was actually created."""
        from frappe.utils import escape_html

        from verenigingen.utils.notification_helpers import notify_administrators

        full_name = frappe.db.get_value("Member", member_name, "full_name") or member_name
        # The failed move was rolled back, so these are the chapters the member is still in.
        sources = frappe.get_all(
            "Chapter Member", filters={"member": member_name, "enabled": 1}, pluck="parent"
        )
        result = notify_administrators(
            subject=f"MijnRood chapter move failed for {member_name}",
            message=(
                f"<p>MijnRood moved member <b>{escape_html(full_name)}</b> ({escape_html(member_name)}) "
                f"to chapter <b>{escape_html(chapter_name)}</b>, but the move did not happen. The member "
                f"is still in: <b>{escape_html(', '.join(sources) or 'no chapter')}</b>.</p>"
                f"<p>Reason: {escape_html(reason)}</p>"
                f"<p>Action required: fix the cause and move the member by hand. MijnRood will not send "
                f"this change again (event {escape_html(event_name)}). This alert "
                "repeats at most once per 24h for the same member, chapter and reason.</p>"
            ),
            notification_key="mijnrood_chapter_move_failed",  # literal: key discovery greps for it
            document_type="Member",
            document_name=member_name,
            event_reference=f"mijnrood_chapter_move_failed:{member_name}",
            # ruling 2026-11-01: staff alerts never go to Administrator
            exclude_users=["Administrator"],
            staff_alert=True,
        )
        result = result or {}
        return (
            bool(result.get("success"))
            and not result.get("skipped")
            and bool(result.get("notifications_created"))
        )

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
        if self.is_acr_queued(member_name):
            return None

        from verenigingen.utils.account_creation_manager import (
            queue_account_creation_for_member,
        )

        try:
            request_name, refusal = self._queue_account_request(
                queue_account_creation_for_member,
                member_name,
                roles=["Verenigingen Member"],
                role_profile="Verenigingen Member",
                priority="Low",
            )
            if request_name:
                self.mark_acr_queued(member_name)
                self.logger.info(
                    "Queued account creation for member %s (request=%s)",
                    member_name,
                    request_name,
                )
                return _("Account creation queued ({0})").format(request_name)
            return refusal
        except Exception as e:
            frappe.log_error(title="MijnRood account creation failed", message=frappe.get_traceback())
            return _("Account creation failed: {0}").format(str(e)[:200])

    def _queue_account_request(self, queue_fn, member_name: str, **kwargs):
        """Call the ACR queue and read its serialized result.

        ``queue_account_creation_for_member`` is wrapped by ``high_security_api``,
        which returns ``OperationResult.to_dict()``: a plain dict, so
        ``result.success`` raises AttributeError (#1638). Same reading as
        ``create_secure_user_account_for_member``.

        Returns:
            ``(request_name, None)`` when queued; ``(None, None)`` when a request
            is already open or the member has no email (expected skips); ``(None, message)``
            for any other refusal, including a Failed blocking request (#1825), which is also
            written to the Error Log (``frappe.logger`` is never read) so it surfaces to the caller.
        """
        result = queue_fn(member_name, **kwargs)
        if result and result.get("success"):
            return (result.get("data") or {}).get("request_name") or "unknown", None

        context = ((result or {}).get("meta") or {}).get("context") or {}
        blocking = (context.get("params") or {}).get("existing_request")
        if blocking:
            return self._skip_for_blocking_request(member_name, blocking)

        error = (result or {}).get("error") or {}
        if error.get("code") == "NO_EMAIL":
            # Maintainer decision (#1638): a member without an email is an expected skip.
            return None, None
        reason = error.get("message") or "Unknown error"
        detail = "; ".join(str(e) for e in error.get("errors") or [])
        frappe.log_error(
            title="MijnRood account creation refused",
            message=f"Member {member_name}: {reason} {detail}".strip(),
        )
        return None, _("Account creation not queued: {0}").format(reason)

    def _skip_for_blocking_request(self, member_name: str, blocking_request: str):
        """An open blocker is an expected skip; a Failed one is a stuck account (#1825).

        ``_find_blocking_request`` also returns a Failed request with retries left, and
        nothing retries a standalone one unattended (only a staff ``retry_failed_request``).
        ``mark_failed`` logs the original failure once (#2066), not each attempt it blocks, so
        without this row the member's blocked attempt leaves no trace.
        """
        status = frappe.db.get_value("Account Creation Request", blocking_request, "status")
        if status != "Failed":
            return None, None
        if (member_name, blocking_request) not in self._acr_blocked_reported:
            self._acr_blocked_reported.add((member_name, blocking_request))
            frappe.log_error(
                title="MijnRood account creation blocked",
                message=(
                    f"Member {member_name}: no account created because Account Creation Request "
                    f"{blocking_request} is Failed and still retryable. Retry or cancel it."
                ),
            )
        return None, _("Account creation blocked by failed request {0}").format(blocking_request)

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
                title=f"MijnRood Sync - Membership Creation Failed: {member_name}",
                message=frappe.get_traceback(),
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
            self.alert_dues_template_unresolved(row_data.get("payment_period"), str(e)[:200], member_doc.name)
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
                title=f"MijnRood Sync - Dues Schedule Backfill Failed: {member_doc.name}",
                message=frappe.get_traceback(),
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
            # Security: MijnRood sync is a trusted system process running
            # outside a permissive user context. It bypasses DocPerms like
            # every other write in this module (event/chapter/state writes
            # all use ignore_permissions). Data originates from the
            # authenticated MijnRood SSH tunnel, not from end users.
            ignore_permissions=True,
        )

        if not result.success:
            self.logger.error("Dues schedule update failed for %s: %s", member_name, result.message)
            frappe.log_error(
                title=f"MijnRood Sync - Dues Schedule Update Failed: {member_name}",
                message="; ".join(result.errors or [result.message]),
            )
            return _("Dues schedule update failed: {0}").format(result.message[:200])

        if result.method_used == "no_change_needed":
            return None

        self.logger.info("Updated dues schedule %s for member %s", schedule.name, member_name)
        return _("Dues schedule {0} updated: {1}").format(schedule.name, result.message)

    def _ensure_user_account_for_volunteer(self, member_name: str) -> Optional[str]:
        """Queue an ACR for a volunteer/staff member who needs a User account.

        Unlike ``_ensure_user_account()`` (which respects the global
        ``create_member_accounts`` toggle), this is unconditional — volunteers
        being assigned to teams or boards always need a User account for
        the role profile system to work.

        The ACR pipeline handles all idempotency checks (existing user,
        pending request, missing email).

        Returns:
            Human-readable status message, or None if user exists / ACR already queued / an
            open request exists. A Failed, still-retryable blocking request returns a
            "blocked by failed request" message (logged once per event) instead (#1825).
        """
        user = frappe.db.get_value("Member", member_name, "user")
        if user:
            return None

        if self.is_acr_queued(member_name):
            return None

        from verenigingen.utils.account_creation_manager import (
            queue_account_creation_for_member,
        )

        try:
            request_name, refusal = self._queue_account_request(
                queue_account_creation_for_member,
                member_name,
                roles=["Verenigingen Volunteer"],
                role_profile="Verenigingen Volunteer",
                priority="Normal",
            )
            if request_name:
                self.mark_acr_queued(member_name)
                self.logger.info(
                    "Queued account creation for volunteer %s (request=%s)",
                    member_name,
                    request_name,
                )
                return _("Account creation queued for volunteer ({0})").format(request_name)
            return refusal
        except Exception as e:
            frappe.log_error(title="MijnRood account creation failed", message=frappe.get_traceback())
            return _("Account creation failed: {0}").format(str(e)[:200])

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


_service_instance: Optional[MijnRoodRelatedRecordsOrchestrator] = None


def get_related_records_orchestrator() -> MijnRoodRelatedRecordsOrchestrator:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodRelatedRecordsOrchestrator()
    return _service_instance
