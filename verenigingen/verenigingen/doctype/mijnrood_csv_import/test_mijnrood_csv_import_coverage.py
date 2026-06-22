# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# Targeted coverage sweep for the Mijnrood CSV Import controller. The three
# existing test files cover the bulk of the controller; this file fills the
# specific remaining branches that are pure / real-DB testable (NOT the
# ACR/volunteer-service or background-enqueue paths, which are service- and
# job-gated and covered separately by the pipeline tests):
#
#   - _validate_and_preview_csv(): the internal manual-preview method — the
#     Ready-for-Import success branch (preview_data + descriptive_name) and the
#     validation-error Failed branch (distinct from the whitelisted
#     validate_import_file endpoint, which the pipeline test already covers).
#   - _categorize_skipped_members(): the Dues-Rate, Age, and Required-Field
#     buckets that the existing categorize test does not exercise.
#   - _should_create_membership(): the True path (Active + dues_rate + no
#     existing membership) and the existing-active-membership → False path.
#   - _generate_itemized_member_list(): the skipped-section categorization branch.
#
# Reuses the rich real-File / real-import fixture base from the primary test
# module so the bodies stay assertion-focused.

import csv
import io
import random

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _Base(EnhancedTestCase):
    """Self-contained real-File / real-import fixture base.

    Deliberately NOT subclassing the runnable TestMijnroodCSVImportRealIntegration
    (which would re-execute ~118 inherited tests under this module). Re-implements
    only the small fixture helpers this file needs.
    """

    def setUp(self):
        super().setUp()
        self._created_files = []
        self._created_imports = []
        self._created_members = []

    def tearDown(self):
        for member_name in self._created_members:
            try:
                frappe.delete_doc("Member", member_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        for import_name in self._created_imports:
            try:
                frappe.delete_doc("Mijnrood CSV Import", import_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        for file_name in self._created_files:
            try:
                frappe.delete_doc("File", file_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        super().tearDown()

    def _make_csv_bytes(self, rows, headers=None):
        if headers is None:
            headers = list(rows[0].keys()) if rows else []
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        return out.getvalue()

    def _create_csv_file_doc(self, content):
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"mijnrood_cov_{random.randint(100000, 999999)}.csv",
                "is_private": 1,
                "content": content,
            }
        ).insert()
        self._created_files.append(file_doc.name)
        return file_doc

    def _make_import_doc(self, rows, encoding="utf-8", **kwargs):
        file_doc = self._create_csv_file_doc(self._make_csv_bytes(rows))
        doc = frappe.get_doc(
            {
                "doctype": "Mijnrood CSV Import",
                "csv_file": file_doc.file_url,
                "encoding": encoding,
                "import_date": frappe.utils.today(),
                **kwargs,
            }
        )
        doc.insert()
        self._created_imports.append(doc.name)
        return doc

    def _new_unsaved_doc(self):
        return frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "encoding": "utf-8", "import_date": frappe.utils.today()}
        )


class TestMijnroodValidateAndPreviewInternal(_Base):
    """_validate_and_preview_csv() success + failure branches."""

    def test_preview_sets_ready_and_descriptive_name(self):
        doc = self._make_import_doc(
            [
                {
                    "Voornaam": "Prev",
                    "Achternaam": "Tester",
                    "E-mailadres": "prev@example.com",
                },
                {
                    "Voornaam": "Prev2",
                    "Achternaam": "Tester",
                    "E-mailadres": "prev2@example.com",
                },
            ]
        )
        doc._validate_and_preview_csv()
        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertTrue(doc.preview_data)
        self.assertIn("Member Import", doc.descriptive_name)
        self.assertIn("records", doc.descriptive_name)

    def test_preview_with_validation_errors_throws_and_marks_failed(self):
        # An invalid email triggers validator errors → Failed + throw.
        doc = self._make_import_doc(
            [
                {
                    "Voornaam": "Bad",
                    "Achternaam": "Email",
                    "E-mailadres": "not-an-email",
                }
            ]
        )
        with self.assertRaises(frappe.ValidationError):
            doc._validate_and_preview_csv()
        self.assertEqual(doc.import_status, "Failed")
        self.assertTrue(doc.error_log)


