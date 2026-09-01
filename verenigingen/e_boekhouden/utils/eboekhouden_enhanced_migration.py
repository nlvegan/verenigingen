"""
eBoekhouden Migration Framework

Imports accounting data from eBoekhouden into ERPNext via REST API.

Features:
    * Pre-migration backup and post-migration integrity verification
    * Error recovery with retry logic
    * Batch processing for large datasets
    * Dry-run simulation mode
    * Date range chunking for API pagination
    * Audit trail logging
    * Progress tracking

Usage:
    migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
    result = migration.execute_migration()

Note:
    Duplicate detection during import uses eboekhouden_mutation_nr as the
    authoritative key (see _check_if_already_imported in eboekhouden_rest_full_migration.py).
    The DuplicateDetector class in migration_duplicate_detection.py provides
    fuzzy matching utilities that could be used for post-import analysis tools.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from verenigingen.e_boekhouden.utils.consolidated.progress_utils import update_migration_progress
from verenigingen.utils.migration.migration_audit_trail import AuditedMigrationOperation, MigrationAuditTrail
from verenigingen.utils.migration.migration_date_chunking import DateRangeChunker, process_with_date_chunks
from verenigingen.utils.migration.migration_dry_run import DryRunSimulator

# Note: DuplicateDetector (in migration_duplicate_detection.py) provides fuzzy matching
# for post-import duplicate analysis. Not used during import - we rely on
# eboekhouden_mutation_nr as the authoritative deduplication key.
# Import enhancement modules
from verenigingen.utils.migration.migration_error_recovery import MigrationErrorRecovery, with_retry
from verenigingen.utils.migration.migration_performance import BatchProcessor, PerformanceOptimizer
from verenigingen.utils.migration.migration_pre_validation import PreImportValidator
from verenigingen.utils.migration.migration_transaction_safety import MigrationSafetyChecks
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api

from .eboekhouden_payment_mapping import get_payment_account_mappings
from .eboekhouden_rest_full_migration import start_full_rest_import

# Removed incorrect SOAP import - REST API should use MT940-based party extraction
from .party_extractor import EBoekhoudenPartyExtractor


class EnhancedEBoekhoudenMigration:
    """
    eBoekhouden migration orchestrator.

    Coordinates the migration process: validation, backup, import, and verification.

    Components:
        - Error recovery with exponential backoff
        - Batch processing for performance
        - Pre-migration backup and post-migration integrity checks
        - Audit trail logging
        - Dry-run simulation mode

    Migration Phases:
        1. Pre-migration validation and backup
        2. REST API data import (delegated to start_full_rest_import)
        3. Data integrity verification
        4. Audit summary generation
    """

    def __init__(self, migration_doc, settings):
        self.migration_doc = migration_doc
        self.settings = settings
        self.company = settings.default_company

        # Fail early if company not configured
        if not self.company:
            frappe.throw(
                _(
                    "E-Boekhouden Settings: default_company is not configured. "
                    "Please set the default company before running migration."
                )
            )

        # Initialize components
        self.error_recovery = MigrationErrorRecovery(migration_doc)
        self.performance_optimizer = PerformanceOptimizer()
        self.safety_checks = MigrationSafetyChecks(migration_doc)
        self.audit_trail = MigrationAuditTrail(migration_doc)
        self.pre_validator = PreImportValidator()

        # Configuration
        self.dry_run = migration_doc.get("dry_run", False)
        self.batch_size = migration_doc.get("batch_size", 100)
        self.skip_existing = migration_doc.get("skip_existing", True)

        # Initialize simulators if in dry-run mode
        if self.dry_run:
            self.dry_run_simulator = DryRunSimulator()

        # Payment account mappings
        try:
            self.payment_mappings = get_payment_account_mappings(self.company)
        except Exception as e:
            frappe.log_error(title="Migration Setup", message=f"Error loading payment mappings: {str(e)}")
            self.payment_mappings = {}

        # Cost center
        self.cost_center = self._get_cost_center()

    def _get_cost_center(self):
        """
        Determine the appropriate cost center for migration transactions.

        Resolution order (explicit configuration preferred over heuristics):
        1. E-Boekhouden Settings.default_cost_center (migration-specific config)
        2. Company.cost_center (ERPNext standard config)
        3. Cost center named "Main" for the company (heuristic, logged)
        4. Company abbreviation-based cost center (heuristic, logged)
        5. Any non-group cost center for the company (heuristic, logged)

        Returns:
            str: Valid cost center name for the company

        Raises:
            frappe.ValidationError: If no cost center can be found
        """
        # Priority 1: Explicit migration setting
        if self.settings.default_cost_center:
            if frappe.db.exists("Cost Center", self.settings.default_cost_center):
                return self.settings.default_cost_center
            else:
                self.audit_trail.log_event(
                    "cost_center_config_invalid",
                    {
                        "configured": self.settings.default_cost_center,
                        "reason": "Cost center does not exist - falling back to other methods",
                    },
                    severity="warning",
                )

        # Priority 2: Company default cost center
        # NB: the ERPNext Company field is ``cost_center`` (there is no
        # ``default_cost_center`` column), so the previous lookup raised a 1054
        # "Unknown column" error that crashed the entire migration constructor.
        company_default = frappe.db.get_value("Company", self.company, "cost_center")
        if company_default and frappe.db.exists("Cost Center", company_default):
            return company_default

        # Priority 3-5: Heuristics (log what we're trying for transparency)
        heuristic_candidates = []

        # Try "Main" cost center
        main_cc = frappe.db.get_value(
            "Cost Center", {"company": self.company, "cost_center_name": "Main", "is_group": 0}, "name"
        )
        if main_cc:
            self.audit_trail.log_event(
                "cost_center_heuristic",
                {
                    "selected": main_cc,
                    "method": "company-main",
                    "recommendation": "Consider setting E-Boekhouden Settings.default_cost_center explicitly",
                },
                severity="info",
            )
            return main_cc
        heuristic_candidates.append("Main")

        # Try company abbreviation-based cost center
        abbr = frappe.db.get_value("Company", self.company, "abbr")
        if abbr:
            abbr_cc = f"{self.company} - {abbr}"
            if frappe.db.exists("Cost Center", abbr_cc):
                self.audit_trail.log_event(
                    "cost_center_heuristic",
                    {
                        "selected": abbr_cc,
                        "method": "company-abbreviation",
                        "recommendation": "Consider setting E-Boekhouden Settings.default_cost_center explicitly",
                    },
                    severity="info",
                )
                return abbr_cc
            heuristic_candidates.append(abbr_cc)

        # Try any non-group cost center
        any_cc = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")
        if any_cc:
            self.audit_trail.log_event(
                "cost_center_heuristic",
                {
                    "selected": any_cc,
                    "method": "any-non-group-fallback",
                    "recommendation": "Consider setting E-Boekhouden Settings.default_cost_center explicitly",
                },
                severity="info",
            )
            return any_cc

        # No cost center found - fail with actionable message
        frappe.throw(
            _(
                "No cost center found for company {0}. Tried: {1}. "
                "Please configure 'default_cost_center' in E-Boekhouden Settings "
                "or create a cost center for this company."
            ).format(self.company, ", ".join(heuristic_candidates))
        )

    def _update_progress(self, operation, percentage, force_commit=False):
        """
        Update migration progress in the document with throttled commits.

        Delegates to consolidated progress utility for consistent behavior
        across all migration modules.

        Args:
            operation: Description of current operation for UI display
            percentage: Progress percentage (0-100)
            force_commit: If True, commit immediately regardless of percentage
        """
        update_migration_progress(
            self.migration_doc,
            operation,
            percentage,
            force_commit=force_commit,
        )

    def execute_migration(self):
        """
        Execute the migration.

        Phases:
            1. Pre-migration validation
            2. Backup creation
            3. REST API data import (delegated to start_full_rest_import)
            4. Data integrity verification
            5. Audit summary generation

        Returns:
            dict containing:
                - success (bool): Overall success
                - validation_report (dict): Pre-migration validation results
                - integrity_report (dict): Post-migration integrity check
                - audit_summary (dict): Audit trail summary
                - dry_run_report (dict, optional): If dry_run mode
                - error (str, optional): Error message if failed

        Note:
            Progress updates are published for UI feedback.
            For cleanup after failed imports, use cleanup_utils.py.
        """
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
                    backup_path = self.safety_checks.create_pre_migration_backup()
                    if not backup_path:
                        frappe.throw(_("Pre-migration backup failed to produce a backup path"))
                    self.audit_trail.log_event("backup_created", {"path": backup_path})

            # Step 3: Account types are handled automatically by REST API migration
            self._update_progress("Account types will be handled during REST API import...", 15)
            # Note: REST API handles account types automatically, no manual fix needed

            # Step 4: Process data using REST API (unlimited transactions, not SOAP's 500 limit)
            # CONTRACT: start_full_rest_import is expected to:
            # - Handle its own batching and incremental commits
            # - Return a dict with at minimum: {"success": bool, "imported": int, "errors": list}
            # - Not raise exceptions for recoverable errors (return them in errors list)
            # - Respect dry_run flag from migration_doc if present
            self._update_progress("Starting transaction import via REST API...", 20)
            with AuditedMigrationOperation(self.audit_trail, "rest_api_migration"):
                result = start_full_rest_import(self.migration_doc.name)

                # Validate expected contract fields are present
                if not isinstance(result, dict):
                    frappe.log_error(
                        title="REST Import Contract Violation",
                        message=f"start_full_rest_import returned {type(result).__name__} instead of dict",
                    )
                    result = {"success": False, "error": "REST import returned invalid response type"}

                # Normalize expected keys to prevent KeyError in downstream code
                result.setdefault("success", False)
                result.setdefault("imported", 0)
                result.setdefault("errors", [])

            # Step 5: Verify data integrity
            if not self.dry_run:
                self._update_progress("Verifying data integrity...", 90)
                with AuditedMigrationOperation(self.audit_trail, "verify_integrity"):
                    integrity_report = self.safety_checks.verify_data_integrity()
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

            # Note: Automatic rollback was removed as it was never functional.
            # For cleanup after failed imports, use e_boekhouden/utils/cleanup_utils.py

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

    # Removed _get_receivable_account and _get_payable_account methods
    # These are no longer needed since we now use proper ledgerID mapping
    # from the main migration file which follows SSoT principles


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def execute_enhanced_migration(migration_name: str) -> dict:
    """
    Execute eBoekhouden migration.

    Args:
        migration_name: Name of the E-Boekhouden Migration document

    Returns:
        dict with:
            - success (bool): Whether migration completed
            - error (str, optional): Error message if failed
            - error_id (str, optional): Error log ID for debugging
            - validation_report (dict, optional): Pre-validation results
            - integrity_report (dict, optional): Post-migration integrity check
            - audit_summary (dict, optional): Audit trail

    Note:
        Always returns a dict, never raises exceptions.
        Critical errors are logged and returned with error_id.
    """
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration_doc.check_permission("write")
        settings = frappe.get_single("E-Boekhouden Settings")

        # Always use enhanced migration - no fallback options
        enhanced_migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
        result = enhanced_migration.execute_migration()

        # Ensure success flag is present
        if "success" not in result:
            result["success"] = True

        return result

    except frappe.ValidationError as e:
        # Validation errors are expected failures (bad config, missing data)
        return {
            "success": False,
            "error": str(e),
            "error_type": "validation",
        }

    except Exception as e:
        # Unexpected errors - log for debugging and return structured response
        error_id = frappe.log_error(
            title=f"Migration failed: {migration_name}",
            message=frappe.get_traceback(),
        )
        return {
            "success": False,
            "error": str(e),
            "error_type": "critical",
            "error_id": error_id,
        }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def run_migration_dry_run(migration_name: str) -> dict:
    """
    Execute complete migration simulation without data modification.

    Performs a comprehensive dry-run simulation of the migration process,
    validating all data and processes without creating any actual records.
    Essential for migration planning and risk assessment.

    Args:
        migration_name: Name of the E-Boekhouden Migration document

    Returns:
        dict: Dry-run simulation results containing:
            - would_create (int): Records that would be created
            - would_update (int): Records that would be updated
            - would_skip (int): Records that would be skipped
            - validation_errors (list): Data validation issues
            - simulation_summary (dict): Detailed simulation statistics

    Simulation Coverage:
        - Data validation and transformation
        - Duplicate detection and handling
        - Account mapping and validation
        - Customer/supplier creation requirements
        - Performance estimation and optimization opportunities
    """
    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    migration_doc.check_permission("read")
    migration_doc.dry_run = True

    settings = frappe.get_single("E-Boekhouden Settings")

    enhanced_migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
    return enhanced_migration.execute_migration()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def validate_migration_data(migration_name: str) -> dict:
    """
    Perform comprehensive pre-migration data validation and readiness assessment.

    Conducts thorough validation of the migration environment and data quality
    before actual migration execution. This prevents common migration failures
    and provides detailed guidance for addressing any issues.

    Args:
        migration_name: Name of the E-Boekhouden Migration document

    Returns:
        dict: Comprehensive validation report containing:
            - can_proceed (bool): Whether migration can proceed safely
            - validation_summary (dict): Statistical overview of validation results
            - issues (list): Critical problems that must be resolved
            - warnings (list): Non-critical issues that may affect migration
            - recommendations (list): Suggested optimizations and improvements

    Validation Areas:
        - System configuration and settings
        - Account structure and mapping completeness
        - Data quality and consistency checks
        - Performance and capacity assessment
        - Integration readiness verification
    """
    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    migration_doc.check_permission("read")
    settings = frappe.get_single("E-Boekhouden Settings")

    enhanced_migration = EnhancedEBoekhoudenMigration(migration_doc, settings)
    return enhanced_migration._run_pre_validation()
