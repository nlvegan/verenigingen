"""
SEPA XML Generation Service

This service handles SEPA XML generation for Dutch direct debit processing.
Uses the SEPAXMLAdapter to generate pain.008.001.08 compliant XML with
proper mandate sign dates.

The actual XML generation is delegated to EnhancedSEPAXMLGenerator via
the SEPAXMLAdapter for better separation of concerns and code reuse.
"""

import os
import tempfile
import xml.dom.minidom
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import nowdate, nowtime, random_string

from verenigingen.services.payment.sepa_upload_guard import get_sepa_upload_guard
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.services.sepa_xml_adapter import get_sepa_xml_adapter
from verenigingen.verenigingen_payments.utils.sepa_utilities import FileManagementUtilities, SEPAXMLValidator


class SEPAXMLGenerationService:
    """Service for generating SEPA XML files for direct debit processing"""

    def __init__(self):
        self.config_service = sepa_config_service
        self.xml_adapter = get_sepa_xml_adapter()

    def generate_sepa_xml_for_batch(self, batch_doc) -> str:
        """
        Generate SEPA Direct Debit XML file for Dutch banks.

        Uses the SEPAXMLAdapter to generate properly formatted XML with
        correct mandate sign dates (DtOfSgntr) from the batch invoices
        or database lookup fallback.

        Args:
            batch_doc: Direct Debit Batch document

        Returns:
            File URL of generated SEPA XML file

        Raises:
            frappe.ValidationError: If required settings are missing
            Exception: If XML generation fails
        """
        try:
            frappe.logger().info(f"Starting SEPA XML generation for batch {batch_doc.name} (pain.008.001.08)")

            # Generate IDs for SEPA message. Reuse previously-stored IDs when the
            # batch is regenerated so the same batch deterministically yields the
            # same file (and is correctly recognized as a duplicate upload);
            # only mint new IDs on the first generation.
            #
            # INVARIANT (safe against cross-batch MsgId reuse): sepa_message_id is
            # written ONLY here (db_set below) — there is no other setter in the
            # codebase and no copy_doc path that carries it onto a different batch.
            # The id is namespaced by batch_doc.name (unique per batch), so reuse
            # can only ever return THIS batch's own previously-minted id, never one
            # a bank already received for a different batch.
            message_id = batch_doc.get("sepa_message_id") or f"BATCH-{batch_doc.name}-{random_string(8)}"
            payment_info_id = (
                batch_doc.get("sepa_payment_info_id") or f"PMT-{batch_doc.name}-{random_string(8)}"
            )

            # Store IDs - use db_set to avoid validation issues after submission.
            # Preserve an existing generation date so regeneration is
            # deterministic (same IDs + timestamp => identical file => duplicate
            # correctly detected).
            generation_date = batch_doc.get("sepa_generation_date") or f"{nowdate()} {nowtime()}"
            batch_doc.db_set("sepa_message_id", message_id)
            batch_doc.db_set("sepa_payment_info_id", payment_info_id)
            batch_doc.db_set("sepa_generation_date", generation_date)

            # Validate required settings
            validation_result = self.config_service.validate_sepa_configuration()
            if not validation_result["is_valid"]:
                missing_settings = validation_result["errors"]
                error_msg = f"Missing required SEPA settings: {', '.join(missing_settings)}"
                frappe.throw(error_msg)

            # Clear adapter cache for fresh lookup
            self.xml_adapter.clear_cache()

            # Generate SEPA XML using the adapter
            xml_string = self.xml_adapter.generate_xml_for_batch(
                batch_doc=batch_doc,
                message_id=message_id,
                payment_info_id=payment_info_id,
            )

            # Validate XML against schema if available
            validation_result = SEPAXMLValidator.validate_sepa_xml_schema(xml_string, batch_doc.name)
            if not validation_result["valid"]:
                frappe.logger().warning(
                    f"SEPA XML validation warnings for batch {batch_doc.name}: {validation_result.get('errors', [])}"
                )
                # Log warnings but continue - some banks may have different validation rules

            # Create and save XML file
            file_url = self._save_xml_file(batch_doc, xml_string)

            frappe.logger().info(f"SEPA XML file generated successfully for batch {batch_doc.name}")
            return file_url

        except Exception as e:
            error_msg = f"Error generating SEPA file: {str(e)}"
            frappe.log_error(
                f"Error generating SEPA file for batch {batch_doc.name}: {str(e)}\n"
                f"Traceback: {frappe.get_traceback()}",
                "SEPA Direct Debit Batch Error",
            )
            raise frappe.ValidationError(error_msg)

    def _save_xml_file(self, batch_doc, xml_string: str) -> str:
        """
        Save XML string to file and attach to document.

        Uses atomic check_and_register() to prevent TOCTOU race conditions.
        The hash is registered BEFORE attachment to prevent two workers from
        both passing the check and uploading duplicates.

        If attachment fails after registration, a "phantom" log entry remains,
        which is safer than allowing duplicate uploads.

        Args:
            batch_doc: Direct Debit Batch document
            xml_string: XML content as string (may be bytes or str)

        Returns:
            File URL of saved XML file

        Raises:
            frappe.ValidationError: If duplicate file detected or sandbox mode active
        """
        # Handle both bytes and string input
        if isinstance(xml_string, bytes):
            xml_content = xml_string.decode("utf-8")
        else:
            xml_content = xml_string

        # Prettify XML if not already prettified
        try:
            dom = xml.dom.minidom.parseString(xml_content.encode("utf-8"))
            xml_pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        except Exception:
            # If parsing fails, use as-is
            xml_pretty = xml_content

        # Get XML content as bytes for hashing (use the final prettified content)
        xml_bytes = xml_pretty.encode("utf-8")

        # ATOMIC check-and-register to prevent TOCTOU race condition
        # This reserves the hash BEFORE attachment to prevent two workers
        # from both passing a check and uploading duplicates
        guard = get_sepa_upload_guard()
        atomic_result = guard.check_and_register(
            xml_bytes,
            batch_doc.name,
            uploaded_by=frappe.session.user,
        )
        if not atomic_result.success:
            frappe.throw(
                _("SEPA file blocked: {0}").format(atomic_result.message),
                title=_("Upload Blocked"),
            )

        # Hash is now reserved - proceed with file attachment
        # Create temporary file
        temp_file_path = os.path.join(tempfile.gettempdir(), f"sepa-{batch_doc.name}.xml")
        with open(temp_file_path, "w", encoding="utf-8") as f:
            f.write(xml_pretty)

        try:
            # Attach to document
            file_url = FileManagementUtilities.attach_file_to_document(
                temp_file_path, batch_doc.doctype, batch_doc.name
            )

            # Update batch document
            batch_doc.db_set("sepa_file", file_url)
            batch_doc.db_set("sepa_file_generated", 1)
            batch_doc.db_set("status", "Generated")

            # Optionally update the upload log with file info
            # Find log by file_hash and set file_name
            frappe.db.set_value(
                "SEPA Batch Upload Log",
                {"file_hash": atomic_result.file_hash},
                {"file_name": f"sepa-{batch_doc.name}.xml"},
            )

            return file_url

        except Exception as e:
            # Attachment failed after hash was registered
            # Update log to mark as failed and set is_phantom flag for efficient querying
            # Hash stays reserved to prevent retries with same content - operator must investigate
            frappe.db.set_value(
                "SEPA Batch Upload Log",
                {"file_hash": atomic_result.file_hash},
                {
                    "bank_status": "Rejected",
                    "bank_error_message": f"Attachment failed: {str(e)}",
                    "is_phantom": 1,
                },
            )
            frappe.logger().error(
                f"SEPA file attachment failed for batch {batch_doc.name} after hash registration: {e}"
            )
            raise

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)


# Singleton instance for global use
sepa_xml_service = SEPAXMLGenerationService()
