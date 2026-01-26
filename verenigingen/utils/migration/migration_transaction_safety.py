"""
Safety checks and backup utilities for eBoekhouden migration.

Provides pre-migration backup and post-migration data integrity verification.

Note: Checkpoint-based rollback functionality was removed as it was not wired
into the import process. For cleaning up failed imports, use the dedicated
cleanup utilities in e_boekhouden/utils/cleanup_utils.py.
"""

import hashlib
import json
import os
import tempfile

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def _write_atomic_json(path: str, data: dict) -> str:
    """
    Write JSON data to a file atomically with checksum verification.

    Uses a temporary file and os.replace() to ensure the write is atomic -
    the file either contains complete valid data or doesn't exist.

    Args:
        path: Destination file path
        data: Dictionary to serialize as JSON

    Returns:
        str: SHA256 checksum of the written data

    Raises:
        OSError: If the write operation fails
    """
    dirpath = os.path.dirname(path)
    os.makedirs(dirpath, exist_ok=True)

    # Serialize data once to compute checksum and write
    json_content = json.dumps(data, indent=2, default=str)
    checksum = hashlib.sha256(json_content.encode()).hexdigest()

    # Write to temp file first, then atomically replace
    fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json_content)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    return checksum


class MigrationSafetyChecks:
    """
    Pre-migration backup and post-migration integrity verification.

    This class provides two main capabilities:
    1. create_pre_migration_backup() - Backs up affected doctypes before import
    2. verify_data_integrity() - Validates data consistency after import

    For cleaning up failed or unwanted imports, use the cleanup utilities
    in e_boekhouden/utils/cleanup_utils.py instead.
    """

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.transaction_log = []
        self.backup_created = False

    def create_pre_migration_backup(self):
        """Create a backup of affected data before migration"""
        backup_data = {"migration": self.migration_doc.name, "timestamp": now_datetime(), "doctypes": {}}

        # Identify doctypes that will be affected
        affected_doctypes = self._get_affected_doctypes()

        for doctype in affected_doctypes:
            # Backup existing records
            records = frappe.get_all(
                doctype,
                filters={"company": self.migration_doc.company},
                fields=["*"],
                limit=10000,  # Safety limit
            )

            backup_data["doctypes"][doctype] = {"count": len(records), "records": records}

        # Save backup
        backup_path = self._save_backup_data(backup_data)

        self.backup_created = True
        self.log_transaction(
            {
                "type": "backup_created",
                "backup_path": backup_path,
                "doctypes_backed_up": list(affected_doctypes),
                "total_records": sum(d["count"] for d in backup_data["doctypes"].values()),
            }
        )

        return backup_path

    def verify_data_integrity(self):
        """Verify data integrity after migration"""
        integrity_report = {"timestamp": now_datetime(), "checks": [], "issues": [], "status": "passed"}

        # Check 1: Accounting balance
        gl_check = self._check_gl_balance()
        integrity_report["checks"].append(gl_check)
        if not gl_check["passed"]:
            integrity_report["issues"].extend(gl_check["issues"])
            integrity_report["status"] = "failed"

        # Check 2: Document relationships
        relationship_check = self._check_document_relationships()
        integrity_report["checks"].append(relationship_check)
        if not relationship_check["passed"]:
            integrity_report["issues"].extend(relationship_check["issues"])
            integrity_report["status"] = "failed"

        # Check 3: Duplicate records
        duplicate_check = self._check_duplicates()
        integrity_report["checks"].append(duplicate_check)
        if not duplicate_check["passed"]:
            integrity_report["issues"].extend(duplicate_check["issues"])
            integrity_report["status"] = "warning"

        # Check 4: Required fields
        field_check = self._check_required_fields()
        integrity_report["checks"].append(field_check)
        if not field_check["passed"]:
            integrity_report["issues"].extend(field_check["issues"])
            integrity_report["status"] = "warning"

        return integrity_report

    def _check_gl_balance(self):
        """Check if GL entries are balanced"""
        check_result = {"check": "GL Balance", "passed": True, "issues": []}

        # Get unbalanced GL entries
        unbalanced = frappe.db.sql(
            """
            SELECT voucher_type, voucher_no, SUM(debit) - SUM(credit) as difference
            FROM `tabGL Entry`
            WHERE company = %s
            AND creation >= %s
            GROUP BY voucher_type, voucher_no
            HAVING difference != 0
        """,
            (self.migration_doc.company, self.migration_doc.creation),
            as_dict=True,
        )

        if unbalanced:
            check_result["passed"] = False
            for entry in unbalanced:
                check_result["issues"].append(
                    {
                        "type": "unbalanced_gl",
                        "voucher_type": entry.voucher_type,
                        "voucher_no": entry.voucher_no,
                        "difference": entry.difference,
                    }
                )

        return check_result

    def _check_document_relationships(self):
        """Check if document relationships are intact"""
        check_result = {"check": "Document Relationships", "passed": True, "issues": []}

        # Check payment entries reference valid invoices
        orphaned_payments = frappe.db.sql(
            """
            SELECT pe.name, pe.party, per.reference_doctype, per.reference_name
            FROM `tabPayment Entry` pe
            LEFT JOIN `tabPayment Entry Reference` per ON pe.name = per.parent
            WHERE pe.company = %s
            AND pe.creation >= %s
            AND per.reference_name IS NOT NULL
            AND per.reference_name != ''
            AND NOT EXISTS (
                SELECT 1 FROM `tabSales Invoice` WHERE name = per.reference_name
                UNION
                SELECT 1 FROM `tabPurchase Invoice` WHERE name = per.reference_name
            )
        """,
            (self.migration_doc.company, self.migration_doc.creation),
            as_dict=True,
        )

        if orphaned_payments:
            check_result["passed"] = False
            for payment in orphaned_payments:
                check_result["issues"].append(
                    {
                        "type": "orphaned_payment_reference",
                        "payment_entry": payment.name,
                        "reference": payment.reference_name,
                    }
                )

        return check_result

    def _check_duplicates(self):
        """Check for potential duplicate records"""
        check_result = {"check": "Duplicate Records", "passed": True, "issues": []}

        # Check for duplicate eboekhouden mutation numbers
        duplicates = frappe.db.sql(
            """
            SELECT doctype, eboekhouden_mutation_nr, COUNT(*) as count
            FROM (
                SELECT 'Sales Invoice' as doctype, eboekhouden_mutation_nr
                FROM `tabSales Invoice`
                WHERE company = %s AND eboekhouden_mutation_nr IS NOT NULL
                UNION ALL
                SELECT 'Purchase Invoice' as doctype, eboekhouden_mutation_nr
                FROM `tabPurchase Invoice`
                WHERE company = %s AND eboekhouden_mutation_nr IS NOT NULL
                UNION ALL
                SELECT 'Payment Entry' as doctype, eboekhouden_mutation_nr
                FROM `tabPayment Entry`
                WHERE company = %s AND eboekhouden_mutation_nr IS NOT NULL
            ) as combined
            GROUP BY doctype, eboekhouden_mutation_nr
            HAVING count > 1
        """,
            (self.migration_doc.company, self.migration_doc.company, self.migration_doc.company),
            as_dict=True,
        )

        if duplicates:
            check_result["passed"] = False
            for dup in duplicates:
                check_result["issues"].append(
                    {
                        "type": "duplicate_mutation_nr",
                        "doctype": dup.doctype,
                        "mutation_nr": dup.eboekhouden_mutation_nr,
                        "count": dup.count,
                    }
                )

        return check_result

    def _check_required_fields(self):
        """Check if required fields are populated"""
        check_result = {"check": "Required Fields", "passed": True, "issues": []}

        # Check for missing required fields in key doctypes
        # Sales Invoice check
        missing_fields = frappe.db.sql(
            """
            SELECT name,
                CASE
                    WHEN customer IS NULL OR customer = '' THEN 'customer'
                    WHEN posting_date IS NULL THEN 'posting_date'
                    WHEN company IS NULL OR company = '' THEN 'company'
                END as missing_field
            FROM `tabSales Invoice`
            WHERE company = %s
            AND creation >= %s
            AND (
                (customer IS NULL OR customer = '') OR
                posting_date IS NULL OR
                (company IS NULL OR company = '')
            )
            LIMIT 10
        """,
            (self.migration_doc.company, self.migration_doc.creation),
            as_dict=True,
        )

        if missing_fields:
            check_result["passed"] = False
            for record in missing_fields:
                check_result["issues"].append(
                    {
                        "type": "missing_required_field",
                        "doctype": "Sales Invoice",
                        "record": record["name"],
                        "field": record["missing_field"],
                    }
                )

        # Purchase Invoice check
        missing_fields = frappe.db.sql(
            """
            SELECT name,
                CASE
                    WHEN supplier IS NULL OR supplier = '' THEN 'supplier'
                    WHEN posting_date IS NULL THEN 'posting_date'
                    WHEN company IS NULL OR company = '' THEN 'company'
                END as missing_field
            FROM `tabPurchase Invoice`
            WHERE company = %s
            AND creation >= %s
            AND (
                (supplier IS NULL OR supplier = '') OR
                posting_date IS NULL OR
                (company IS NULL OR company = '')
            )
            LIMIT 10
        """,
            (self.migration_doc.company, self.migration_doc.creation),
            as_dict=True,
        )

        if missing_fields:
            check_result["passed"] = False
            for record in missing_fields:
                check_result["issues"].append(
                    {
                        "type": "missing_required_field",
                        "doctype": "Purchase Invoice",
                        "record": record["name"],
                        "field": record["missing_field"],
                    }
                )

        # Payment Entry check
        missing_fields = frappe.db.sql(
            """
            SELECT name,
                CASE
                    WHEN party IS NULL OR party = '' THEN 'party'
                    WHEN posting_date IS NULL THEN 'posting_date'
                    WHEN company IS NULL OR company = '' THEN 'company'
                END as missing_field
            FROM `tabPayment Entry`
            WHERE company = %s
            AND creation >= %s
            AND (
                (party IS NULL OR party = '') OR
                posting_date IS NULL OR
                (company IS NULL OR company = '')
            )
            LIMIT 10
        """,
            (self.migration_doc.company, self.migration_doc.creation),
            as_dict=True,
        )

        if missing_fields:
            check_result["passed"] = False
            for record in missing_fields:
                check_result["issues"].append(
                    {
                        "type": "missing_required_field",
                        "doctype": "Payment Entry",
                        "record": record["name"],
                        "field": record["missing_field"],
                    }
                )

        return check_result

    def log_transaction(self, transaction_data):
        """Log a transaction event"""
        self.transaction_log.append({"timestamp": now_datetime(), "data": transaction_data})

        # Periodically save to file
        if len(self.transaction_log) % 100 == 0:
            self._save_transaction_log()

    def _save_backup_data(self, backup_data):
        """Save backup data to file atomically with checksum"""
        file_path = frappe.get_site_path(
            "private",
            "files",
            "migration_backups",
            f"backup_{self.migration_doc.name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}.json",
        )

        checksum = _write_atomic_json(file_path, backup_data)

        # Log checksum for verification
        self.log_transaction(
            {
                "type": "backup_checksum",
                "path": file_path,
                "checksum": checksum,
            }
        )

        return file_path

    def _save_transaction_log(self):
        """Save transaction log to file atomically"""
        file_path = frappe.get_site_path(
            "private",
            "files",
            "migration_transaction_logs",
            f"transaction_log_{self.migration_doc.name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}.json",
        )

        _write_atomic_json(file_path, {"log": self.transaction_log})

    def _get_affected_doctypes(self):
        """Get list of doctypes that will be affected by migration"""
        return [
            "Account",
            "Cost Center",
            "Customer",
            "Supplier",
            "Sales Invoice",
            "Purchase Invoice",
            "Payment Entry",
            "Journal Entry",
        ]


