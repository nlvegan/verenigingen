"""
Test enhanced E-Boekhouden migration via whitelisted API
"""

import json
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import now_datetime


@frappe.whitelist()
def run_migration_test():
    """Run a comprehensive test of the enhanced migration system"""
    results = {"tests": [], "summary": {"passed": 0, "failed": 0, "warnings": 0}}

    def add_test_result(name, status, message, details=None):
        results["tests"].append({"name": name, "status": status, "message": message, "details": details})
        results["summary"][status] += 1

    try:
        # Test 1: Check settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if settings.api_token:
            add_test_result(
                "E-Boekhouden Settings", "passed", f"Settings configured for {settings.default_company}"
            )
        else:
            add_test_result("E-Boekhouden Settings", "failed", "API token not configured")
            return results

        # Test 2: Check payment mappings
        try:
            from verenigingen.utils.eboekhouden_payment_mapping import get_payment_account_mappings

            mappings = get_payment_account_mappings(settings.default_company)
            add_test_result("Payment Mappings", "passed", f"Found {len(mappings)} mappings", mappings)
        except Exception as e:
            add_test_result("Payment Mappings", "warnings", f"No custom mappings: {str(e)}")

        # Test 3: Create test migration
        to_date = datetime.now().date()
        from_date = to_date - timedelta(days=30)

        # migration_doc = frappe.get_doc(
        #     {
        #         "doctype": "E-Boekhouden Migration",
        #         "migration_name": "API Test {now_datetime()}",
        #         "company": settings.default_company,
        #         "migration_status": "Draft",
        #         "date_from": from_date,
        #         "date_to": to_date,
        #         "migrate_accounts": 1,
        #         "migrate_customers": 1,
        #         "migrate_suppliers": 1,
        #         "migrate_transactions": 1,
        #         "use_enhanced_migration": 1,
        #         "dry_run": 1,
        #         "skip_existing": 1,
        #         "batch_size": 10,
        #         "use_date_chunking": 1,
        #         "enable_audit_trail": 1,
        #     }
        # ).insert()

        add_test_result("Create Migration", "passed", f"Created {migration_doc.name}")

        # Test 4: Test dry run
        try:
            from verenigingen.utils.eboekhouden_enhanced_migration import run_migration_dry_run

            dry_run_result = run_migration_dry_run(migration_doc.name)

            if dry_run_result.get("dry_run_report"):
                report = dry_run_result["dry_run_report"]
                add_test_result(
                    "Dry Run",
                    "passed",
                    f"Analyzed {report['summary']['total_records_analyzed']} records",
                    report["summary"],
                )
            else:
                add_test_result("Dry Run", "passed", "Dry run completed", dry_run_result)

        except Exception as e:
            add_test_result("Dry Run", "failed", str(e))

        # Test 5: Test validation
        try:
            from verenigingen.utils.eboekhouden_enhanced_migration import validate_migration_data

            # validation_result = validate_migration_data(migration_doc.name)
            validate_migration_data(migration_doc.name)
            add_test_result(
                "Pre-Validation", "passed", f"Can proceed: {validation_result.get('can_proceed', False)}"
            )
        except Exception as e:
            add_test_result("Pre-Validation", "failed", str(e))

        # Test 6: Test duplicate detection
        try:
            from verenigingen.utils.migration.migration_duplicate_detection import DuplicateDetector

            detector = DuplicateDetector()
            test_record = {
                "customer": "Test Customer",
                "posting_date": str(to_date),
                "grand_total": 100.0,
                "eboekhouden_mutation_nr": "TEST123",
            }
            # dup_result = detector.check_duplicate("Sales Invoice", test_record)
            detector.check_duplicate("Sales Invoice", test_record)
            add_test_result(
                "Duplicate Detection",
                "passed",
                f"Duplicate check: {'Found' if dup_result['is_duplicate'] else 'No'} duplicates",
            )
        except Exception as e:
            add_test_result("Duplicate Detection", "warnings", str(e))

        # Test 7: Test audit trail
        try:
            from verenigingen.utils.migration.migration_audit_trail import MigrationAuditTrail

            audit = MigrationAuditTrail(migration_doc)
            audit.log_event("test", {"message": "Testing audit trail"})
            add_test_result("Audit Trail", "passed", "Audit trail operational")
        except Exception as e:
            add_test_result("Audit Trail", "failed", str(e))

        # Test 8: Test error recovery
        try:
            from verenigingen.utils.migration.migration_error_recovery import MigrationErrorRecovery

            recovery = MigrationErrorRecovery(migration_doc)
            recovery.log_error("Test error", {"test": True})
            add_test_result("Error Recovery", "passed", "Error recovery operational")
        except Exception as e:
            add_test_result("Error Recovery", "failed", str(e))

        # Test 9: Test date chunking
        try:
            from verenigingen.utils.migration.migration_date_chunking import DateRangeChunker

            chunker = DateRangeChunker(api_limit=500)
            # chunks = chunker.calculate_optimal_chunks(from_date, to_date, estimated_records_per_day=10)
            chunker.calculate_optimal_chunks(from_date, to_date, estimated_records_per_day=10)
            add_test_result("Date Chunking", "passed", f"Created {len(chunks)} chunks")
        except Exception as e:
            add_test_result("Date Chunking", "failed", str(e))

        # Test 10: Test transaction safety
        try:
            from verenigingen.utils.migration.migration_transaction_safety import MigrationTransaction

            trans = MigrationTransaction(migration_doc)
            checkpoint = trans.create_checkpoint("test_operation")
            trans.commit_checkpoint(checkpoint)
            add_test_result("Transaction Safety", "passed", "Transaction management operational")
        except Exception as e:
            add_test_result("Transaction Safety", "failed", str(e))

        # Cleanup
        frappe.delete_doc("E-Boekhouden Migration", migration_doc.name, force=True)
        frappe.db.commit()

    except Exception as e:
        add_test_result("Overall Test", "failed", str(e))

    # Add summary
    results["overall_status"] = "passed" if results["summary"]["failed"] == 0 else "failed"
    results["recommendation"] = (
        "System ready for migration"
        if results["summary"]["failed"] == 0
        else "Fix failed tests before proceeding"
    )

    return results


