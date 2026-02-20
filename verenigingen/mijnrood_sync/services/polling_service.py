"""
MijnRood Polling Service

Orchestrates the poll-compare-create cycle:
1. Connect to MijnRood DB via SSH tunnel
2. For each configured table, fetch row checksums
3. Compare against stored Sync State
4. Create Sync Events for new/changed/deleted rows
5. Update Sync State with current checksums
"""

import json
import uuid
from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient
from verenigingen.mijnrood_sync.field_mapping import (
    MIJNROOD_FIELD_LABELS,
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    TABLE_PRIMARY_KEY,
    get_status_labels,
)
from verenigingen.mijnrood_sync.utils import safe_int
from verenigingen.services.infrastructure.base_service import StatefulService

# Maps MijnRood field names to triage-friendly category tags
FIELD_TAG_MAP = {
    "current_membership_status_id": "Status",
    "division_id": "Chapter",
    "preferred_division_id": "Chapter",
    "contribution_per_period_in_cents": "Financial",
    "contribution_period": "Financial",
    "iban": "Financial",
    "mollie_customer_id": "Financial",
    "mollie_subscription_id": "Financial",
    "email": "Contact",
    "phone": "Contact",
    "first_name": "Personal",
    "middle_name": "Personal",
    "last_name": "Personal",
    "date_of_birth": "Personal",
    "address": "Address",
    "city": "Address",
    "post_code": "Address",
    "country": "Address",
    "roles": "Roles",
    "managed_division_ids": "Roles",
}

# Tag display order (highest priority first)
TAG_ORDER = ["Status", "Chapter", "Financial", "Roles", "Contact", "Personal", "Address"]

# Table-to-label map for New events
_NEW_TABLE_LABELS = {
    "admin_member": "New Member",
    "admin_membership_application": "New Application",
    "admin_division": "New Division",
}


def compute_change_tags(event_type: str, table: str, changed_fields: list | None) -> str:
    """Compute comma-separated change category tags for a sync event.

    Used both during polling (new events) and for backfilling existing events.
    """
    if event_type == "New":
        return _NEW_TABLE_LABELS.get(table, "New")
    if event_type == "Deleted":
        return "Deleted"
    # Changed
    if not changed_fields:
        return ""
    tags = set()
    for cf in changed_fields:
        field = cf.get("field") if isinstance(cf, dict) else cf
        tag = FIELD_TAG_MAP.get(field)
        if tag:
            tags.add(tag)
    if not tags:
        return "Other"
    return ",".join(t for t in TAG_ORDER if t in tags)


