"""
VIP Import DocType

Handles import of volunteer data from Volunteer Information Portal (VIP) exports.
Creates/updates Volunteer records linked to existing Members.

Import Flow:
1. Upload CSV file → Validate → Preview
2. Submit form → Queue background job
3. Background job processes rows in batches
4. Progress updates visible in real-time
"""

import json
import re
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, today

from verenigingen.utils.account_creation_manager import queue_bulk_account_creation_for_members
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.csv.vip_data_validator import VIPDataValidator
from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor
from verenigingen.utils.security.api_security_framework import OperationType, critical_api

# ==================== CONSTANTS ====================
# Import processing limits
MAX_FILE_SIZE_MB = 10
TEST_MODE_ROW_LIMIT = 25
BATCH_SIZE = 50
BACKGROUND_JOB_TIMEOUT = 3600  # 1 hour
MAX_ERRORS_TO_LOG = 100
MAX_SKIPPED_TO_LOG = 20

# PII patterns for sanitization
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"\+?\d{10,15}|\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}")


def _sanitize_error_message(message: str) -> str:
    """
    Sanitize PII (email addresses, phone numbers) from error messages.

    Args:
        message: Error message that may contain PII

    Returns:
        Sanitized message with PII redacted
    """
    sanitized = _EMAIL_PATTERN.sub("[EMAIL REDACTED]", message)
    sanitized = _PHONE_PATTERN.sub("[PHONE REDACTED]", sanitized)
    return sanitized


def _check_duplicate_vip_id(vip_user_id: str, mapped_data: List[Dict]) -> List[str]:
    """
    Check for duplicate VIP User IDs within the import data.

    Args:
        vip_user_id: VIP User ID to check
        mapped_data: List of mapped row data

    Returns:
        List of error messages for duplicates found
    """
    errors = []
    vip_ids_seen = {}

    for row in mapped_data:
        row_vip_id = row.get("vip_user_id")
        if not row_vip_id:
            continue

        row_num = row.get("row_number", "?")

        if row_vip_id in vip_ids_seen:
            errors.append(
                f"Row {row_num}: Duplicate VIP User ID '{row_vip_id}' - also found in row {vip_ids_seen[row_vip_id]}"
            )
        else:
            vip_ids_seen[row_vip_id] = row_num

    return errors


class VIPImport(Document):
    """
    VIP Import DocType for importing Volunteer Information Portal data.

    Workflow:
    1. User uploads CSV file
    2. User clicks "Validate CSV" → validation runs, preview shown
    3. User reviews preview and clicks "Process Import" (submit)
    4. Background job processes rows and updates progress
    """

    def validate(self):
        """Validate document before save."""
        if not self.import_date:
            self.import_date = today()

        if self.is_new():
            self.import_status = "Pending"

        # Validate file size
        if self.csv_file:
            self._validate_file_size()

    def _validate_file_size(self):
        """Validate uploaded file size doesn't exceed limit."""
        import os

        try:
            file_doc = frappe.get_doc("File", {"file_url": self.csv_file})
            file_path = file_doc.get_full_path()

            if os.path.exists(file_path):
                file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                if file_size_mb > MAX_FILE_SIZE_MB:
                    frappe.throw(
                        _("File size ({0:.2f} MB) exceeds maximum allowed size ({1} MB)").format(
                            file_size_mb, MAX_FILE_SIZE_MB
                        )
                    )
        except frappe.DoesNotExistError:
            pass  # File document not found yet - will be validated on process

    def on_submit(self):
        """Queue background import job when document is submitted."""
        if self.import_status not in ["Ready for Import", "Pending"]:
            frappe.throw(
                _(
                    "Import status must be 'Ready for Import' or 'Pending' to process. Current status: {0}"
                ).format(self.import_status)
            )

        # Queue background job
        self.db_set("import_status", "Queued")
        frappe.db.commit()

        frappe.enqueue(
            "verenigingen.verenigingen.doctype.vip_import.vip_import.process_import_background",
            queue="long",
            timeout=BACKGROUND_JOB_TIMEOUT,
            import_doc_name=self.name,
            test_mode=bool(self.test_mode),
        )

        frappe.msgprint(
            _("VIP Import has been queued for processing. You can monitor progress on this page."),
            indicator="blue",
        )


