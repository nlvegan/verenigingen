import json

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


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
        self._validate_role_mapping()

    def _validate_role_mapping(self):
        """Validate role mapping child table entries."""
        if not self.role_mapping:
            return

        seen_roles = set()
        for row in self.role_mapping:
            if row.mijnrood_role in seen_roles:
                frappe.throw(_("Duplicate MijnRood role '{0}' in row {1}").format(row.mijnrood_role, row.idx))
            seen_roles.add(row.mijnrood_role)

            if row.add_to_chapter_board and not row.chapter_role:
                frappe.throw(
                    _(
                        "Row {0} ({1}): 'Toevoegen aan Afdelingsbestuur' is checked but no Bestuursrol is set"
                    ).format(row.idx, row.mijnrood_role)
                )

            if row.verenigingen_role and not row.create_volunteer:
                frappe.throw(
                    _(
                        "Row {0} ({1}): Verenigingen Rol is set but 'Maak Vrijwilliger Aan' is not checked. "
                        "A user account (via Volunteer creation) is needed to assign a role."
                    ).format(row.idx, row.mijnrood_role)
                )

            if row.verenigingen_role and not frappe.db.exists("Role", row.verenigingen_role):
                frappe.throw(
                    _("Row {0} ({1}): Verenigingen Rol '{2}' does not exist").format(
                        row.idx, row.mijnrood_role, row.verenigingen_role
                    )
                )

            if row.chapter_role and not frappe.db.exists("Chapter Role", row.chapter_role):
                frappe.throw(
                    _("Row {0} ({1}): Bestuursrol '{2}' does not exist").format(
                        row.idx, row.mijnrood_role, row.chapter_role
                    )
                )

            if row.add_to_team and not row.default_team:
                frappe.throw(
                    _("Row {0} ({1}): 'Toevoegen aan Team' is checked but no Team is set").format(
                        row.idx, row.mijnrood_role
                    )
                )

            if row.default_team and not frappe.db.exists("Team", row.default_team):
                frappe.throw(
                    _("Row {0} ({1}): Team '{2}' does not exist").format(
                        row.idx, row.mijnrood_role, row.default_team
                    )
                )

            if row.add_to_team and not row.create_volunteer:
                frappe.throw(
                    _(
                        "Row {0} ({1}): 'Toevoegen aan Team' requires 'Maak Vrijwilliger Aan' "
                        "to be checked (Volunteer record is needed for team membership)"
                    ).format(row.idx, row.mijnrood_role)
                )

            if row.mijnrood_role == "ROLE_ADMIN" and row.add_to_chapter_board:
                frappe.msgprint(
                    _(
                        "Row {0} (ROLE_ADMIN): 'Toevoegen aan Afdelingsbestuur' is enabled but global admins "
                        "are not tied to a specific chapter. This setting will have no effect for ROLE_ADMIN."
                    ),
                    indicator="orange",
                    alert=True,
                )

    def _validate_status_mapping(self):
        """Validate status mapping child table entries."""
        if not self.status_mapping:
            return

        seen_ids = set()
        for row in self.status_mapping:
            if row.mijnrood_status_id in seen_ids:
                frappe.throw(_("Duplicate Status ID {0} in row {1}").format(row.mijnrood_status_id, row.idx))
            seen_ids.add(row.mijnrood_status_id)

            if row.is_active and not row.verenigingen_membership_type:
                frappe.msgprint(
                    _(
                        "Row {0} (Status ID {1}, '{2}'): active status has no Verenigingen Lidmaatschapstype set. "
                        "The sync will fall back to pattern-matching."
                    ).format(row.idx, row.mijnrood_status_id, row.label),
                    indicator="yellow",
                    alert=True,
                )

            if not row.is_active and not row.termination_type:
                frappe.msgprint(
                    _("Row {0} (Status ID {1}): non-active status has no termination type set").format(
                        row.idx, row.mijnrood_status_id
                    ),
                    indicator="orange",
                    alert=True,
                )

    def on_update(self):
        """Clear cached mappings when settings change."""
        frappe.cache.delete_value("mijnrood_status_mapping")
        frappe.cache.delete_value("mijnrood_role_mapping")

    @frappe.whitelist()
    def fetch_lidmaatschapstypes_from_mijnrood(self):
        """Fetch membership statuses from MijnRood's admin_membershipstatus table.

        Merges fetched data into the child table:
        - Existing rows (by mijnrood_status_id): updates label, membership_type_string,
          allows_login, and is_active (unless admin has set an explicit membership type).
          Preserves admin-configured verenigingen_membership_type and termination_type.
        - New rows: appended with is_active guessed from allowed_access.
        """
        from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

        # Rate limit: max once per 60 seconds
        rate_key = "mijnrood_fetch_lidmaatschapstypes_ratelimit"
        if frappe.cache.get_value(rate_key):
            return {"success": False, "message": _("Please wait at least 60 seconds between fetches")}

        client = MijnRoodDatabaseClient(settings=self)
        try:
            with client:
                statuses = client.fetch_membership_statuses()
        except Exception as e:
            error_msg = str(e)[:500]
            frappe.log_error(frappe.get_traceback(), "MijnRood Fetch Lidmaatschapstypes Failed")
            return {"success": False, "message": _("Connection failed: {0}").format(error_msg)}

        if not statuses:
            return {"success": False, "message": _("No membership statuses found in MijnRood")}

        # Build lookup of existing rows by status ID
        existing = {}
        for row in self.status_mapping or []:
            existing[row.mijnrood_status_id] = row

        updated = 0
        created = 0
        skipped = 0
        seen_ids = set()
        for status in statuses:
            status_id = status.get("id")
            name = (status.get("name") or "").strip()

            # Skip rows with missing ID or name (required fields)
            if status_id is None or not name:
                skipped += 1
                continue

            # Skip duplicates from MijnRood data
            if status_id in seen_ids:
                skipped += 1
                continue
            seen_ids.add(status_id)

            allowed_access = bool(status.get("allowed_access"))

            if status_id in existing:
                row = existing[status_id]
                row.label = name
                row.membership_type_string = name
                row.allows_login = 1 if allowed_access else 0
                # Update is_active from MijnRood unless admin has configured
                # an explicit membership type (indicating deliberate override)
                if not row.verenigingen_membership_type:
                    row.is_active = 1 if allowed_access else 0
                # Preserve: verenigingen_membership_type, termination_type
                updated += 1
            else:
                self.append(
                    "status_mapping",
                    {
                        "mijnrood_status_id": status_id,
                        "label": name,
                        "membership_type_string": name,
                        "is_active": 1 if allowed_access else 0,
                        "allows_login": 1 if allowed_access else 0,
                        "termination_type": "" if allowed_access else "Administrative",
                    },
                )
                created += 1

        try:
            self.save()
        finally:
            # Always invalidate cache — even if save fails, in-memory rows
            # were modified and the cache must not serve stale data.
            frappe.cache.delete_value("mijnrood_status_mapping")

        frappe.cache.set_value(rate_key, "1", expires_in_sec=60)

        message = _("Fetched {0} statuses from MijnRood ({1} updated, {2} new)").format(
            len(statuses), updated, created
        )
        if skipped:
            message += _("; {0} skipped (missing ID/name or duplicate)").format(skipped)
        return {"success": True, "message": message}

    @frappe.whitelist()
    def populate_default_status_mapping(self):
        """Load default status mapping values into the child table.

        Fallback for when MijnRood is not reachable.
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
            self.append(
                "status_mapping",
                {
                    "mijnrood_status_id": status_id,
                    "label": _DEFAULT_STATUS_ID_LABELS.get(status_id, type_string),
                    "membership_type_string": type_string,
                    "is_active": 1 if status_id in _DEFAULT_ACTIVE_STATUS_IDS else 0,
                    "termination_type": _DEFAULT_STATUS_ID_TO_TERMINATION_TYPE.get(status_id, ""),
                    "allows_login": 1 if status_id in _DEFAULT_ACTIVE_STATUS_IDS else 0,
                },
            )

        self.save()
        return {
            "success": True,
            "message": _("Loaded {0} default status mappings").format(len(self.status_mapping)),
        }

    @frappe.whitelist()
    def populate_default_role_mapping(self):
        """Load default role mapping values into the child table.

        Pre-populates ROLE_ADMIN and ROLE_DIVISION_CONTACT with recommended defaults.
        ROLE_ADMIN is configured to add members to the "Secretariaat" team (created
        automatically if it doesn't exist). Admin can adjust all settings afterwards.
        Only populates if the table is empty to avoid overwriting customizations.
        """
        if self.role_mapping:
            frappe.throw(_("Role mapping table is not empty. Clear it first to reload defaults."))

        # Ensure the Secretariaat team exists for ROLE_ADMIN default
        secretariaat_team = self._ensure_secretariaat_team()

        defaults = [
            {
                "mijnrood_role": "ROLE_ADMIN",
                "label": "Landelijk Beheerder",
                "create_volunteer": 1,
                "add_to_chapter_board": 0,
                "add_to_team": 1,
                "default_team": secretariaat_team,
            },
            {
                "mijnrood_role": "ROLE_DIVISION_CONTACT",
                "label": "Afdelingscontact",
                "create_volunteer": 0,
                "add_to_chapter_board": 0,
            },
        ]

        for row_data in defaults:
            self.append("role_mapping", row_data)

        self.save()
        frappe.cache.delete_value("mijnrood_role_mapping")
        return {
            "success": True,
            "message": _("Loaded {0} default role mappings").format(len(self.role_mapping)),
        }

    def _ensure_secretariaat_team(self):
        """Create the Secretariaat team if it doesn't already exist.

        Returns:
            str: The team name ("Secretariaat").
        """
        team_name = "Secretariaat"
        if not frappe.db.exists("Team", team_name):
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": team_name,
                    "description": _("National administration team for MijnRood administrators."),
                    "status": "Active",
                    "is_association_wide": 1,
                }
            )
            team.insert()
            frappe.logger().info(f"Created default Secretariaat team: {team.name}")
        return team_name

    @frappe.whitelist()
    def fetch_document_folders(self):
        """Fetch document folders from MijnRood and populate the mapping table.

        Connects to MijnRood DB, fetches root-level folders from
        admin_document_folder, and populates the document_folder_mapping
        child table. Admin then configures organization_type + entity +
        document_type for each folder.
        """
        from verenigingen.mijnrood_sync.services.document_import_service import DocumentImportService

        # Rate limit: max once per 60 seconds
        rate_key = "mijnrood_fetch_document_folders_ratelimit"
        if frappe.cache.get_value(rate_key):
            return {"success": False, "message": _("Please wait at least 60 seconds between fetches")}

        service = DocumentImportService(settings=self)
        result = service.fetch_and_populate_folders()

        if result.get("success"):
            frappe.cache.set_value(rate_key, "1", expires_in_sec=60)

        return result

    @frappe.whitelist()
    def import_documents(self):
        """Enqueue a background job to import documents from MijnRood.

        Downloads files via SFTP and creates Organization Document records.
        Progress is published via frappe.realtime.
        """
        # Validate that mappings are configured
        configured = [
            row for row in (self.document_folder_mapping or []) if row.organization_type and row.document_type
        ]
        if not configured:
            return {
                "success": False,
                "message": _(
                    "No folder mappings configured. Fetch folders and set organization/document types first."
                ),
            }

        frappe.enqueue(
            "verenigingen.mijnrood_sync.services.document_import_service.import_all",
            queue="long",
            timeout=3600,
            job_name="mijnrood_document_import",
        )

        self.db_set("document_import_status", _("Import job enqueued"))
        frappe.db.commit()
        return {
            "success": True,
            "message": _("Document import job enqueued. Check progress in the Import Status field."),
        }


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
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