class MijnRoodPollingService(StatefulService):
    """Polls MijnRood DB for changes and creates Sync Events for review."""

    def __init__(self):
        super().__init__(service_name="MijnRoodPollingService")

    def run_sync(self) -> dict:
        """Main entry point. Called by scheduler or manual trigger.

        Returns:
            Summary dict with counts of new/changed/deleted events
        """
        settings = frappe.get_single("MijnRood Sync Settings")

        sync_run_id = str(uuid.uuid4())[:12]
        started_at = now_datetime()

        # Create sync log (status=Running)
        log_doc = frappe.new_doc("MijnRood Sync Log")
        log_doc.sync_run_id = sync_run_id
        log_doc.status = "Running"
        log_doc.started_at = started_at
        # Security: System-internal audit log, runs in background scheduler context
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Update settings status
        settings.db_set("last_sync_status", "Running", update_modified=False)
        frappe.db.commit()

        tables = json.loads(settings.tables_to_sync or "[]")
        totals = {
            "new": 0,
            "changed": 0,
            "deleted": 0,
            "unchanged": 0,
            "rows_scanned": 0,
        }

        try:
            client = MijnRoodDatabaseClient(settings=settings)
            with client:
                for table in tables:
                    table_stats = self._poll_table(client, table, sync_run_id)
                    totals["new"] += table_stats["new"]
                    totals["changed"] += table_stats["changed"]
                    totals["deleted"] += table_stats["deleted"]
                    totals["unchanged"] += table_stats["unchanged"]
                    totals["rows_scanned"] += table_stats["rows_scanned"]

                # Poll division_member junction table for role changes
                dc_events = self._poll_division_contacts(client, settings, sync_run_id)
                totals["changed"] += dc_events

            # Update sync log
            completed_at = now_datetime()
            duration = (completed_at - started_at).total_seconds()
            log_doc.reload()
            log_doc.status = "Success"
            log_doc.completed_at = completed_at
            log_doc.duration_seconds = duration
            log_doc.tables_polled = json.dumps(tables)
            log_doc.rows_scanned = totals["rows_scanned"]
            log_doc.new_events = totals["new"]
            log_doc.changed_events = totals["changed"]
            log_doc.deleted_events = totals["deleted"]
            log_doc.unchanged_rows = totals["unchanged"]
            # Security: System-internal audit log update in scheduler context
            log_doc.save(ignore_permissions=True)

            # Update settings
            pending_count = frappe.db.count("MijnRood Sync Event", {"status": "Pending"})
            msg = _("Synced {0} tables: {1} new, {2} changed, {3} deleted").format(
                len(tables), totals["new"], totals["changed"], totals["deleted"]
            )
            settings.db_set(
                {
                    "last_sync_time": completed_at,
                    "last_sync_status": "Success",
                    "last_sync_message": msg,
                    "total_events_pending": pending_count,
                },
                update_modified=False,
            )
            frappe.db.commit()

            self.logger.info("Sync complete: %s", msg)
            return totals

        except Exception as e:
            error_msg = str(e)[:2000]
            self.logger.error("Sync failed: %s", error_msg)
            frappe.log_error(frappe.get_traceback(), "MijnRood Sync Failed")

            # Update log
            try:
                log_doc.reload()
                log_doc.status = "Failed"
                log_doc.completed_at = now_datetime()
                log_doc.error_message = error_msg
                # Security: System-internal error recording in scheduler context
                log_doc.save(ignore_permissions=True)
            except Exception:
                pass

            # Update settings
            try:
                settings.db_set(
                    {
                        "last_sync_status": "Failed",
                        "last_sync_message": error_msg[:500],
                    },
                    update_modified=False,
                )
                frappe.db.commit()
            except Exception:
                pass

            raise

    def _poll_table(self, client: MijnRoodDatabaseClient, table: str, sync_run_id: str) -> dict:
        """Poll a single MijnRood table for changes.

        Args:
            client: Connected MijnRood DB client
            table: Table name to poll
            sync_run_id: Current sync run ID

        Returns:
            Dict with counts: new, changed, deleted, unchanged, rows_scanned
        """
        self.logger.info("Polling table: %s", table)

        # 1. Fetch checksums from MijnRood
        mijnrood_checksums = client.fetch_row_checksums(table)
        mijnrood_ids = set(mijnrood_checksums.keys())

        # 2. Load existing sync state for this table
        state_rows = frappe.get_all(
            "MijnRood Sync State",
            filters={"mijnrood_table": table},
            fields=["name", "mijnrood_row_id", "row_checksum", "raw_data"],
        )
        state_by_id = {row.mijnrood_row_id: row for row in state_rows}
        state_ids = set(state_by_id.keys())

        # 3. Classify changes
        new_ids = mijnrood_ids - state_ids
        deleted_ids = state_ids - mijnrood_ids
        common_ids = mijnrood_ids & state_ids
        changed_ids = {
            row_id
            for row_id in common_ids
            if mijnrood_checksums[row_id] != (state_by_id[row_id].row_checksum or "")
        }
        unchanged_count = len(common_ids) - len(changed_ids)

        stats = {
            "new": 0,
            "changed": 0,
            "deleted": 0,
            "unchanged": unchanged_count,
            "rows_scanned": len(mijnrood_ids),
        }

        # 4. Fetch full row data for new/changed rows (batch)
        ids_needing_data = list(new_ids | changed_ids)
        row_data_by_id = {}
        if ids_needing_data:
            rows = client.fetch_rows_by_ids(table, ids_needing_data)
            pk = TABLE_PRIMARY_KEY.get(table, "id")
            row_data_by_id = {row[pk]: row for row in rows}

        now = now_datetime()

        # 5. Process NEW rows
        for row_id in new_ids:
            new_data = row_data_by_id.get(row_id, {})
            linked_member = self._find_linked_member(table, row_id)

            self._create_sync_event(
                event_type="New",
                table=table,
                row_id=row_id,
                old_data=None,
                new_data=new_data,
                linked_member=linked_member,
                sync_run_id=sync_run_id,
                detected_at=now,
            )

            self._upsert_sync_state(
                table=table,
                row_id=row_id,
                checksum=mijnrood_checksums[row_id],
                raw_data=new_data,
                linked_member=linked_member,
                last_seen=now,
            )
            stats["new"] += 1

        # 6. Process CHANGED rows
        for row_id in changed_ids:
            new_data = row_data_by_id.get(row_id, {})
            state = state_by_id[row_id]
            old_data = json.loads(state.raw_data) if state.raw_data else {}
            changed_fields = self._compute_changed_fields(old_data, new_data)
            linked_member = state.get("linked_member") or self._find_linked_member(table, row_id)

            self._create_sync_event(
                event_type="Changed",
                table=table,
                row_id=row_id,
                old_data=old_data,
                new_data=new_data,
                changed_fields=changed_fields,
                linked_member=linked_member,
                sync_run_id=sync_run_id,
                detected_at=now,
            )

            self._upsert_sync_state(
                table=table,
                row_id=row_id,
                checksum=mijnrood_checksums[row_id],
                raw_data=new_data,
                linked_member=linked_member,
                last_seen=now,
            )
            stats["changed"] += 1

        # 7. Process DELETED rows
        for row_id in deleted_ids:
            state = state_by_id[row_id]
            old_data = json.loads(state.raw_data) if state.raw_data else {}
            linked_member = state.get("linked_member")

            self._create_sync_event(
                event_type="Deleted",
                table=table,
                row_id=row_id,
                old_data=old_data,
                new_data=None,
                linked_member=linked_member,
                sync_run_id=sync_run_id,
                detected_at=now,
            )

            # Remove sync state for deleted rows
            # Security: System-internal state cleanup in scheduler context
            frappe.delete_doc("MijnRood Sync State", state.name, ignore_permissions=True)
            stats["deleted"] += 1

        # 8. Update last_seen for unchanged rows
        if common_ids - changed_ids:
            unchanged_names = [state_by_id[row_id].name for row_id in (common_ids - changed_ids)]
            # Batch update last_seen
            for name in unchanged_names:
                frappe.db.set_value("MijnRood Sync State", name, "last_seen", now, update_modified=False)

        frappe.db.commit()

        self.logger.info(
            "Table %s: %d new, %d changed, %d deleted, %d unchanged",
            table,
            stats["new"],
            stats["changed"],
            stats["deleted"],
            stats["unchanged"],
        )
        return stats

    def _poll_division_contacts(
        self,
        client: MijnRoodDatabaseClient,
        settings,
        sync_run_id: str,
    ) -> int:
        """Poll the division_member junction table for ROLE_DIVISION_CONTACT changes.

        Fetches the full table (~50 rows), compares against last-seen state stored
        in settings.last_division_contacts_hash, and creates synthetic Changed events
        on admin_member for any members whose managed divisions changed.

        Returns:
            Number of events created.
        """
        try:
            current = client.fetch_division_contacts()
        except Exception as e:
            self.logger.warning("Failed to fetch division_member table (may not exist): %s", e)
            return 0

        # Load previous state
        previous: dict[int, list[int]] = {}
        if settings.last_division_contacts_hash:
            try:
                raw = json.loads(settings.last_division_contacts_hash)
                # JSON keys are strings — convert back to int
                previous = {int(k): v for k, v in raw.items()}
            except (json.JSONDecodeError, ValueError):
                self.logger.warning("Invalid last_division_contacts_hash, treating as empty")

        # Diff: find members whose managed divisions changed
        all_member_ids = set(current.keys()) | set(previous.keys())
        events_created = 0
        now = now_datetime()

        for member_id in all_member_ids:
            old_divs = previous.get(member_id, [])
            new_divs = current.get(member_id, [])

            if old_divs == new_divs:
                continue

            # Create a synthetic Changed event on admin_member
            linked_member = self._find_linked_member("admin_member", member_id)
            self._create_sync_event(
                event_type="Changed",
                table="admin_member",
                row_id=member_id,
                old_data={"managed_division_ids": old_divs},
                new_data={"managed_division_ids": new_divs},
                changed_fields=[
                    {
                        "field": "managed_division_ids",
                        "old": old_divs,
                        "new": new_divs,
                        "label": "Managed Divisions (Afdelingscontact)",
                    }
                ],
                linked_member=linked_member,
                sync_run_id=sync_run_id,
                detected_at=now,
            )
            events_created += 1

        # Store current state — use string keys for JSON
        new_hash = json.dumps({str(k): v for k, v in current.items()}, sort_keys=True)
        settings.db_set("last_division_contacts_hash", new_hash, update_modified=False)
        frappe.db.commit()

        if events_created:
            self.logger.info(
                "Division contacts: %d changes detected (%d total contacts)",
                events_created,
                len(current),
            )

        return events_created

    def _create_sync_event(
        self,
        event_type: str,
        table: str,
        row_id: int,
        old_data: Optional[dict],
        new_data: Optional[dict],
        sync_run_id: str,
        detected_at: Any,
        linked_member: Optional[str] = None,
        changed_fields: Optional[list] = None,
    ):
        """Create a MijnRood Sync Event document."""
        change_summary = self._compute_change_summary(event_type, table, old_data, new_data, changed_fields)

        event = frappe.new_doc("MijnRood Sync Event")
        event.event_type = event_type
        event.mijnrood_table = table
        event.mijnrood_row_id = row_id
        event.status = "Pending"
        event.linked_member = linked_member
        event.old_data = json.dumps(old_data) if old_data else None
        event.new_data = json.dumps(new_data) if new_data else None
        event.changed_fields = json.dumps(changed_fields) if changed_fields else None
        event.change_summary = change_summary
        event.change_tags = compute_change_tags(event_type, table, changed_fields)
        event.detected_at = detected_at
        event.sync_run_id = sync_run_id
        # Security: System-internal sync event creation in scheduler context
        event.insert(ignore_permissions=True)

    def _upsert_sync_state(
        self,
        table: str,
        row_id: int,
        checksum: str,
        raw_data: dict,
        linked_member: Optional[str],
        last_seen: Any,
    ):
        """Create or update a Sync State record."""
        state_key = f"{table}-{row_id}"

        if frappe.db.exists("MijnRood Sync State", state_key):
            frappe.db.set_value(
                "MijnRood Sync State",
                state_key,
                {
                    "row_checksum": checksum,
                    "raw_data": json.dumps(raw_data),
                    "linked_member": linked_member,
                    "last_seen": last_seen,
                },
                update_modified=False,
            )
        else:
            state = frappe.new_doc("MijnRood Sync State")
            state.state_key = state_key
            state.mijnrood_table = table
            state.mijnrood_row_id = row_id
            state.row_checksum = checksum
            state.raw_data = json.dumps(raw_data)
            state.linked_member = linked_member
            state.last_seen = last_seen
            # Security: System-internal state tracking in scheduler context
            state.insert(ignore_permissions=True)

    def _compute_changed_fields(self, old_data: dict, new_data: dict) -> list[dict]:
        """Compare old and new data to find changed fields.

        Returns:
            List of dicts with keys: field, old, new, label,
            and optionally old_display/new_display for resolved values.
        """
        changed = []
        all_keys = set(old_data.keys()) | set(new_data.keys())

        for key in sorted(all_keys):
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            # Normalize for comparison (None vs empty string)
            if old_val is None:
                old_val = ""
            if new_val is None:
                new_val = ""
            if str(old_val) != str(new_val):
                entry = {
                    "field": key,
                    "old": old_val,
                    "new": new_val,
                    "label": MIJNROOD_FIELD_LABELS.get(key, key),
                }

                # Resolve display values for special fields
                if key == "current_membership_status_id":
                    labels = get_status_labels()
                    entry["old_display"] = labels.get(safe_int(old_val), str(old_val))
                    entry["new_display"] = labels.get(safe_int(new_val), str(new_val))
                elif key in ("division_id", "preferred_division_id"):
                    entry["old_display"] = self._resolve_division_name(old_val) or str(old_val)
                    entry["new_display"] = self._resolve_division_name(new_val) or str(new_val)

                changed.append(entry)

        return changed

    def _resolve_division_name(self, division_id) -> str | None:
        """Resolve a MijnRood division_id to a human-readable chapter name.

        Looks up the admin_division sync state to find the division's name field.
        """
        div_id = safe_int(division_id)
        if div_id is None:
            return None

        state = frappe.db.get_value(
            "MijnRood Sync State",
            {"mijnrood_table": "admin_division", "mijnrood_row_id": div_id},
            "raw_data",
        )
        if state:
            data = json.loads(state)
            return data.get("name")
        return None

    def _compute_change_summary(
        self,
        event_type: str,
        table: str,
        old_data: Optional[dict],
        new_data: Optional[dict],
        changed_fields: Optional[list],
    ) -> str:
        """Generate human-readable change summary with values."""
        if event_type == "New":
            return self._summary_for_new(table, new_data)

        if event_type == "Deleted":
            name_parts = []
            if old_data:
                for field in ["first_name", "middle_name", "last_name"]:
                    val = old_data.get(field)
                    if val:
                        name_parts.append(str(val))
            name = " ".join(name_parts) if name_parts else "unknown"
            return f"Deleted {table} record: {name}"

        if event_type == "Changed" and changed_fields:
            return self._summary_for_changed(changed_fields)

        return f"{event_type} event for {table}"

    def _summary_for_new(self, table: str, new_data: Optional[dict]) -> str:
        """Build a summary for New events with key contextual fields."""
        if not new_data:
            return f"New {table} record"

        name_parts = []
        for field in ["first_name", "middle_name", "last_name"]:
            val = new_data.get(field)
            if val:
                name_parts.append(str(val))
        name = " ".join(name_parts) if name_parts else f"row {new_data.get('id', '?')}"

        details = []
        if table in ("admin_member", "admin_support_member", "admin_membership_application"):
            if new_data.get("email"):
                details.append(str(new_data["email"]))
            if new_data.get("city"):
                details.append(str(new_data["city"]))
            div_id = new_data.get("division_id") or new_data.get("preferred_division_id")
            if div_id:
                chapter = self._resolve_division_name(div_id)
                details.append(chapter or f"div#{div_id}")
            status_id = new_data.get("current_membership_status_id")
            if status_id is not None:
                label = get_status_labels().get(safe_int(status_id), str(status_id))
                details.append(label)
        elif table == "admin_division":
            if new_data.get("city"):
                details.append(str(new_data["city"]))
            if new_data.get("email_id"):
                details.append(str(new_data["email_id"]))

        summary = f"New {table} record: {name}"
        if details:
            summary += f" ({', '.join(details)})"
        return summary

    @staticmethod
    def _summary_for_changed(changed_fields: list) -> str:
        """Build a summary for Changed events including old→new values."""
        summaries = []
        for change in changed_fields[:5]:
            label = change.get("label", change["field"])
            old_display = change.get("old_display") or change.get("old", "")
            new_display = change.get("new_display") or change.get("new", "")

            # Truncate long values for summary readability
            old_str = str(old_display)[:30]
            new_str = str(new_display)[:30]

            if old_str and new_str:
                summaries.append(f"{label}: {old_str} → {new_str}")
            elif new_str:
                summaries.append(f"{label}: (empty) → {new_str}")
            elif old_str:
                summaries.append(f"{label}: {old_str} → (empty)")
            else:
                summaries.append(f"{label} changed")

        summary = "; ".join(summaries)
        if len(changed_fields) > 5:
            summary += f" (+{len(changed_fields) - 5} more)"
        return summary

    def _find_linked_member(self, table: str, row_id: int) -> Optional[str]:
        """Look up Verenigingen Member by member_id matching MijnRood row ID.

        Applies to admin_member and admin_membership_application tables,
        which both use member_id to link to Verenigingen Members.
        """
        if table not in ("admin_member", "admin_membership_application"):
            return None

        member = frappe.db.get_value(
            "Member",
            {"member_id": row_id},
            "name",
        )
        return member


# Module-level singleton accessor
_service_instance: Optional[MijnRoodPollingService] = None


def get_polling_service() -> MijnRoodPollingService:
    """Get singleton instance of MijnRoodPollingService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodPollingService()
    return _service_instance