# ==================== HELPER FUNCTIONS ====================


def _find_member(row: Dict) -> Optional[Document]:
    """
    Find existing Member by cascade matching.

    Matching order:
    1. member_id (nvv_relatie_nummer)
    2. procurios_id (alternate member ID source)
    3. personal_email (private_email)
    4. organization_email (email)

    Args:
        row: Mapped row data from validator

    Returns:
        Member document or None if not found
    """
    # Try member_id first (from nvv_relatie_nummer)
    if row.get("member_id"):
        member_name = frappe.db.get_value("Member", {"member_id": row["member_id"]}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)

    # Try procurios_id as alternate member_id lookup
    if row.get("procurios_id"):
        member_name = frappe.db.get_value("Member", {"member_id": row["procurios_id"]}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)

    # Try personal email
    if row.get("personal_email"):
        member_name = frappe.db.get_value("Member", {"email": row["personal_email"]}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)

    # Try organization email
    if row.get("organization_email"):
        member_name = frappe.db.get_value("Member", {"email": row["organization_email"]}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)

    return None


def _find_volunteer(row: Dict, member: Optional[Document]) -> Optional[Document]:
    """
    Find existing Volunteer record.

    Matching order:
    1. vip_user_id
    2. member link (member.volunteer_record)
    3. member field on Volunteer
    4. organization_email

    Args:
        row: Mapped row data from validator
        member: Member document (may be None)

    Returns:
        Volunteer document or None if not found
    """
    # Try vip_user_id first
    if row.get("vip_user_id"):
        vol_name = frappe.db.get_value("Volunteer", {"vip_user_id": row["vip_user_id"]}, "name")
        if vol_name:
            return frappe.get_doc("Volunteer", vol_name)

    # Try member's volunteer_record link
    if member and member.get("volunteer_record"):
        return frappe.get_doc("Volunteer", member.volunteer_record)

    # Try finding by member field
    if member:
        vol_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        if vol_name:
            return frappe.get_doc("Volunteer", vol_name)

    # Try organization email
    if row.get("organization_email"):
        vol_name = frappe.db.get_value("Volunteer", {"email": row["organization_email"]}, "name")
        if vol_name:
            return frappe.get_doc("Volunteer", vol_name)

    return None


def _create_member(row: Dict) -> Document:
    """
    Create a new Member record from VIP data.

    Args:
        row: Mapped row data from validator

    Returns:
        Created Member document
    """
    member = frappe.new_doc("Member")

    # Required fields
    member.first_name = row.get("first_name", "Unknown")
    member.last_name = row.get("last_name", "Unknown")

    # Optional fields
    if row.get("personal_email"):
        member.email = row["personal_email"]
    elif row.get("organization_email"):
        member.email = row["organization_email"]

    if row.get("contact_number"):
        member.contact_number = row["contact_number"]

    if row.get("member_id"):
        member.member_id = row["member_id"]

    # Set status to Active for new members
    member.status = "Active"
    member.member_since = row.get("start_date") or today()

    # Skip volunteer auto-creation during bulk import
    member.flags.bulk_member_operations = True

    # Bulk import operation - permissions validated at API level via @critical_api decorator
    # User must have VIP Import create/submit permission to reach this code path
    member.insert(ignore_permissions=True)
    return member


def _validate_volunteer_age(member: Document) -> Optional[str]:
    """
    Validate that member meets minimum volunteer age requirement.

    Uses the minimum_volunteer_age setting from Verenigingen Settings.

    Args:
        member: Member document to validate

    Returns:
        Error message if validation fails, None if valid
    """
    from frappe.utils import date_diff, getdate

    if not member.get("birth_date"):
        return None  # Can't validate without birth date

    try:
        settings = frappe.get_cached_doc("Verenigingen Settings")
        min_volunteer_age = settings.get("minimum_volunteer_age") or 16
    except Exception:
        min_volunteer_age = 16

    age_in_days = date_diff(today(), member.birth_date)
    age_in_years = age_in_days / 365.25

    if age_in_years < min_volunteer_age:
        return f"Member must be at least {min_volunteer_age} years old to be a volunteer (current age: {int(age_in_years)})"

    return None


