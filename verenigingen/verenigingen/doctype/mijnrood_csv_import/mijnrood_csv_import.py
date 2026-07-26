# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import csv
import io
import json
import os
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, getdate, today

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.services.member.member_lookup_service import get_member_lookup_service
from verenigingen.utils.account_creation_manager import queue_bulk_account_creation_for_members
from verenigingen.utils.csv.csv_data_validator import CSVDataValidator
from verenigingen.utils.csv.data_transformers import (
    calculate_next_invoice_date,
    clean_phone_number,
    clean_value,
    convert_country_code,
    convert_membership_type,
    determine_membership_type_for_csv_import,
    get_dues_schedule_template_from_payment_period,
    map_payment_period_to_billing_frequency,
    parse_date,
)
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.csv_import_processor import (
    CSVImportBackgroundProcessor,
    ensure_bulk_import_members_set,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.utils.safe_member_optimizer import safe_member_optimizer
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
)

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def _sanitize_error_message(message: str) -> str:
    """
    Sanitize PII (email addresses, phone numbers) from error messages.

    Uses centralized sanitize_error_for_audit utility for consistent
    PII redaction across the application.

    Args:
        message: Raw error message that may contain PII

    Returns:
        Sanitized message with PII redacted
    """
    return (
        sanitize_error_for_audit(
            message,
            max_length=1000,
            remove_stack_trace=False,  # Preserve structure for import errors
            redact_pii=True,
        )
        or message
    )


