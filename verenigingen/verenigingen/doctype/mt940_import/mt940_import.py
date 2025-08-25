# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import base64

import frappe
from frappe.model.document import Document
from frappe.utils import formatdate, getdate, today


class MT940Import(Document):
    def validate(self):
        """Validate the MT940 import document"""
        # For Mollie bulk imports, MT940 file is not required
        if self.import_type == "Mollie Bulk Import":
            # Validate Mollie-specific required fields
            if not self.mollie_from_date:
                frappe.throw("From Date is required for Mollie bulk import")
            if not self.mollie_to_date:
                frappe.throw("To Date is required for Mollie bulk import")

            # Skip MT940 file validation for Mollie imports - no file needed
            return
        else:
            # For regular MT940 imports, file is required
            if not self.mt940_file:
                frappe.throw("MT940 file is required for file-based imports")

    def before_save(self):
        """Set company from bank account and import date if not set"""
        if self.bank_account and not self.company:
            self.company = frappe.db.get_value("Bank Account", self.bank_account, "company")

        # Set import date if not set
        if not getattr(self, "import_date", None):
            self.import_date = today()

        # Set status to pending if not set
        if not getattr(self, "import_status", None):
            self.import_status = "Pending"

        # Set default import type if not set (fallback, field should have default)
        if not self.import_type:
            self.import_type = "MT940 File Import"

    def on_submit(self):
        """Process the import when document is submitted (MT940 or Mollie bulk)"""
        try:
            self.import_status = "In Progress"
            self.save()

            # Determine import type and process accordingly
            if self.import_type == "Mollie Bulk Import":
                result = self.process_mollie_bulk_import()
            else:
                # Default to MT940 import
                result = self.process_mt940_import()

            if result.get("success") or result.get("status") == "completed":
                self.import_status = "Completed"
                self.import_summary = result.get(
                    "message", result.get("import_summary", "Import completed successfully")
                )
                self.transactions_created = result.get(
                    "transactions_created", result.get("transactions", {}).get("total_imported", 0)
                )
                self.transactions_skipped = result.get(
                    "transactions_skipped", result.get("transactions", {}).get("duplicates_skipped", 0)
                )

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

    def process_mollie_bulk_import(self):
        """Process Mollie bulk import using the bulk transaction importer"""
        try:
            # Import the bulk transaction importer
            from datetime import datetime

            from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
                BulkTransactionImporter,
            )

            # Get import parameters from DocType fields
            mollie_from_date = self.mollie_from_date
            mollie_to_date = self.mollie_to_date

            # Map DocType strategy values back to bulk importer expected values
            doctype_strategy = self.mollie_import_strategy or "hybrid"
            strategy_to_importer = {
                "payments_only": "payments",
                "balances_only": "settlements",
                "hybrid": "hybrid",
            }
            import_strategy = strategy_to_importer.get(doctype_strategy, "hybrid")

            # Convert date strings to date objects, then to datetime objects
            if mollie_from_date:
                from_date_obj = (
                    getdate(mollie_from_date) if isinstance(mollie_from_date, str) else mollie_from_date
                )
                from_date = datetime.combine(from_date_obj, datetime.min.time())
            else:
                from_date = None

            if mollie_to_date:
                to_date_obj = getdate(mollie_to_date) if isinstance(mollie_to_date, str) else mollie_to_date
                to_date = datetime.combine(to_date_obj, datetime.min.time())
            else:
                to_date = None

            if not from_date or not to_date:
                return {
                    "success": False,
                    "message": "From date and to date are required for Mollie bulk import",
                }

            # Initialize and run the bulk importer
            importer = BulkTransactionImporter()
            result = importer.import_transactions(
                from_date=from_date,
                to_date=to_date,
                import_strategy=import_strategy,
                company=self.company,
                bank_account=self.bank_account,
            )

            # Update descriptive name for Mollie import
            if result.get("status") in ["completed", "completed_with_warnings", "completed_with_errors"]:
                total_imported = result.get("transactions", {}).get("total_imported", 0)
                from_date_str = self.mollie_from_date or "Unknown"
                to_date_str = self.mollie_to_date or "Unknown"
                self.descriptive_name = (
                    f"Mollie Bulk Import - {from_date_str} to {to_date_str} ({total_imported} txns)"
                )

            return result

        except Exception as e:
            frappe.logger().error(f"Error in Mollie bulk import processing: {str(e)}")
            return {"success": False, "message": f"Mollie bulk import failed: {str(e)}", "errors": [str(e)]}


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