def _create_volunteer(row: Dict, member: Document, import_batch_name: Optional[str] = None) -> Document:
    """
    Create a new Volunteer record.

    Args:
        row: Mapped row data from validator
        member: Member document to link
        import_batch_name: Name of the VIP Import document for batch tracking

    Returns:
        Created Volunteer document

    Raises:
        frappe.ValidationError: If member doesn't meet age requirement
    """
    # Validate volunteer age requirement
    age_error = _validate_volunteer_age(member)
    if age_error:
        frappe.throw(_(age_error))

    volunteer = frappe.new_doc("Volunteer")

    # Set name from member
    volunteer.volunteer_name = member.full_name or f"{member.first_name} {member.last_name}"
    volunteer.member = member.name

    # Organization email (from VIP)
    if row.get("organization_email"):
        volunteer.email = row["organization_email"]

    # VIP IDs
    if row.get("vip_user_id"):
        volunteer.vip_user_id = str(row["vip_user_id"])

    if row.get("google_workspace_id"):
        volunteer.google_workspace_id = row["google_workspace_id"]

    # Import batch tracking
    if import_batch_name:
        volunteer.vip_import_batch = import_batch_name

    # Status
    volunteer.status = row.get("volunteer_status", "Active")

    # Start date
    if row.get("start_date"):
        volunteer.start_date = row["start_date"]
    else:
        volunteer.start_date = today()

    # Notes
    notes_parts = []
    if row.get("notes"):
        notes_parts.append(row["notes"])
    if row.get("status_notes"):
        notes_parts.append(f"[Status Notes]: {row['status_notes']}")
    if notes_parts:
        volunteer.note = "\n\n".join(notes_parts)

    # Skip account creation during bulk import
    volunteer.flags.bulk_member_operations = True
    volunteer.flags.skip_volunteer_account_creation = True

    # Bulk import operation - permissions validated at API level via @critical_api decorator
    # User must have VIP Import create/submit permission to reach this code path
    volunteer.insert(ignore_permissions=True)

    # Update member's volunteer_record link with race condition protection
    # Re-check current state before updating to avoid overwriting concurrent updates
    current_volunteer_record = frappe.db.get_value("Member", member.name, "volunteer_record")
    if not current_volunteer_record:
        frappe.db.set_value("Member", member.name, "volunteer_record", volunteer.name, update_modified=False)

    return volunteer


def _update_volunteer(
    volunteer: Document, row: Dict, member: Document, import_batch_name: Optional[str] = None
) -> Document:
    """
    Update an existing Volunteer record with VIP data.

    Args:
        volunteer: Existing Volunteer document
        row: Mapped row data from validator
        member: Member document
        import_batch_name: Name of the VIP Import document for batch tracking

    Returns:
        Updated Volunteer document
    """
    changed = False

    # Update VIP IDs if not set
    if row.get("vip_user_id") and not volunteer.vip_user_id:
        volunteer.vip_user_id = str(row["vip_user_id"])
        changed = True

    if row.get("google_workspace_id") and not volunteer.google_workspace_id:
        volunteer.google_workspace_id = row["google_workspace_id"]
        changed = True

    # Update import batch tracking
    if import_batch_name:
        volunteer.vip_import_batch = import_batch_name
        changed = True

    # Update organization email if not set
    if row.get("organization_email") and not volunteer.email:
        volunteer.email = row["organization_email"]
        changed = True

    # Update status
    if row.get("volunteer_status"):
        volunteer.status = row["volunteer_status"]
        changed = True

    # Update start_date if not set
    if row.get("start_date") and not volunteer.start_date:
        volunteer.start_date = row["start_date"]
        changed = True

    # Append notes
    if row.get("notes") or row.get("status_notes"):
        notes_parts = []
        if volunteer.note:
            notes_parts.append(volunteer.note)

        import_note = f"\n\n--- VIP Import {today()} ---\n"
        if row.get("notes"):
            import_note += row["notes"]
        if row.get("status_notes"):
            import_note += f"\n[Status Notes]: {row['status_notes']}"

        notes_parts.append(import_note)
        volunteer.note = "".join(notes_parts)
        changed = True

    # Update member link if not set
    if not volunteer.member and member:
        volunteer.member = member.name
        changed = True

    if changed:
        volunteer.flags.bulk_member_operations = True
        volunteer.flags.skip_volunteer_account_creation = True
        # Bulk import operation - permissions validated at API level via @critical_api decorator
        # User must have VIP Import create/submit permission to reach this code path
        volunteer.save(ignore_permissions=True)

    # Update member's volunteer_record link with race condition protection
    # Re-check current state before updating to avoid overwriting concurrent updates
    if member:
        current_volunteer_record = frappe.db.get_value("Member", member.name, "volunteer_record")
        if not current_volunteer_record:
            frappe.db.set_value(
                "Member", member.name, "volunteer_record", volunteer.name, update_modified=False
            )

    return volunteer


