"""
Coverage tests for verenigingen/utils/migration/migration_transaction_safety.py

MigrationSafetyChecks does pre-migration backup and post-migration integrity
verification (GL balance, document relationships, duplicate mutation numbers,
required fields) via real SQL against a real saved E-Boekhouden Migration doc and
a real Company. We assert the structure/contract of each check and the atomic
JSON writer's checksum behaviour. A clean company (no migrated transactions)
trivially passes the integrity checks - we assert that contract.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_transaction_safety
"""

import json
import os
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_transaction_safety import (
    MigrationSafetyChecks,
    MigrationTransaction,
    _write_atomic_json,
)


def _persist_company(name="TxnSafety Co", abbr="TSCO"):
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = abbr
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return name


def _make_migration_doc(company):
    doc = frappe.new_doc("E-Boekhouden Migration")
    doc.migration_name = "Txn Safety Coverage"
    doc.company = company
    doc.migration_status = "Draft"
    doc.date_from = "2024-01-01"
    doc.date_to = "2024-12-31"
    doc.insert(ignore_permissions=True)
    return doc


class TestAtomicJsonWriter(EnhancedTestCase):
    def test_writes_file_and_returns_checksum(self):
        path = frappe.get_site_path("private", "files", "test_atomic_writer", "out.json")
        try:
            checksum = _write_atomic_json(path, {"a": 1, "b": [2, 3]})
            self.assertTrue(os.path.exists(path))
            self.assertEqual(len(checksum), 64)  # sha256 hex digest
            with open(path) as f:
                self.assertEqual(json.load(f), {"a": 1, "b": [2, 3]})
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_no_temp_file_left_behind(self):
        path = frappe.get_site_path("private", "files", "test_atomic_writer2", "out.json")
        try:
            _write_atomic_json(path, {"x": 1})
            leftovers = [f for f in os.listdir(os.path.dirname(path)) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])
        finally:
            d = os.path.dirname(path)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    os.remove(os.path.join(d, f))


class _SafetyBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_company()

    def setUp(self):
        super().setUp()
        self.migration = _make_migration_doc(self.company)
        self.safety = MigrationSafetyChecks(self.migration)


class TestIntegrityChecks(_SafetyBase):
    def test_backwards_compatible_alias(self):
        # External code may still import the old MigrationTransaction name.
        self.assertIs(MigrationTransaction, MigrationSafetyChecks)

    def test_gl_balance_check_passes_on_clean_company(self):
        # Freshly created company has no migrated GL entries -> balanced.
        with self.assertNoErrorLog():
            result = self.safety._check_gl_balance()
        self.assertEqual(result["check"], "GL Balance")
        self.assertTrue(result["passed"])
        self.assertEqual(result["issues"], [])

    def test_document_relationship_check_contract(self):
        with self.assertNoErrorLog():
            result = self.safety._check_document_relationships()
        self.assertEqual(result["check"], "Document Relationships")
        self.assertTrue(result["passed"])

    def test_duplicate_check_contract(self):
        with self.assertNoErrorLog():
            result = self.safety._check_duplicates()
        self.assertEqual(result["check"], "Duplicate Records")
        self.assertTrue(result["passed"])

    def test_required_fields_check_contract(self):
        with self.assertNoErrorLog():
            result = self.safety._check_required_fields()
        self.assertEqual(result["check"], "Required Fields")
        self.assertTrue(result["passed"])

    def test_verify_data_integrity_aggregates_all_checks(self):
        with self.assertNoErrorLog():
            report = self.safety.verify_data_integrity()
        self.assertEqual(report["status"], "passed")
        check_names = {c["check"] for c in report["checks"]}
        self.assertEqual(
            check_names,
            {"GL Balance", "Document Relationships", "Duplicate Records", "Required Fields"},
        )
        self.assertEqual(report["issues"], [])


class TestBackupAndLogging(_SafetyBase):
    def test_affected_doctypes_list(self):
        doctypes = self.safety._get_affected_doctypes()
        self.assertIn("Sales Invoice", doctypes)
        self.assertIn("Payment Entry", doctypes)
        self.assertIn("Account", doctypes)

    def test_log_transaction_appends(self):
        self.safety.log_transaction({"type": "test_event"})
        self.assertEqual(len(self.safety.transaction_log), 1)
        self.assertEqual(self.safety.transaction_log[0]["data"]["type"], "test_event")

    def test_create_pre_migration_backup_writes_file(self):
        with self.assertNoErrorLog():
            backup_path = self.safety.create_pre_migration_backup()
        try:
            self.assertTrue(os.path.exists(backup_path))
            self.assertTrue(self.safety.backup_created)
            with open(backup_path) as f:
                data = json.load(f)
            self.assertEqual(data["migration"], self.migration.name)
            self.assertIn("Account", data["doctypes"])
            # A backup_created + backup_checksum transaction were logged.
            types = [t["data"]["type"] for t in self.safety.transaction_log]
            self.assertIn("backup_created", types)
            self.assertIn("backup_checksum", types)
        finally:
            if os.path.exists(backup_path):
                os.remove(backup_path)


if __name__ == "__main__":
    unittest.main()
