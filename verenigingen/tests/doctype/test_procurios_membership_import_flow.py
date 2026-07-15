# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Real integration flow tests for the Procurios membership importer.

Creates real Members (with a procurios_id), real Membership Types wired to
real dues-schedule templates, and configures Verenigingen Settings with real
CSV dues-schedule templates. No business logic is mocked: the per-row
processor, MembershipImportService, and the Membership controller all run for
real, and we assert the observable effects (counters, created Membership
status, dues-schedule existence, error_log contents).
"""

import os
import tempfile

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.procurios_membership_import.procurios_membership_import import (
    process_import_background,
)

HEADER = "Debiteur Id,Debiteur Naam,Type,Looptijd,Ingangsdatum,Opgezegd,Einddatum,Normale prijs (type),Id"

SETTINGS_FIELDS = (
    "csv_monthly_dues_schedule",
    "csv_quarterly_dues_schedule",
    "csv_annual_dues_schedule",
)


class TestMembershipImportFlow(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._created_files = []
        self._created_imports = []

        # Real Membership Types for the two mapped Procurios types.
        self.monthly_type = self.create_test_membership_type("ProcMonthly", amount=2.5)
        self.annual_type = self.create_test_membership_type("ProcAnnual", amount=20.0)

        # Real dues-schedule templates wired into Verenigingen Settings so the
        # active-membership path can resolve a template from payment_period.
        self._saved_settings = {
            f: frappe.db.get_single_value("Verenigingen Settings", f) for f in SETTINGS_FIELDS
        }
        settings = frappe.get_single("Verenigingen Settings")
        settings.csv_monthly_dues_schedule = self.ensure_dues_schedule_template("Procurios Monthly").name
        settings.csv_quarterly_dues_schedule = self.ensure_dues_schedule_template("Procurios Quarterly").name
        settings.csv_annual_dues_schedule = self.ensure_dues_schedule_template("Procurios Annual").name
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        for name in self._created_imports:
            self._force_delete("Procurios Membership Import", name)
        for name in self._created_files:
            self._force_delete("File", name)
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in self._saved_settings.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    @staticmethod
    def _force_delete(doctype, name):
        try:
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        except Exception:
            pass

    # ---- helpers ----

    def _make_csv_file(self, rows):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n")
            for r in rows:
                f.write(r + "\n")
        with open(path, "rb") as fh:
            filedoc = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": "procurios_memb_flow.csv",
                    "is_private": 1,
                    "content": fh.read(),
                }
            ).insert(ignore_permissions=True)
        os.unlink(path)
        self._created_files.append(filedoc.name)
        return filedoc.file_url

    def _make_import_doc(self, csv_url):
        return frappe.get_doc(
            {"doctype": "Procurios Membership Import", "csv_file": csv_url, "csv_delimiter": "Comma"}
        ).insert(ignore_permissions=True)

    def _run_import(self, rows, mapping):
        """Create + validate the import doc, apply the type mapping, then run
        the background processor synchronously. Returns the reloaded doc."""
        url = self._make_csv_file(rows)
        doc = self._make_import_doc(url)
        self._created_imports.append(doc.name)

        # Populates membership_type_mapping from the CSV's distinct Type values.
        doc._validate_and_preview_csv()
        doc.reload()

        for child in doc.membership_type_mapping:
            if child.procurios_type in mapping:
                child.membership_type = mapping[child.procurios_type]
        doc.save()
        frappe.db.commit()

        process_import_background(doc.name, test_mode=False)

        doc.reload()
        return doc

    # ---- tests ----

    def test_active_row_creates_membership_and_dues_schedule(self):
        member = self.create_test_member(procurios_id="900001")
        doc = self._run_import(
            ["900001,Test A,Maandlid,1 Maand,2022-11-27,,,2.5,900001"],
            {"Maandlid": self.monthly_type.name},
        )
        self.assertEqual(doc.memberships_created, 1)
        m = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "status", "procurios_membership_id"],
        )
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].status, "Active")
        self.assertEqual(m[0].procurios_membership_id, "900001")
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", {"member": member.name}))

    def test_no_member_skips_and_logs(self):
        doc = self._run_import(
            ["999999,Nobody,Maandlid,1 Maand,2022-11-27,,,2.5,900002"],
            {"Maandlid": self.monthly_type.name},
        )
        self.assertEqual(doc.memberships_created, 0)
        self.assertEqual(doc.memberships_skipped, 1)
        self.assertIn("no Member with procurios_id=999999", doc.error_log)

    def test_cancelled_row_creates_historical_no_dues(self):
        member = self.create_test_member(procurios_id="900003")
        doc = self._run_import(
            ["900003,Test C,Jaarlid,1 Jaar,2018-01-01,2020-06-01,,20,900003"],
            {"Jaarlid": self.annual_type.name},
        )
        self.assertEqual(doc.memberships_created, 1)
        m = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "status"],
        )
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0].status, "Cancelled")
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", {"member": member.name}))

    def test_idempotent_rerun_creates_nothing_new(self):
        member = self.create_test_member(procurios_id="900004")
        rows = ["900004,Test D,Maandlid,1 Maand,2022-11-27,,,2.5,900004"]
        first = self._run_import(rows, {"Maandlid": self.monthly_type.name})
        self.assertEqual(first.memberships_created, 1)

        second = self._run_import(rows, {"Maandlid": self.monthly_type.name})
        self.assertEqual(second.memberships_created, 0)
        self.assertEqual(frappe.db.count("Membership", {"member": member.name}), 1)

    def test_already_active_membership_skips_and_logs(self):
        member = self.create_test_member(procurios_id="900005")
        # Give the member a pre-existing active membership.
        self.create_test_membership(member=member.name, membership_type=self.monthly_type.name)
        doc = self._run_import(
            ["900005,Test E,Maandlid,1 Maand,2022-11-27,,,2.5,900005"],
            {"Maandlid": self.monthly_type.name},
        )
        self.assertEqual(doc.memberships_created, 0)
        self.assertIn("already has an active membership", doc.error_log)
