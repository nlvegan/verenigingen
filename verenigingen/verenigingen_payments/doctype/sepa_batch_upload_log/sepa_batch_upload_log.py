# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
SEPA Batch Upload Log DocType

Tracks SEPA XML file uploads to the bank for audit purposes and duplicate prevention.
Each upload creates a log entry with the file's SHA256 hash, ensuring that the same
file cannot be uploaded twice (preventing duplicate payment batches).

Key Features:
- File hash uniqueness enforcement to prevent duplicate uploads
- Complete audit trail of upload attempts and bank responses
- Status tracking from upload through bank acknowledgement
- Integration with Direct Debit Batch for payment workflow

Business Context:
SEPA Direct Debit files must only be uploaded to the bank once. Duplicate uploads
can cause members to be charged multiple times. This DocType prevents duplicates
by storing and validating file hashes before any upload proceeds.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SEPABatchUploadLog(Document):
    """
    Audit log for SEPA batch file uploads with duplicate prevention.

    The file_hash field (SHA256) is unique to ensure the same file content
    cannot be uploaded twice. This is a critical safety feature to prevent
    duplicate bank submissions that could result in members being charged
    multiple times.
    """

    def validate(self):
        """Validate the upload log entry before saving."""
        self.validate_unique_hash()

    def validate_unique_hash(self):
        """
        Ensure file hash is unique to prevent duplicate uploads.

        This is a critical safety check. If a file with the same hash already
        exists in the system, it means the exact same file content was already
        uploaded. Allowing a second upload would risk duplicate payments.
        """
        if not self.file_hash:
            return

        existing = frappe.db.get_value(
            "SEPA Batch Upload Log",
            {"file_hash": self.file_hash, "name": ("!=", self.name)},
            "name",
        )

        if existing:
            frappe.throw(
                _(
                    "A file with this hash was already uploaded (Log: {0}). "
                    "This appears to be a duplicate upload attempt."
                ).format(existing),
                frappe.DuplicateEntryError,
            )

    def on_trash(self):
        """
        Prevent deletion of upload logs to maintain audit trail integrity.

        Upload logs are part of the financial audit trail and must be retained
        for regulatory compliance. Only system-level operations may delete these
        records during automated cleanup processes.
        """
        if frappe.session.user not in ["Administrator", "System"]:
            frappe.throw(_("SEPA upload logs cannot be manually deleted for audit trail integrity."))