# Backwards-compatible alias for external code that may import the old name
MigrationTransaction = MigrationSafetyChecks


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_migration_backup(migration_name: str) -> dict:
    """
    Create a backup before starting migration.

    Requires System Manager role and write permission on the migration document.

    Args:
        migration_name: Name of the E-Boekhouden Migration document

    Returns:
        dict: Success status with backup path
    """
    user = frappe.session.user
    if not frappe.has_role(user, "System Manager"):
        frappe.throw("Only System Manager can create migration backups")

    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    migration_doc.check_permission("write")

    # Audit log: record who initiated the backup
    frappe.logger("migration_audit").info(
        f"Migration backup initiated | user={user} | migration={migration_name}"
    )

    safety_checks = MigrationSafetyChecks(migration_doc)
    safety_checks.log_transaction(
        {
            "type": "admin_action",
            "action": "create_backup",
            "user": user,
            "migration": migration_name,
        }
    )

    backup_path = safety_checks.create_pre_migration_backup()

    return {
        "success": True,
        "backup_path": backup_path,
        "message": "Backup created successfully",
        "created_by": user,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def verify_migration_integrity(migration_name: str) -> dict:
    """
    Verify data integrity after migration.

    Requires System Manager role and read permission on the migration document.

    Args:
        migration_name: Name of the E-Boekhouden Migration document

    Returns:
        dict: Integrity report with checks, issues, and status
    """
    user = frappe.session.user
    if not frappe.has_role(user, "System Manager"):
        frappe.throw("Only System Manager can verify migration integrity")

    migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
    migration_doc.check_permission("read")

    # Audit log: record who initiated the verification
    frappe.logger("migration_audit").info(
        f"Migration integrity check initiated | user={user} | migration={migration_name}"
    )

    safety_checks = MigrationSafetyChecks(migration_doc)
    safety_checks.log_transaction(
        {
            "type": "admin_action",
            "action": "verify_integrity",
            "user": user,
            "migration": migration_name,
        }
    )

    result = safety_checks.verify_data_integrity()
    result["verified_by"] = user
    return result
