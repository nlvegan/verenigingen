# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Integration tests for DocumentImportService.

Covers the PURE classification/mapping logic and the import orchestration
driven through an injected fake SFTP client. The remote MijnRood SSH/SFTP/DB
boundary is the only thing stubbed — all app business logic (folder
classification, chapter inference, dedup, Organization Document creation) runs
against the real database.
"""

import hashlib

import frappe

from verenigingen.mijnrood_sync.services.document_import_service import DocumentImportService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# A minimal but structurally valid PDF. Frappe's File doctype runs the bytes
# through pypdf on save, so the canned SFTP payload must be a real PDF.
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
    """Return a valid PDF, optionally varied by a marker so hashes differ."""
    if not marker:
        return _MINIMAL_PDF
    return _MINIMAL_PDF + b"%% " + marker + b"\n"


class _FakeSFTPClient:
    """Boundary stub for MijnRoodSFTPClient — returns canned file bytes.

    Only the SFTP transport is faked; everything the service does with the
    bytes (hashing, dedup, file storage, doc creation) is real.
    """

    def __init__(self, files: dict[str, bytes]):
        self._files = files
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.entered = False
        return False

    def download_file(self, remote_filename: str) -> bytes:
        if remote_filename not in self._files:
            raise FileNotFoundError(remote_filename)
        return self._files[remote_filename]


class TestDocumentImportServiceLogic(EnhancedTestCase):
    """Pure classification / mapping logic — no external boundary needed."""

    def _make_service(self):
        """Build a service against the real MijnRood Sync Settings single."""
        return DocumentImportService()

    # ---- _infer_document_type -------------------------------------------

    def test_infer_document_type_matches_keyword(self):
        service = self._make_service()
        keyword_map = {"Financial Report": ["financien", "begroting"]}
        self.assertEqual(
            service._infer_document_type("landelijk / financien / 2024", keyword_map),
            "Financial Report",
        )

    def test_infer_document_type_no_match_returns_blank(self):
        service = self._make_service()
        keyword_map = {"Financial Report": ["financien"]}
        self.assertEqual(service._infer_document_type("random / unrelated", keyword_map), "")

    def test_infer_document_type_empty_path_returns_blank(self):
        service = self._make_service()
        self.assertEqual(service._infer_document_type("", {"X": ["y"]}), "")

    def test_infer_document_type_uses_real_keyword_map(self):
        """Drive _infer_document_type with the real Board Document Categories."""
        service = self._make_service()
        keyword_map = service._load_category_keywords()
        # The seeded site has "notulen" -> Meeting Minutes. If the site's
        # categories differ, just assert it returns a valid (possibly blank)
        # string without crashing.
        result = service._infer_document_type("bestuur / notulen / 2023", keyword_map)
        self.assertIsInstance(result, str)
        if "Meeting Minutes" in keyword_map:
            self.assertEqual(result, "Meeting Minutes")

    # ---- _infer_chapter --------------------------------------------------

    def test_infer_chapter_national_synonym(self):
        service = self._make_service()
        result = service._infer_chapter("landelijk / 2024", {}, "National Board")
        self.assertEqual(result, "National Board")

    def test_infer_chapter_exact_match(self):
        service = self._make_service()
        chapter_names = {"amsterdam": "Amsterdam"}
        result = service._infer_chapter("afdelingen / amsterdam", chapter_names, "National Board")
        self.assertEqual(result, "Amsterdam")

    def test_infer_chapter_partial_match(self):
        service = self._make_service()
        chapter_names = {"amsterdam": "Amsterdam"}
        # segment "amsterdam noord" contains chapter "amsterdam"
        result = service._infer_chapter("afdelingen / amsterdam noord", chapter_names, "National Board")
        self.assertEqual(result, "Amsterdam")

    def test_infer_chapter_falls_back_to_national(self):
        service = self._make_service()
        result = service._infer_chapter("some / unmatched / path", {}, "National Board")
        self.assertEqual(result, "National Board")

    # ---- _build_parent_map ----------------------------------------------

    def test_build_parent_map_simple_hierarchy(self):
        service = self._make_service()
        rows = [
            frappe._dict({"mijnrood_folder_id": 1, "folder_path": "A"}),
            frappe._dict({"mijnrood_folder_id": 2, "folder_path": "A / B"}),
            frappe._dict({"mijnrood_folder_id": 3, "folder_path": "A / B / C"}),
        ]
        parent_map = service._build_parent_map(rows)
        self.assertIsNone(parent_map[1])
        self.assertEqual(parent_map[2], 1)
        self.assertEqual(parent_map[3], 2)

    def test_build_parent_map_skips_missing_intermediate(self):
        """Path 'A / B / C' with no row for 'A / B' walks up to 'A'."""
        service = self._make_service()
        rows = [
            frappe._dict({"mijnrood_folder_id": 1, "folder_path": "A"}),
            frappe._dict({"mijnrood_folder_id": 3, "folder_path": "A / B / C"}),
        ]
        parent_map = service._build_parent_map(rows)
        self.assertIsNone(parent_map[1])
        self.assertEqual(parent_map[3], 1)

    def test_build_parent_map_no_path(self):
        service = self._make_service()
        rows = [frappe._dict({"mijnrood_folder_id": 1, "folder_path": None})]
        parent_map = service._build_parent_map(rows)
        self.assertIsNone(parent_map[1])

    # ---- _compute_folder_path / _get_folder_path ------------------------

    def test_compute_folder_path(self):
        service = self._make_service()
        tree = {
            1: {"id": 1, "name": "Financien", "parent_id": None},
            2: {"id": 2, "name": "2024", "parent_id": 1},
        }
        self.assertEqual(service._compute_folder_path(2, tree), "Financien / 2024")

    def test_compute_folder_path_handles_cycle(self):
        """A parent_id cycle must not loop forever."""
        service = self._make_service()
        tree = {
            1: {"id": 1, "name": "A", "parent_id": 2},
            2: {"id": 2, "name": "B", "parent_id": 1},
        }
        # Should terminate (seen-set guard) and return some path
        result = service._compute_folder_path(1, tree)
        self.assertIn("A", result)

    def test_get_folder_path_none_id(self):
        service = self._make_service()
        service.folder_tree = {1: {"id": 1, "name": "A", "parent_id": None}}
        self.assertIsNone(service._get_folder_path(None))

    def test_get_folder_path_not_in_tree(self):
        service = self._make_service()
        service.folder_tree = {1: {"id": 1, "name": "A", "parent_id": None}}
        self.assertIsNone(service._get_folder_path(99))

    def test_get_folder_path_empty_tree(self):
        service = self._make_service()
        service.folder_tree = {}
        self.assertIsNone(service._get_folder_path(1))

    def test_get_folder_path_resolves(self):
        service = self._make_service()
        service.folder_tree = {
            1: {"id": 1, "name": "Landelijk", "parent_id": None},
            2: {"id": 2, "name": "Notulen", "parent_id": 1},
        }
        self.assertEqual(service._get_folder_path(2), "Landelijk / Notulen")

    # ---- _resolve_mapped_folder -----------------------------------------

    def test_resolve_mapped_folder_direct(self):
        service = self._make_service()
        service.folder_mapping = {5: {"organization_type": "Chapter"}}
        service.folder_tree = {5: {"id": 5, "parent_id": None}}
        self.assertEqual(service._resolve_mapped_folder(5), 5)

    def test_resolve_mapped_folder_walks_to_ancestor(self):
        service = self._make_service()
        service.folder_mapping = {1: {"organization_type": "Chapter"}}
        service.folder_tree = {
            1: {"id": 1, "parent_id": None},
            2: {"id": 2, "parent_id": 1},  # year subfolder, unmapped
        }
        self.assertEqual(service._resolve_mapped_folder(2), 1)

    def test_resolve_mapped_folder_no_ancestor(self):
        service = self._make_service()
        service.folder_mapping = {}
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        self.assertIsNone(service._resolve_mapped_folder(1))

    def test_resolve_mapped_folder_uses_cache(self):
        service = self._make_service()
        service.folder_mapping = {1: {"organization_type": "Chapter"}}
        service.folder_tree = {1: {"id": 1, "parent_id": None}, 2: {"id": 2, "parent_id": 1}}
        self.assertEqual(service._resolve_mapped_folder(2), 1)
        # Second call should hit the cache and return same result
        self.assertIn(2, service.root_cache)
        self.assertEqual(service._resolve_mapped_folder(2), 1)

    def test_resolve_mapped_folder_handles_cycle(self):
        service = self._make_service()
        service.folder_mapping = {}
        service.folder_tree = {
            1: {"id": 1, "parent_id": 2},
            2: {"id": 2, "parent_id": 1},
        }
        self.assertIsNone(service._resolve_mapped_folder(1))

    # ---- _get_mapping_for_document --------------------------------------

    def test_get_mapping_for_document_no_folder_id(self):
        service = self._make_service()
        self.assertIsNone(service._get_mapping_for_document({"id": 1}))

    def test_get_mapping_for_document_resolves(self):
        service = self._make_service()
        mapping = {"organization_type": "Chapter", "chapter": "X", "document_type": "Other"}
        service.folder_mapping = {1: mapping}
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        self.assertEqual(service._get_mapping_for_document({"folder_id": 1}), mapping)

    def test_get_mapping_for_document_unmapped(self):
        service = self._make_service()
        service.folder_mapping = {}
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        self.assertIsNone(service._get_mapping_for_document({"folder_id": 1}))

    # ---- _dry_run_summary -----------------------------------------------

    def test_dry_run_summary_counts(self):
        service = self._make_service()
        service.folder_mapping = {
            1: {"organization_type": "Chapter", "chapter": "MyChapter", "document_type": "Other"},
        }
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        documents = [
            {"id": 10, "folder_id": 1},  # mappable
            {"id": 11, "folder_id": 99},  # unmapped
            {"id": 12, "folder_id": None},  # unmapped
        ]
        summary = service._dry_run_summary(documents)
        self.assertTrue(summary["dry_run"])
        self.assertEqual(summary["would_import"], 1)
        self.assertEqual(summary["unmapped"], 2)
        self.assertEqual(summary["total_documents"], 3)

    def test_dry_run_summary_mapping_without_entity_is_unmapped(self):
        """A mapping whose org entity field is blank counts as unmapped."""
        service = self._make_service()
        service.folder_mapping = {
            1: {"organization_type": "Chapter", "chapter": "", "document_type": "Other"},
        }
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        summary = service._dry_run_summary([{"id": 10, "folder_id": 1}])
        self.assertEqual(summary["would_import"], 0)
        self.assertEqual(summary["unmapped"], 1)

    # ---- _get_default_mapping -------------------------------------------

    def test_get_default_mapping_no_national_chapter(self):
        """When national_board_chapter is unset, defaults are empty."""
        service = self._make_service()
        orig = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", "")
            self.assertEqual(service._get_default_mapping(), {})
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", orig or "")

    def test_get_default_mapping_with_national_chapter(self):
        service = self._make_service()
        chapter = self.create_test_chapter()
        orig = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", chapter.name)
            result = service._get_default_mapping()
            self.assertEqual(result["organization_type"], "Chapter")
            self.assertEqual(result["chapter"], chapter.name)
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", orig or "")

    # ---- _load_chapter_names --------------------------------------------

    def test_load_chapter_names_includes_active_chapter(self):
        chapter = self.create_test_chapter()
        names = DocumentImportService._load_chapter_names()
        self.assertIn(chapter.name.lower(), names)
        self.assertEqual(names[chapter.name.lower()], chapter.name)


class TestDocumentImportServiceImport(EnhancedTestCase):
    """import_all / _import_single_document driven through a fake SFTP client.

    These exercise the real dedup, file-storage, and Organization Document
    creation paths. The MijnRood SFTP boundary is replaced by _FakeSFTPClient.
    """

    def _build_service_with_mapping(self, chapter_name):
        """Service whose in-memory folder_mapping points at a real Chapter."""
        service = DocumentImportService()
        service.folder_mapping = {
            1: {
                "organization_type": "Chapter",
                "chapter": chapter_name,
                "team": None,
                "movement": None,
                "document_type": "Other",
            }
        }
        service.folder_tree = {1: {"id": 1, "name": "Landelijk", "parent_id": None}}
        return service

    def test_import_single_document_creates_org_doc(self):
        chapter = self.create_test_chapter()
        service = self._build_service_with_mapping(chapter.name)
        content = _pdf(b"create-org-doc")
        fake_sftp = _FakeSFTPClient({"file_abc.pdf": content})

        doc = {
            "id": 100,
            "name": "Notulen 2024-03-01.pdf",
            "folder_id": 1,
            "upload_file_name": "file_abc.pdf",
        }
        result = service._import_single_document(doc, fake_sftp)
        self.assertEqual(result, "imported")

        file_hash = hashlib.sha256(content).hexdigest()
        created = frappe.db.exists("Organization Document", {"file_hash": file_hash})
        self.assertTrue(created)
        org_doc = frappe.get_doc("Organization Document", created)
        self.assertEqual(org_doc.organization_type, "Chapter")
        self.assertEqual(org_doc.chapter, chapter.name)
        self.assertEqual(org_doc.source_folder_id, 1)
        # Date extracted from the filename
        self.assertEqual(str(org_doc.applies_on), "2024-03-01")

    def test_import_single_document_dedup_skips_duplicate(self):
        chapter = self.create_test_chapter()
        service = self._build_service_with_mapping(chapter.name)
        content = _pdf(b"dedup-bytes")
        fake_sftp = _FakeSFTPClient({"dup1.pdf": content, "dup2.pdf": content})

        doc1 = {"id": 1, "name": "first.pdf", "folder_id": 1, "upload_file_name": "dup1.pdf"}
        doc2 = {"id": 2, "name": "second.pdf", "folder_id": 1, "upload_file_name": "dup2.pdf"}

        self.assertEqual(service._import_single_document(doc1, fake_sftp), "imported")
        # Same bytes -> same hash -> skipped
        self.assertEqual(service._import_single_document(doc2, fake_sftp), "skipped")

    def test_import_single_document_no_mapping_skips(self):
        service = DocumentImportService()
        service.folder_mapping = {}
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        fake_sftp = _FakeSFTPClient({"x.pdf": b"x"})
        doc = {"id": 1, "folder_id": 1, "upload_file_name": "x.pdf"}
        self.assertEqual(service._import_single_document(doc, fake_sftp), "skipped")

    def test_import_single_document_no_upload_filename_skips(self):
        chapter = self.create_test_chapter()
        service = self._build_service_with_mapping(chapter.name)
        fake_sftp = _FakeSFTPClient({})
        doc = {"id": 1, "folder_id": 1, "upload_file_name": ""}
        self.assertEqual(service._import_single_document(doc, fake_sftp), "skipped")

    def test_import_single_document_nonexistent_org_skips(self):
        service = DocumentImportService()
        service.folder_mapping = {
            1: {
                "organization_type": "Chapter",
                "chapter": "Definitely Nonexistent Chapter ZZZ",
                "team": None,
                "movement": None,
                "document_type": "Other",
            }
        }
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        fake_sftp = _FakeSFTPClient({"x.pdf": b"x"})
        doc = {"id": 1, "name": "x.pdf", "folder_id": 1, "upload_file_name": "x.pdf"}
        self.assertEqual(service._import_single_document(doc, fake_sftp), "skipped")

    def test_import_single_document_mapping_missing_entity_skips(self):
        service = DocumentImportService()
        service.folder_mapping = {
            1: {
                "organization_type": "Chapter",
                "chapter": "",  # entity not set
                "team": None,
                "movement": None,
                "document_type": "Other",
            }
        }
        service.folder_tree = {1: {"id": 1, "parent_id": None}}
        fake_sftp = _FakeSFTPClient({"x.pdf": b"x"})
        doc = {"id": 1, "name": "x.pdf", "folder_id": 1, "upload_file_name": "x.pdf"}
        self.assertEqual(service._import_single_document(doc, fake_sftp), "skipped")

    def test_import_all_no_mapping_returns_error(self):
        """import_all short-circuits when no folder mapping is configured."""
        service = DocumentImportService()
        # Force empty mapping regardless of settings child rows
        service._load_folder_mapping = lambda: setattr(service, "folder_mapping", {})
        result = service.import_all(dry_run=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["imported"], 0)
        self.assertTrue(result["errors"])