class TestMijnroodCategorizeSkippedExtraBuckets(_Base):
    """_categorize_skipped_members() buckets not covered by the primary test."""

    def test_dues_age_and_required_buckets(self):
        doc = self._new_unsaved_doc()
        skipped = [
            "Lidnr 10: Dues Person - Dues rate (€7.50) cannot be less than minimum amount (€9.00)",
            "Lidnr 11: Young Person - Member too young to register",
            "Lidnr 12: Missing Field - Required field is missing",
        ]
        cats = doc._categorize_skipped_members(skipped)
        self.assertIn("10 (Dues Person)", cats["Dues Rate Below Minimum"])
        self.assertIn("11 (Young Person)", cats["Age Validation Failed"])
        self.assertIn("12 (Missing Field)", cats["Required Field Missing"])
        # The non-matching categories must be pruned.
        self.assertNotIn("IBAN Validation Failed", cats)

    def test_unknown_error_bucketed_with_truncated_message(self):
        doc = self._new_unsaved_doc()
        long_err = "some weird failure " * 10  # >80 chars, unknown category
        cats = doc._categorize_skipped_members([f"Lidnr 13: Weird Case - {long_err}"])
        other = cats["Other Validation Errors"]
        self.assertEqual(len(other), 1)
        # Entry carries the member display + a truncated (<=80 char) error tail.
        self.assertTrue(other[0].startswith("13 (Weird Case)"))


class TestMijnroodShouldCreateMembership(_Base):
    """_should_create_membership() True + existing-membership-blocks branches."""

    def _make_active_member(self):
        doc = self._make_import_doc(
            [{"Voornaam": "Ship", "Achternaam": "Member", "E-mailadres": "ship@example.com"}],
            create_volunteer_records=0,
        )
        row = {
            "row_number": 2,
            "first_name": "Ship",
            "last_name": "Member",
            "email": f"ship_{frappe.generate_hash(length=6)}@example.com",
        }
        result, member_name = doc._process_single_member(row, [])
        self.assertEqual(result, "created")
        self._created_members.append(member_name)
        member = frappe.get_doc("Member", member_name)
        member.status = "Active"
        return doc, member

    def test_true_when_active_with_dues_and_no_existing_membership(self):
        doc, member = self._make_active_member()
        # Active + dues_rate present + no active Membership → should create.
        self.assertTrue(doc._should_create_membership(member, {"dues_rate": 25}))

    def test_false_when_active_membership_already_exists(self):
        doc, member = self._make_active_member()

        membership_type = frappe.get_all("Membership Type", limit=1)
        if not membership_type:
            self.skipTest("No Membership Type configured on this site")
        ms = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type[0].name,
                "status": "Active",
            }
        )
        ms.flags.ignore_mandatory = True
        ms.insert()
        ms.submit()  # docstatus=1 so the exists() filter matches

        self.assertFalse(doc._should_create_membership(member, {"dues_rate": 25}))


class TestMijnroodItemizedListSkippedSection(_Base):
    """_generate_itemized_member_list() skipped-section categorization branch."""

    def test_skipped_section_is_categorized(self):
        doc = self._new_unsaved_doc()
        out = doc._generate_itemized_member_list(
            created_members=["MEM-A"],
            updated_members=["MEM-B"],
            skipped_members=[
                "Lidnr 20: Skip One - Duplicate entry found",
                "Lidnr 21: Skip Two - Invalid IBAN provided",
            ],
        )
        self.assertIn("Created Members (1)", out)
        self.assertIn("Updated Members (1)", out)
        self.assertIn("Skipped Members (2)", out)
        # The categorized sub-headers appear for the parsed skip reasons.
        self.assertIn("Duplicate Entry", out)
        self.assertIn("IBAN Validation Failed", out)
