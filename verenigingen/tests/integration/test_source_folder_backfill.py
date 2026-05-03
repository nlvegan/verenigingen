"""Integration tests for source_folder_backfill command.

The backfill connects to the MijnRood DB to fetch {file_hash: folder_id};
in this test we monkey-patch that fetch to a fake mapping so the test
runs without a live MijnRood DB.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSourceFolderBackfill(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(cleanup_on_exit=False)
        cls.chapter = cls.factory.create_test_chapter()

    @classmethod
    def tearDownClass(cls):
        cls.factory.cleanup()
        super().tearDownClass()

    def _make_doc(self, file_hash, source_folder_id=None):
        doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": "Chapter",
                "chapter": self.chapter.name,
                "document_name": f"hash-{file_hash[:6]}",
                "document_type": "Other",
                "document_file": "/private/files/dummy.pdf",
                "file_hash": file_hash,
                "source_folder_id": source_folder_id,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        self.addCleanup(lambda n=doc.name: frappe.delete_doc(
            "Organization Document", n, ignore_permissions=True, force=True))
        return doc

    def test_backfill_matches_by_hash(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="a" * 64)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={"a" * 64: 42},
        ):
            result = source_folder_backfill.backfill_source_folder_ids()

        # Assert tolerantly: the suite is shared with other tests that may
        # leave Organization Documents with file_hash but unset source_folder_id
        # (and thus contribute to no_hash_match). The contract this test cares
        # about is: this test's doc was matched and updated.
        self.assertGreaterEqual(result["matched"], 1)
        doc.reload()
        self.assertEqual(doc.source_folder_id, 42)

    def test_backfill_skips_already_set(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="b" * 64, source_folder_id=99)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={"b" * 64: 42},
        ):
            result = source_folder_backfill.backfill_source_folder_ids()

        # Already-set rows aren't re-considered or counted as matched
        self.assertEqual(result["matched"], 0)
        self.assertGreaterEqual(result["already_set"], 1)

        # And — critically — the existing value must NOT be overwritten with 42
        doc.reload()
        self.assertEqual(doc.source_folder_id, 99)

    def test_backfill_records_no_hash_match(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="c" * 64)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={},
        ):
            result = source_folder_backfill.backfill_source_folder_ids()

        self.assertEqual(result["matched"], 0)
        self.assertGreaterEqual(result["no_hash_match"], 1)
        doc.reload()
        # Int field defaults to 0 (NOT NULL); 0 means "not set"
        self.assertFalse(doc.source_folder_id)

    def test_backfill_dry_run_does_not_write(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="d" * 64)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={"d" * 64: 7},
        ):
            result = source_folder_backfill.backfill_source_folder_ids(dry_run=True)

        # Counts the would-be match
        self.assertEqual(result["matched"], 1)
        self.assertTrue(result["dry_run"])
        doc.reload()
        # Int field defaults to 0 (NOT NULL); 0 means "not set"
        self.assertFalse(doc.source_folder_id)
