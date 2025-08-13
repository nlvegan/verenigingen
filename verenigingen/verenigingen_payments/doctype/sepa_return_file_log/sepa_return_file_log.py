# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SEPAReturnFileLog(Document):
    def before_insert(self):
        """Set file size if not provided"""
        if not self.file_size and hasattr(self, "_file_content"):
            self.file_size = len(self._file_content.encode("utf-8"))

    def validate(self):
        """Validate return file log data"""
        if self.status == "Completed":
            if not self.return_count:
                self.return_count = 0
            if not self.successful_reversals:
                self.successful_reversals = 0
            if not self.failed_reversals:
                self.failed_reversals = 0
