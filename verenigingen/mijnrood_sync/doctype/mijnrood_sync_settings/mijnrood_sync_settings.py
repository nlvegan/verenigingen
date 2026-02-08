import json

import frappe
from frappe import _
from frappe.model.document import Document


class MijnRoodSyncSettings(Document):
    @frappe.whitelist()
    def test_connection(self):
        """Test SSH tunnel and database connectivity."""
        from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

        try:
            client = MijnRoodDatabaseClient(settings=self)
            with client:
                row_count = client.test_query()
            self.db_set(
                "connection_status", _("Connected successfully ({0} rows in admin_member)").format(row_count)
            )
            frappe.db.commit()
            return {"success": True, "message": _("Connection successful"), "row_count": row_count}
        except Exception as e:
            error_msg = str(e)[:500]
            self.db_set("connection_status", _("Connection failed: {0}").format(error_msg))
            frappe.db.commit()
            frappe.log_error(frappe.get_traceback(), "MijnRood Connection Test Failed")
            return {"success": False, "message": error_msg}

    @frappe.whitelist()
    def trigger_sync_now(self):
        """Enqueue an immediate sync job."""
        frappe.enqueue(
            "verenigingen.mijnrood_sync.tasks.run_mijnrood_sync",
            queue="long",
            timeout=3600,
            job_name="mijnrood_sync_manual",
        )
        return {"success": True, "message": _("Sync job enqueued")}

    def validate(self):
        """Validate settings before save."""
        if self.tables_to_sync:
            try:
                tables = json.loads(self.tables_to_sync)
                if not isinstance(tables, list):
                    frappe.throw(_("Tables to Sync must be a JSON list"))
            except json.JSONDecodeError:
                frappe.throw(_("Tables to Sync must be valid JSON"))

        if self.poll_interval_minutes and self.poll_interval_minutes < 1:
            frappe.throw(_("Poll interval must be at least 1 minute"))

        if self.ssh_port and (self.ssh_port < 1 or self.ssh_port > 65535):
            frappe.throw(_("SSH port must be between 1 and 65535"))

        if self.db_port and (self.db_port < 1 or self.db_port > 65535):
            frappe.throw(_("Database port must be between 1 and 65535"))

        self._validate_status_mapping()

    def _validate_status_mapping(self):
        """Validate status mapping child table entries."""
        if not self.status_mapping:
            return

        seen_ids = set()
        for row in self.status_mapping:
            if row.mijnrood_status_id in seen_ids:
                frappe.throw(
                    _("Duplicate Status ID {0} in row {1}").format(
                        row.mijnrood_status_id, row.idx
                    )
                )
            seen_ids.add(row.mijnrood_status_id)

            if not row.is_active and not row.termination_type:
                frappe.msgprint(
                    _("Row {0} (Status ID {1}): non-active status has no termination type set").format(
                        row.idx, row.mijnrood_status_id
                    ),
                    indicator="orange",
                    alert=True,
                )

    def on_update(self):
        """Clear cached status mapping when settings change."""
        frappe.cache.delete_value("mijnrood_status_mapping")

    @frappe.whitelist()
    def populate_default_status_mapping(self):
        """Load default status mapping values into the child table.

        Only populates if the table is empty to avoid overwriting
        admin customizations.
        """
        if self.status_mapping:
            frappe.throw(_("Status mapping table is not empty. Clear it first to reload defaults."))

        from verenigingen.mijnrood_sync.field_mapping import (
            _DEFAULT_ACTIVE_STATUS_IDS,
            _DEFAULT_STATUS_ID_LABELS,
            _DEFAULT_STATUS_ID_MAP,
            _DEFAULT_STATUS_ID_TO_TERMINATION_TYPE,
        )

        for status_id, type_string in _DEFAULT_STATUS_ID_MAP.items():
            self.append("status_mapping", {
                "mijnrood_status_id": status_id,
                "label": _DEFAULT_STATUS_ID_LABELS.get(status_id, type_string),
                "membership_type_string": type_string,
                "is_active": 1 if status_id in _DEFAULT_ACTIVE_STATUS_IDS else 0,
                "termination_type": _DEFAULT_STATUS_ID_TO_TERMINATION_TYPE.get(status_id, ""),
            })

        self.save()
        return {"success": True, "message": _("Loaded {0} default status mappings").format(len(self.status_mapping))}


@frappe.whitelist()
def get_status_mapping_for_client():
    """Return status mapping for JS client rendering.

    Returns dict keyed by status_id with label, is_active, termination_type.
    Used by mijnrood_sync_event.js for implications panel and diff display.
    """
    from verenigingen.mijnrood_sync.field_mapping import get_status_labels, get_terminated_status_ids

    labels = get_status_labels()
    terminated = get_terminated_status_ids()

    result = {}
    for status_id, label in labels.items():
        result[str(status_id)] = {
            "label": label,
            "is_terminated": status_id in terminated,
        }
    return result
