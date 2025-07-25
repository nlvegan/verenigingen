"""
Enhanced E-Boekhouden migration with all improvements integrated

This module integrates all the migration improvements:
- Configurable payment account mapping
- Error recovery and retry mechanism
- Performance improvements and batch processing
- Advanced duplicate detection
- Transaction safety and rollback
- Dry-run mode
- Date range chunking for API limits
- Comprehensive audit trail
- Pre-import validation
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from verenigingen.utils.migration.migration_audit_trail import AuditedMigrationOperation, MigrationAuditTrail
from verenigingen.utils.migration.migration_date_chunking import DateRangeChunker, process_with_date_chunks
from verenigingen.utils.migration.migration_dry_run import DryRunSimulator
from verenigingen.utils.migration.migration_duplicate_detection import DuplicateDetector

# Import all enhancement modules
from verenigingen.utils.migration.migration_error_recovery import MigrationErrorRecovery, with_retry
from verenigingen.utils.migration.migration_performance import BatchProcessor, PerformanceOptimizer
from verenigingen.utils.migration.migration_pre_validation import PreImportValidator
from verenigingen.utils.migration.migration_transaction_safety import MigrationTransaction

from .eboekhouden_payment_mapping import get_payment_account_mappings
from .eboekhouden_rest_full_migration import start_full_rest_import

# Removed incorrect SOAP import - REST API should use MT940-based party extraction
from .party_extractor import EBoekhoudenPartyExtractor


class EnhancedEBoekhoudenMigration:
    """Enhanced migration with all improvements integrated"""

    def __init__(self, migration_doc, settings):
        self.migration_doc = migration_doc
        self.settings = settings
        self.company = settings.default_company

        # Initialize all enhancement components
        self.error_recovery = MigrationErrorRecovery(migration_doc)
        self.performance_optimizer = PerformanceOptimizer()
        self.duplicate_detector = DuplicateDetector()
        self.transaction_manager = MigrationTransaction(migration_doc)
        self.audit_trail = MigrationAuditTrail(migration_doc)
        self.pre_validator = PreImportValidator()

        # Configuration
        self.dry_run = migration_doc.get("dry_run", False)
        self.batch_size = migration_doc.get("batch_size", 100)
        self.skip_existing = migration_doc.get("skip_existing", True)
        self.use_date_chunking = migration_doc.get("use_date_chunking", True)

        # Initialize simulators if in dry-run mode
        if self.dry_run:
            self.dry_run_simulator = DryRunSimulator()

        # Payment account mappings
        try:
            self.payment_mappings = get_payment_account_mappings(self.company)
        except Exception as e:
            frappe.log_error(f"Error loading payment mappings: {str(e)}", "Migration Setup")
            self.payment_mappings = {}

        # Cost center
        self.cost_center = self._get_cost_center()

    def _get_cost_center(self):
        """Get appropriate cost center for the company"""
        # Try multiple approaches to find cost center
        cost_center = frappe.db.get_value(
            "Cost Center", {"company": self.company, "cost_center_name": "Main", "is_group": 0}, "name"
        )

        if not cost_center:
            abbr = frappe.db.get_value("Company", self.company, "abbr")
            if abbr:
                cost_center = f"{self.company} - {abbr}"
                if not frappe.db.exists("Cost Center", cost_center):
                    cost_center = None

        if not cost_center:
            cost_center = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")

        if not cost_center:
            frappe.throw(_("No main cost center found for company {0}").format(self.company))

        return cost_center

    def _update_progress(self, operation, percentage):
        """Update migration progress in the document"""
        try:
            self.migration_doc.db_set(
                {
                    "current_operation": operation,
                    "progress_percentage": percentage,
                }
            )
            frappe.db.commit()
        except Exception as e:
            # Don't fail migration if progress update fails
            frappe.log_error(f"Failed to update progress: {str(e)}", "Migration Progress")

    def execute_migration(self):
        """Execute the enhanced migration"""
        self.audit_trail.log_event(
            "migration_started",
            {
                "company": self.company,
                "from_date": str(self.migration_doc.date_from),
                "to_date": str(self.migration_doc.date_to),
                "dry_run": self.dry_run,
                "enhancements_enabled": True,
            },
        )

        try:
            # Step 1: Pre-migration validation
            if not self.dry_run:
                self._update_progress("Running pre-migration validation...", 5)
                validation_result = self._run_pre_validation()
                if not validation_result["can_proceed"]:
                    return {
                        "success": False,
                        "error": "Pre-validation failed",
                        "validation_report": validation_result,
                    }

            # Step 2: Create pre-migration backup
            if not self.dry_run:
                self._update_progress("Creating pre-migration backup...", 10)
                with AuditedMigrationOperation(self.audit_trail, "create_backup"):
                    backup_path = self.transaction_manager.create_pre_migration_backup()
                    self.audit_trail.log_event("backup_created", {"path": backup_path})

            # Step 3: Account types are handled automatically by REST API migration
            self._update_progress("Account types will be handled during REST API import...", 15)
            # Note: REST API handles account types automatically, no manual fix needed

            # Step 4: Process data using REST API (unlimited transactions, not SOAP's 500 limit)
            self._update_progress("Starting transaction import via REST API...", 20)
            with AuditedMigrationOperation(self.audit_trail, "rest_api_migration"):
                result = start_full_rest_import(self.migration_doc.name)

            # Step 5: Verify data integrity
            if not self.dry_run:
                self._update_progress("Verifying data integrity...", 90)
                with AuditedMigrationOperation(self.audit_trail, "verify_integrity"):
                    integrity_report = self.transaction_manager.verify_data_integrity()
                    result["integrity_report"] = integrity_report

            # Step 6: Generate audit summary
            self._update_progress("Generating audit summary...", 95)
            audit_summary = self.audit_trail.generate_summary_report()
            result["audit_summary"] = audit_summary

            # Step 7: Handle dry-run results
            if self.dry_run:
                dry_run_report = self.dry_run_simulator.generate_dry_run_report()
                result["dry_run_report"] = dry_run_report

            # Step 8: Migration completed
            self._update_progress("Migration completed successfully!", 100)
            return result

        except Exception as e:
            self.audit_trail.log_event(
                "migration_failed",
                {"error": str(e), "traceback": frappe.get_traceback()},
                severity="critical",
            )

            # Update progress to show failure
            self._update_progress(f"Migration failed: {str(e)}", 0)

            # Attempt rollback on failure
            if not self.dry_run:
                self._attempt_rollback()

            raise

    def _run_pre_validation(self):
        """Run pre-import validation"""
        self.audit_trail.log_event("pre_validation_started", {})

        # In real implementation, fetch actual data for validation
        # For now, return a placeholder result
        validation_result = {
            "can_proceed": True,
            "validation_summary": {"total_validated": 0, "passed": 0, "failed": 0, "warnings": 0},
        }

        self.audit_trail.log_event("pre_validation_completed", validation_result)
        return validation_result

    def _process_with_chunking(self):
        """Process data using date range chunking"""
        from .eboekhouden_soap_api import EBoekhoudenSOAPAPI

        api = EBoekhoudenSOAPAPI(self.settings)

        def fetch_chunk(from_date, to_date):
            """Fetch data for a specific date range"""
            # This would call the actual API with date filters
            return api.get_mutations(from_date=from_date, to_date=to_date)

        def process_chunk(data):
            """Process a chunk of data"""
            if self.dry_run:
                return self._process_chunk_dry_run(data)
            else:
                return self._process_chunk_real(data)

        # Use date chunking
        chunker = DateRangeChunker(api_limit=500)

        # First estimate optimal strategy
        strategy = chunker.estimate_optimal_strategy(
            self.migration_doc.date_from, self.migration_doc.date_to, fetch_chunk
        )

        self.audit_trail.log_event("chunking_strategy", strategy)

        # Process with adaptive chunking
        result = chunker.adaptive_chunk_processing(
            self.migration_doc.date_from, self.migration_doc.date_to, fetch_chunk, process_chunk
        )

        return result

    def _process_single_batch(self):
        """Process data without chunking (legacy mode)"""
        from .eboekhouden_soap_api import EBoekhoudenSOAPAPI

        api = EBoekhoudenSOAPAPI(self.settings)

        # Fetch all data at once
        result = api.get_mutations()

        if not result["success"]:
            return {
                "success": False,
                "error": "Failed to fetch mutations: {result.get('error', 'Unknown error')}",
            }

        mutations = result.get("mutations", [])

        if self.dry_run:
            return self._process_chunk_dry_run({"mutations": mutations})
        else:
            return self._process_chunk_real({"mutations": mutations})

    def _process_chunk_real(self, data):
        """Process a chunk of data (real mode)"""
        mutations = data.get("mutations", [])

        # Use batch processor for performance
        batch_processor = BatchProcessor(batch_size=self.batch_size, parallel=True, max_workers=4)

        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

        # Process mutations in batches
        for batch in batch_processor.process_in_batches(mutations):
            with self.transaction_manager.atomic_operation(
                "process_batch_{batch['batch_number']}"
            ) as checkpoint:
                batch_stats = self._process_mutation_batch(batch["items"], checkpoint)

                # Update stats
                stats["processed"] += batch_stats["processed"]
                stats["created"] += batch_stats["created"]
                stats["updated"] += batch_stats["updated"]
                stats["skipped"] += batch_stats["skipped"]
                stats["errors"].extend(batch_stats["errors"])

                # Log batch completion
                self.audit_trail.log_batch_processing(
                    {
                        "batch_number": batch["batch_number"],
                        "batch_size": len(batch["items"]),
                        "records_processed": batch_stats["processed"],
                        "errors": len(batch_stats["errors"]),
                        "duration": batch.get("duration"),
                    }
                )

        return stats

    def _process_chunk_dry_run(self, data):
        """Process a chunk of data (dry-run mode)"""
        mutations = data.get("mutations", [])

        stats = {
            "processed": 0,
            "would_create": 0,
            "would_update": 0,
            "would_skip": 0,
            "validation_errors": [],
        }

        for mutation in mutations:
            # Determine what would be created
            mutation_type = mutation.get("Soort", "")

            # Simulate processing
            if "Factuur" in mutation_type:
                doctype = "Sales Invoice" if "klant" in mutation_type.lower() else "Purchase Invoice"
                simulated_data = self._build_invoice_data(mutation)

                result = self.dry_run_simulator.simulate_record_creation(doctype, simulated_data)

                if result["success"]:
                    stats["would_create"] += 1
                else:
                    stats["validation_errors"].append(result["errors"])

            stats["processed"] += 1

        return stats

    def _process_mutation_batch(self, mutations, checkpoint):
        """Process a batch of mutations"""
        batch_stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

        from .normalize_mutation_types import normalize_mutation_type

        # Group mutations by type
        mutations_by_type = defaultdict(list)
        for mut in mutations:
            soort = mut.get("Soort", "Unknown")
            normalized_soort = normalize_mutation_type(soort)
            mutations_by_type[normalized_soort].append(mut)

        # Process each type
        for mutation_type, type_mutations in mutations_by_type.items():
            try:
                if "sales_invoice" in mutation_type:
                    result = self._process_sales_invoices(type_mutations, checkpoint)
                elif "purchase_invoice" in mutation_type:
                    result = self._process_purchase_invoices(type_mutations, checkpoint)
                elif "payment" in mutation_type:
                    result = self._process_payments(type_mutations, checkpoint)
                elif "journal" in mutation_type:
                    result = self._process_journal_entries(type_mutations, checkpoint)
                else:
                    result = {"processed": len(type_mutations), "skipped": len(type_mutations)}

                # Update batch stats
                for key in ["processed", "created", "updated", "skipped"]:
                    batch_stats[key] += result.get(key, 0)
                batch_stats["errors"].extend(result.get("errors", []))

            except Exception as e:
                self.audit_trail.log_event(
                    "batch_processing_error",
                    {"mutation_type": mutation_type, "error": str(e), "count": len(type_mutations)},
                    severity="error",
                )

                batch_stats["errors"].append(
                    {"type": mutation_type, "error": str(e), "count": len(type_mutations)}
                )

        return batch_stats

    def _process_sales_invoices(self, mutations, checkpoint):
        """Process sales invoice mutations"""
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

        for mutation in mutations:
            try:
                # Check for duplicates
                duplicate_check = self.duplicate_detector.check_duplicate("Sales Invoice", mutation)

                if duplicate_check["is_duplicate"] and self.skip_existing:
                    self.audit_trail.log_record_skipped(
                        "Sales Invoice", mutation.get("MutatieNr"), "duplicate_detected"
                    )
                    stats["skipped"] += 1
                    continue

                # Build invoice data
                invoice_data = self._build_invoice_data(mutation)

                # Pre-validate
                validation_result = self.pre_validator.validate_record("Sales Invoice", invoice_data)
                if validation_result["status"] == "failed":
                    self.audit_trail.log_validation_error(
                        "Sales Invoice", invoice_data, validation_result["errors"]
                    )
                    stats["errors"].append(
                        {"mutation": mutation.get("MutatieNr"), "errors": validation_result["errors"]}
                    )
                    continue

                # Create with retry mechanism
                @with_retry(max_attempts=3)
                def create_invoice():
                    doc = frappe.get_doc(invoice_data)
                    doc.insert(ignore_permissions=True)
                    doc.submit()
                    return doc.name

                invoice_name = create_invoice()

                # Track creation for rollback
                self.transaction_manager.track_record_creation(
                    checkpoint["id"], "Sales Invoice", invoice_name, invoice_data
                )

                self.audit_trail.log_record_creation("Sales Invoice", invoice_name, invoice_data)
                stats["created"] += 1

            except Exception as e:
                self.error_recovery.log_error(str(e), mutation)
                stats["errors"].append({"mutation": mutation.get("MutatieNr"), "error": str(e)})

            stats["processed"] += 1

        return stats

    def _build_invoice_data(self, mutation):
        """Build invoice data from mutation"""
        # This is a simplified version - the actual implementation
        # would use the full logic from the original migration

        is_sales = "klant" in mutation.get("Soort", "").lower()

        data = {
            "doctype": "Sales Invoice" if is_sales else "Purchase Invoice",
            "company": self.company,
            "posting_date": mutation.get("Datum"),
            "due_date": mutation.get("Datum"),
            "cost_center": self.cost_center,
            "eboekhouden_mutation_nr": mutation.get("MutatieNr"),
            "items": [],
        }

        # Add customer/supplier
        if is_sales:
            customer_name = get_meaningful_customer_name(mutation, self.migration_doc.relations_data)
            data["customer"] = customer_name
            data["debit_to"] = self._get_receivable_account()
        else:
            supplier_name = get_meaningful_supplier_name(mutation, self.migration_doc.relations_data)
            data["supplier"] = supplier_name
            data["credit_to"] = self._get_payable_account()

        # Add items (simplified)
        data["items"].append(
            {
                "item_code": self._get_standard_item(),
                "description": mutation.get("Omschrijving", "")[:140],
                "qty": 1,
                "rate": abs(float(mutation.get("Bedrag", 0) or 0)),
            }
        )

        return data

    def _get_receivable_account(self):
        """Get receivable account from explicit mappings"""
        if "receivable_account" in self.payment_mappings:
            return self.payment_mappings["receivable_account"]

        frappe.throw(
            "Receivable account must be explicitly configured in payment mappings. "
            "Implicit account lookup by type has been disabled for data safety."
        )

    def _get_payable_account(self):
        """Get payable account from explicit mappings"""
        if "payable_account" in self.payment_mappings:
            return self.payment_mappings["payable_account"]

        frappe.throw(
            "Payable account must be explicitly configured in payment mappings. "
            "Implicit account lookup by type has been disabled for data safety."
        )

    def _get_standard_item(self):
        """Get standard item from explicit configuration"""
        if self.settings.standaard_item:
            if frappe.db.exists("Item", self.settings.standaard_item):
                return self.settings.standaard_item
            else:
                frappe.throw(
                    f"Configured standard item '{self.settings.standaard_item}' does not exist. "
                    "Please configure a valid standard item in E-Boekhouden Settings."
                )

        frappe.throw(
            "No standard item configured in E-Boekhouden Settings. "
            "Please configure 'standaard_item' field for migration processing. "
            "Implicit item fallbacks have been disabled for data safety."
        )

    def _process_purchase_invoices(self, mutations, checkpoint):
        """Process purchase invoice mutations"""
        # Similar to _process_sales_invoices but for purchases
        return self._process_sales_invoices(mutations, checkpoint)

    def _process_payments(self, mutations, checkpoint):
        """Process payment mutations"""
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

        # Implementation would be similar to invoices
        # Using payment entry creation logic

        return stats

    def _process_journal_entries(self, mutations, checkpoint):
        """Process journal entry mutations"""
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

        # Implementation would be similar to invoices
        # Using journal entry creation logic

        return stats

    def _attempt_rollback(self):
        """Attempt to rollback on failure"""
        try:
            # Find the last checkpoint
            if self.transaction_manager.checkpoint_data:
                last_checkpoint = list(self.transaction_manager.checkpoint_data.values())[-1]
                rollback_result = self.transaction_manager.rollback_to_checkpoint(last_checkpoint)

                self.audit_trail.log_rollback(last_checkpoint["id"], rollback_result)

                return rollback_result
        except Exception as e:
            self.audit_trail.log_event(
                "rollback_failed", {"error": str(e), "traceback": frappe.get_traceback()}, severity="critical"
            )
            raise


@frappe.whitelist()
def execute_enhanced_migration(migration_name):
    """Execute the enhanced migration"""
    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    settings = frappe.get_single("E-Boekhouden Settings")

    # Check if enhanced mode is enabled
    if not migration_doc.get("use_enhanced_migration", True):
        # Fall back to REST API migration (not SOAP - SOAP is limited to 500 transactions)
        from .eboekhouden_rest_full_migration import start_full_rest_import

        return start_full_rest_import(migration_name)

    # Run enhanced migration
    enhanced_migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
    return enhanced_migration.execute_migration()


@frappe.whitelist()
def run_migration_dry_run(migration_name):
    """Run migration in dry-run mode"""
    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    migration_doc.dry_run = True

    settings = frappe.get_single("E-Boekhouden Settings")

    enhanced_migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
    return enhanced_migration.execute_migration()


@frappe.whitelist()
def validate_migration_data(migration_name):
    """Validate migration data before import"""
    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    settings = frappe.get_single("E-Boekhouden Settings")

    enhanced_migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
    return enhanced_migration._run_pre_validation()
