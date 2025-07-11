"""
Transaction safety and rollback mechanisms for eBoekhouden migration

Provides atomic operations, rollback capabilities, and data integrity
checks for safe migration processing.
"""

import json
import os
from contextlib import contextmanager
from datetime import datetime

import frappe
from frappe.utils import now_datetime


class MigrationTransaction:
    """Manages transactional safety for migration operations"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.transaction_log = []
        self.rollback_queue = []
        self.checkpoint_data = {}
        self.backup_created = False

    @contextmanager
    def atomic_operation(self, operation_name):
        """
        Context manager for atomic operations with automatic rollback

        Usage:
            with transaction.atomic_operation("create_invoices"):
                # Do operations
                # Automatic rollback on exception
        """
        checkpoint = self.create_checkpoint(operation_name)

        try:
            yield checkpoint
            self.commit_checkpoint(checkpoint)
        except Exception:
            self.rollback_to_checkpoint(checkpoint)
            raise

    def create_checkpoint(self, operation_name):
        """Create a checkpoint for potential rollback"""
        checkpoint = {
            "id": f"{operation_name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}",
            "operation": operation_name,
            "timestamp": now_datetime(),
            "created_records": [],
            "modified_records": [],
            "deleted_records": [],
        }

        self.checkpoint_data[checkpoint["id"]] = checkpoint

        # Log checkpoint creation
        self.log_transaction(
            {"type": "checkpoint_created", "checkpoint_id": checkpoint["id"], "operation": operation_name}
        )

        return checkpoint

    def track_record_creation(self, checkpoint_id, doctype, name, data=None):
        """Track a newly created record for potential rollback"""
        if checkpoint_id in self.checkpoint_data:
            self.checkpoint_data[checkpoint_id]["created_records"].append(
                {"doctype": doctype, "name": name, "data": data or {}, "timestamp": now_datetime()}
            )

    def track_record_modification(self, checkpoint_id, doctype, name, old_data, new_data):
        """Track a modified record with before state for rollback"""
        if checkpoint_id in self.checkpoint_data:
            self.checkpoint_data[checkpoint_id]["modified_records"].append(
                {
                    "doctype": doctype,
                    "name": name,
                    "old_data": old_data,
                    "new_data": new_data,
                    "timestamp": now_datetime(),
                }
            )

    def track_record_deletion(self, checkpoint_id, doctype, name, data):
        """Track a deleted record for potential restoration"""
        if checkpoint_id in self.checkpoint_data:
            self.checkpoint_data[checkpoint_id]["deleted_records"].append(
                {"doctype": doctype, "name": name, "data": data, "timestamp": now_datetime()}
            )

    def commit_checkpoint(self, checkpoint):
        """Commit a checkpoint (mark as successful)"""
        checkpoint["status"] = "committed"
        checkpoint["committed_at"] = now_datetime()

        self.log_transaction(
            {
                "type": "checkpoint_committed",
                "checkpoint_id": checkpoint["id"],
                "records_created": len(checkpoint["created_records"]),
                "records_modified": len(checkpoint["modified_records"]),
                "records_deleted": len(checkpoint["deleted_records"]),
            }
        )

        # Save checkpoint data for audit
        self._save_checkpoint_data(checkpoint)

    def rollback_to_checkpoint(self, checkpoint):
        """Rollback all operations to a checkpoint"""
        rollback_log = {"checkpoint_id": checkpoint["id"], "started_at": now_datetime(), "actions": []}

        try:
            # Rollback in reverse order

            # 1. Delete created records
            for record in reversed(checkpoint["created_records"]):
                try:
                    if frappe.db.exists(record["doctype"], record["name"]):
                        # Handle submitted documents
                        doc = frappe.get_doc(record["doctype"], record["name"])
                        if hasattr(doc, "docstatus") and doc.docstatus == 1:
                            doc.cancel()

                        frappe.delete_doc(record["doctype"], record["name"], force=True)
                        rollback_log["actions"].append(
                            {"action": "deleted", "doctype": record["doctype"], "name": record["name"]}
                        )
                except Exception as e:
                    rollback_log["actions"].append(
                        {
                            "action": "delete_failed",
                            "doctype": record["doctype"],
                            "name": record["name"],
                            "error": str(e),
                        }
                    )

            # 2. Restore modified records
            for record in reversed(checkpoint["modified_records"]):
                try:
                    if frappe.db.exists(record["doctype"], record["name"]):
                        doc = frappe.get_doc(record["doctype"], record["name"])

                        # Restore old data
                        for field, value in record["old_data"].items():
                            if hasattr(doc, field):
                                setattr(doc, field, value)

                        doc.save(ignore_permissions=True)
                        rollback_log["actions"].append(
                            {"action": "restored", "doctype": record["doctype"], "name": record["name"]}
                        )
                except Exception as e:
                    rollback_log["actions"].append(
                        {
                            "action": "restore_failed",
                            "doctype": record["doctype"],
                            "name": record["name"],
                            "error": str(e),
                        }
                    )

            # 3. Recreate deleted records
            for record in reversed(checkpoint["deleted_records"]):
                try:
                    doc = frappe.get_doc(record["data"])
                    doc.insert(ignore_permissions=True)

                    # Restore to original state if it was submitted
                    if record["data"].get("docstatus") == 1:
                        doc.submit()

                    rollback_log["actions"].append(
                        {"action": "recreated", "doctype": record["doctype"], "name": record["name"]}
                    )
                except Exception as e:
                    rollback_log["actions"].append(
                        {
                            "action": "recreate_failed",
                            "doctype": record["doctype"],
                            "name": record["name"],
                            "error": str(e),
                        }
                    )

            # Mark checkpoint as rolled back
            checkpoint["status"] = "rolled_back"
            checkpoint["rolled_back_at"] = now_datetime()

            rollback_log["completed_at"] = now_datetime()
            rollback_log["success"] = True

        except Exception as e:
            rollback_log["success"] = False
            rollback_log["error"] = str(e)

        # Log rollback
        self.log_transaction(
            {
                "type": "checkpoint_rolled_back",
                "checkpoint_id": checkpoint["id"],
                "rollback_log": rollback_log,
            }
        )

        return rollback_log

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

    def _save_checkpoint_data(self, checkpoint):
        """Save checkpoint data to file"""
        file_path = frappe.get_site_path(
            "private", "files", "migration_checkpoints", f"checkpoint_{checkpoint['id']}.json"
        )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w") as f:
            json.dump(checkpoint, f, indent=2, default=str)

    def _save_backup_data(self, backup_data):
        """Save backup data to file"""
        file_path = frappe.get_site_path(
            "private",
            "files",
            "migration_backups",
            f"backup_{self.migration_doc.name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}.json",
        )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w") as f:
            json.dump(backup_data, f, indent=2, default=str)

        return file_path

    def _save_transaction_log(self):
        """Save transaction log to file"""
        file_path = frappe.get_site_path(
            "private",
            "files",
            "migration_transaction_logs",
            f"transaction_log_{self.migration_doc.name}_{now_datetime().strftime('%Y%m%d_%H%M%S')}.json",
        )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w") as f:
            json.dump(self.transaction_log, f, indent=2, default=str)

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


@frappe.whitelist()
def create_migration_backup(migration_name):
    """Create a backup before starting migration"""
    migration_doc = frappe.get_doc("E Boekhouden Migration", migration_name)
    transaction = MigrationTransaction(migration_doc)

    backup_path = transaction.create_pre_migration_backup()

    return {"success": True, "backup_path": backup_path, "message": "Backup created successfully"}


@frappe.whitelist()
def verify_migration_integrity(migration_name):
    """Verify data integrity after migration"""
    migration_doc = frappe.get_doc("E Boekhouden Migration", migration_name)
    transaction = MigrationTransaction(migration_doc)

    return transaction.verify_data_integrity()


@frappe.whitelist()
def rollback_migration_checkpoint(migration_name, checkpoint_id):
    """Rollback to a specific checkpoint"""
    migration_doc = frappe.get_doc("E Boekhouden Migration", migration_name)
    transaction = MigrationTransaction(migration_doc)

    # Load checkpoint data
    checkpoint_file = frappe.get_site_path(
        "private", "files", "migration_checkpoints", f"checkpoint_{checkpoint_id}.json"
    )

    with open(checkpoint_file, "r") as f:
        checkpoint = json.load(f)

    return transaction.rollback_to_checkpoint(checkpoint)
