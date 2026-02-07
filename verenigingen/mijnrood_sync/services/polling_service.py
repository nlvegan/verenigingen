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
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    STATUS_ID_LABELS,
    TABLE_PRIMARY_KEY,
)
from verenigingen.services.infrastructure.base_service import StatefulService


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
            List of {field, old, new} dicts
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
                changed.append({"field": key, "old": old_val, "new": new_val})

        return changed

    def _compute_change_summary(
        self,
        event_type: str,
        table: str,
        old_data: Optional[dict],
        new_data: Optional[dict],
        changed_fields: Optional[list],
    ) -> str:
        """Generate human-readable change summary."""
        if event_type == "New":
            name_parts = []
            if new_data:
                for field in ["first_name", "middle_name", "last_name"]:
                    val = new_data.get(field)
                    if val:
                        name_parts.append(str(val))
            name = " ".join(name_parts) if name_parts else f"row {new_data.get('id', '?')}"
            return f"New {table} record: {name}"

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
            summaries = []
            for change in changed_fields[:5]:
                field = change["field"]
                old_val = change["old"]
                new_val = change["new"]

                # Special handling for status changes
                if field == "current_membership_status_id":
                    old_label = STATUS_ID_LABELS.get(int(old_val) if old_val else None, str(old_val))
                    new_label = STATUS_ID_LABELS.get(int(new_val) if new_val else None, str(new_val))
                    summaries.append(f"Status: {old_label} → {new_label}")
                else:
                    # Use mapped field name if available
                    display_name = MIJNROOD_TO_MEMBER_FIELD_MAP.get(field, field)
                    summaries.append(f"{display_name} changed")

            summary = "; ".join(summaries)
            if len(changed_fields) > 5:
                summary += f" (+{len(changed_fields) - 5} more)"
            return summary

        return f"{event_type} event for {table}"

    def _find_linked_member(self, table: str, row_id: int) -> Optional[str]:
        """Look up Verenigingen Member by member_id matching MijnRood row ID.

        Only applies to admin_member table — other tables need different
        matching logic or don't link directly to members.
        """
        if table != "admin_member":
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
