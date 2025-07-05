# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import base64

import frappe
from frappe.model.document import Document
from frappe.utils import formatdate, getdate, today


class MT940Import(Document):
    def before_save(self):
        """Set company from bank account and import date if not set"""
        if self.bank_account and not self.company:
            self.company = frappe.db.get_value("Bank Account", self.bank_account, "company")

        # Set import date if not set
        if not hasattr(self, "import_date") or not self.import_date:
            self.import_date = today()

        # Set status to pending if not set
        if not hasattr(self, "import_status") or not self.import_status:
            self.import_status = "Pending"

    def on_submit(self):
        """Process the MT940 import when document is submitted"""
        try:
            self.import_status = "In Progress"
            self.save()

            # Process the import
            result = self.process_mt940_import()

            if result.get("success"):
                self.import_status = "Completed"
                self.import_summary = result.get("message", "Import completed successfully")
                self.transactions_created = result.get("transactions_created", 0)
                self.transactions_skipped = result.get("transactions_skipped", 0)

                # Extract and set date range information
                self.extract_date_range_from_result(result)
            else:
                self.import_status = "Failed"
                self.import_summary = result.get("message", "Import failed")
                self.error_log = str(result.get("errors", []))

            self.save()

        except Exception as e:
            self.import_status = "Failed"
            self.import_summary = f"Import failed with error: {str(e)}"
            self.error_log = frappe.get_traceback()
            self.save()
            raise

    def extract_date_range_from_result(self, result):
        """Extract date range from import result and create descriptive name"""
        try:
            # Try to get date range from the MT940 processing result first
            if result.get("statement_from_date") and result.get("statement_to_date"):
                self.statement_from_date = getdate(result.get("statement_from_date"))
                self.statement_to_date = getdate(result.get("statement_to_date"))
            elif result.get("transactions_created", 0) > 0:
                # Fallback: Get the date range of transactions created in this import
                from_date, to_date = self.get_transaction_date_range()

                if from_date and to_date:
                    self.statement_from_date = from_date
                    self.statement_to_date = to_date
                else:
                    # Fallback to using the import date
                    self.statement_from_date = self.import_date
                    self.statement_to_date = self.import_date
            else:
                # No transactions created, use import date
                self.statement_from_date = self.import_date
                self.statement_to_date = self.import_date

            # Generate descriptive name
            self.descriptive_name = self.generate_descriptive_name()

        except Exception as e:
            frappe.logger().error(f"Error extracting date range: {str(e)}")
            # Fallback naming
            self.statement_from_date = self.import_date
            self.statement_to_date = self.import_date
            self.descriptive_name = self.generate_descriptive_name()

    def get_transaction_date_range(self):
        """Get the date range of transactions created in this import session"""
        try:
            # Get transactions created in the last few minutes (during this import)
            pass

            import frappe.utils

            # Look for transactions created in the last 5 minutes
            cutoff_time = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-5)

            transactions = frappe.db.sql(
                """
                SELECT MIN(date) as from_date, MAX(date) as to_date
                FROM `tabBank Transaction`
                WHERE bank_account = %s
                AND company = %s
                AND creation >= %s
                AND docstatus = 1
            """,
                (self.bank_account, self.company, cutoff_time),
                as_dict=True,
            )

            if transactions and transactions[0].from_date:
                return transactions[0].from_date, transactions[0].to_date

            return None, None

        except Exception as e:
            frappe.logger().error(f"Error getting transaction date range: {str(e)}")
            return None, None

    def generate_descriptive_name(self):
        """Generate a descriptive name for the MT940 import"""
        try:
            # Get bank account name (without company suffix if present)
            bank_account_name = self.bank_account
            if " - " in bank_account_name:
                bank_account_name = bank_account_name.split(" - ")[0]

            # Format dates for name
            if self.statement_from_date and self.statement_to_date:
                from_date_str = formatdate(self.statement_from_date, "dd-MM-yyyy")
                to_date_str = formatdate(self.statement_to_date, "dd-MM-yyyy")

                if self.statement_from_date == self.statement_to_date:
                    # Single day import
                    date_part = from_date_str
                else:
                    # Date range import
                    date_part = f"{from_date_str} to {to_date_str}"
            else:
                # Fallback to import date
                date_part = formatdate(self.import_date, "dd-MM-yyyy")

            # Include transaction count for clarity
            if hasattr(self, "transactions_created") and self.transactions_created:
                count_part = f"({self.transactions_created} txns)"
            else:
                count_part = ""

            # Generate final name
            if count_part:
                descriptive_name = f"{bank_account_name} - {date_part} {count_part}"
            else:
                descriptive_name = f"{bank_account_name} - {date_part}"

            return descriptive_name

        except Exception as e:
            frappe.logger().error(f"Error generating descriptive name: {str(e)}")
            # Fallback to basic naming
            return f"{self.bank_account} - {formatdate(self.import_date or today(), 'dd-MM-yyyy')}"

    def process_mt940_import(self):
        """Process the MT940 file and create bank transactions"""
        try:
            # Get the file content
            if not self.mt940_file:
                return {"success": False, "message": "No MT940 file attached"}

            # Get file content from attachment
            file_doc = frappe.get_doc("File", {"file_url": self.mt940_file})
            file_path = file_doc.get_full_path()

            with open(file_path, "r", encoding="utf-8") as f:
                mt940_content = f.read()

            # Encode as base64 for processing
            file_content_b64 = base64.b64encode(mt940_content.encode("utf-8")).decode("utf-8")

            # Use enhanced import function with Banking app features
            from verenigingen.utils.mt940_import import import_mt940_file

            result = import_mt940_file(self.bank_account, file_content_b64, self.company)

            return result

        except Exception as e:
            frappe.logger().error(f"Error in MT940 import processing: {str(e)}")
            return {"success": False, "message": f"Processing failed: {str(e)}", "errors": [str(e)]}


