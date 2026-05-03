"""Integration tests for document_reclassify_service.reclassify_documents."""

from datetime import date

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class TestReclassifyDocuments(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(cleanup_on_exit=False)
        cls.chapter_a = cls.factory.create_test_chapter()
        cls.chapter_b = cls.factory.create_test_chapter()

        # Configure the MijnRood Sync Settings child table with two mappings.
        # Snapshot the original mapping so tearDownClass restores it.
        settings = frappe.get_single("MijnRood Sync Settings")
        cls._original_mapping = [
            {
                "mijnrood_folder_id": r.mijnrood_folder_id,
                "folder_name": r.folder_name,
                "folder_path": r.folder_path,
                "organization_type": r.organization_type,
                "chapter": r.chapter,
                "team": r.team,
                "movement": r.movement,
                "document_type": r.document_type,
            }
            for r in (settings.document_folder_mapping or [])
        ]

        settings.set("document_folder_mapping", [])
        settings.append(
            "document_folder_mapping",
            {
                "mijnrood_folder_id": 100,
                "folder_name": "Meeting Minutes",
                "folder_path": "Afdelingen / Test A / Meeting Minutes",
                "organization_type": "Chapter",
                "chapter": cls.chapter_a.name,
                "document_type": "Meeting Minutes",
            },
        )
        settings.append(
            "document_folder_mapping",
            {
                "mijnrood_folder_id": 101,
                "folder_name": "Overig",
                "folder_path": "Afdelingen / Test B / Overig",
                "organization_type": "Chapter",
                "chapter": cls.chapter_b.name,
                "document_type": "Other",
            },
        )
        settings.flags.ignore_validate = True
        settings.flags.ignore_permissions = True
        settings.save()

        cls.settings_doc = settings

    @classmethod
    def tearDownClass(cls):
        # Restore the original mapping so we don't pollute the dev site
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("document_folder_mapping", [])
        for row in cls._original_mapping:
            settings.append("document_folder_mapping", row)
        settings.flags.ignore_validate = True
        settings.flags.ignore_permissions = True
        settings.save()

        cls.factory.cleanup()
        super().tearDownClass()

    def _make_doc(self, **overrides):
        defaults = dict(
            doctype="Organization Document",
            organization_type="Chapter",
            chapter=self.chapter_b.name,  # "wrong" chapter on purpose
            document_name="2024-05-17 notulen.pdf",
            document_type="Other",
            document_file="/private/files/dummy.pdf",
            source_folder_id=100,  # mapped to chapter_a + Notulen
        )
        defaults.update(overrides)
        doc = frappe.get_doc(defaults)
        doc.flags.ignore_permissions = True
        doc.insert()
        self.addCleanup(lambda n=doc.name: frappe.delete_doc(
            "Organization Document", n, ignore_permissions=True, force=True))
        return doc

    def test_dry_run_returns_diff_without_writing(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc()
        result = reclassify_documents([doc.name], dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(len(result["changes"]), 1)

        change = result["changes"][0]
        self.assertEqual(change["name"], doc.name)
        self.assertIn("document_type", change["diff_fields"])
        self.assertIn("chapter", change["diff_fields"])
        self.assertIn("applies_on", change["diff_fields"])
        self.assertEqual(change["proposed"]["document_type"], "Meeting Minutes")
        self.assertEqual(change["proposed"]["chapter"], self.chapter_a.name)
        self.assertEqual(change["proposed"]["applies_on"], "2024-05-17")
        self.assertEqual(change["proposed"]["applies_on_precision"], "Day")

        # Verify nothing actually written
        doc.reload()
        self.assertEqual(doc.document_type, "Other")
        self.assertEqual(doc.chapter, self.chapter_b.name)
        self.assertIsNone(doc.applies_on)

    def test_apply_mode_writes_diff(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc()
        result = reclassify_documents([doc.name], dry_run=False)

        self.assertEqual(result["applied"], 1)
        doc.reload()
        self.assertEqual(doc.document_type, "Meeting Minutes")
        self.assertEqual(doc.chapter, self.chapter_a.name)
        self.assertEqual(doc.applies_on, date(2024, 5, 17))
        self.assertEqual(doc.applies_on_precision, "Day")

    def test_unchanged_doc_skipped(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        # Doc that already matches the mapping
        doc = self._make_doc(
            chapter=self.chapter_a.name,
            document_type="Meeting Minutes",
            applies_on="2024-05-17",
            applies_on_precision="Day",
        )
        result = reclassify_documents([doc.name], dry_run=True)
        self.assertEqual(len(result["changes"]), 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "unchanged")

    def test_no_source_folder_id_skipped(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc(source_folder_id=None)
        result = reclassify_documents([doc.name], dry_run=True)
        self.assertEqual(len(result["changes"]), 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("no source_folder_id", result["skipped"][0]["reason"])

    def test_unmapped_folder_skipped(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc(source_folder_id=99999)  # not in mapping
        result = reclassify_documents([doc.name], dry_run=True)
        self.assertEqual(len(result["changes"]), 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "no folder mapping")

    def test_year_subfolder_walks_parent_chain(self):
        """A doc whose source_folder_id is a year-subfolder (not in mapping)
        should resolve via the parent chain to its mapped ancestor.

        Mirrors document_import_service's _resolve_mapped_folder behavior.
        """
        from unittest.mock import patch

        from verenigingen.mijnrood_sync.services import document_reclassify_service

        # Fake folder tree: folder 250 ("2024") is the year-subfolder of folder 100 (mapped to chapter_a + Meeting Minutes)
        fake_tree = {
            100: {"id": 100, "name": "Notulen", "parent_id": None},
            250: {"id": 250, "name": "2024", "parent_id": 100},
        }

        doc = self._make_doc(
            source_folder_id=250,  # year-subfolder, NOT directly in mapping
            chapter=self.chapter_b.name,  # wrong on purpose
            document_type="Other",
        )

        with patch.object(
            document_reclassify_service,
            "_fetch_folder_tree",
            return_value=fake_tree,
        ):
            result = document_reclassify_service.reclassify_documents(
                [doc.name], dry_run=True
            )

        self.assertEqual(len(result["changes"]), 1, msg=f"expected 1 change, got result={result}")
        change = result["changes"][0]
        self.assertEqual(change["proposed"]["chapter"], self.chapter_a.name)
        self.assertEqual(change["proposed"]["document_type"], "Meeting Minutes")

    def _setup_folder_path(self, folder_id, folder_path):
        """Setup helper: patch a folder mapping's folder_path for a test."""
        settings = frappe.get_single("MijnRood Sync Settings")
        for row in settings.document_folder_mapping:
            if row.mijnrood_folder_id == folder_id:
                row.folder_path = folder_path
        settings.flags.ignore_validate = True
        settings.flags.ignore_permissions = True
        settings.save()

    def test_date_falls_back_to_folder_path(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        # Folder 101's folder_path is "Afdelingen / Test B / Overig" — no date.
        # Append a year so the path-fallback fires:
        self._setup_folder_path(101, "Afdelingen / Test B / Overig / 2023")

        doc = self._make_doc(
            source_folder_id=101,
            chapter=self.chapter_a.name,  # wrong on purpose
            document_name="overige notulen.pdf",  # no date in name
        )
        result = reclassify_documents([doc.name], dry_run=True)

        change = result["changes"][0]
        self.assertEqual(change["proposed"]["applies_on"], "2023-01-01")
        self.assertEqual(change["proposed"]["applies_on_precision"], "Year")

    def test_cap_at_500(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        names = [f"doc-{i}" for i in range(501)]
        with self.assertRaises(frappe.ValidationError):
            reclassify_documents(names, dry_run=True)

    def test_permission_denied_for_non_admin(self):
        """A user without System Manager / Verenigingen Administrator gets PermissionError.

        Per MEMORY.md: tests must exercise non-Admin role paths (Admin bypasses
        all DocPerms / only_for checks).
        """
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        # Create a member-only test user (no admin roles)
        member = self.factory.create_test_member()
        # The factory's create_test_member should produce a User; if not, skip with reason
        if not getattr(member, "user", None):
            self.skipTest("Test factory did not link a User to the Member")

        with self.as_user(member.user):
            with self.assertRaises(frappe.PermissionError):
                reclassify_documents(["nonexistent"], dry_run=True)
