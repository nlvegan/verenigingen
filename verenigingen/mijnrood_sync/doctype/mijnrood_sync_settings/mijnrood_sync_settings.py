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