# ==================== ROW PROCESSING ====================


def _process_single_row(row: Dict, import_doc: Document, stats: Dict) -> Dict[str, Any]:
    """
    Process a single row from the VIP import.

    Args:
        row: Mapped row data from validator
        import_doc: VIP Import document
        stats: Statistics dictionary to update

    Returns:
        Result dictionary with status and details
    """
    row_num = row.get("row_number", "?")

    try:
        # Find existing Member
        member = _find_member(row)

        if not member:
            if import_doc.create_members_if_missing:
                member = _create_member(row)
                stats["members_created"] += 1
            else:
                stats["members_not_found"] += 1
                return {
                    "status": "skipped",
                    "reason": "member_not_found",
                    "row": row_num,
                    "identifier": row.get("member_id") or row.get("organization_email"),
                }

        # Find existing Volunteer
        volunteer = _find_volunteer(row, member)

        if volunteer:
            # Handle based on duplicate_handling setting
            if import_doc.duplicate_handling == "Skip existing":
                stats["volunteers_skipped"] += 1
                return {
                    "status": "skipped",
                    "reason": "volunteer_exists",
                    "row": row_num,
                    "volunteer": volunteer.name,
                }
            else:
                # Update existing with import batch tracking
                _update_volunteer(volunteer, row, member, import_batch_name=import_doc.name)
                stats["volunteers_updated"] += 1
                return {
                    "status": "updated",
                    "row": row_num,
                    "volunteer": volunteer.name,
                }
        else:
            # Create new Volunteer with import batch tracking
            volunteer = _create_volunteer(row, member, import_batch_name=import_doc.name)
            stats["volunteers_created"] += 1
            return {
                "status": "created",
                "row": row_num,
                "volunteer": volunteer.name,
            }

    except Exception as e:
        frappe.log_error(
            title=f"VIP Import Row {row_num} Error",
            message=f"Error: {str(e)}\nRow data: {json.dumps(row, default=str)}",
        )
        return {
            "status": "error",
            "row": row_num,
            "error": str(e),
        }


# ==================== SKIPPED ROWS LOGGING ====================


def _format_skip_info(row: Dict, result: Dict[str, Any]) -> Dict[str, str]:
    """
    Format skip information for logging.

    Args:
        row: Original row data from validator
        result: Result dictionary from _process_single_row

    Returns:
        Dict with skip details for categorization
    """
    row_num = result.get("row", "?")
    reason = result.get("reason", "unknown")
    status = result.get("status", "skipped")

    # Build identifier string
    identifiers = []
    if row.get("vip_user_id"):
        identifiers.append(f"VIP ID: {row['vip_user_id']}")
    if row.get("member_id"):
        identifiers.append(f"Member ID: {row['member_id']}")
    if row.get("organization_email"):
        identifiers.append(row["organization_email"])

    # Build name string
    name_parts = []
    if row.get("first_name"):
        name_parts.append(row["first_name"])
    if row.get("last_name"):
        name_parts.append(row["last_name"])
    name = " ".join(name_parts) if name_parts else "Unknown"

    identifier_str = " | ".join(identifiers) if identifiers else "No identifier"

    return {
        "row": row_num,
        "reason": reason,
        "status": status,
        "name": name,
        "identifier": identifier_str,
        "error": result.get("error", ""),
        "volunteer": result.get("volunteer", ""),
    }


