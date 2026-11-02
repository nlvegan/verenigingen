"""Import provenance on Member (#1777): which import record created/updated a member.

Every test drives the REAL import entry point of the importer (no hand-set fields) except the
integrity-check control, which builds its non-imported Quit member by a direct status write: the
termination service creates Quit and the Executed request together, so no flow produces that state.
"""

import frappe

from verenigingen.services.termination import termination_utils as tu
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.csv_import_processor import bulk_member_operations


class TestMemberImportProvenance(EnhancedTestCase):
    def _import_doc(self, doctype="Mijnrood CSV Import", **fields):
        # The placeholder csv_file makes Frappe log a (harmless) "Error Attaching File".
        self.expectErrorLog("Error Attaching File")
        doc = frappe.get_doc(
            {"doctype": doctype, "csv_file": "/files/none.csv", "encoding": "utf-8", **fields}
        )
        doc.insert()
        return doc

    def _mijnrood_row(self, **overrides):
        row = {
            "row_number": 1,
            "member_id": f"PROV-{frappe.generate_hash(length=8)}",
            "first_name": "Prov",
            "last_name": f"Enance{self.uid}",
            "email": f"prov-{frappe.generate_hash(length=8)}@example.com",
            "membership_type": "lid",
        }
        row.update(overrides)
        return row

    def _run_mijnrood(self, row, import_doc):
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        with bulk_member_operations(import_doc.name):
            return get_member_import_service().create_or_update_member(
                row_data=row, import_doc_name=import_doc.name, create_volunteer_records=False
            )

    def _source(self, member_name):
        return frappe.db.get_value(
            "Member", member_name, ["import_source_type", "import_source"], as_dict=True
        )

    # ---- importers -------------------------------------------------------------
    def test_mijnrood_import_marks_created_and_updated_member(self):
        first = self._import_doc()
        row = self._mijnrood_row()
        status, name = self._run_mijnrood(row, first)
        self.assertEqual(status, "created")
        self.assertEqual(self._source(name).import_source_type, "Mijnrood CSV Import")
        self.assertEqual(self._source(name).import_source, first.name)

        second = self._import_doc()
        status, name2 = self._run_mijnrood(dict(row, first_name="Changed"), second)
        self.assertEqual((status, name2), ("updated", name))
        self.assertEqual(self._source(name).import_source, second.name)

    def test_member_import_marks_created_member(self):
        from verenigingen.verenigingen.doctype.member_import.member_import import MemberImport

        doc = self._import_doc("Member Import", csv_delimiter="Semicolon")
        row = {
            "member_id": f"PROC-{frappe.generate_hash(length=8)}",
            "procurios_id": f"P{frappe.generate_hash(length=6)}",
            "first_name": "Proc",
            "last_name": f"Urios{self.uid}",
            "email": f"proc-{frappe.generate_hash(length=8)}@example.com",
            "row_number": 1,
        }
        errors = []
        status, name = MemberImport._process_single_member(doc, row, errors)
        self.assertEqual((status, errors), ("created", []))
        self.assertEqual(self._source(name).import_source_type, "Member Import")
        self.assertEqual(self._source(name).import_source, doc.name)

    def test_vip_import_marks_created_member(self):
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _create_member

        doc = self._import_doc("VIP Import", duplicate_handling="Update existing")
        member = _create_member(
            {
                "first_name": "Vip",
                "last_name": f"Row{self.uid}",
                "personal_email": f"vip-{frappe.generate_hash(length=8)}@example.com",
            },
            doc,
        )
        self.assertEqual(self._source(member.name).import_source_type, "VIP Import")
        self.assertEqual(self._source(member.name).import_source, doc.name)

    def test_unknown_import_record_leaves_fields_empty(self):
        """The MijnRood event sync passes a label ('MijnRood Sync: ...'), not a record name."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        row = self._mijnrood_row()
        with bulk_member_operations("MijnRood Sync: EVT-1"):
            status, name = get_member_import_service().create_or_update_member(
                row_data=row, import_doc_name="MijnRood Sync: EVT-1", create_volunteer_records=False
            )
        self.assertEqual(status, "created")
        self.assertFalse(self._source(name).import_source)
        self.assertFalse(self._source(name).import_source_type)

    # ---- integrity check -------------------------------------------------------
    def test_integrity_check_skips_imported_quit_member_but_flags_hand_made_one(self):
        imported_doc = self._import_doc()
        status, imported = self._run_mijnrood(self._mijnrood_row(membership_type="opgezegd"), imported_doc)
        self.assertEqual(status, "created")
        self.assertEqual(frappe.db.get_value("Member", imported, "status"), "Quit")

        hand_made = self.create_test_member(first_name="Hand", last_name=f"Made{self.uid}").name
        frappe.db.set_value("Member", hand_made, "status", "Quit")  # probe shortcut, see module docstring

        flagged = tu.get_quit_members_without_executed_termination()
        self.assertIn(hand_made, flagged)
        self.assertNotIn(imported, flagged)


class TestBackfillMemberImportSource(EnhancedTestCase):
    def _member_with_notes(self, review_notes, **fields):
        member = self.create_test_member(first_name="Back", last_name=f"Fill{self.uid}")
        frappe.db.set_value("Member", member.name, {"review_notes": review_notes, **fields})
        return member.name

    def _import_name(self):
        self.expectErrorLog("Error Attaching File")
        return (
            frappe.get_doc(
                {"doctype": "Mijnrood CSV Import", "csv_file": "/files/none.csv", "encoding": "utf-8"}
            )
            .insert()
            .name
        )

    def _pair(self, name):
        return tuple(frappe.db.get_value("Member", name, ["import_source_type", "import_source"]))

    def test_backfill_cases(self):
        from verenigingen.patches.v2_2.backfill_member_import_source import (
            backfill_member_import_source,
        )

        first, second, other = self._import_name(), self._import_name(), self._import_name()
        note = "Imported from Mijnrood CSV (Import: {})"
        matched = self._member_with_notes(f"hello\n{note.format(first)}\n{note.format(second)}")
        missing = self._member_with_notes(note.format("MIJ-DOES-NOT-EXIST"))
        no_note = self._member_with_notes("just a note")
        already = self._member_with_notes(
            note.format(first), import_source_type="Mijnrood CSV Import", import_source=other
        )

        counts = backfill_member_import_source()

        self.assertEqual(self._pair(matched), ("Mijnrood CSV Import", second), "last note line wins")
        self.assertEqual(self._pair(missing), (None, None))
        self.assertEqual(self._pair(no_note), (None, None))
        self.assertEqual(self._pair(already), ("Mijnrood CSV Import", other), "never overwritten")
        self.assertGreaterEqual(counts["set"], 1)
        self.assertGreaterEqual(counts["missing_import"], 1)
        self.assertGreaterEqual(counts["already_set"], 1)

        again = backfill_member_import_source()
        self.assertEqual(again["set"], 0, "idempotent")
        self.assertEqual(self._pair(matched), ("Mijnrood CSV Import", second))