class MijnroodCSVImport(Document):
    """DocType for importing member data from CSV files with validation and preview.

    Why this class does NOT inherit from BaseCSVImport:

    1. The property-cache idiom here uses the explicit-mangled-name form
       (`hasattr(self, "_MijnroodCSVImport__validator")` + `self.__validator = ...`).
       The two Procurios importers use the single-underscore form
       (`hasattr(self, "_validator_instance")` + `self._validator_instance = ...`)
       via BaseCSVImport. Both are correct; they are NOT interchangeable
       because the mangled form embeds this class's name. Do not
       "clean up" the underscores here — switching to the BaseCSVImport
       form would silently break the cache the moment a subclass appears.

    2. This controller is ~2000 LOC of domain orchestration (Account
       Creation Requests, Bulk Volunteer Service, Mollie sync, chapter
       provisioning, atomic tracker linking). A shared base class buys
       little and would have to host carve-outs for every one of those
       concerns.

    See `verenigingen/utils/csv/base_csv_import.py` for the shared
    scaffolding used by the Procurios importers.
    """

    # Lazy-initialized instances to avoid repeated instantiation
    @property
    def _validator(self):
        """Lazy-initialized CSVDataValidator instance."""
        if not hasattr(self, "_MijnroodCSVImport__validator"):
            self.__validator = CSVDataValidator()
        return self.__validator

    @property
    def _parser(self):
        """Lazy-initialized SecureCSVParser instance with document encoding."""
        if not hasattr(self, "_MijnroodCSVImport__parser"):
            self.__parser = SecureCSVParser(encoding=getattr(self, "encoding", None))
        return self.__parser

    def validate(self):
        """Validate the document before saving."""
        # Only do basic validation - no file processing
        if not getattr(self, "import_date", None):
            self.import_date = today()

        # Validate CSV import membership type settings are configured
        if self.docstatus == 1:  # On submit
            self._validate_csv_import_settings()

        # Skip automatic CSV validation - make it manual only
        pass

    def _validate_csv_import_settings(self):
        """Validate that CSV import settings are configured."""
        settings = frappe.get_single("Verenigingen Settings")

        missing_settings = []

        # Check dues schedule templates
        if not settings.csv_monthly_dues_schedule:
            missing_settings.append("CSV Monthly Dues Schedule")

        if not settings.csv_annual_dues_schedule:
            missing_settings.append("CSV Annual Dues Schedule")

        # Check membership type defaults
        if not settings.default_membership_type:
            missing_settings.append("Default Membership Type")

        if missing_settings:
            frappe.throw(
                _(
                    "Cannot start CSV import. Please configure the following in Verenigingen Settings:<br><br>"
                    "<b>{0}</b><br><br>"
                    "Go to: <a href='/app/verenigingen-settings'>Verenigingen Settings</a> → "
                    "Mijnrood CSV Import Settings section"
                ).format("<br>".join(f"• {s}" for s in missing_settings)),
                title=_("Missing CSV Import Configuration"),
            )

    def on_submit(self):
        """Queue the CSV import for background processing."""
        # Queue import as background job (both normal and test mode)
        frappe.enqueue(
            method="verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.process_import_background",
            queue="long",
            timeout=3600,  # 1 hour timeout
            import_doc_name=self.name,
            test_mode=self.test_mode,
            now=False,
        )
        self.import_status = "Queued"
        self.save()
        if self.test_mode:
            frappe.msgprint(
                _("Test import queued (first 25 rows only). You will receive an email when it completes.")
            )
        else:
            frappe.msgprint(
                _("Import queued for background processing. You will receive an email when it completes.")
            )

    def _validate_and_preview_csv(self):
        """Validate CSV file and prepare preview data."""
        try:
            # Read and parse CSV
            csv_data = self._read_csv_file()
            if not csv_data:
                frappe.throw(_("Could not read CSV file or file is empty"))

            # Validate and map fields
            mapped_data, validation_errors = self._validate_and_map_data(csv_data)

            # Set preview data and status
            if validation_errors:
                self.import_status = "Failed"
                self.error_log = "\\n".join(validation_errors)
                frappe.throw(_("CSV validation failed. Check Error Log for details."))
            else:
                self.import_status = "Ready for Import"
                self.preview_data = json.dumps(mapped_data[:5], indent=2, default=str)  # Show first 5 records
                self.descriptive_name = f"Member Import {self.import_date} ({len(mapped_data)} records)"

        except Exception as e:
            self.import_status = "Failed"
            error_msg = str(e)[:500]  # Limit error message length
            self.error_log = f"Validation Error: {error_msg}"
            # Use shorter log title
            frappe.log_error(error_msg, "CSV Import Failed")
            frappe.throw(_("CSV validation failed: {0}").format(error_msg))

    def _read_csv_file(self) -> List[Dict]:
        """Read CSV file and return parsed data using SecureCSVParser."""
        return self._parser.read_csv_file(self.csv_file)

    def _sanitize_filename(self) -> str:
        """Sanitize filename to prevent security issues."""
        return self._parser._sanitize_filename(self.csv_file)

    def _resolve_file_location(self, filename: str) -> Tuple[Optional[str], Optional[bytes]]:
        """Resolve file location using multiple methods."""
        return self._parser._resolve_file_location(self.csv_file, filename)

    def _try_file_document_lookup(self, filename: str) -> Tuple[Optional[str], Optional[bytes]]:
        """Try to find file via Frappe File document lookup."""
        return self._parser._try_file_document_lookup(self.csv_file, filename)

    def _try_direct_path_construction(self, filename: str) -> Optional[str]:
        """Try to construct file path directly using common locations."""
        return self._parser._try_direct_path_construction(filename)

    def _handle_file_not_found(self, filename: str):
        """Handle file not found scenario with helpful debug information."""
        self._parser._handle_file_not_found(self.csv_file, filename)

    def _parse_file_data(
        self, file_path: Optional[str], file_content: Optional[bytes], filename: str
    ) -> List[Dict]:
        """Parse file data based on available file path or content."""
        return self._parser._parse_file_data(file_path, file_content, filename)

    def _is_safe_file_path(self, file_path: str) -> bool:
        """Check if file path is within allowed directories for security."""
        return self._parser.validate_file_path(file_path)

    def _read_file_from_path(self, file_path: str) -> List[Dict]:
        """Read file from file system path."""
        return self._parser._read_file_from_path(file_path)

    def _read_file_from_content(self, file_content: bytes, filename: str) -> List[Dict]:
        """Read file from content bytes."""
        return self._parser._read_file_from_content(file_content, filename)

    def _parse_csv_content(self, csvfile) -> List[Dict]:
        """Parse CSV content from file-like object."""
        return self._parser.parse_csv_content(csvfile)

    def _validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """Validate CSV data and map to Member fields using CSVDataValidator."""
        return self._validator.validate_and_map_data(csv_data)

    def _map_row_data(self, row: Dict, field_mapping: Dict, row_num: int) -> Dict:
        """Map a single row from CSV to Member fields using CSVDataValidator."""
        return self._validator.map_row_data(row, row_num)

    def _validate_row(self, row: Dict, row_num: int) -> List[str]:
        """Validate a single row using CSVDataValidator."""
        return self._validator.validate_row(row, row_num)

    def _is_valid_email(self, email: str) -> bool:
        """Validate email format using CSVDataValidator."""
        return self._validator.validate_email(email)

    def _is_valid_iban(self, iban: str) -> bool:
        """Validate IBAN format using CSVDataValidator."""
        return self._validator.validate_iban(iban)

    def _clean_value(self, value: str, field_type: str) -> Any:
        """Clean and convert values based on field type."""
        return clean_value(value, field_type)

    def _convert_country_code(self, country_code: str) -> str:
        """Convert country codes to full country names."""
        return convert_country_code(country_code)

    def _clean_phone_number(self, phone_number: str) -> str:
        """Clean and normalize phone number format for validation compatibility."""
        return clean_phone_number(phone_number)

    def _convert_membership_type(self, membership_type: str) -> str:
        """Convert Dutch membership types to standardized values."""
        return convert_membership_type(membership_type)

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to YYYY-MM-DD format."""
        return parse_date(date_str)

    def _process_single_member(self, row: Dict, error_log: List[str]) -> tuple:
        """Process a single member with proper error handling and transaction isolation.

        Uses MemberImportService for member creation/update and orchestrates
        related record creation via _create_related_records_via_services.
        """
        from verenigingen.services.csv_import.member_import_service import (
            get_member_import_service,
        )

        try:
            # Use MemberImportService for member creation/update
            service = get_member_import_service()
            result, member_name = service.create_or_update_member(
                row_data=row,
                import_doc_name=self.name,
                create_volunteer_records=self.create_volunteer_records,
            )

            # Create related records if member was successfully created/updated
            if result in ("created", "updated") and member_name:
                related_failures = self._create_related_records_via_services(member_name, row)
                if related_failures:
                    self._append_to_error_log(
                        f"Member {member_name} {result} but with related record issues: "
                        f"{', '.join(related_failures)}"
                    )
            elif result.startswith("failed"):
                # The service returns "failed: <reason>", but the batch processor
                # only buckets non-created/updated statuses into skipped_count and
                # discards the string — so without this the reason dies one frame
                # above where it was produced, and a genuine failure is
                # indistinguishable from a legitimate duplicate skip.
                self._append_to_error_log(f"Row {row.get('row_number', '?')}: {result}")

            return result, member_name
        except frappe.ValidationError as ve:
            # Enhanced error message with row number and field values for debugging
            row_num = row.get("row_number", "?")
            member_id = row.get("member_id", "N/A")
            first_name = row.get("first_name", "N/A")
            last_name = row.get("last_name", "N/A")
            email = row.get("email", "N/A")

            skip_msg = f"Row {row_num}: Validation error - {str(ve)}"
            error_log.append(skip_msg)

            # Only log detailed error for validation errors that aren't categorized and aggregated
            # Skip logging for: dues rate errors (aggregated), phone format errors (noisy)
            error_str = str(ve).lower()
            should_skip_log = any(
                [
                    "dues rate" in error_str
                    and "minimum amount" in error_str,  # Financial validation (aggregated)
                    "not a valid phone number"
                    in error_str,  # Phone format (too noisy, will be in skip summary)
                ]
            )

            if not should_skip_log:
                detailed_error = (
                    f"Row {row_num} validation failed:\n"
                    f"  Error: {str(ve)}\n"
                    f"  Lidnummer: '{member_id}'\n"
                    f"  First Name: '{first_name}'\n"
                    f"  Last Name: '{last_name}'\n"
                    f"  Email: '{email}'"
                )
                frappe.log_error(detailed_error, "CSV Import Row Validation")
            # Return skip info with lidnummer
            return "skipped", f"Lidnr {member_id}: {first_name} {last_name} - {str(ve)[:100]}"
        except frappe.DuplicateEntryError as de:
            member_id = row.get("member_id", "N/A")
            skip_msg = f"Row {row.get('row_number', '?')}: Duplicate entry - {str(de)}"
            error_log.append(skip_msg)
            frappe.log_error(f"Import duplicate error: {str(de)}", "CSV Import Duplicate")
            return "skipped", f"Lidnr {member_id}: Duplicate - {str(de)[:100]}"
        except Exception as e:
            member_id = row.get("member_id", "N/A")
            skip_msg = f"Row {row.get('row_number', '?')}: Unexpected error - {str(e)}"
            error_log.append(skip_msg)
            frappe.log_error(f"Import unexpected error: {str(e)}", "CSV Import Unexpected Error")
            return "skipped", f"Lidnr {member_id}: {str(e)[:100]}"

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        error_log: List[str],
        created_members: List[str] = None,
        updated_members: List[str] = None,
        skipped_members: List[str] = None,
    ):
        """Finalize import results and update document status."""
        self.members_created = created_count
        self.members_updated = updated_count
        self.members_skipped = skipped_count

        # Combine all members for bulk operations
        processed_members = (created_members or []) + (updated_members or [])

        # Bulk operations flag should already be set from _process_import
        # Verify it's still set for the finalization phase
        if not getattr(frappe.flags, "bulk_member_operations", False):
            frappe.logger().warning(
                "[CSV IMPORT DEBUG] bulk_member_operations flag was NOT set during finalization - setting it now"
            )
            frappe.flags.bulk_member_operations = True
        else:
            frappe.logger().info(
                "[CSV IMPORT DEBUG] Confirmed bulk_member_operations flag still set during finalization"
            )

        try:
            # Process bulk operations if enabled
            user_account_summary = ""
            if self.create_user_accounts and processed_members:
                frappe.logger().info(
                    f"[CSV IMPORT] Starting user account creation for {len(processed_members)} members"
                )
                user_account_summary = self._process_user_account_creation(processed_members)
                frappe.logger().info(f"[CSV IMPORT] User account creation result: {user_account_summary}")
            else:
                frappe.logger().info(
                    f"[CSV IMPORT] Skipping user account creation: create_user_accounts={self.create_user_accounts}, "
                    f"processed_members={len(processed_members) if processed_members else 0}"
                )

            volunteer_summary = ""
            if self.create_volunteer_records and processed_members:
                frappe.logger().info(
                    f"[CSV IMPORT] Starting volunteer creation for {len(processed_members)} members"
                )
                volunteer_summary = self._process_bulk_volunteer_creation(processed_members)
                frappe.logger().info(f"[CSV IMPORT] Volunteer creation result: {volunteer_summary}")
        except Exception as e:
            frappe.logger().error(
                f"[CSV IMPORT] ERROR during finalization bulk operations: {str(e)}", exc_info=True
            )
            frappe.log_error(
                message=f"Finalization error: {str(e)}\n{frappe.get_traceback()}",
                title=f"CSV Import Finalization Error: {self.name}",
            )
            # Re-raise to ensure import status shows failure
            raise
        finally:
            # Always clear the bulk operations flag
            frappe.flags.bulk_member_operations = False
            frappe.logger().info("[CSV IMPORT] Cleared bulk_member_operations flag at end of finalization")

        # Validate Mollie subscription data preservation (via MollieSyncService)
        mollie_validation_summary = ""
        if processed_members:
            from verenigingen.services.csv_import.mollie_sync_service import (
                get_mollie_sync_service,
            )

            mollie_service = get_mollie_sync_service()
            mollie_issues, auto_fixed, critical_issues = mollie_service.validate_mollie_data_preservation(
                processed_members
            )

            # Surface critical issues prominently
            if critical_issues:
                frappe.logger().error(
                    f"MOLLIE CRITICAL: {len(critical_issues)} members have active subscriptions "
                    "but are terminated/banned/deceased"
                )
                self._append_to_error_log(
                    f"\n=== CRITICAL MOLLIE ISSUES ({len(critical_issues)}) ===\n"
                    + "\n".join(critical_issues[:20])
                    + ("\n... and more" if len(critical_issues) > 20 else "")
                )
                frappe.log_error(
                    f"CSV Import {self.name} - Critical Mollie Issues:\n\n" + "\n".join(critical_issues),
                    "CRITICAL: Mollie Subscriptions Need Cancellation",
                )

            if mollie_issues:
                mollie_validation_summary = (
                    f". Mollie validation: {len(mollie_issues)} issues found (see Error Log)"
                )
                if not critical_issues:
                    frappe.logger().warning("Mollie data validation found %d issues", len(mollie_issues))
                    frappe.log_error(
                        "Mollie data preservation issues:\n" + "\n".join(mollie_issues),
                        "Mollie Data Preservation Validation",
                    )
            else:
                mollie_validation_summary = ". Mollie data: preserved correctly"
                frappe.logger().info("Mollie data preservation validation passed")

        # Aggregate and report validation warnings. Note: affected members FAILED
        # their dues-schedule validation, so they are NOT in processed_members —
        # the warnings come from data captured during per-member processing.
        validation_warnings_summary = ""
        validation_warnings = self._aggregate_validation_warnings()
        if validation_warnings:
            validation_warnings_summary = f". {len(validation_warnings)} validation warnings (see notes)"
            # Append to error log
            if self.error_log:
                self.error_log += "\n\n=== Validation Warnings ===\n"
            else:
                self.error_log = "=== Validation Warnings ===\n"
            self.error_log += "\n".join(validation_warnings[:50])  # Limit to 50

        self.import_status = "Completed"
        base_summary = f"Import completed successfully. Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}"

        self.import_summary = f"{base_summary}{user_account_summary}{volunteer_summary}{mollie_validation_summary}{validation_warnings_summary}"

        if error_log:
            # Persist full error log as File attachment before truncating for UI
            from verenigingen.utils.import_helpers import (
                persist_full_error_log,
                truncate_error_log_for_display,
            )

            filename = persist_full_error_log(error_log, self.doctype, self.name)
            # Truncate for UI display (full log available as attachment)
            self.error_log = truncate_error_log_for_display(
                error_log, max_lines=50, full_log_filename=filename
            )

        # Update account creation tracking from Bulk Operation Tracker
        if self.create_user_accounts and processed_members:
            self._update_account_creation_tracking()

        # Capture the finalized fields before the reload below. reload() restores
        # the row from the DB - where the background processor last wrote
        # import_status="In Progress" - so any in-memory values set above are
        # discarded unless re-applied afterwards (otherwise a successful import
        # is never marked "Completed" and import_summary is never persisted).
        final_import_status = self.import_status
        final_import_summary = self.import_summary
        final_error_log = self.error_log

        # Reload to avoid timestamp mismatch from concurrent progress updates
        self.reload()

        # Re-apply the finalized fields AFTER reload so they aren't wiped out
        # (same reason the notes assignment below happens post-reload).
        self.import_status = final_import_status
        self.import_summary = final_import_summary
        self.error_log = final_error_log

        # Set notes AFTER reload so it doesn't get wiped out
        self.notes = self._generate_itemized_member_list(created_members, updated_members, skipped_members)
        frappe.logger().info("Notes field set with itemized member lists")

        self.save()

    def _process_user_account_creation(self, processed_members: List[str]) -> str:
        """
        Queue bulk user account creation for successfully imported members.

        This is now a thin wrapper that delegates all logic to AccountCreationService
        via queue_bulk_account_creation_for_members().
        """
        try:
            if not processed_members:
                frappe.logger().info("No members to create accounts for")
                return ". No user accounts created (no members processed)"

            frappe.logger().info(
                "Queuing bulk account creation for %d members (AccountCreationService will filter by status)",
                len(processed_members),
            )

            # Set role profile based on whether volunteer records are being created
            if self.create_volunteer_records:
                roles = ["Verenigingen Member", "Verenigingen Volunteer"]
                role_profile = "Verenigingen Volunteer"
            else:
                roles = ["Verenigingen Member"]
                role_profile = "Verenigingen Member"

            # Use AccountCreationManager which now delegates to AccountCreationService
            # The service handles all filtering, validation, linking, and request creation
            result = queue_bulk_account_creation_for_members(
                member_names=processed_members,  # Service will filter by status
                roles=roles,
                role_profile=role_profile,
                batch_size=50,
                priority="Low",
                create_employee=bool(getattr(self, "create_employee_records", False)),
            )

            # queue_bulk_account_creation_for_members is wrapped by @critical_api,
            # which serializes its OperationResult via to_dict(nested=True): the
            # payload (counts, request_names, tracker_name) lives under "data" and a
            # failure puts the human message under error["message"]. Reading these at
            # the top level silently yields defaults, so the summary would always say
            # "no accounts created/linked" and the tracker would never link. Read the
            # nested shape, with a flat fallback for resilience if the shape changes.
            if not result.get("success"):
                error_obj = result.get("error")
                if isinstance(error_obj, dict):
                    error_msg = error_obj.get("message") or "Unknown error during bulk queue operation"
                else:
                    error_msg = error_obj or "Unknown error during bulk queue operation"
                frappe.log_error(
                    f"Bulk account creation queue failed: {error_msg}", "Mijnrood Bulk Account Creation Error"
                )
                return f". User account creation failed: {error_msg}"

            data = result.get("data") if isinstance(result.get("data"), dict) else result

            # Create summary based on queue results
            summary_parts = []

            # Users linked to existing accounts
            users_linked = data.get("users_linked", 0)
            if users_linked > 0:
                summary_parts.append(f"{users_linked} users linked to existing accounts")

            # Requests successfully created and queued
            requests_created = data.get("requests_created", 0)
            if requests_created > 0:
                summary_parts.append(f"{requests_created} new account requests queued")

            # Validation errors (members that couldn't be processed)
            validation_errors = data.get("validation_errors_count", 0)
            if validation_errors > 0:
                summary_parts.append(f"{validation_errors} members skipped (validation errors)")

            # Batch information
            batch_count = data.get("batch_count", 0)
            if batch_count > 0:
                summary_parts.append(f"{batch_count} processing batches")

            if summary_parts:
                summary = f". User Accounts: {', '.join(summary_parts)}"
            else:
                summary = ". No user accounts created or linked"

            # Log detailed queue results for monitoring
            tracker_info = f"Tracker: {data.get('tracker_name', 'Unknown')}"
            frappe.logger().info(
                f"Bulk account creation queued: {requests_created} requests, {users_linked} linked, "
                f"{batch_count} batches, {validation_errors} validation errors, {tracker_info}"
            )

            # Store request tracking information for follow-up monitoring
            if data.get("request_names"):
                # Store first 10 request names for tracking (avoid overwhelming the log)
                sample_requests = data["request_names"][:10]
                frappe.logger().info("Sample account creation requests: %s", sample_requests)

                # Log any batches that failed to queue
                failed_batches = [
                    batch for batch in data.get("batches", []) if batch.get("status") == "failed"
                ]
                if failed_batches:
                    frappe.log_error(
                        f"Failed to queue {len(failed_batches)} batches: {failed_batches}",
                        "Mijnrood Batch Queue Failures",
                    )

            # Add tracker information to summary if available AND link to import
            if data.get("tracker_name"):
                tracker_name = data["tracker_name"]
                summary_parts.append(f"progress tracker: {tracker_name}")

                # Use atomic linking to prevent race condition with concurrent modifications
                self._link_tracker_atomically(tracker_name)

            return summary

        except Exception as e:
            error_msg = f"Error during bulk account creation queueing: {str(e)}"
            frappe.log_error(frappe.get_traceback(), "Mijnrood Bulk Account Creation Error")
            frappe.logger().error(error_msg)
            return f". User account creation failed: {str(e)}"

    def _process_bulk_volunteer_creation(self, processed_members: List[str]) -> str:
        """Create volunteer records using the robust BulkVolunteerCreationService.

        This method:
        - Uses members queued during inline processing (via _pending_volunteer_members)
        - Falls back to processed_members list if no pending members
        - Provides detailed tracking of success/failure/skipped
        - Adds error details to the import's error_log
        """
        try:
            from verenigingen.services.volunteer.bulk_volunteer_creation_service import (
                get_bulk_volunteer_creation_service,
            )

            # Use pending volunteer members if available (from inline _create_volunteer_for_member calls)
            # Otherwise fall back to processed_members
            members_for_volunteers = getattr(self, "_pending_volunteer_members", None)
            if not members_for_volunteers:
                # Fall back to filtering processed_members for active status
                members_for_volunteers = [
                    member_name
                    for member_name in processed_members
                    if frappe.db.get_value("Member", member_name, "status") == "Active"
                ]

            if not members_for_volunteers:
                frappe.logger().info("No members queued for volunteer creation")
                return ". No volunteer records created (no eligible members)"

            frappe.logger().info(
                f"Starting bulk volunteer creation for {len(members_for_volunteers)} members"
            )

            # Use the robust bulk creation service
            service = get_bulk_volunteer_creation_service()
            summary = service.create_volunteers_for_members(
                member_names=members_for_volunteers,
                batch_size=50,
                commit_per_batch=True,
            )

            # Store summary for potential retry
            self._volunteer_creation_summary = summary

            # Add error details to import error log if there were failures
            if summary.total_errors > 0:
                error_details = summary.get_error_summary(max_errors=20)
                if error_details:
                    volunteer_errors = "\n=== Volunteer Creation Errors ===\n" + "\n".join(error_details)
                    if self.error_log:
                        self.error_log += "\n" + volunteer_errors
                    else:
                        self.error_log = volunteer_errors

            # Log detailed results
            frappe.logger().info(
                f"Bulk volunteer creation completed: "
                f"created={summary.created}, existed={summary.already_existed}, "
                f"skipped_inactive={summary.skipped_inactive}, skipped_young={summary.skipped_too_young}, "
                f"errors={summary.total_errors}"
            )

            # Clean up pending list
            if hasattr(self, "_pending_volunteer_members"):
                del self._pending_volunteer_members

            return summary.to_summary_string()

        except Exception as e:
            error_msg = f"Error during bulk volunteer creation: {str(e)}"
            frappe.log_error(frappe.get_traceback(), "Mijnrood Bulk Volunteer Creation Error")
            frappe.logger().error(error_msg)
            return f". Volunteer creation failed: {str(e)}"

    def _update_account_creation_tracking(self):
        """
        Update account creation tracking fields from Bulk Operation Tracker.

        This method uses the linked Bulk Operation Tracker (if available) to extract
        ACR statistics and queries the database for actual created records.
        """
        try:
            frappe.logger().info(f"[CSV IMPORT] Updating account creation tracking for {self.name}")

            # Use linked Bulk Operation Tracker if available
            tracker = None
            if self.bulk_operation_tracker:
                frappe.logger().info(f"[CSV IMPORT] Using linked tracker: {self.bulk_operation_tracker}")
                try:
                    tracker_doc = frappe.get_doc("Bulk Operation Tracker", self.bulk_operation_tracker)
                    tracker = [
                        {
                            "name": tracker_doc.name,
                            "total_records": tracker_doc.total_records,
                            "processed_records": tracker_doc.processed_records,
                            "successful_records": tracker_doc.successful_records,
                            "failed_records": tracker_doc.failed_records,
                            "retry_queue": tracker_doc.get_retry_requests(),
                        }
                    ]
                except Exception as e:
                    frappe.logger().warning(
                        f"[CSV IMPORT] Linked tracker {self.bulk_operation_tracker} not found: {str(e)}"
                    )

            # Fallback: Search for most recent BOT if no linked tracker
            if not tracker:
                frappe.logger().info("[CSV IMPORT] No linked tracker, searching by creation time")
                tracker = frappe.get_all(
                    "Bulk Operation Tracker",
                    filters={
                        "operation_type": "Account Creation",
                        "creation": [">", frappe.utils.add_to_date(self.creation, hours=-1)],
                    },
                    fields=[
                        "name",
                        "total_records",
                        "processed_records",
                        "successful_records",
                        "failed_records",
                        "retry_queue",
                    ],
                    order_by="creation desc",
                    limit=1,
                )

            if tracker:
                tracker_data = tracker[0]
                # tracker_data is a dict from get_all or a dict we created from get_doc
                # Access as dict, not as Document object
                self.bulk_operation_tracker = tracker_data.get("name") or tracker_data["name"]
                self.acrs_created = tracker_data.get("total_records", 0)
                self.acrs_successful = tracker_data.get("successful_records", 0)
                self.acrs_failed = tracker_data.get("failed_records", 0)

                frappe.logger().info(
                    f"[CSV IMPORT] Tracker {self.bulk_operation_tracker}: "
                    f"{self.acrs_created} created, {self.acrs_successful} successful, {self.acrs_failed} failed"
                )

                # Query actual created records
                # Get all ACRs from this tracker to find created users/employees
                if self.acrs_successful > 0:
                    # Query completed ACRs from the tracker
                    acr_names = frappe.get_all(
                        "Account Creation Request",
                        filters={
                            "bulk_operation_tracker": self.bulk_operation_tracker,
                            "status": "Completed",
                        },
                        fields=["created_user", "created_employee"],
                        limit=1000,  # Reasonable limit
                    )

                    # Count actual created records
                    self.users_created = sum(1 for acr in acr_names if acr.created_user)
                    self.employees_created = sum(1 for acr in acr_names if acr.created_employee)
                    # Contacts are created inline with users, so use same count
                    self.contacts_created = self.users_created

                    frappe.logger().info(
                        f"[CSV IMPORT] Created records: "
                        f"{self.users_created} users, {self.employees_created} employees, "
                        f"{self.contacts_created} contacts"
                    )

                # Generate top errors summary from failed ACRs
                if self.acrs_failed > 0:
                    self.top_errors_summary = self._generate_top_errors_summary(self.bulk_operation_tracker)

            else:
                frappe.logger().warning(
                    f"[CSV IMPORT] No Bulk Operation Tracker found for import {self.name}"
                )

        except Exception as e:
            frappe.logger().error(
                f"[CSV IMPORT] Error updating account creation tracking: {str(e)}", exc_info=True
            )
            frappe.log_error(
                message=f"Error updating account creation tracking: {str(e)}\\n{frappe.get_traceback()}",
                title=f"CSV Import Tracking Update Error: {self.name}",
            )

    def _generate_top_errors_summary(self, tracker_name: str) -> str:
        """
        Generate a summary of top errors from failed ACRs.

        Args:
            tracker_name: Name of the Bulk Operation Tracker

        Returns:
            A formatted string summarizing the top errors
        """
        try:
            # Get failed ACRs
            failed_acrs = frappe.get_all(
                "Account Creation Request",
                filters={"bulk_operation_tracker": tracker_name, "status": "Failed"},
                fields=["name", "failure_reason"],
                limit=500,  # Get up to 500 failures
            )

            if not failed_acrs:
                return ""

            # Count error types
            from collections import Counter

            error_counts = Counter()

            for acr in failed_acrs:
                # Extract the first line of the error message as the error type
                if acr.failure_reason:
                    error_type = acr.failure_reason.split("\\n")[0][:200]  # First 200 chars
                    error_counts[error_type] += 1

            # Generate summary of top 10 errors
            summary_lines = [f"Top {min(10, len(error_counts))} Errors:"]
            for error_type, count in error_counts.most_common(10):
                summary_lines.append(f"• [{count:>3}] {error_type}")

            return "\\n".join(summary_lines)

        except Exception as e:
            frappe.logger().error(f"Error generating top errors summary: {str(e)}")
            return f"Error generating summary: {str(e)}"

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def retry_failed_account_creations(self):
        """
        Retry failed account creation requests from the associated Bulk Operation Tracker.

        This method can be called manually from the UI to reprocess failed ACRs.
        Returns a summary of the retry operation.
        """
        if not self.bulk_operation_tracker:
            frappe.throw(_("No Bulk Operation Tracker found for this import"))

        try:
            frappe.logger().info(
                f"[CSV IMPORT] Retrying failed account creations for {self.name} "
                f"(tracker: {self.bulk_operation_tracker})"
            )

            # Get the tracker document
            tracker = frappe.get_doc("Bulk Operation Tracker", self.bulk_operation_tracker)

            # Failed requests to retry are derived from ACR status (#172): the
            # returned names are already the tracker's Failed ACRs.
            retry_items = tracker.get_retry_requests()
            if not retry_items:
                frappe.msgprint(_("No failed account creation requests to retry"))
                return {"success": False, "message": "No failed items"}

            # Resolve the member (source_record) behind each Failed ACR.
            failed_acrs = frappe.get_all(
                "Account Creation Request",
                filters={"name": ["in", retry_items]},
                fields=["source_record"],
                limit=1000,
            )
            member_names = [acr.source_record for acr in failed_acrs if acr.source_record]

            if not member_names:
                frappe.msgprint(_("No member records found for failed ACRs"))
                return {"success": False, "message": "No members found"}

            # Queue retry using existing account creation function
            from verenigingen.utils.account_creation_manager import queue_bulk_account_creation_for_members

            # Use same settings as original import
            if self.create_volunteer_records:
                roles = ["Verenigingen Member", "Verenigingen Volunteer"]
                role_profile = "Verenigingen Volunteer"
            else:
                roles = ["Verenigingen Member"]
                role_profile = "Verenigingen Member"

            result = queue_bulk_account_creation_for_members(
                member_names=member_names,
                roles=roles,
                role_profile=role_profile,
                batch_size=50,
                priority="Normal",
                create_employee=bool(getattr(self, "create_employee_records", False)),
            )

            if result.get("success"):
                # Update tracking fields after retry
                frappe.enqueue(
                    method="verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.update_import_tracking_after_retry",
                    queue="short",
                    timeout=300,
                    import_doc_name=self.name,
                    delay=60,  # Wait 60 seconds for retry to process
                )

                frappe.msgprint(
                    _(
                        f"Retry queued: {len(retry_items)} failed requests will be reprocessed. "
                        f"Tracking fields will be updated automatically."
                    )
                )
                return {"success": True, "retry_count": len(retry_items)}
            else:
                error_msg = result.get("error", "Unknown error")
                frappe.throw(_("Failed to queue retry: {0}").format(error_msg))

        except Exception as e:
            frappe.logger().error(
                f"[CSV IMPORT] Error retrying failed account creations: {str(e)}", exc_info=True
            )
            frappe.log_error(
                message=f"Error retrying failed account creations: {str(e)}\\n{frappe.get_traceback()}",
                title=f"CSV Import Retry Error: {self.name}",
            )
            frappe.throw(_("Error retrying failed account creations: {0}").format(str(e)))

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def retry_failed_volunteer_creations(self):
        """
        Retry volunteer creation for members that failed during import.

        This method finds active members without volunteer records and attempts
        to create volunteers for them using the robust BulkVolunteerCreationService.
        """
        try:
            from verenigingen.services.volunteer.bulk_volunteer_creation_service import (
                get_bulk_volunteer_creation_service,
            )

            frappe.logger().info(f"[CSV IMPORT] Retrying failed volunteer creations for {self.name}")

            # Find active members from this import that don't have volunteer records
            # Get members that were likely imported (have review_notes mentioning this import)
            imported_members = frappe.get_all(
                "Member",
                filters={
                    "review_notes": ["like", f"%{self.name}%"],
                    "status": "Active",
                },
                fields=["name", "volunteer_record"],
            )

            # Filter to members without volunteer records
            members_needing_volunteers = [
                m.name
                for m in imported_members
                if not m.volunteer_record and not frappe.db.exists("Volunteer", {"member": m.name})
            ]

            if not members_needing_volunteers:
                frappe.msgprint(_("No members found that need volunteer records"))
                return {"success": True, "message": "No members need volunteer records", "created": 0}

            frappe.logger().info(
                f"[CSV IMPORT] Found {len(members_needing_volunteers)} members needing volunteers"
            )

            # Use the robust bulk creation service
            service = get_bulk_volunteer_creation_service()
            summary = service.create_volunteers_for_members(
                member_names=members_needing_volunteers,
                batch_size=50,
                commit_per_batch=True,
            )

            # Update error log with any new errors
            if summary.total_errors > 0:
                error_details = summary.get_error_summary(max_errors=20)
                if error_details:
                    volunteer_errors = (
                        f"\n\n=== Volunteer Retry Errors ({frappe.utils.now()}) ===\n"
                        + "\n".join(error_details)
                    )
                    if self.error_log:
                        self.error_log += volunteer_errors
                    else:
                        self.error_log = volunteer_errors
                    # Security: Import doc updating its own error log - doc controller method
                    self.save(ignore_permissions=True)

            result_message = (
                f"Retry completed: {summary.created} created, "
                f"{summary.already_existed} already existed, "
                f"{summary.total_skipped} skipped, "
                f"{summary.total_errors} errors"
            )

            frappe.msgprint(_(result_message))

            return {
                "success": True,
                "message": result_message,
                "created": summary.created,
                "already_existed": summary.already_existed,
                "skipped": summary.total_skipped,
                "errors": summary.total_errors,
            }

        except Exception as e:
            frappe.logger().error(f"[CSV IMPORT] Error retrying volunteer creations: {str(e)}", exc_info=True)
            frappe.log_error(
                message=f"Error retrying volunteer creations: {str(e)}\n{frappe.get_traceback()}",
                title=f"CSV Import Volunteer Retry Error: {self.name}",
            )
            frappe.throw(_("Error retrying volunteer creations: {0}").format(str(e)))

    def _check_dues_rate_below_minimum(self, row: Dict) -> None:
        """Detect a below-minimum dues rate for an imported row and record it.

        The dues-schedule validation that enforces the minimum runs deep inside
        membership creation and its error is swallowed (MembershipCreationService
        logs "Failed to create dues schedule" and continues), so we compare the
        row's dues_rate against the resolved Membership Type minimum directly --
        the same value (Membership Type.minimum_amount) that validation uses.
        """
        raw_rate = row.get("dues_rate")
        if raw_rate is None or (isinstance(raw_rate, str) and not raw_rate.strip()):
            return
        try:
            dues_rate = float(raw_rate)
        except (TypeError, ValueError):
            return

        try:
            membership_type = determine_membership_type_for_csv_import(row)
        except Exception:
            return  # type unresolvable -> membership (and its validation) won't run

        minimum = frappe.db.get_value("Membership Type", membership_type, "minimum_amount")
        if minimum and dues_rate < float(minimum):
            self._record_dues_rate_warning(row, dues_rate, float(minimum))

    def _record_dues_rate_warning(self, row: Dict, dues_rate: float, minimum: float) -> None:
        """Record a below-minimum dues-rate warning (member identity + amounts)
        for later aggregation into the import summary."""
        member_id = row.get("member_id") or "?"
        name = " ".join(p for p in (row.get("first_name"), row.get("last_name")) if p).strip()
        label = f"Lidnr {member_id}" + (f" ({name})" if name else "")
        if not hasattr(self, "_dues_rate_warnings"):
            self._dues_rate_warnings = []
        self._dues_rate_warnings.append(
            {"dues_rate": f"{dues_rate:.2f}", "minimum": f"{minimum:.2f}", "member": label}
        )

    def _aggregate_validation_warnings(self) -> List[str]:
        """Aggregate captured below-minimum dues-rate failures into summary lines.

        Buckets the warnings recorded by _record_dues_rate_warning during member
        processing by their shortfall (e.g. "€7.50 < €9.00"), listing affected
        members with a "... and N more" truncation past the first five.
        """
        warnings = []
        buckets: Dict[str, List[str]] = {}
        for entry in getattr(self, "_dues_rate_warnings", []):
            key = f"€{entry['dues_rate']} < €{entry['minimum']}"
            buckets.setdefault(key, []).append(entry["member"])

        for rate_issue, member_list in buckets.items():
            warnings.append(
                f"Dues rate below minimum ({rate_issue}): {len(member_list)} members - "
                f"{', '.join(member_list[:5])}"
            )
            if len(member_list) > 5:
                warnings.append(f"  ... and {len(member_list) - 5} more")

        return warnings

    def _create_related_records_via_services(self, member_name: str, row_data: Dict) -> List[str]:
        """Create related records using extracted services.

        This method orchestrates service calls for related record creation,
        replacing the inline logic in _create_related_records_with_tracking.

        IMPORTANT - Partial Commit Behavior:
        -----------------------------------
        The Member record is committed to the database BEFORE this method is
        called (see _process_single_member). This means:

        1. Member exists and is fully persisted when related record creation begins
        2. Each related record (address, mollie, termination, volunteer) is created
           independently with its own try/except block
        3. If one related record fails, others will still be attempted
        4. Failures are tracked and logged, but do not cause rollback of the member

        This is intentional: we prioritize having the member record even if some
        related records fail (e.g., due to validation errors or external service
        issues). Failed operations can be retried later or fixed manually.

        Example failure scenario:
        - Member MEM-12345 created and committed
        - Address creation succeeds
        - Mollie sync fails (validation error)
        - Termination record creation succeeds
        - Result: Member has address and termination record, Mollie data missing
        - The error log will show "mollie_data" as a failed operation

        Args:
            member_name: Name of the member document
            row_data: Original CSV row data

        Returns:
            List of failed operation names (empty if all succeeded)
        """
        from verenigingen.services.csv_import.address_import_service import (
            get_address_import_service,
        )
        from verenigingen.services.csv_import.membership_import_service import (
            get_membership_import_service,
        )
        from verenigingen.services.csv_import.mollie_sync_service import (
            get_mollie_sync_service,
        )

        member_doc = frappe.get_doc("Member", member_name)
        failed_operations = []

        # Address creation - check row_data for address fields
        if self._has_address_data(row_data):
            try:
                address_service = get_address_import_service()
                address_name = address_service.create_or_update_address(member_doc, row_data)
                if address_name:
                    frappe.db.set_value(
                        "Member",
                        member_name,
                        "primary_address",
                        address_name,
                        update_modified=False,
                    )
            except Exception as e:
                failed_operations.append("address")
                frappe.log_error(
                    f"Address creation failed for {member_name}: {e}",
                    "CSV Import - Address Error",
                )

        # Mollie data sync - check row_data for Mollie fields
        if row_data.get("custom_mollie_customer_id") or row_data.get("custom_mollie_subscription_id"):
            try:
                mollie_service = get_mollie_sync_service()
                mollie_data = {
                    "custom_mollie_customer_id": row_data.get("custom_mollie_customer_id"),
                    "custom_mollie_subscription_id": row_data.get("custom_mollie_subscription_id"),
                    "custom_subscription_status": (
                        "active" if row_data.get("custom_mollie_subscription_id") else None
                    ),
                }
                mollie_service.sync_mollie_data(member_doc, mollie_data)
            except Exception as e:
                failed_operations.append("mollie_data")
                frappe.log_error(
                    f"Mollie sync failed for {member_name}: {e}",
                    "CSV Import - Mollie Error",
                )

        # Termination record - delegate to existing method for now
        membership_type = (row_data.get("membership_type") or "").lower()
        if membership_type in [
            "opgezegd",
            "terminated",
            "uitgeschreven",
            "geroyeerd",
            "expelled",
            "geschorst",
            "overleden",
            "deceased",
        ]:
            try:
                termination_data = {
                    "membership_type": membership_type,
                    "member_since": row_data.get("member_since"),
                    "termination_reason": self._get_termination_reason(membership_type),
                }
                self._create_termination_record(member_doc, termination_data)
            except Exception as e:
                failed_operations.append("termination")
                frappe.log_error(
                    f"Termination record failed for {member_name}: {e}",
                    "CSV Import - Termination Error",
                )

        # Volunteer creation - delegate to existing method
        if self.create_volunteer_records and member_doc.status == "Active":
            try:
                self._create_volunteer_for_member(member_doc)
            except Exception as e:
                failed_operations.append("volunteer")
                frappe.log_error(
                    f"Volunteer creation failed for {member_name}: {e}",
                    "CSV Import - Volunteer Error",
                )

        # Chapter assignment
        if row_data.get("chapter"):
            chapter_raw = str(row_data["chapter"]).strip()
            chapter_name = chapter_raw.rstrip("*").strip()
            if chapter_name:
                try:
                    self._assign_member_to_chapter(member_doc, chapter_name)
                except Exception as e:
                    failed_operations.append("chapter")
                    frappe.log_error(
                        f"Chapter assignment failed for {member_name}: {e}",
                        "CSV Import - Chapter Error",
                    )

        # Membership creation via service
        if self._should_create_membership(member_doc, row_data):
            # Proactively flag a below-minimum dues rate for the validation-warning
            # summary. The dues-schedule validation error is swallowed several
            # layers deep (MembershipCreationService logs "Failed to create dues
            # schedule" and continues), so we detect the condition directly here
            # rather than trying to catch a deeply-suppressed exception.
            self._check_dues_rate_below_minimum(row_data)
            try:
                membership_service = get_membership_import_service()
                membership_service.create_membership_from_csv(member_doc, row_data)
            except Exception as e:
                failed_operations.append("membership")
                frappe.log_error(
                    f"Membership creation failed for {member_name}: {e}",
                    "CSV Import - Membership Error",
                )

        return failed_operations

    def _has_address_data(self, row_data: Dict) -> bool:
        """Check if row_data has meaningful address data."""
        address_line1 = row_data.get("address_line1")
        city = row_data.get("city")
        if address_line1:
            address_line1 = str(address_line1).strip()
        if city:
            city = str(city).strip()
        return bool(address_line1 and city)

    def _should_create_membership(self, member_doc: Document, row_data: Dict) -> bool:
        """Check if membership should be created for this member."""
        if member_doc.status != "Active":
            return False
        # Check if dues_rate is provided (indicating membership data exists)
        if "dues_rate" not in row_data:
            return False
        # Check no active membership exists
        existing = frappe.db.exists(
            "Membership",
            {"member": member_doc.name, "status": "Active", "docstatus": 1},
        )
        return not existing

    def _get_termination_reason(self, membership_type: str) -> str:
        """Get human-readable termination reason from membership type."""
        reason_mapping = {
            "uitgeschreven": "Voluntarily left membership",
            "opgezegd": "Membership cancelled/terminated voluntarily",
            "terminated": "Membership terminated",
            "geroyeerd": "Expelled from organization for cause",
            "expelled": "Expelled from organization",
            "geschorst": "Membership suspended",
            "overleden": "Member deceased",
            "deceased": "Member deceased",
        }
        return reason_mapping.get(membership_type, f"Terminated ({membership_type})")

    def _append_to_error_log(self, message: str, max_size: int = 50000):
        """Append message to error_log field with size management.

        Prevents the error_log field from growing unboundedly by truncating
        old entries when the log exceeds max_size.

        Args:
            message: Message to append to the error log
            max_size: Maximum size in characters before truncation (default 50KB)
        """
        current_log = self.error_log or ""

        if len(current_log) + len(message) + 1 > max_size:
            # Truncate old entries, keeping the header if present
            lines = current_log.split("\n")
            header = lines[0] if lines and lines[0].startswith("===") else ""

            # Keep only the header and add truncation notice
            if header:
                self.error_log = f"{header}\n\n... (earlier entries truncated) ...\n\n{message}"
            else:
                self.error_log = f"... (earlier entries truncated) ...\n\n{message}"
        else:
            if current_log:
                self.error_log = f"{current_log}\n{message}"
            else:
                self.error_log = message

    def _link_tracker_atomically(self, tracker_name: str):
        """Link the bulk operation tracker to this import under a row lock.

        Serializes concurrent linkers with SELECT ... FOR UPDATE so a tracker
        link is not lost to a racing writer, and persists via a direct db write
        so the value survives a later reload().

        Runs INSIDE the caller's (request / background-job) transaction and
        deliberately does NOT call frappe.db.begin()/commit(): begin() issues
        START TRANSACTION, which trips Frappe's implicit-commit guard whenever
        writes are already pending (e.g. the ACRs just created upstream) and would
        otherwise prematurely commit the surrounding transaction. The FOR UPDATE
        lock is held until — and the link persisted at — the normal request-level
        commit.
        """
        try:
            # Lock the import row to serialize concurrent tracker linking.
            locked_row = frappe.db.sql(
                """
                SELECT name, bulk_operation_tracker
                FROM `tabMijnrood CSV Import`
                WHERE name = %s
                FOR UPDATE
                """,
                self.name,
                as_dict=True,
            )

            if not locked_row:
                frappe.log_error(f"Import {self.name} not found during tracker linking", "Tracker Link Error")
                return

            # Idempotent: if already linked, keep the existing tracker.
            if locked_row[0].bulk_operation_tracker:
                frappe.logger().info(
                    f"[CSV IMPORT] Import {self.name} already has tracker "
                    f"{locked_row[0].bulk_operation_tracker}, not overwriting with {tracker_name}"
                )
                return

            # Direct DB write (no document methods that could fail); persists at the
            # request-level commit and survives a later reload().
            frappe.db.set_value(
                "Mijnrood CSV Import",
                self.name,
                "bulk_operation_tracker",
                tracker_name,
                update_modified=False,
            )

            # Keep the in-memory value consistent with the DB.
            self.bulk_operation_tracker = tracker_name

            frappe.logger().info(
                f"[CSV IMPORT] Linked Bulk Operation Tracker {tracker_name} to import {self.name}"
            )

        except Exception as e:
            # Do NOT roll back here: without our own transaction that would discard
            # the surrounding import work. Log and fall back to an in-memory
            # assignment so the value is at least available to this request.
            frappe.log_error(
                f"Failed to link tracker {tracker_name} to import {self.name}: {str(e)}",
                "Tracker Link Error",
            )
            self.bulk_operation_tracker = tracker_name

    def _create_termination_record(self, member_doc: Document, termination_data: dict):
        """Create a membership termination record for historical accuracy."""
        try:
            # Check if Member Termination Request DocType exists
            if not frappe.db.exists("DocType", "Membership Termination Request"):
                frappe.logger().info(
                    "Membership Termination Request DocType not found, skipping termination record creation"
                )
                return

            # Skip if member is already in a terminal state (Terminated, Banned)
            if member_doc.status in ["Quit", "Banned"]:
                frappe.logger().info(
                    f"Member {member_doc.name} already has status {member_doc.status}, skipping termination request"
                )
                return

            termination_doc = frappe.new_doc("Membership Termination Request")
            termination_doc.member = member_doc.name
            termination_doc.termination_reason = termination_data["termination_reason"]
            # For imported terminated members, use today as both request and termination date
            # since these are historical records
            termination_doc.request_date = today()
            termination_doc.termination_date = today()
            termination_doc.notes = (
                f"Imported from CSV - Original type: {termination_data['membership_type']}"
            )
            termination_doc.status = "Approved"  # Historical data is pre-approved

            # Set flags to bypass workflow for historical data
            termination_doc._csv_import = True

            # Insert termination record with proper permissions
            termination_doc.insert()
            frappe.logger().info("Created termination record for member %s", member_doc.name)

        except Exception as e:
            frappe.logger().error("Failed to create termination record for %s: %s", member_doc.name, str(e))
            # Don't fail the entire import for termination record issues

    def _create_volunteer_for_member(self, member_doc: Document):
        """Mark member for volunteer creation during batch processing.

        Instead of creating volunteers inline (which loses error tracking),
        this method collects member names for batch processing in _process_bulk_volunteer_creation.

        The actual creation is handled by BulkVolunteerCreationService which provides:
        - Proper error tracking and categorization
        - Batch efficiency with pre-fetched data
        - Detailed reporting for import summaries
        """
        # Initialize tracking list if not exists
        if not hasattr(self, "_pending_volunteer_members"):
            self._pending_volunteer_members = []

        # Just collect the member name for batch processing
        # Actual creation happens in _process_bulk_volunteer_creation
        self._pending_volunteer_members.append(member_doc.name)
        frappe.logger().debug(f"Queued {member_doc.name} for volunteer creation")

    def _assign_member_to_chapter(self, member_doc: Document, chapter_name: str):
        """Assign member to chapter based on chapter name from CSV, with optional auto-creation."""
        try:
            # CRITICAL: Ensure member has been saved and has a name before chapter operations
            if not member_doc.name:
                frappe.logger().error(
                    f"Cannot assign member to chapter '{chapter_name}' - member not yet saved (no name)"
                )
                return

            # Check if the chapter exists
            if not frappe.db.exists("Chapter", chapter_name):
                if self.auto_create_chapters:
                    # Try to create the chapter automatically
                    from verenigingen.services.chapter.chapter_provisioning_service import ensure_chapter

                    created_chapter = ensure_chapter(chapter_name, default_region=self.default_region)
                    if not created_chapter:
                        error_msg = f"Failed to auto-create chapter '{chapter_name}'. Skipping chapter assignment for member {member_doc.name}"
                        frappe.logger().error(error_msg)
                        frappe.logger().error(error_msg)
                        return
                    frappe.logger().info(
                        f"Auto-created chapter '{chapter_name}' and assigning member {member_doc.name}"
                    )
                else:
                    # Original behavior: log warning and skip
                    frappe.logger().warning(
                        f"Chapter '{chapter_name}' does not exist. Skipping chapter assignment for member {member_doc.name}"
                    )
                    return

            # Use the centralized ChapterMembershipManager for proper assignment
            # Suppress notifications during bulk CSV imports to avoid email flood
            # NOTE: Explicit notify=False is preferred here for clarity
            # Alternatively, could wrap entire import in suppress_chapter_notifications() context
            result = ChapterMembershipManager.assign_member_to_chapter(
                member_id=member_doc.name,
                chapter_name=chapter_name,
                reason=f"Imported from Mijnrood CSV (Import: {self.name})",
                assigned_by=frappe.session.user,
                notify=False,  # Never send notifications during bulk imports
                join_date=member_doc.member_since,  # Use membership start date as chapter join date
            )

            if result.get("success"):
                frappe.logger().info(
                    f"Successfully assigned member {member_doc.name} to chapter {chapter_name}"
                )
            elif result.get("action") == "already_exists":
                # Member already in chapter - this is fine, not an error
                frappe.logger().info(f"Member {member_doc.name} already assigned to chapter {chapter_name}")
            else:
                error_msg = (
                    result.get("error") or result.get("message") or "Unknown error - check result for details"
                )
                full_error = f"Failed to assign member {member_doc.name} to chapter {chapter_name}: {error_msg}. Full result: {result}"
                frappe.logger().error(full_error)

        except Exception as e:
            error_msg = f"Failed to assign member {member_doc.name} to chapter {chapter_name}: {str(e)}"
            frappe.logger().error(error_msg)
            # Don't fail the entire import for chapter assignment issues

    def _generate_itemized_member_list(
        self,
        created_members: List[str] = None,
        updated_members: List[str] = None,
        skipped_members: List[str] = None,
    ) -> str:
        """Generate itemized list of created/updated/skipped members with categorized skip reasons."""
        output = []
        output.append("## Itemized Import Results\n")

        if created_members:
            output.append(f"\n### Created Members ({len(created_members)}):")
            for name in created_members[:100]:  # Limit to first 100
                output.append(f"- {name}")
            if len(created_members) > 100:
                output.append(f"... and {len(created_members) - 100} more")

        if updated_members:
            output.append(f"\n### Updated Members ({len(updated_members)}):")
            for name in updated_members[:100]:
                output.append(f"- {name}")
            if len(updated_members) > 100:
                output.append(f"... and {len(updated_members) - 100} more")

        if skipped_members:
            output.append(f"\n### Skipped Members ({len(skipped_members)}) - Categorized by Reason:\n")
            # Categorize skipped members by error type
            skip_categories = self._categorize_skipped_members(skipped_members)

            for category, members in skip_categories.items():
                output.append(f"\n**{category}** ({len(members)} members):")
                for member_info in members[:20]:  # Show first 20 per category
                    output.append(f"  - {member_info}")
                if len(members) > 20:
                    output.append(f"  ... and {len(members) - 20} more")

        return "\n".join(output) if output else ""

    def _categorize_skipped_members(self, skipped_members: List[str]) -> Dict[str, List[str]]:
        """Categorize skipped members by error type for better clarity."""
        categories = {
            "Dues Rate Below Minimum": [],
            "Age Validation Failed": [],
            "Duplicate Entry": [],
            "Email Validation Failed": [],
            "IBAN Validation Failed": [],
            "Required Field Missing": [],
            "Other Validation Errors": [],
        }

        for skip_info in skipped_members:
            # Parse the skip_info string: "Lidnr {member_id}: {first_name} {last_name} - {error}"
            # Extract member ID and error message
            match = re.match(r"Lidnr\s+([^:]+):\s+(.+?)\s+-\s+(.+)$", skip_info)
            if not match:
                categories["Other Validation Errors"].append(skip_info)
                continue

            member_id = match.group(1).strip()
            member_name = match.group(2).strip()
            error_msg = match.group(3).strip().lower()

            display_info = f"{member_id} ({member_name})"

            # Categorize by error type
            if "dues rate" in error_msg and "minimum amount" in error_msg:
                categories["Dues Rate Below Minimum"].append(display_info)
            elif "too young" in error_msg or ("age" in error_msg and "minimum" in error_msg):
                categories["Age Validation Failed"].append(display_info)
            elif "duplicate" in error_msg:
                categories["Duplicate Entry"].append(display_info)
            elif "email" in error_msg and ("invalid" in error_msg or "format" in error_msg):
                categories["Email Validation Failed"].append(display_info)
            elif "iban" in error_msg:
                categories["IBAN Validation Failed"].append(display_info)
            elif "required" in error_msg or "mandatory" in error_msg or "missing" in error_msg:
                categories["Required Field Missing"].append(display_info)
            else:
                # Include truncated error message for unknown categories
                categories["Other Validation Errors"].append(f"{display_info}: {error_msg[:80]}")

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}


def _persist_validation_failure(doc, error_log: str, message: str, log_title: str = None) -> dict:
    """Mark an import doc Failed and return the standard error envelope.

    Centralises the persist-and-return that every validate_import_file failure
    arm repeats. Pass log_title to also record an Error Log row (reserved for
    genuinely unexpected failures, not expected validation errors).
    """
    doc.import_status = "Failed"
    doc.error_log = error_log
    doc.save()
    if log_title:
        frappe.log_error(error_log, log_title)
    return {"status": "error", "message": message}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def validate_import_file(import_doc_name: str) -> dict:
    """Manually validate an import file."""
    try:
        doc = frappe.get_doc("Mijnrood CSV Import", import_doc_name)

        # Skip validation if no file
        if not doc.csv_file:
            return {"status": "error", "message": "Please upload a CSV or Excel file first"}

        # Set status to validating
        doc.import_status = "Validating"
        doc.save()
        frappe.db.commit()

        # Perform validation
        try:
            csv_data = doc._read_csv_file()
            if not csv_data:
                return _persist_validation_failure(
                    doc, "CSV file is empty or unreadable", "CSV file is empty or unreadable"
                )

            # Validate and map data
            mapped_data, validation_errors = doc._validate_and_map_data(csv_data)

            if validation_errors:
                return _persist_validation_failure(
                    doc,
                    "\\n".join(validation_errors[:10]),  # Show first 10 errors
                    f"Validation failed: {len(validation_errors)} errors found. Check Error Log.",
                )

            doc.import_status = "Ready for Import"
            doc.preview_data = json.dumps(mapped_data[:5], indent=2, default=str)
            doc.descriptive_name = f"Member Import {doc.import_date} ({len(mapped_data)} records)"
            doc.save()
            return {
                "status": "success",
                "message": f"File validated successfully. Ready to import {len(mapped_data)} records.",
            }

        # The CSV parser (SecureCSVParser) funnels every file/format problem --
        # including missing or unreadable files -- through frappe.throw, so they
        # reach us as ValidationError. There is intentionally no separate
        # FileNotFoundError/PermissionError arm: those types cannot propagate here.
        except frappe.ValidationError as ve:
            msg = f"Data validation error: {str(ve)[:200]}"
            return _persist_validation_failure(doc, msg, msg)
        except Exception as ve:
            msg = f"Unexpected error: {str(ve)[:200]}"
            return _persist_validation_failure(doc, msg, msg, log_title="CSV Import Validation")

    except (frappe.DoesNotExistError, frappe.PermissionError) as pe:
        frappe.log_error(f"Permission/access error in CSV import: {str(pe)}", "CSV Import Access")
        return {"status": "error", "message": f"Access denied: {str(pe)[:200]}"}
    except Exception as e:
        frappe.log_error(f"Manual validation failed: {str(e)}", "CSV Import Manual Validation")
        return {"status": "error", "message": f"System error: {str(e)[:200]}"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def get_import_template():
    """Generate a CSV template for member import."""
    headers = [
        "Lidnr.",
        "Voornaam",
        "Tussenvoegsel",
        "Achternaam",
        "Geboortedatum",
        "Inschrijfdataum",
        "Groep",
        "E-mailadres",
        "Telefoonnr.",
        "Adres",
        "Plaats",
        "Postcode",
        "Landcode",
        "IBAN",
        "Contributiebedrag",
        "Betaalperiode",
        "Betaald",
        "Mollie CID",
        "Mollie SID",
        "Privacybeleid geaccepteerd",
        "Lidmaatschapstype",
    ]

    sample_data = [
        "12345",
        "Jan",
        "van der",
        "Berg",
        "1990-01-15",
        "2024-01-01",
        "Amsterdam",
        "jan.jansen@example.com",
        "+31612345678",
        "Hoofdstraat 123",
        "Amsterdam",
        "1000 AA",
        "NL",
        "NL91ABNA0417164300",
        "25.00",
        "Maandelijks",
        "Ja",
        "cst_example123",
        "sub_example456",
        "Ja",
        "Standard",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerow(sample_data)

    return {"filename": "member_import_template.csv", "content": output.getvalue()}


# Background Processing Functions


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def update_import_tracking_after_retry(import_doc_name: str):
    """
    Update import tracking fields after retry processing completes.

    This function is queued after retry_failed_account_creations() to update
    the tracking fields once the retry has been processed.

    Args:
        import_doc_name: Name of the Mijnrood CSV Import document
    """
    try:
        frappe.logger().info(f"[CSV IMPORT] Updating tracking after retry for {import_doc_name}")

        # Load the import document
        import_doc = frappe.get_doc("Mijnrood CSV Import", import_doc_name)

        # Re-run the tracking update to get latest numbers
        import_doc._update_account_creation_tracking()

        # Save the updated tracking
        # Security: Background job updating its own import document tracking
        import_doc.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.logger().info(f"[CSV IMPORT] Tracking updated after retry for {import_doc_name}")

    except Exception as e:
        frappe.logger().error(f"[CSV IMPORT] Error updating tracking after retry: {str(e)}", exc_info=True)
        frappe.log_error(
            message=f"Error updating tracking after retry: {str(e)}\\n{frappe.get_traceback()}",
            title=f"CSV Import Tracking Update After Retry Error: {import_doc_name}",
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_import_background(import_doc_name: str, test_mode: bool = False):
    """
    Background job function to process member CSV import.

    This function is called by the Redis queue system and processes the import
    in batches to prevent timeouts and provide progress tracking.

    Args:
        import_doc_name: Name of the Mijnrood CSV Import document
        test_mode: If True, only process the first 25 rows
    """
    # Mark this as a background job for scope-based rate limiting
    frappe.flags.in_background_job = True
    # Disable notifications during bulk import
    frappe.flags.in_bulk_import = True
    # Suppress chapter events during bulk import to prevent queue overflow (919 events in past imports)
    frappe.flags.bulk_chapter_operations = True
    # Suppress member events during bulk import to prevent queue overflow
    frappe.flags.bulk_member_operations = True
    # Suppress version tracking to prevent activity log flooding during bulk operations
    frappe.flags.ignore_version_changes = True

    test_mode_str = " (TEST MODE - first 25 rows)" if test_mode else ""
    frappe.logger().info(f"Starting background import processing for {import_doc_name}{test_mode_str}")

    try:
        # Load the import document
        import_doc = frappe.get_doc("Mijnrood CSV Import", import_doc_name)

        # Read and validate CSV data
        csv_data = import_doc._read_csv_file()
        mapped_data, validation_errors = import_doc._validate_and_map_data(csv_data)

        # In test mode, limit to first 25 rows
        if test_mode and len(mapped_data) > 25:
            frappe.logger().info(f"Test mode: limiting import from {len(mapped_data)} to 25 rows")
            mapped_data = mapped_data[:25]

        if validation_errors:
            import_doc.import_status = "Failed"
            import_doc.error_log = "\n".join(validation_errors)
            # Security: Background job updating its own import document status
            import_doc.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.logger().error(f"Import validation failed for {import_doc_name}")
            return

        # Create background processor
        processor = CSVImportBackgroundProcessor(
            import_doc_name=import_doc_name, doctype="Mijnrood CSV Import"
        )

        # Define row processing callback
        def process_row(row: Dict, error_log: List[str]) -> tuple:
            """Process a single member row."""
            return import_doc._process_single_member(row, error_log)

        # Define finalization callback
        def finalize_import(
            created_count: int,
            updated_count: int,
            skipped_count: int,
            error_log: List[str],
            created_members: List[str],
            updated_members: List[str],
            skipped_members: List[str],
        ):
            """Finalize the import with account creation and summaries."""
            import_doc._finalize_import_results(
                created_count,
                updated_count,
                skipped_count,
                error_log,
                created_members,
                updated_members,
                skipped_members,
            )

        # Process the import in batches
        result = processor.process_import(
            data_rows=mapped_data,
            process_row_callback=process_row,
            finalize_callback=finalize_import,
            batch_size=50,  # Process 50 members per batch
            batch_commit=True,  # Commit after each batch
        )

        frappe.logger().info(f"Background import completed for {import_doc_name}: {result}")

    except Exception as e:
        frappe.logger().error(f"Background import failed for {import_doc_name}: {str(e)}", exc_info=True)
        frappe.log_error(
            message=f"Background import failed: {str(e)}\n{traceback.format_exc()}",
            title=f"CSV Import Background Job Failed: {import_doc_name}",
        )

        # Update import status to show failure
        try:
            import_doc = frappe.get_doc("Mijnrood CSV Import", import_doc_name)
            import_doc.import_status = "Failed"
            import_doc.error_log = f"Background job failed: {str(e)}\n\nSee Error Log for full traceback"
            # Security: Background job updating its own import document failure status
            import_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as status_error:
            frappe.logger().error(f"Failed to update import status: {str(status_error)}")