def _generate_skipped_rows_log(skipped_rows: List[Dict[str, str]]) -> str:
    """
    Generate an itemized list of skipped rows, categorized by reason.

    Similar to MijnRood's _generate_itemized_member_list but adapted for VIP import.

    Args:
        skipped_rows: List of skip info dicts from _format_skip_info

    Returns:
        Formatted string for the skipped_rows_log field
    """
    if not skipped_rows:
        return ""

    output = []
    output.append("## Skipped Rows Detail\n")

    # Categorize by reason
    categories = {
        "Member Not Found": [],
        "Volunteer Already Exists": [],
        "Processing Errors": [],
        "Other": [],
    }

    for skip_info in skipped_rows:
        reason = skip_info.get("reason", "unknown")
        status = skip_info.get("status", "skipped")
        row_num = skip_info.get("row", "?")
        name = skip_info.get("name", "Unknown")
        identifier = skip_info.get("identifier", "")
        error = skip_info.get("error", "")
        volunteer = skip_info.get("volunteer", "")

        # Format the entry
        if reason == "member_not_found":
            entry = f"Row {row_num}: {name} ({identifier})"
            categories["Member Not Found"].append(entry)
        elif reason == "volunteer_exists":
            entry = f"Row {row_num}: {name} - existing volunteer: {volunteer}"
            categories["Volunteer Already Exists"].append(entry)
        elif status == "error":
            # Sanitize error message
            sanitized_error = _sanitize_error_message(error) if error else "Unknown error"
            entry = f"Row {row_num}: {name} - {sanitized_error[:100]}"
            categories["Processing Errors"].append(entry)
        else:
            entry = f"Row {row_num}: {name} ({identifier}) - {reason}"
            categories["Other"].append(entry)

    # Generate output for each non-empty category
    for category, entries in categories.items():
        if entries:
            output.append(f"\n### {category} ({len(entries)} rows):\n")
            for entry in entries[:50]:  # Limit to first 50 per category
                output.append(f"- {entry}")
            if len(entries) > 50:
                output.append(f"- ... and {len(entries) - 50} more")

    return "\n".join(output) if output else ""


# ==================== ACCOUNT CREATION ====================


