# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for source_folder_backfill.backfill_source_folder_ids.

Matches Organization Documents (by SHA256 file_hash) against MijnRood's
hash→folder_id map and stamps source_folder_id. The MijnRood hash-fetch
boundary (_fetch_mijnrood_hash_to_folder) is the only thing stubbed; the
hash lookup, dry-run, and db.set_value persistence run against the real
test_site_4 database.
"""

import hashlib
from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync.services import source_folder_backfill as bf
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# A minimal but structurally valid PDF (Frappe runs bytes through pypdf on save).
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000052 00000 n \n0000000101 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n164\n%%EOF\n"
)


def _pdf(marker: bytes = b"") -> bytes:
    if not marker:
        return _MINIMAL_PDF
    return _MINIMAL_PDF + b"%% " + marker + b"\n"


class TestBackfillSourceFolderIds(EnhancedTestCase):
    def _make_org_doc(self, chapter_name, file_hash, source_folder_id=0):
        from verenigingen.utils.file_storage import save_organization_document

        file_result = save_organization_document(
            content=_pdf(frappe.generate_hash()[:8].encode()),
            filename="backfill.pdf",
            organization_type="Chapter",
            organization_name=chapter_name,
            category="Other",
            year="Other",
            is_private=1,
        )
        doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": "Chapter",
                "chapter": chapter_name,
                "document_name": "Backfill Target.pdf",
                "document_type": "Other",
                "document_file": file_result["file_url"],
                "file_hash": file_hash,
                "source_folder_id": source_folder_id,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        return doc

    def _hash(self, marker):
        return hashlib.sha256(marker.encode()).hexdigest()

    # ---- input validation -------------------------------------------------

    def test_invalid_batch_size_raises(self):
        with self.assertRaises(ValueError):
            bf.backfill_source_folder_ids(batch_size=0)
        with self.assertRaises(ValueError):
            bf.backfill_source_folder_ids(batch_size=-5)
        with self.assertRaises(ValueError):
            bf.backfill_source_folder_ids(batch_size="20")

    # ---- happy path -------------------------------------------------------

    def test_matches_and_stamps_folder_id(self):
        chapter = self.create_test_chapter()
        h = self._hash(frappe.generate_hash())
        doc = self._make_org_doc(chapter.name, h, source_folder_id=0)

        with patch.object(bf, "_fetch_mijnrood_hash_to_folder", return_value={h: 77}):
            result = bf.backfill_source_folder_ids(dry_run=False)

        self.assertGreaterEqual(result["matched"], 1)
        self.assertEqual(frappe.db.get_value("Organization Document", doc.name, "source_folder_id"), 77)

    def test_dry_run_does_not_write(self):
        chapter = self.create_test_chapter()
        h = self._hash(frappe.generate_hash())
        doc = self._make_org_doc(chapter.name, h, source_folder_id=0)

        with patch.object(bf, "_fetch_mijnrood_hash_to_folder", return_value={h: 88}):
            result = bf.backfill_source_folder_ids(dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertGreaterEqual(result["matched"], 1)
        # Not persisted
        self.assertEqual(frappe.db.get_value("Organization Document", doc.name, "source_folder_id"), 0)

    def test_no_hash_match_counted(self):
        chapter = self.create_test_chapter()
        h = self._hash(frappe.generate_hash())
        doc = self._make_org_doc(chapter.name, h, source_folder_id=0)

        # MijnRood map has a different hash -> this doc is no_hash_match
        with patch.object(bf, "_fetch_mijnrood_hash_to_folder", return_value={"deadbeef": 5}):
            result = bf.backfill_source_folder_ids(dry_run=False)

        self.assertGreaterEqual(result["no_hash_match"], 1)
        self.assertEqual(frappe.db.get_value("Organization Document", doc.name, "source_folder_id"), 0)

    def test_already_set_rows_excluded_from_matching(self):
        """A doc that already has source_folder_id > 0 is not re-processed."""
        chapter = self.create_test_chapter()
        h = self._hash(frappe.generate_hash())
        doc = self._make_org_doc(chapter.name, h, source_folder_id=123)

        with patch.object(bf, "_fetch_mijnrood_hash_to_folder", return_value={h: 999}) as fetch:
            result = bf.backfill_source_folder_ids(dry_run=False)

        # already_set count includes our row
        self.assertGreaterEqual(result["already_set"], 1)
        # Value untouched (not overwritten with 999)
        self.assertEqual(frappe.db.get_value("Organization Document", doc.name, "source_folder_id"), 123)

    def test_mijnrood_fetch_failure_returns_error(self):
        chapter = self.create_test_chapter()
        h = self._hash(frappe.generate_hash())
        self._make_org_doc(chapter.name, h, source_folder_id=0)

        with patch.object(bf, "_fetch_mijnrood_hash_to_folder", side_effect=ConnectionError("DB down")):
            result = bf.backfill_source_folder_ids(dry_run=False)

        self.assertEqual(result["matched"], 0)
        self.assertTrue(result["errors"])
        self.assertIn("MijnRood fetch failed", result["errors"][0])

    def test_no_rows_short_circuits_without_fetch(self):
        """When no candidate rows exist, MijnRood is never queried."""
        # Ensure there are no source_folder_id=0 rows by patching the candidate query.
        # Use the public function but assert it returns the empty-shape dict.
        with (
            patch.object(frappe.db, "get_all", return_value=[]) as get_all,
            patch.object(bf, "_fetch_mijnrood_hash_to_folder") as fetch,
        ):
            result = bf.backfill_source_folder_ids(dry_run=False)

        fetch.assert_not_called()
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["no_hash_match"], 0)


class TestFetchMijnroodHashToFolder(EnhancedTestCase):
    """_fetch_mijnrood_hash_to_folder DB-column-first / SFTP-fallback logic."""

    class _DBClientWithHash:
        def __init__(self, mapping):
            self._mapping = mapping

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def fetch_document_hash_to_folder(self):
            return self._mapping

    class _DBClientNoHashMethod:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        # no fetch_document_hash_to_folder attribute

    def test_uses_db_hash_column_when_available(self):
        client = self._DBClientWithHash({"abc": 4})
        with (
            patch("verenigingen.mijnrood_sync.client.MijnRoodDatabaseClient", return_value=client),
            patch.object(frappe, "get_single", return_value=frappe._dict()),
        ):
            result = bf._fetch_mijnrood_hash_to_folder()
        self.assertEqual(result, {"abc": 4})

    def test_falls_back_to_sftp_when_no_hash_method(self):
        client = self._DBClientNoHashMethod()
        with (
            patch("verenigingen.mijnrood_sync.client.MijnRoodDatabaseClient", return_value=client),
            patch.object(frappe, "get_single", return_value=frappe._dict()),
            patch.object(bf, "_sftp_hash_to_folder", return_value={"fromsftp": 1}) as sftp_fb,
        ):
            result = bf._fetch_mijnrood_hash_to_folder()
        sftp_fb.assert_called_once()
        self.assertEqual(result, {"fromsftp": 1})