@frappe.whitelist()
def test_soap_api_connection():
    """Test the SOAP API connection"""
    try:
        from verenigingen.utils.eboekhouden_soap_api import EBoekhoudenSOAPAPI

        settings = frappe.get_single("E-Boekhouden Settings")

        api = EBoekhoudenSOAPAPI(settings)

        # Test getting mutations (will be limited to 500)
        result = api.get_mutations()

        if result["success"]:
            mutations = result.get("mutations", [])
            return {
                "success": True,
                "message": "Successfully connected to SOAP API",
                "mutations_count": len(mutations),
                "sample": mutations[0] if mutations else None,
            }
        else:
            return {"success": False, "error": result.get("error", "Unknown error")}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def ensure_payment_mapping_doctype():
    """Ensure the E-Boekhouden Payment Mapping DocType exists"""
    try:
        if not frappe.db.exists("DocType", "E-Boekhouden Payment Mapping"):
            # Use a simplified approach - just return that it needs to be created
            return {
                "success": False,
                "message": "E-Boekhouden Payment Mapping DocType needs to be created. Please run bench migrate.",
            }
        return {"success": True, "message": "E-Boekhouden Payment Mapping DocType exists"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_test_payment_mappings():
    """Create test payment account mappings"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Get default accounts
        receivable = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Receivable"}, "name"
        )
        payable = frappe.db.get_value("Account", {"company": company, "account_type": "Payable"}, "name")
        bank = frappe.db.get_value("Account", {"company": company, "account_type": "Bank"}, "name")

        mappings_created = []

        # Create receivable mapping
        if receivable:
            # mapping = frappe.get_doc(
            frappe.get_doc(
                {
                    "doctype": "E-Boekhouden Payment Mapping",
                    "company": company,
                    "mapping_type": "Account Type",
                    "account_type": "Receivable",
                    "erpnext_account": receivable,
                }
            ).insert()
            mappings_created.append(f"Receivable → {receivable}")

        # Create payable mapping
        if payable:
            # mapping = frappe.get_doc(
            frappe.get_doc(
                {
                    "doctype": "E-Boekhouden Payment Mapping",
                    "company": company,
                    "mapping_type": "Account Type",
                    "account_type": "Payable",
                    "erpnext_account": payable,
                }
            ).insert()
            mappings_created.append(f"Payable → {payable}")

        # Create bank mapping
        if bank:
            # mapping = frappe.get_doc(
            frappe.get_doc(
                {
                    "doctype": "E-Boekhouden Payment Mapping",
                    "company": company,
                    "mapping_type": "Account Type",
                    "account_type": "Bank",
                    "erpnext_account": bank,
                }
            ).insert()
            mappings_created.append(f"Bank → {bank}")

        frappe.db.commit()

        return {
            "success": True,
            "message": "Created {len(mappings_created)} payment mappings",
            "mappings": mappings_created,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