@frappe.whitelist()
def estimate_mollie_bulk_import(from_date, to_date, strategy="hybrid"):
    """API endpoint to estimate Mollie bulk import size"""
    try:
        from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
            estimate_bulk_import_size,
        )

        return estimate_bulk_import_size(from_date, to_date, strategy)
    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def create_mollie_bulk_import(from_date, to_date, strategy="hybrid", company=None, bank_account=None):
    """API endpoint to create a new Mollie bulk import document"""
    try:
        if not frappe.has_permission("MT940 Import", "create"):
            frappe.throw("Insufficient permissions to create bulk import")

        # Get default company if not provided
        if not company:
            company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
                "Global Defaults", "default_company"
            )

        if not company:
            frappe.throw("No company specified and no default company found")

        # Get default bank account if not provided
        if not bank_account:
            # First try to get default bank account for the company
            bank_account = frappe.db.get_value("Bank Account", {"company": company, "is_default": 1}, "name")
            # If no default, get any bank account for the company
            if not bank_account:
                bank_account = frappe.db.get_value("Bank Account", {"company": company}, "name")
            # If still no bank account, check if any exist at all
            if not bank_account:
                # Check if there are any bank accounts in the system
                any_bank_account = frappe.db.get_value("Bank Account", {}, "name")
                if any_bank_account:
                    frappe.throw(
                        f"No bank account found for company '{company}'. Available bank accounts exist but are linked to other companies."
                    )
                else:
                    frappe.throw("No bank accounts found in the system. Please create a bank account first.")

        # Map strategy values to DocType field options
        strategy_mapping = {
            # Bulk importer uses these values
            "payments": "payments_only",
            "settlements": "balances_only",
            "balances": "balances_only",
            "hybrid": "hybrid",
            # DocType field options (already correct)
            "payments_only": "payments_only",
            "balances_only": "balances_only",
        }

        # Normalize strategy
        mapped_strategy = strategy_mapping.get(strategy, "hybrid")

        # Final validation before document creation
        if not bank_account:
            frappe.throw("Bank account is required but could not be determined")
        if not company:
            frappe.throw("Company is required but could not be determined")

        # Debug logging to identify the issue
        frappe.logger().info(
            f"Creating Mollie bulk import with bank_account='{bank_account}', company='{company}'"
        )

        # Create the import document
        import_doc = frappe.new_doc("MT940 Import")
        import_doc.update(
            {
                "import_type": "Mollie Bulk Import",
                "bank_account": bank_account,
                "company": company,
                "import_status": "Pending",
                "mollie_from_date": from_date,
                "mollie_to_date": to_date,
                "mollie_import_strategy": mapped_strategy,
            }
        )

        # Validate bank account exists before inserting
        if not frappe.db.exists("Bank Account", bank_account):
            frappe.throw(f"Bank Account '{bank_account}' not found")

        # Double-check the document fields before insertion
        frappe.logger().info(
            f"Document fields before insert: bank_account='{import_doc.bank_account}', import_type='{import_doc.import_type}'"
        )

        import_doc.insert()

        return {
            "success": True,
            "import_doc_name": import_doc.name,
            "message": f"Created Mollie bulk import: {import_doc.name}",
        }

    except Exception as e:
        frappe.log_error(f"Error creating Mollie bulk import: {str(e)}", "Mollie Bulk Import Creation")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def submit_import(import_name):
    """Submit an MT940 Import document"""
    try:
        if not frappe.has_permission("MT940 Import", "submit"):
            frappe.throw("Insufficient permissions to submit import")

        doc = frappe.get_doc("MT940 Import", import_name)

        if doc.docstatus != 0:
            frappe.throw("Document is already submitted or cancelled")

        doc.submit()

        return {"success": True, "message": f"Import {import_name} submitted successfully"}

    except Exception as e:
        frappe.log_error(f"Error submitting import {import_name}: {str(e)}", "MT940 Import Submit")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_mollie_bulk_import_history(days=30):
    """Get history of Mollie bulk imports"""
    try:
        from frappe.utils import add_days, getdate

        from_date = add_days(getdate(), -int(days))

        imports = frappe.get_all(
            "MT940 Import",
            filters={"import_type": "Mollie Bulk Import", "creation": [">=", from_date]},
            fields=[
                "name",
                "descriptive_name",
                "import_date",
                "import_status",
                "transactions_created",
                "transactions_skipped",
                "import_summary",
                "mollie_from_date",
                "mollie_to_date",
                "mollie_import_strategy",
            ],
            order_by="creation desc",
        )

        return imports

    except Exception as e:
        return [{"error": str(e)}]