@frappe.whitelist()
def debug_import(bank_account, file_url):
    """Debug method for testing MT940 import"""
    try:
        # Get file content from attachment
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_path = file_doc.get_full_path()

        with open(file_path, "r", encoding="utf-8") as f:
            mt940_content = f.read()

        # Encode as base64 for processing
        file_content_b64 = base64.b64encode(mt940_content.encode("utf-8")).decode("utf-8")

        # Use existing debug function
        from verenigingen.api.member_management import debug_mt940_import_detailed

        company = frappe.db.get_value("Bank Account", bank_account, "company")
        result = debug_mt940_import_detailed(file_content_b64, bank_account, company)

        return result

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_duplicates(bank_account, file_url):
    """Debug method for analyzing duplicate detection logic"""
    try:
        # Get file content from attachment
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_path = file_doc.get_full_path()

        with open(file_path, "r", encoding="utf-8") as f:
            mt940_content = f.read()

        # Encode as base64 for processing
        file_content_b64 = base64.b64encode(mt940_content.encode("utf-8")).decode("utf-8")

        # Use duplicate detection debug function
        from verenigingen.api.member_management import debug_duplicate_detection

        company = frappe.db.get_value("Bank Account", bank_account, "company")
        result = debug_duplicate_detection(file_content_b64, bank_account, company)

        return result

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_enhanced_import(bank_account, file_url):
    """Debug method for testing enhanced MT940 import with SEPA features"""
    try:
        # Get file content from attachment
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_path = file_doc.get_full_path()

        with open(file_path, "r", encoding="utf-8") as f:
            mt940_content = f.read()

        # Encode as base64 for processing
        file_content_b64 = base64.b64encode(mt940_content.encode("utf-8")).decode("utf-8")

        # Use enhanced validation function
        from verenigingen.utils.mt940_import import validate_mt940_file

        company = frappe.db.get_value("Bank Account", bank_account, "company")
        validation_result = validate_mt940_file(file_content_b64)

        # Check enhanced fields status
        from verenigingen.utils.mt940_enhanced_fields import get_field_creation_status

        field_status = get_field_creation_status()

        return {
            "validation_result": validation_result,
            "enhanced_fields_status": field_status,
            "bank_account": bank_account,
            "company": company,
            "file_size": len(mt940_content),
            "enhanced_features": {
                "sepa_data_extraction": True,
                "dutch_banking_codes": True,
                "enhanced_duplicate_detection": True,
                "transaction_type_classification": True,
            },
        }

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}
