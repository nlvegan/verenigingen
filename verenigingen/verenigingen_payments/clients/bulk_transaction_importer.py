"""
Mollie Bulk Transaction Importer
Hybrid bulk import combining Balance Transactions and Individual Payments
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import formatdate, getdate

from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.compliance.audit_trail import ImmutableAuditTrail as AuditTrail
from ..core.mollie_base_client import MollieBaseClient
from .balances_client import BalancesClient
from .payments_client import PaymentsClient
from .settlements_client import SettlementsClient


class BulkTransactionImporter(MollieBaseClient):
    """
    Bulk transaction importer for Mollie backend data

    Provides:
    - Hybrid data fetching (settlements + individual payments)
    - Historical transaction backfill
    - Gap detection and reconciliation
    - Integration with existing reconciliation engine
    - Performance-optimized bulk processing
    """

    def __init__(self):
        """Initialize bulk importer with required clients"""
        super().__init__()
        self.audit_trail = AuditTrail()

        # Initialize API clients
        self.balances_client = BalancesClient()
        self.settlements_client = SettlementsClient()
        self.payments_client = PaymentsClient()

        # Track import state
        self.import_id = None
        self.start_time = None
        self.errors = []
        self.warnings = []
        self.imported_transactions = []

    def import_transactions(
        self,
        from_date: datetime,
        to_date: datetime,
        import_strategy: str = "hybrid",
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
    ) -> Dict:
        """
        Import transactions for a date range using specified strategy

        Args:
            from_date: Start date for import
            to_date: End date for import
            import_strategy: "settlements", "payments", or "hybrid"
            company: Company to import for
            bank_account: Bank account to link transactions to

        Returns:
            Dict with import results
        """
        # 🔍 DEBUG: Log import_transactions parameters
        frappe.logger().error("🔍 import_transactions called with:")
        frappe.logger().error(f"🔍   from_date: {from_date}")
        frappe.logger().error(f"🔍   to_date: {to_date}")
        frappe.logger().error(f"🔍   import_strategy: '{import_strategy}'")
        frappe.logger().error(f"🔍   company: '{company}'")
        frappe.logger().error(f"🔍   bank_account: '{bank_account}'")

        self.import_id = frappe.generate_hash(length=10)
        self.start_time = datetime.now()
        self.errors = []
        self.warnings = []
        self.imported_transactions = []

        self.audit_trail.log_event(
            AuditEventType.SETTLEMENT_PROCESSED,
            AuditSeverity.INFO,
            f"Starting bulk transaction import: {self.import_id}",
            details={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "strategy": import_strategy,
            },
        )

        results = {
            "import_id": self.import_id,
            "start_time": self.start_time.isoformat(),
            "strategy": import_strategy,
            "company": company,  # ✅ Add missing company parameter
            "bank_account": bank_account,  # ✅ Add missing bank_account parameter
            "date_range": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            "status": "in_progress",
            "transactions": {
                "settlements_imported": 0,
                "payments_imported": 0,
                "duplicates_skipped": 0,
                "errors": 0,
            },
        }

        try:
            if import_strategy in ["settlements", "hybrid"]:
                # Import settlement/balance transaction data
                settlement_results = self._import_settlement_data(from_date, to_date, company, bank_account)
                results["transactions"]["settlements_imported"] = settlement_results.get("imported", 0)

                if settlement_results.get("errors"):
                    self.errors.extend(settlement_results["errors"])
                if settlement_results.get("warnings"):
                    self.warnings.extend(settlement_results["warnings"])

            if import_strategy in ["payments", "hybrid"]:
                # Import individual payment data
                payment_results = self._import_payment_data(from_date, to_date, company, bank_account)
                results["transactions"]["payments_imported"] = payment_results.get("imported", 0)
                results["transactions"]["duplicates_skipped"] += payment_results.get("duplicates_skipped", 0)

                if payment_results.get("errors"):
                    self.errors.extend(payment_results["errors"])
                if payment_results.get("warnings"):
                    self.warnings.extend(payment_results["warnings"])

            # Determine overall status
            if self.errors:
                results["status"] = "completed_with_errors"
            elif self.warnings:
                results["status"] = "completed_with_warnings"
            else:
                results["status"] = "completed"

        except Exception as e:
            results["status"] = "failed"
            results["error"] = str(e)
            self.errors.append(str(e))

            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED,
                AuditSeverity.ERROR,
                f"Bulk import failed: {str(e)}",
                details={"import_id": self.import_id},
            )

        finally:
            # Finalize results
            results["end_time"] = datetime.now().isoformat()
            results["duration_seconds"] = (datetime.now() - self.start_time).total_seconds()
            results["errors"] = self.errors
            results["warnings"] = self.warnings
            results["transactions"]["total_imported"] = (
                results["transactions"]["settlements_imported"] + results["transactions"]["payments_imported"]
            )
            results["transactions"]["errors"] = len(self.errors)

            # Save import record with debug logging
            frappe.log_error(
                f"DEBUG: About to call _save_import_record with bank_account='{results.get('bank_account')}'",
                "Debug Before Save",
            )
            self._save_import_record(results)

        return results

    def _import_settlement_data(
        self,
        from_date: datetime,
        to_date: datetime,
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
    ) -> Dict:
        """
        Import settlement/balance transaction data for bulk historical import

        Args:
            from_date: Start date
            to_date: End date
            company: Company to import for
            bank_account: Bank account to link to

        Returns:
            Dict with settlement import results
        """
        results = {"imported": 0, "skipped": 0, "errors": [], "warnings": []}

        try:
            # Get settlements for the date range
            settlements = self.settlements_client.get_settlements_by_date_range(
                from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")
            )

            frappe.logger().info(f"Found {len(settlements)} settlements for bulk import")

            for settlement in settlements:
                try:
                    # Process each settlement
                    settlement_result = self._process_settlement_for_import(settlement, company, bank_account)

                    if settlement_result.get("imported"):
                        results["imported"] += settlement_result["imported"]
                    if settlement_result.get("skipped"):
                        results["skipped"] += settlement_result["skipped"]

                except Exception as e:
                    error_msg = f"Error processing settlement {settlement.get('id', 'unknown')}: {str(e)}"
                    results["errors"].append(error_msg)
                    frappe.log_error(error_msg, "Bulk Settlement Import")

        except Exception as e:
            results["errors"].append(f"Settlement data import failed: {str(e)}")
            frappe.log_error(f"Settlement bulk import error: {str(e)}", "Bulk Transaction Import")

        return results

    def _import_payment_data(
        self,
        from_date: datetime,
        to_date: datetime,
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
    ) -> Dict:
        """
        Import individual payment data for detailed transaction records

        Args:
            from_date: Start date
            to_date: End date
            company: Company to import for
            bank_account: Bank account to link to

        Returns:
            Dict with payment import results
        """
        results = {"imported": 0, "duplicates_skipped": 0, "errors": [], "warnings": []}

        try:
            # Convert naive datetime objects to timezone-aware (UTC) for proper comparison
            from datetime import timezone

            # Handle timezone conversion with logging for audit trail
            if from_date.tzinfo is None:
                from_date_tz = from_date.replace(tzinfo=timezone.utc)
                frappe.logger().info(f"Converting naive from_date {from_date} to UTC: {from_date_tz}")
            else:
                from_date_tz = from_date

            if to_date.tzinfo is None:
                to_date_tz = to_date.replace(tzinfo=timezone.utc)
                frappe.logger().info(f"Converting naive to_date {to_date} to UTC: {to_date_tz}")
            else:
                to_date_tz = to_date

            # Get payments for the date range
            payments = self.payments_client.list_payments(from_date=from_date_tz, to_date=to_date_tz)

            frappe.logger().info(f"Found {len(payments)} payments for bulk import")

            # Process in batches for large datasets
            batch_size = 100  # Process 100 transactions at a time
            total_batches = (len(payments) + batch_size - 1) // batch_size

            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min((batch_num + 1) * batch_size, len(payments))
                batch_payments = payments[start_idx:end_idx]

                frappe.logger().info(
                    f"Processing batch {batch_num + 1}/{total_batches} ({len(batch_payments)} payments)"
                )

                for payment in batch_payments:
                    try:
                        # Create transaction data for duplicate checking
                        transaction_data = {
                            "custom_mollie_payment_id": payment.get("id"),
                            "date": datetime.fromisoformat(
                                payment.get("createdAt", "").replace("Z", "+00:00")
                            ).date(),
                            "deposit": float(payment.get("amount", {}).get("value", "0"))
                            if float(payment.get("amount", {}).get("value", "0")) > 0
                            else 0,
                            "withdrawal": abs(float(payment.get("amount", {}).get("value", "0")))
                            if float(payment.get("amount", {}).get("value", "0")) < 0
                            else 0,
                            "reference_number": payment.get("id"),
                        }

                        # Enhanced duplicate detection
                        if self._validate_duplicate_transaction(transaction_data):
                            results["duplicates_skipped"] += 1
                            continue

                        # Process payment for import
                        payment_result = self._process_payment_for_import(payment, company, bank_account)

                        if payment_result.get("imported"):
                            results["imported"] += 1
                            self.imported_transactions.append(payment_result["transaction"])

                    except (ValueError, TypeError) as e:
                        error_msg = (
                            f"Data validation error for payment {payment.get('id', 'unknown')}: {str(e)}"
                        )
                        results["errors"].append(error_msg)
                        frappe.log_error(error_msg, "Payment Data Validation")
                    except frappe.PermissionError as e:
                        error_msg = (
                            f"Permission error processing payment {payment.get('id', 'unknown')}: {str(e)}"
                        )
                        results["errors"].append(error_msg)
                        frappe.log_error(error_msg, "Payment Permission Error")
                    except Exception as e:
                        error_msg = (
                            f"Unexpected error processing payment {payment.get('id', 'unknown')}: {str(e)}"
                        )
                        results["errors"].append(error_msg)
                        frappe.log_error(error_msg, "Bulk Payment Import")

                # Commit batch to database
                frappe.db.commit()
                frappe.logger().info(f"Completed batch {batch_num + 1}/{total_batches}")

        except (ConnectionError, TimeoutError) as e:
            results["errors"].append(f"Network error during payment import: {str(e)}")
            frappe.log_error(f"Network error in payment bulk import: {str(e)}", "Bulk Payment Network Error")
        except frappe.ValidationError as e:
            results["errors"].append(f"Validation error: {str(e)}")
            frappe.log_error(f"Validation error in payment bulk import: {str(e)}", "Bulk Payment Validation")
        except Exception as e:
            results["errors"].append(f"Payment data import failed: {str(e)}")
            frappe.log_error(f"Payment bulk import error: {str(e)}", "Bulk Transaction Import")

        return results

    def _process_settlement_for_import(
        self, settlement: Dict, company: Optional[str] = None, bank_account: Optional[str] = None
    ) -> Dict:
        """
        Process a single settlement for import

        Args:
            settlement: Settlement data from Mollie API
            company: Company to import for
            bank_account: Bank account to link to

        Returns:
            Dict with processing results
        """
        result = {"imported": 0, "skipped": 0}

        try:
            settlement_id = settlement.get("id")
            settlement_date = settlement.get("settledAt")

            if not settlement_date:
                return {"skipped": 1, "reason": "No settlement date"}

            # Parse settlement date
            from datetime import datetime

            settled_at = datetime.fromisoformat(settlement_date.replace("Z", "+00:00"))

            # Create Bank Transaction for the settlement
            bank_transaction = self._create_bank_transaction_from_settlement(
                settlement, settled_at, company, bank_account
            )

            if bank_transaction:
                result["imported"] = 1
                result["transaction"] = bank_transaction.name

                # Log successful import
                frappe.logger().info(
                    f"Imported settlement {settlement_id} as Bank Transaction {bank_transaction.name}"
                )
            else:
                result["skipped"] = 1
                result["reason"] = "Failed to create bank transaction"

        except Exception as e:
            frappe.log_error(f"Settlement processing error: {str(e)}", "Bulk Settlement Processing")
            result["error"] = str(e)

        return result

    def _process_payment_for_import(
        self, payment: Dict, company: Optional[str] = None, bank_account: Optional[str] = None
    ) -> Dict:
        """
        Process a single payment for import

        Args:
            payment: Payment data from Mollie API
            company: Company to import for
            bank_account: Bank account to link to

        Returns:
            Dict with processing results
        """
        result = {"imported": False}

        try:
            payment_id = payment.get("id")
            created_at = payment.get("createdAt")

            if not created_at:
                return {"error": "No payment date"}

            # Parse payment date
            payment_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

            # Create Bank Transaction for the payment
            bank_transaction = self._create_bank_transaction_from_payment(
                payment, payment_date, company, bank_account
            )

            if bank_transaction:
                result["imported"] = True
                result["transaction"] = bank_transaction.name

                frappe.logger().info(
                    f"Imported payment {payment_id} as Bank Transaction {bank_transaction.name}"
                )

        except Exception as e:
            frappe.log_error(f"Payment processing error: {str(e)}", "Bulk Payment Processing")
            result["error"] = str(e)

        return result

    def _create_bank_transaction_from_settlement(
        self,
        settlement: Dict,
        settlement_date: datetime,
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
    ) -> Optional[object]:
        """
        Create Bank Transaction from settlement data

        Args:
            settlement: Settlement data from Mollie
            settlement_date: When settlement occurred
            company: Company to link to
            bank_account: Bank account to link to

        Returns:
            Bank Transaction document or None
        """
        try:
            # Get default company and bank account if not provided
            if not company:
                company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
                    "Global Defaults", "default_company"
                )

            if not bank_account:
                # Get first active bank account for the company
                bank_account = frappe.db.get_value(
                    "Bank Account", {"company": company, "is_default": 1}, "name"
                )
                if not bank_account:
                    bank_account = frappe.db.get_value("Bank Account", {"company": company}, "name")

            if not bank_account:
                frappe.logger().warning("No bank account found for settlement import")
                return None

            # Create Bank Transaction
            bank_transaction = frappe.new_doc("Bank Transaction")
            bank_transaction.update(
                {
                    "date": settlement_date.date(),
                    "bank_account": bank_account,
                    "company": company,
                    "deposit": float(settlement.get("amount", {}).get("value", "0")),
                    "withdrawal": 0,
                    "currency": settlement.get("amount", {}).get("currency", "EUR"),
                    "description": f"Mollie Settlement {settlement.get('reference', settlement.get('id', ''))}",
                    "reference_number": settlement.get("id"),
                    "transaction_type": "Mollie Settlement",
                    # Add Mollie-specific fields
                    "custom_mollie_settlement_id": settlement.get("id"),
                    "custom_mollie_reference": settlement.get("reference"),
                    "custom_mollie_import_source": "Bulk Import",
                    "custom_import_batch_id": self.import_id,
                }
            )

            # Validate permissions before creating financial records
            if not frappe.has_permission("Bank Transaction", "create"):
                raise frappe.PermissionError("Insufficient permissions to create Bank Transaction")

            # Validate custom fields exist before using them
            self._validate_mollie_custom_fields()

            bank_transaction.insert()

            # Submit only if user has submit permissions
            if frappe.has_permission("Bank Transaction", "submit"):
                bank_transaction.submit()
            else:
                frappe.logger().info(
                    f"Bank Transaction {bank_transaction.name} created but not submitted - no submit permission"
                )

            return bank_transaction

        except Exception as e:
            frappe.log_error(
                f"Error creating bank transaction from settlement: {str(e)}", "Bulk Settlement Import"
            )
            return None

    def _create_bank_transaction_from_payment(
        self,
        payment: Dict,
        payment_date: datetime,
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
    ) -> Optional[object]:
        """
        Create Bank Transaction from individual payment data

        Args:
            payment: Payment data from Mollie
            payment_date: When payment occurred
            company: Company to link to
            bank_account: Bank account to link to

        Returns:
            Bank Transaction document or None
        """
        try:
            # Get default company and bank account if not provided
            if not company:
                company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
                    "Global Defaults", "default_company"
                )

            if not bank_account:
                # Get first active bank account for the company
                bank_account = frappe.db.get_value(
                    "Bank Account", {"company": company, "is_default": 1}, "name"
                )
                if not bank_account:
                    bank_account = frappe.db.get_value("Bank Account", {"company": company}, "name")

            if not bank_account:
                frappe.logger().warning("No bank account found for payment import")
                return None

            # Determine amount and direction
            amount = float(payment.get("amount", {}).get("value", "0"))
            deposit = amount if amount > 0 else 0
            withdrawal = abs(amount) if amount < 0 else 0

            # Create Bank Transaction
            bank_transaction = frappe.new_doc("Bank Transaction")
            bank_transaction.update(
                {
                    "date": payment_date.date(),
                    "bank_account": bank_account,
                    "company": company,
                    "deposit": deposit,
                    "withdrawal": withdrawal,
                    "currency": payment.get("amount", {}).get("currency", "EUR"),
                    "description": payment.get("description", f"Mollie Payment {payment.get('id', '')}"),
                    "reference_number": payment.get("id"),
                    "transaction_type": "Mollie Payment",
                    # Add Mollie-specific fields
                    "custom_mollie_payment_id": payment.get("id"),
                    "custom_mollie_status": payment.get("status"),
                    "custom_mollie_method": payment.get("method"),
                    "custom_mollie_import_source": "Bulk Import",
                    "custom_import_batch_id": self.import_id,
                }
            )

            # Validate permissions before creating financial records
            if not frappe.has_permission("Bank Transaction", "create"):
                raise frappe.PermissionError("Insufficient permissions to create Bank Transaction")

            # Validate custom fields exist before using them
            self._validate_mollie_custom_fields()

            bank_transaction.insert()

            # Submit only if user has submit permissions
            if frappe.has_permission("Bank Transaction", "submit"):
                bank_transaction.submit()
            else:
                frappe.logger().info(
                    f"Bank Transaction {bank_transaction.name} created but not submitted - no submit permission"
                )

            return bank_transaction

        except Exception as e:
            frappe.log_error(f"Error creating bank transaction from payment: {str(e)}", "Bulk Payment Import")
            return None

    def _check_existing_payment_transaction(self, payment: Dict) -> bool:
        """
        Check if a payment has already been imported to avoid duplicates

        Args:
            payment: Payment data from Mollie

        Returns:
            True if payment already exists, False otherwise
        """
        try:
            payment_id = payment.get("id")
            if not payment_id:
                return False

            # Check for existing Bank Transaction with this payment ID
            existing = frappe.db.exists(
                "Bank Transaction", {"custom_mollie_payment_id": payment_id, "docstatus": 1}
            )

            return bool(existing)

        except Exception as e:
            frappe.logger().warning(f"Error checking for existing payment: {str(e)}")
            return False

    def _validate_mollie_custom_fields(self):
        """
        Validate that required Mollie custom fields exist on Bank Transaction DocType

        Raises:
            ValidationError if required fields are missing
        """
        required_fields = [
            "custom_mollie_settlement_id",
            "custom_mollie_payment_id",
            "custom_mollie_reference",
            "custom_mollie_status",
            "custom_mollie_method",
            "custom_mollie_import_source",
            "custom_import_batch_id",
        ]

        # Get Bank Transaction DocType meta
        try:
            bank_transaction_meta = frappe.get_meta("Bank Transaction")
            existing_fields = [field.fieldname for field in bank_transaction_meta.fields]

            missing_fields = []
            for field in required_fields:
                if field not in existing_fields:
                    missing_fields.append(field)

            if missing_fields:
                error_msg = (
                    f"Missing required custom fields on Bank Transaction DocType: {', '.join(missing_fields)}"
                )
                frappe.log_error(error_msg, "Mollie Bulk Import Validation")
                raise frappe.ValidationError(error_msg)

        except Exception as e:
            if "ValidationError" in str(type(e)):
                raise  # Re-raise validation errors
            frappe.log_error(f"Error validating custom fields: {str(e)}", "Mollie Field Validation")
            # Continue without field validation if meta loading fails

    def _validate_duplicate_transaction(self, transaction_data: Dict) -> bool:
        """
        Enhanced duplicate detection for financial transactions

        Args:
            transaction_data: Transaction data to check

        Returns:
            True if duplicate found, False otherwise
        """
        try:
            # Check multiple criteria for duplicate detection
            filters = []

            # Primary check: Mollie IDs
            mollie_settlement_id = transaction_data.get("custom_mollie_settlement_id")
            mollie_payment_id = transaction_data.get("custom_mollie_payment_id")

            if mollie_settlement_id:
                filters.append({"custom_mollie_settlement_id": mollie_settlement_id})

            if mollie_payment_id:
                filters.append({"custom_mollie_payment_id": mollie_payment_id})

            # Secondary check: amount, date, and reference combination
            amount_filter = {}
            if transaction_data.get("deposit"):
                amount_filter["deposit"] = transaction_data["deposit"]
            if transaction_data.get("withdrawal"):
                amount_filter["withdrawal"] = transaction_data["withdrawal"]

            if amount_filter and transaction_data.get("date") and transaction_data.get("reference_number"):
                filters.append(
                    {
                        **amount_filter,
                        "date": transaction_data["date"],
                        "reference_number": transaction_data["reference_number"],
                        "docstatus": ["!=", 2],  # Not cancelled
                    }
                )

            # Check each filter condition
            for filter_condition in filters:
                existing = frappe.db.exists("Bank Transaction", filter_condition)
                if existing:
                    frappe.logger().info(f"Duplicate transaction found: {existing}")
                    return True

            return False

        except Exception as e:
            frappe.log_error(f"Error in duplicate validation: {str(e)}", "Duplicate Detection")
            # If validation fails, assume no duplicate to avoid blocking imports
            return False

    def _map_strategy_for_doctype(self, strategy: str) -> str:
        """
        Map frontend strategy values to DocType-compatible values

        Args:
            strategy: Strategy from frontend ("payments", "balances", "hybrid")

        Returns:
            DocType-compatible strategy value
        """
        strategy_mapping = {
            "payments": "payments_only",
            "balances": "balances_only",
            "settlements": "balances_only",
            "hybrid": "hybrid",
        }
        return strategy_mapping.get(strategy, "hybrid")

    def _save_import_record(self, results: Dict):
        """
        Save bulk import record for tracking and history

        Args:
            results: Import results dictionary
        """
        try:
            # 🔍 DEBUG: Log the entire results dictionary
            frappe.logger().error(f"🔍 _save_import_record called with results keys: {list(results.keys())}")
            frappe.logger().error(f"🔍 results.get('bank_account'): '{results.get('bank_account')}'")
            frappe.logger().error(f"🔍 results.get('company'): '{results.get('company')}'")

            # 🔍 DEBUG: Check bank account resolution
            bank_account_from_results = results.get("bank_account")
            frappe.logger().error(
                f"🔍 bank_account_from_results: '{bank_account_from_results}' (type: {type(bank_account_from_results)})"
            )

            # Get fallback bank account if needed
            fallback_bank_account = None
            if not bank_account_from_results:
                fallback_bank_account = frappe.db.get_value("Bank Account", {}, "name")
                frappe.logger().error(f"🔍 fallback_bank_account: '{fallback_bank_account}'")

            final_bank_account = bank_account_from_results or fallback_bank_account
            frappe.logger().error(f"🔍 final_bank_account: '{final_bank_account}'")

            # 🔍 DEBUG: Check if bank account exists
            if final_bank_account:
                bank_exists = frappe.db.exists("Bank Account", final_bank_account)
                frappe.logger().error(f"🔍 Bank Account '{final_bank_account}' exists: {bank_exists}")
                if not bank_exists:
                    # List available bank accounts
                    all_banks = frappe.db.get_all("Bank Account", fields=["name", "account_name"])
                    frappe.logger().error(f"🔍 Available Bank Accounts: {all_banks}")

            # Create or update MT940 Import record to track this bulk import
            import_record = frappe.new_doc("MT940 Import")

            # 🔍 DEBUG: Log values before assignment
            company_value = results.get("company", frappe.defaults.get_user_default("Company"))
            frappe.logger().error(
                f"🔍 About to set fields - bank_account: '{final_bank_account}', company: '{company_value}'"
            )

            import_record.update(
                {
                    "import_type": "Mollie Bulk Import",
                    "bank_account": final_bank_account,
                    "company": company_value,
                    "import_date": getdate(),
                    "import_status": results["status"].title().replace("_", " "),
                    "import_summary": f"Bulk import {results['import_id']}: {results['transactions']['total_imported']} transactions imported",
                    "transactions_created": results["transactions"]["total_imported"],
                    "transactions_skipped": results["transactions"]["duplicates_skipped"],
                    "descriptive_name": f"Mollie Bulk Import - {formatdate(getdate())} ({results['transactions']['total_imported']} txns)",
                    "statement_from_date": getdate(results["date_range"]["from"]),
                    "statement_to_date": getdate(results["date_range"]["to"]),
                    # Add required Mollie fields for validation
                    "mollie_from_date": getdate(results["date_range"]["from"]),
                    "mollie_to_date": getdate(results["date_range"]["to"]),
                    "mollie_import_strategy": self._map_strategy_for_doctype(
                        results.get("strategy", "hybrid")
                    ),
                    # Store detailed results in error log field (repurposed as import details)
                    "error_log": frappe.as_json(results, indent=2),
                }
            )

            # 🔍 DEBUG: Log document fields after assignment
            frappe.logger().error("🔍 Document fields after update:")
            frappe.logger().error(f"🔍   import_record.import_type: '{import_record.import_type}'")
            frappe.logger().error(f"🔍   import_record.bank_account: '{import_record.bank_account}'")
            frappe.logger().error(f"🔍   import_record.company: '{import_record.company}'")

            # Check permission to create import records
            if not frappe.has_permission("MT940 Import", "create"):
                frappe.log_error("No permission to create MT940 Import record", "Bulk Import Record")
                return

            # 🔍 DEBUG: Log before validation/insertion
            frappe.logger().error("🔍 About to call import_record.insert()")

            import_record.insert()
            frappe.db.commit()

            frappe.logger().info(f"Saved bulk import record: {import_record.name}")

        except Exception as e:
            frappe.log_error(f"Failed to save bulk import record: {str(e)}", "Bulk Import Record")

    def get_import_history(self, days: int = 30) -> List[Dict]:
        """
        Get history of bulk imports

        Args:
            days: Number of days to look back

        Returns:
            List of import records
        """
        from frappe.utils import add_days

        from_date = add_days(getdate(), -days)

        records = frappe.get_all(
            "MT940 Import",
            filters={"import_date": [">=", from_date], "import_summary": ["like", "%Bulk import%"]},
            fields=[
                "name",
                "descriptive_name",
                "import_date",
                "import_status",
                "transactions_created",
                "transactions_skipped",
                "import_summary",
            ],
            order_by="import_date desc",
        )

        return records

    def estimate_import_size(self, from_date: datetime, to_date: datetime, strategy: str = "hybrid") -> Dict:
        """
        Estimate the size of a bulk import before running it

        Args:
            from_date: Start date
            to_date: End date
            strategy: Import strategy ("settlements", "payments", or "hybrid")

        Returns:
            Dict with size estimates
        """
        estimates = {
            "date_range": {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "days": (to_date - from_date).days,
            },
            "estimated_transactions": 0,
            "strategy": strategy,
            "warnings": [],
        }

        try:
            if strategy in ["settlements", "hybrid"]:
                # Estimate settlements
                settlements = self.settlements_client.get_settlements_by_date_range(
                    from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")
                )
                estimates["settlements_count"] = len(settlements)
                estimates["estimated_transactions"] += len(settlements)

            if strategy in ["payments", "hybrid"]:
                # For payments, we can't easily get count without fetching all
                # Provide rough estimate based on date range
                days = (to_date - from_date).days
                estimated_payments = days * 50  # Rough estimate: 50 payments per day
                estimates["estimated_payments"] = estimated_payments
                estimates["estimated_transactions"] += estimated_payments

                if days > 90:
                    estimates["warnings"].append(
                        f"Large date range ({days} days) may result in slow import. "
                        "Consider splitting into smaller ranges."
                    )

        except Exception as e:
            estimates["error"] = f"Could not estimate import size: {str(e)}"

        return estimates


# API endpoints for bulk import functionality
@frappe.whitelist()
def estimate_bulk_import_size(from_date: str, to_date: str, strategy: str = "hybrid") -> Dict:
    """
    API endpoint to estimate bulk import size

    Args:
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        strategy: Import strategy

    Returns:
        Dict with size estimates
    """
    try:
        from_dt = datetime.fromisoformat(from_date)
        to_dt = datetime.fromisoformat(to_date)

        importer = BulkTransactionImporter()
        return importer.estimate_import_size(from_dt, to_dt, strategy)

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def run_bulk_import(
    from_date: str,
    to_date: str,
    strategy: str = "hybrid",
    company: Optional[str] = None,
    bank_account: Optional[str] = None,
) -> Dict:
    """
    API endpoint to run bulk transaction import

    Args:
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        strategy: Import strategy ("settlements", "payments", or "hybrid")
        company: Company to import for
        bank_account: Bank account to link to

    Returns:
        Dict with import results
    """
    if not frappe.has_permission("Bank Transaction", "create"):
        frappe.throw(_("Insufficient permissions to run bulk import"))

    try:
        from_dt = datetime.fromisoformat(from_date)
        to_dt = datetime.fromisoformat(to_date)

        # Ensure timezone-aware datetimes for proper Mollie API filtering
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=timezone.utc)
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=timezone.utc)

        # Run the import
        importer = BulkTransactionImporter()
        results = importer.import_transactions(from_dt, to_dt, strategy, company, bank_account)

        return results

    except Exception as e:
        frappe.log_error(f"Bulk import API error: {str(e)}", "Bulk Import API")
        return {"status": "failed", "error": str(e)}


@frappe.whitelist()
def get_bulk_import_history(days: int = 30) -> List[Dict]:
    """
    API endpoint to get bulk import history

    Args:
        days: Number of days to look back

    Returns:
        List of import records
    """
    try:
        importer = BulkTransactionImporter()
        return importer.get_import_history(days)

    except Exception as e:
        return [{"error": str(e)}]
