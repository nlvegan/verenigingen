# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

import os

import frappe
from frappe import _
from frappe.model.document import Document

# Allowed file extensions for board documents
ALLOWED_EXTENSIONS = {
    # Document formats
    ".pdf",  # PDF documents
    ".doc",  # Microsoft Word (legacy)
    ".docx",  # Microsoft Word
    ".odt",  # OpenDocument Text
    ".txt",  # Plain text
    ".rtf",  # Rich Text Format
    ".md",  # Markdown
    # Spreadsheet formats
    ".xls",  # Microsoft Excel (legacy)
    ".xlsx",  # Microsoft Excel
    ".ods",  # OpenDocument Spreadsheet
    ".csv",  # Comma-separated values
    # E-book formats
    ".epub",  # EPUB e-book
    ".mobi",  # Mobipocket e-book
    # Image formats (for scanned documents, photos of meetings, etc.)
    ".jpg",  # JPEG image
    ".jpeg",  # JPEG image
    ".png",  # PNG image
    ".gif",  # GIF image
    ".bmp",  # Bitmap image
    ".tiff",  # TIFF image
    ".tif",  # TIFF image
    ".webp",  # WebP image
    ".svg",  # SVG vector image
}


class ChapterBoardDocument(Document):
    """Child DocType for managing chapter board documents (policies, minutes, etc.)"""

    def validate(self):
        """Validate document data"""
        # Ensure document name is provided
        if not self.document_name:
            frappe.throw(_("Document Name is required"))

        # Validate document name doesn't contain path traversal characters
        if any(char in self.document_name for char in ["..", "/", "\\"]):
            frappe.throw(_("Document name cannot contain '..' or path separators"))

        # Ensure document file is attached
        if not self.document_file:
            frappe.throw(_("Document File is required"))

        # Validate file extension
        file_ext = os.path.splitext(self.document_file.lower())[1]
        if file_ext not in ALLOWED_EXTENSIONS:
            allowed_list = ", ".join(sorted(ALLOWED_EXTENSIONS))
            frappe.throw(
                _("File type '{0}' is not allowed. Allowed types: {1}").format(
                    file_ext or _("(no extension)"), allowed_list
                )
            )

        # Set upload date if not already set
        if not self.upload_date:
            self.upload_date = frappe.utils.today()