def _process_account_creation(
    import_doc: Document, processed_volunteers: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Queue account creation requests for Active volunteers only.

    This upgrades existing user accounts (created during membership approval) to
    Volunteer role profiles and creates Employee records for expense functionality.

    Volunteers with Inactive or Retired status are skipped as they should not get
    upgraded role profiles or employee records.

    Args:
        import_doc: VIP Import document
        processed_volunteers: List of dicts with volunteer processing results
            Each dict has: status, row, volunteer (name), volunteer_status

    Returns:
        Dict with account creation summary:
        {
            "active_volunteers_queued": int,
            "inactive_skipped": int,
            "acrs_created": int,
            "users_linked": int,
            "tracker_name": str or None,
            "error": str or None
        }
    """
    result = {
        "active_volunteers_queued": 0,
        "inactive_skipped": 0,
        "acrs_created": 0,
        "users_linked": 0,
        "tracker_name": None,
        "error": None,
    }

    try:
        # Filter to only Active volunteers that were created or updated
        active_member_names = []

        for vol_result in processed_volunteers:
            if vol_result.get("status") not in ("created", "updated"):
                continue

            volunteer_name = vol_result.get("volunteer")
            if not volunteer_name:
                continue

            # Get volunteer status
            volunteer_status = frappe.db.get_value("Volunteer", volunteer_name, "status")

            if volunteer_status == "Active":
                # Get the linked member
                member_name = frappe.db.get_value("Volunteer", volunteer_name, "member")
                if member_name:
                    active_member_names.append(member_name)
                    result["active_volunteers_queued"] += 1
            else:
                # Inactive, Retired, or other non-active status - skip account upgrade
                result["inactive_skipped"] += 1
                frappe.logger().debug(
                    f"[VIP Import] Skipping account creation for {volunteer_name} "
                    f"(status: {volunteer_status})"
                )

        if not active_member_names:
            frappe.logger().info("[VIP Import] No active volunteers to process for account creation")
            return result

        frappe.logger().info(
            f"[VIP Import] Queuing account creation for {len(active_member_names)} active volunteers "
            f"({result['inactive_skipped']} inactive/retired skipped)"
        )

        # Queue account creation with Volunteer role profile and employee creation
        acr_result = queue_bulk_account_creation_for_members(
            member_names=active_member_names,
            roles=["Verenigingen Member", "Verenigingen Volunteer"],
            role_profile="Verenigingen Volunteer",
            batch_size=50,
            priority="Low",
            create_employee=True,  # Volunteers need Employee records for expenses
        )

        if acr_result.get("success"):
            result["acrs_created"] = acr_result.get("requests_created", 0)
            result["users_linked"] = acr_result.get("users_linked", 0)
            result["tracker_name"] = acr_result.get("tracker_name")

            frappe.logger().info(
                f"[VIP Import] Account creation queued: {result['acrs_created']} ACRs created, "
                f"{result['users_linked']} users linked, tracker: {result['tracker_name']}"
            )
        else:
            result["error"] = acr_result.get("error", "Unknown error during account creation")
            frappe.log_error(
                f"VIP Import account creation failed: {result['error']}",
                "VIP Import Account Creation Error",
            )

    except Exception as e:
        result["error"] = str(e)
        frappe.log_error(
            f"VIP Import account creation error: {str(e)}\n{frappe.get_traceback()}",
            "VIP Import Account Creation Error",
        )

    return result


# ==================== BACKGROUND JOB ====================


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_import_background(import_doc_name: str, test_mode: bool = False):
    """
    Background job to process VIP import.

    Args:
        import_doc_name: Name of the VIP Import document
        test_mode: If True, only process first TEST_MODE_ROW_LIMIT rows
    """
    import_doc = frappe.get_doc("VIP Import", import_doc_name)

    try:
        # Set status to In Progress
        import_doc.db_set("import_status", "In Progress")
        frappe.db.commit()

        # Set bulk operation flag
        frappe.flags.bulk_member_operations = True

        # Read CSV file
        parser = SecureCSVParser(encoding=import_doc.encoding)
        csv_data = parser.read_csv_file(import_doc.csv_file)

        if not csv_data:
            import_doc.db_set("import_status", "Failed")
            import_doc.db_set("error_log", "CSV file is empty or could not be parsed")
            frappe.db.commit()
            return

        # Validate and map data
        validator = VIPDataValidator()
        mapped_data, validation_errors, skipped_reasons = validator.validate_and_map_data(
            csv_data, skip_delegated=bool(import_doc.skip_delegated_accounts)
        )

        if not mapped_data:
            import_doc.db_set("import_status", "Failed")
            import_doc.db_set(
                "error_log",
                "No valid rows to import.\n\nValidation errors:\n" + "\n".join(validation_errors[:50]),
            )
            frappe.db.commit()
            return

        # Limit rows in test mode
        if test_mode:
            mapped_data = mapped_data[:TEST_MODE_ROW_LIMIT]

        # Initialize stats
        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }
        errors = []
        processed_volunteers = []  # Track for account creation
        skipped_rows = []  # Track skipped rows for detailed logging
        total_rows = len(mapped_data)

        import_doc.db_set("total_rows", total_rows)
        frappe.db.commit()

        # Process rows in batches
        batch_size = BATCH_SIZE
        for i, row in enumerate(mapped_data):
            result = _process_single_row(row, import_doc, stats)

            # Track volunteer results for account creation
            if result.get("status") in ("created", "updated"):
                processed_volunteers.append(result)

            # Track skipped rows for detailed logging
            if result.get("status") == "skipped":
                skip_info = _format_skip_info(row, result)
                skipped_rows.append(skip_info)

            if result.get("status") == "error":
                errors.append(f"Row {result['row']}: {result['error']}")
                # Also track errors in skipped rows
                skip_info = _format_skip_info(row, result)
                skipped_rows.append(skip_info)

            # Update progress every batch_size rows
            if (i + 1) % batch_size == 0 or (i + 1) == total_rows:
                _update_progress(import_doc_name, i + 1, total_rows, stats)
                frappe.db.commit()

        # Process account creation for Active volunteers
        acr_result = _process_account_creation(import_doc, processed_volunteers)

        # Finalize
        import_doc.reload()
        import_doc.db_set("import_status", "Completed")
        import_doc.db_set("volunteers_created", stats["volunteers_created"])
        import_doc.db_set("volunteers_updated", stats["volunteers_updated"])
        import_doc.db_set("volunteers_skipped", stats["volunteers_skipped"])
        import_doc.db_set("members_not_found", stats["members_not_found"])
        import_doc.db_set("members_created", stats["members_created"])

        # Set account creation tracking fields
        import_doc.db_set("acrs_created", acr_result.get("acrs_created", 0))
        import_doc.db_set("acrs_queued_for_active", acr_result.get("active_volunteers_queued", 0))
        import_doc.db_set("users_upgraded", acr_result.get("users_linked", 0))
        if acr_result.get("tracker_name"):
            import_doc.db_set("bulk_operation_tracker", acr_result["tracker_name"])

        # Set skipped rows log
        if skipped_rows:
            skipped_rows_log = _generate_skipped_rows_log(skipped_rows)
            import_doc.db_set("skipped_rows_log", skipped_rows_log)

        # Set summary
        summary_parts = [
            f"Import completed at {now_datetime()}",
            f"Volunteers created: {stats['volunteers_created']}",
            f"Volunteers updated: {stats['volunteers_updated']}",
            f"Volunteers skipped: {stats['volunteers_skipped']}",
        ]
        if stats["members_created"] > 0:
            summary_parts.append(f"Members created: {stats['members_created']}")
        if stats["members_not_found"] > 0:
            summary_parts.append(f"Members not found: {stats['members_not_found']}")

        # Add account creation summary
        if acr_result.get("active_volunteers_queued", 0) > 0:
            summary_parts.append("")
            summary_parts.append("--- Account Creation ---")
            summary_parts.append(f"Active volunteers queued: {acr_result['active_volunteers_queued']}")
            if acr_result.get("inactive_skipped", 0) > 0:
                summary_parts.append(f"Inactive/Retired skipped: {acr_result['inactive_skipped']}")
            if acr_result.get("acrs_created", 0) > 0:
                summary_parts.append(f"Account creation requests: {acr_result['acrs_created']}")
            if acr_result.get("users_linked", 0) > 0:
                summary_parts.append(f"Users linked (already had accounts): {acr_result['users_linked']}")
            if acr_result.get("tracker_name"):
                summary_parts.append(f"Progress tracker: {acr_result['tracker_name']}")
        elif acr_result.get("inactive_skipped", 0) > 0:
            summary_parts.append("")
            summary_parts.append("--- Account Creation ---")
            summary_parts.append(
                f"All {acr_result['inactive_skipped']} volunteers have Inactive/Retired status - no account upgrades needed"
            )

        if acr_result.get("error"):
            summary_parts.append(f"Account creation error: {acr_result['error']}")

        import_doc.db_set("import_summary", "\n".join(summary_parts))

        # Set errors (sanitize PII from error messages)
        if errors:
            sanitized_errors = [_sanitize_error_message(e) for e in errors[:MAX_ERRORS_TO_LOG]]
            import_doc.db_set("error_log", "\n".join(sanitized_errors))
            import_doc.db_set("top_errors_summary", f"{len(errors)} errors encountered during import")

        # Include skipped delegated accounts in error log if any (sanitize PII)
        if skipped_reasons:
            current_log = import_doc.error_log or ""
            sanitized_skipped = [_sanitize_error_message(r) for r in skipped_reasons[:MAX_SKIPPED_TO_LOG]]
            delegated_section = "\n\n--- Delegated Accounts Skipped ---\n" + "\n".join(sanitized_skipped)
            import_doc.db_set("error_log", current_log + delegated_section)

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            title=f"VIP Import {import_doc_name} Failed",
            message=frappe.get_traceback(),
        )
        import_doc.db_set("import_status", "Failed")
        import_doc.db_set("error_log", f"Import failed: {str(e)}\n\n{frappe.get_traceback()}")
        frappe.db.commit()

    finally:
        frappe.flags.bulk_member_operations = False


def _update_progress(import_doc_name: str, processed: int, total: int, stats: Dict):
    """
    Update progress fields on the import document.

    Args:
        import_doc_name: Name of the VIP Import document
        processed: Number of rows processed
        total: Total number of rows
        stats: Statistics dictionary
    """
    progress = (processed / total) * 100 if total > 0 else 0

    frappe.db.set_value(
        "VIP Import",
        import_doc_name,
        {
            "progress_percentage": progress,
            "rows_processed": processed,
            "last_processed_at": now_datetime(),
            "volunteers_created": stats["volunteers_created"],
            "volunteers_updated": stats["volunteers_updated"],
            "volunteers_skipped": stats["volunteers_skipped"],
        },
        update_modified=False,
    )


# ==================== API ENDPOINTS ====================


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def validate_import_file(import_doc_name: str) -> Dict[str, Any]:
    """
    Validate a VIP import file and generate preview.

    Args:
        import_doc_name: Name of the VIP Import document

    Returns:
        Dictionary with validation result and preview data
    """
    import_doc = frappe.get_doc("VIP Import", import_doc_name)

    try:
        import_doc.db_set("import_status", "Validating")
        frappe.db.commit()

        # Read CSV file
        parser = SecureCSVParser(encoding=import_doc.encoding)
        csv_data = parser.read_csv_file(import_doc.csv_file)

        if not csv_data:
            import_doc.db_set("import_status", "Failed")
            import_doc.db_set("error_log", "CSV file is empty or could not be parsed")
            frappe.db.commit()
            return {"success": False, "error": "CSV file is empty or could not be parsed"}

        # Validate and generate preview
        validator = VIPDataValidator()
        preview = validator.get_preview_summary(csv_data)

        # Store preview data
        import_doc.db_set("preview_data", json.dumps(preview, indent=2, default=str))
        import_doc.db_set("total_rows", preview["total_rows"])

        if preview["error_rows"] > 0 and preview["valid_rows"] == 0:
            import_doc.db_set("import_status", "Failed")
            import_doc.db_set("error_log", "\n".join(preview.get("sample_errors", [])))
            frappe.db.commit()
            return {
                "success": False,
                "error": "No valid rows found",
                "preview": preview,
            }

        import_doc.db_set("import_status", "Ready for Import")
        frappe.db.commit()

        return {"success": True, "preview": preview}

    except Exception as e:
        import_doc.db_set("import_status", "Failed")
        import_doc.db_set("error_log", f"Validation failed: {str(e)}")
        frappe.db.commit()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.UTILITY)
def get_import_template() -> str:
    """
    Generate a CSV template for VIP import.

    Returns:
        CSV template string
    """
    headers = [
        "id",
        "google_account_ref",
        "nvv_relatie_nummer",
        "email",
        "private_email",
        "first_name",
        "last_name",
        "phone_number",
        "mobile_number",
        "date_joined",
        "status",
        "notes",
        "status_notes",
        "is_delegated_account",
    ]

    sample_row = [
        "123",
        "abc123xyz",
        "12345",
        "volunteer@org.example.com",
        "personal@example.com",
        "Jan",
        "de Vries",
        "+31201234567",
        "+31612345678",
        "2024-01-15",
        "available",
        "Active volunteer since 2024",
        "",
        "false",
    ]

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerow(sample_row)

    return output.getvalue()
