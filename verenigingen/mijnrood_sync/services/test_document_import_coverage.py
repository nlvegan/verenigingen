# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Coverage-gap tests for DocumentImportService + document_reclassify_service.

Complements test_document_import_service.py (do NOT duplicate). Focuses on:
  - auto_classify_folder_mappings (folder-keyword → document_type, chapter
    inference, parent inheritance, manual-config preservation)
  - fetch_and_populate_folders (year-folder skip, default pre-fill,
    connection-failure handling) — MijnRood DB boundary stubbed
  - import_all happy-path + per-document error isolation + realtime/commit
  - _load_folder_mapping skip-incomplete-rows
  - document_reclassify_service._process_doc / reclassify_documents

The only thing stubbed is the remote MijnRood SSH/SFTP/DB boundary
(MijnRoodDatabaseClient, the SFTP client). All app business logic runs
against the real test_site_4 database.
"""

import hashlib
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync.services import document_reclassify_service as recl_mod
from verenigingen.mijnrood_sync.services.document_import_service import DocumentImportService
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


class _FakeSFTPClient:
    """Boundary stub for MijnRoodSFTPClient — returns canned file bytes."""

    def __init__(self, files: dict[str, bytes], raise_on_enter: bool = False):
        self._files = files
        self._raise_on_enter = raise_on_enter
        self.entered = False

    def __enter__(self):
        if self._raise_on_enter:
            raise ConnectionError("SFTP boom")
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.entered = False
        return False

    def download_file(self, remote_filename: str) -> bytes:
        if remote_filename not in self._files:
            raise FileNotFoundError(remote_filename)
        return self._files[remote_filename]


class _FakeDBClient:
    """Boundary stub for MijnRoodDatabaseClient — returns canned folders/docs."""

    def __init__(self, folders=None, documents=None, raise_on_enter=False):
        self._folders = folders or []
        self._documents = documents if documents is not None else []
        self._raise_on_enter = raise_on_enter
        self.entered = False

    def __enter__(self):
        if self._raise_on_enter:
            raise ConnectionError("DB unreachable")
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.entered = False
        return False

    def fetch_document_folders(self):
        return self._folders

    def fetch_documents(self):
        return self._documents


@contextmanager
def _patch_db_client(client):
    """Patch the MijnRoodDatabaseClient constructor used inside the service."""
    with patch("verenigingen.mijnrood_sync.client.MijnRoodDatabaseClient", return_value=client):
        yield


# ──────────────────────────────────────────────────────────────────────────
# auto_classify_folder_mappings
# ──────────────────────────────────────────────────────────────────────────
class TestAutoClassifyFolderMappings(EnhancedTestCase):
    """auto_classify_folder_mappings against an in-memory settings stub.

    We feed real-ish folder mapping rows (frappe._dict) on a throwaway
    settings object so we exercise the classification/inheritance logic
    without persisting to the global MijnRood Sync Settings single.
    """

    class _StubSettings:
        def __init__(self, rows):
            self.document_folder_mapping = rows
            self.saved = False

        def save(self):
            self.saved = True

    def _row(self, fid, path, name=None, document_type=None, chapter=None, org_type=None):
        return frappe._dict(
            {
                "mijnrood_folder_id": fid,
                "folder_path": path,
                "folder_name": name or path,
                "document_type": document_type,
                "chapter": chapter,
                "organization_type": org_type,
                "team": None,
                "movement": None,
            }
        )

    def _service(self, rows):
        settings = self._StubSettings(rows)
        return DocumentImportService(settings=settings), settings

    def test_no_rows_returns_failure(self):
        service, _ = self._service([])
        result = service.auto_classify_folder_mappings()
        self.assertFalse(result["success"])
        self.assertIn("Fetch folders first", result["message"])

    def test_classifies_document_type_from_keyword(self):
        """A 'financien' folder gets the Financial Report category inferred."""
        keyword_map = {"Financial Report": ["financien"], "Meeting Minutes": ["notulen"]}
        rows = [self._row(1, "Landelijk / Financien")]
        service, settings = self._service(rows)
        with (
            patch.object(service, "_load_category_keywords", return_value=keyword_map),
            patch.object(service, "_load_chapter_names", return_value={}),
            patch.object(frappe.db, "get_single_value", return_value=None),
        ):
            result = service.auto_classify_folder_mappings()
        self.assertTrue(result["success"])
        self.assertEqual(rows[0].document_type, "Financial Report")
        self.assertEqual(rows[0].organization_type, "Chapter")
        self.assertTrue(settings.saved)

    def test_blank_type_when_no_keyword_match(self):
        """No keyword match → document_type stays blank (not a fabricated value)."""
        rows = [self._row(1, "Landelijk / Misc")]
        service, _ = self._service(rows)
        with (
            patch.object(service, "_load_category_keywords", return_value={"X": ["zzz"]}),
            patch.object(service, "_load_chapter_names", return_value={}),
            patch.object(frappe.db, "get_single_value", return_value="Nat"),
        ):
            service.auto_classify_folder_mappings()
        self.assertEqual(rows[0].document_type, "")
        # chapter falls back to national when no segment matches
        self.assertEqual(rows[0].chapter, "Nat")

    def test_chapter_inferred_from_path_segment(self):
        rows = [self._row(1, "Afdelingen / Amsterdam")]
        service, _ = self._service(rows)
        with (
            patch.object(service, "_load_category_keywords", return_value={}),
            patch.object(service, "_load_chapter_names", return_value={"amsterdam": "Amsterdam"}),
            patch.object(frappe.db, "get_single_value", return_value="Nat"),
        ):
            service.auto_classify_folder_mappings()
        self.assertEqual(rows[0].chapter, "Amsterdam")

    def test_preserves_manually_configured_row(self):
        """A row with a non-Other document_type is left untouched."""
        rows = [self._row(1, "Landelijk / Financien", document_type="Policy", chapter="Keep")]
        service, _ = self._service(rows)
        with (
            patch.object(
                service, "_load_category_keywords", return_value={"Financial Report": ["financien"]}
            ),
            patch.object(service, "_load_chapter_names", return_value={}),
            patch.object(frappe.db, "get_single_value", return_value="Nat"),
        ):
            result = service.auto_classify_folder_mappings()
        # Unchanged — manual config wins
        self.assertEqual(rows[0].document_type, "Policy")
        self.assertEqual(rows[0].chapter, "Keep")
        self.assertIn("already configured", result["message"])

    def test_other_placeholder_is_reclassified(self):
        """document_type == 'Other' is a placeholder eligible for overwrite."""
        rows = [self._row(1, "Landelijk / Financien", document_type="Other")]
        service, _ = self._service(rows)
        with (
            patch.object(
                service, "_load_category_keywords", return_value={"Financial Report": ["financien"]}
            ),
            patch.object(service, "_load_chapter_names", return_value={}),
            patch.object(frappe.db, "get_single_value", return_value="Nat"),
        ):
            service.auto_classify_folder_mappings()
        self.assertEqual(rows[0].document_type, "Financial Report")

    def test_child_inherits_blank_when_same_classification_as_parent(self):
        """A child folder with the same inferred type/chapter is left blank."""
        rows = [
            self._row(1, "Financien"),
            self._row(2, "Financien / Subfolder"),
        ]
        service, _ = self._service(rows)
        with (
            patch.object(
                service, "_load_category_keywords", return_value={"Financial Report": ["financien"]}
            ),
            patch.object(service, "_load_chapter_names", return_value={}),
            patch.object(frappe.db, "get_single_value", return_value="Nat"),
        ):
            result = service.auto_classify_folder_mappings()
        # Parent classified
        self.assertEqual(rows[0].document_type, "Financial Report")
        # Child has identical inference -> left blank for inheritance
        self.assertIsNone(rows[1].document_type)
        self.assertIn("left blank for inheritance", result["message"])

    def test_child_classified_when_different_from_parent(self):
        """A child whose inferred type differs from the parent is set explicitly."""
        rows = [
            self._row(1, "Landelijk"),
            self._row(2, "Landelijk / Financien"),
        ]
        service, _ = self._service(rows)
        with (
            patch.object(
                service, "_load_category_keywords", return_value={"Financial Report": ["financien"]}
            ),
            patch.object(service, "_load_chapter_names", return_value={}),
            patch.object(frappe.db, "get_single_value", return_value="Nat"),
        ):
            service.auto_classify_folder_mappings()
        # Parent "Landelijk" matches no keyword -> blank
        self.assertEqual(rows[0].document_type, "")
        # Child matches financien -> classified (differs from parent)
        self.assertEqual(rows[1].document_type, "Financial Report")


# ──────────────────────────────────────────────────────────────────────────
# fetch_and_populate_folders
# ──────────────────────────────────────────────────────────────────────────
class TestFetchAndPopulateFolders(EnhancedTestCase):
    class _StubSettings:
        def __init__(self, rows=None):
            self.document_folder_mapping = rows or []
            self.saved = False

        def append(self, _table, values):
            self.document_folder_mapping.append(frappe._dict(values))

        def save(self):
            self.saved = True

    def _service(self, rows=None):
        settings = self._StubSettings(rows)
        return DocumentImportService(settings=settings), settings

    def test_connection_failure_returns_error(self):
        service, _ = self._service()
        client = _FakeDBClient(raise_on_enter=True)
        # Production logs the connection failure via frappe.log_error — expected.
        self.expectErrorLog("MijnRood Fetch Document Folders Failed")
        with _patch_db_client(client):
            result = service.fetch_and_populate_folders()
        self.assertFalse(result["success"])
        self.assertIn("Connection failed", result["message"])

    def test_no_folders_returns_error(self):
        service, _ = self._service()
        with _patch_db_client(_FakeDBClient(folders=[])):
            result = service.fetch_and_populate_folders()
        self.assertFalse(result["success"])
        self.assertIn("No document folders", result["message"])

    def test_creates_rows_and_skips_year_folders(self):
        """Year-only subfolders (20xx) are skipped; real folders create rows."""
        folders = [
            {"id": 1, "name": "Financien", "parent_id": None},
            {"id": 2, "name": "2024", "parent_id": 1},  # year folder -> skip
            {"id": 3, "name": "Notulen", "parent_id": 1},
        ]
        service, settings = self._service()
        with (
            _patch_db_client(_FakeDBClient(folders=folders)),
            patch.object(DocumentImportService, "_get_default_mapping", return_value={}),
        ):
            result = service.fetch_and_populate_folders()
        self.assertTrue(result["success"])
        created_ids = {r.mijnrood_folder_id for r in settings.document_folder_mapping}
        self.assertEqual(created_ids, {1, 3})
        self.assertIn("1 year-folders skipped", result["message"])
        # folder_path computed for the child
        notulen = next(r for r in settings.document_folder_mapping if r.mijnrood_folder_id == 3)
        self.assertEqual(notulen.folder_path, "Financien / Notulen")

    def test_updates_existing_row_name_and_path(self):
        existing = frappe._dict({"mijnrood_folder_id": 1, "folder_name": "OldName", "folder_path": "Old"})
        service, settings = self._service(rows=[existing])
        folders = [{"id": 1, "name": "NewName", "parent_id": None}]
        with _patch_db_client(_FakeDBClient(folders=folders)):
            result = service.fetch_and_populate_folders()
        self.assertTrue(result["success"])
        self.assertEqual(existing.folder_name, "NewName")
        self.assertEqual(existing.folder_path, "NewName")
        self.assertIn("1 updated", result["message"])


# ──────────────────────────────────────────────────────────────────────────
# import_all full orchestration (DB stubbed, SFTP faked, real doc creation)
# ──────────────────────────────────────────────────────────────────────────
class TestImportAllOrchestration(EnhancedTestCase):
    def _service_with_real_chapter(self, chapter_name):
        service = DocumentImportService()
        # Bypass settings-table loading; inject in-memory mapping
        service._load_folder_mapping = lambda: setattr(
            service,
            "folder_mapping",
            {
                1: {
                    "organization_type": "Chapter",
                    "chapter": chapter_name,
                    "team": None,
                    "movement": None,
                    "document_type": "Other",
                }
            },
        )
        return service

    def test_import_all_db_connection_error(self):
        service = self._service_with_real_chapter("X")
        service._load_folder_mapping = lambda: setattr(service, "folder_mapping", {1: {}})
        with _patch_db_client(_FakeDBClient(raise_on_enter=True)):
            result = service.import_all(dry_run=True)
        self.assertFalse(result["success"])
        self.assertTrue(result["errors"])

    def test_import_all_no_documents_succeeds_with_zero(self):
        service = self._service_with_real_chapter("X")
        service._load_folder_mapping = lambda: setattr(service, "folder_mapping", {1: {}})
        folders = [{"id": 1, "name": "Landelijk", "parent_id": None}]
        with _patch_db_client(_FakeDBClient(folders=folders, documents=[])):
            result = service.import_all(dry_run=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["imported"], 0)

    def test_import_all_dry_run_counts(self):
        chapter = self.create_test_chapter()
        service = self._service_with_real_chapter(chapter.name)
        folders = [{"id": 1, "name": "Landelijk", "parent_id": None}]
        documents = [
            {"id": 10, "folder_id": 1, "name": "a.pdf", "upload_file_name": "a.pdf"},
            {"id": 11, "folder_id": 99, "name": "b.pdf", "upload_file_name": "b.pdf"},
        ]
        with _patch_db_client(_FakeDBClient(folders=folders, documents=documents)):
            result = service.import_all(dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["would_import"], 1)
        self.assertEqual(result["unmapped"], 1)

    def test_import_all_happy_path_creates_doc(self):
        """Full import: DB stub + fake SFTP, real Organization Document created."""
        chapter = self.create_test_chapter()
        service = self._service_with_real_chapter(chapter.name)
        folders = [{"id": 1, "name": "Landelijk", "parent_id": None}]
        content = _pdf(b"import-all-happy")
        documents = [
            {"id": 10, "folder_id": 1, "name": "Notulen 2024-05-02.pdf", "upload_file_name": "f1.pdf"},
        ]
        fake_sftp = _FakeSFTPClient({"f1.pdf": content})
        realtime_calls = []
        with (
            _patch_db_client(_FakeDBClient(folders=folders, documents=documents)),
            patch("verenigingen.mijnrood_sync.sftp_client.MijnRoodSFTPClient", return_value=fake_sftp),
            patch.object(frappe, "publish_realtime", side_effect=lambda *a, **k: realtime_calls.append(a)),
        ):
            result = service.import_all(dry_run=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["imported"], 1)
        file_hash = hashlib.sha256(content).hexdigest()
        created = frappe.db.exists("Organization Document", {"file_hash": file_hash})
        self.assertTrue(created)
        # Progress published at least once (idx == total)
        self.assertTrue(realtime_calls)

    def test_import_all_per_document_error_isolated(self):
        """One failing document is captured in errors; others still import."""
        chapter = self.create_test_chapter()
        service = self._service_with_real_chapter(chapter.name)
        folders = [{"id": 1, "name": "Landelijk", "parent_id": None}]
        good = _pdf(b"good-one")
        documents = [
            {"id": 10, "folder_id": 1, "name": "good.pdf", "upload_file_name": "good.pdf"},
            {"id": 11, "folder_id": 1, "name": "missing.pdf", "upload_file_name": "missing.pdf"},
        ]
        # "missing.pdf" not in the fake store -> download raises -> error captured
        fake_sftp = _FakeSFTPClient({"good.pdf": good})
        with (
            _patch_db_client(_FakeDBClient(folders=folders, documents=documents)),
            patch("verenigingen.mijnrood_sync.sftp_client.MijnRoodSFTPClient", return_value=fake_sftp),
            patch.object(frappe, "publish_realtime"),
        ):
            result = service.import_all(dry_run=False)
        self.assertEqual(result["imported"], 1)
        self.assertFalse(result["success"])  # has errors
        self.assertTrue(any("missing.pdf" in e for e in result["errors"]))


# ──────────────────────────────────────────────────────────────────────────
# _load_folder_mapping
# ──────────────────────────────────────────────────────────────────────────
class TestLoadFolderMapping(EnhancedTestCase):
    class _StubSettings:
        def __init__(self, rows):
            self.document_folder_mapping = rows

    def _row(self, fid, org_type, document_type, **kw):
        return frappe._dict(
            {
                "mijnrood_folder_id": fid,
                "organization_type": org_type,
                "document_type": document_type,
                "chapter": kw.get("chapter"),
                "team": kw.get("team"),
                "movement": kw.get("movement"),
                "folder_name": kw.get("folder_name"),
                "idx": kw.get("idx", 1),
            }
        )

    def test_complete_rows_loaded_incomplete_skipped(self):
        rows = [
            self._row(1, "Chapter", "Policy", chapter="C1"),
            self._row(2, "", "Policy", folder_name="incomplete"),  # no org_type -> skip
            self._row(3, "Chapter", "", folder_name="no-type"),  # no document_type -> skip
        ]
        service = DocumentImportService(settings=self._StubSettings(rows))
        service._load_folder_mapping()
        self.assertEqual(set(service.folder_mapping.keys()), {1})
        self.assertEqual(service.folder_mapping[1]["chapter"], "C1")


# ──────────────────────────────────────────────────────────────────────────
# document_reclassify_service
# ──────────────────────────────────────────────────────────────────────────
class TestReclassifyResolveMappedFolder(EnhancedTestCase):
    """_resolve_mapped_folder standalone helper."""

    def test_direct_hit(self):
        mapping = {5: frappe._dict({"organization_type": "Chapter"})}
        result = recl_mod._resolve_mapped_folder(5, mapping, {})
        self.assertEqual(result["organization_type"], "Chapter")

    def test_walks_to_ancestor(self):
        mapping = {1: frappe._dict({"organization_type": "Chapter"})}
        tree = {1: {"id": 1, "parent_id": None}, 2: {"id": 2, "parent_id": 1}}
        result = recl_mod._resolve_mapped_folder(2, mapping, tree)
        self.assertEqual(result["organization_type"], "Chapter")

    def test_no_mapping_returns_none(self):
        tree = {1: {"id": 1, "parent_id": None}}
        self.assertIsNone(recl_mod._resolve_mapped_folder(1, {}, tree))

    def test_cycle_terminates(self):
        tree = {1: {"id": 1, "parent_id": 2}, 2: {"id": 2, "parent_id": 1}}
        self.assertIsNone(recl_mod._resolve_mapped_folder(1, {}, tree))


class TestReclassifyDocuments(EnhancedTestCase):
    """reclassify_documents / _process_doc against real Organization Documents."""

    def _make_org_doc(self, chapter_name, **overrides):
        from verenigingen.utils.file_storage import save_organization_document

        # Create a real attached file so OrganizationDocument doesn't log an
        # "Error Attaching File" against a non-existent placeholder URL.
        file_result = save_organization_document(
            content=_pdf(frappe.generate_hash()[:8].encode()),
            filename="recl.pdf",
            organization_type="Chapter",
            organization_name=chapter_name,
            category="Other",
            year="Other",
            is_private=1,
        )
        data = {
            "doctype": "Organization Document",
            "organization_type": "Chapter",
            "chapter": chapter_name,
            "document_name": overrides.pop("document_name", "Plain Notes.pdf"),
            "document_type": overrides.pop("document_type", "Other"),
            "document_file": file_result["file_url"],
            "file_hash": hashlib.sha256(frappe.generate_hash().encode()).hexdigest(),
            **overrides,
        }
        doc = frappe.get_doc(data)
        doc.flags.ignore_permissions = True
        doc.insert()
        return doc

    def _mapping_row(self, fid, chapter, document_type="Policy", folder_path="Landelijk / Statuten"):
        return frappe._dict(
            {
                "mijnrood_folder_id": fid,
                "organization_type": "Chapter",
                "chapter": chapter,
                "team": None,
                "movement": None,
                "document_type": document_type,
                "folder_path": folder_path,
            }
        )

    def test_process_doc_no_source_folder_id_skips(self):
        chapter = self.create_test_chapter()
        doc = self._make_org_doc(chapter.name, source_folder_id=0)
        result = recl_mod._process_doc(doc, {}, lambda: {}, dry_run=True)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("no source_folder_id", result["reason"])

    def test_process_doc_no_mapping_skips(self):
        chapter = self.create_test_chapter()
        doc = self._make_org_doc(chapter.name, source_folder_id=42)
        result = recl_mod._process_doc(doc, {}, lambda: {}, dry_run=True)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no folder mapping")

    def test_process_doc_mapping_missing_entity_skips(self):
        chapter = self.create_test_chapter()
        doc = self._make_org_doc(chapter.name, source_folder_id=7)
        mapping = {7: self._mapping_row(7, chapter=None)}  # chapter blank
        result = recl_mod._process_doc(doc, mapping, lambda: {}, dry_run=True)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("no entity set", result["reason"])

    def test_process_doc_dry_run_computes_diff_without_writing(self):
        chapter = self.create_test_chapter()
        # Doc has document_type Other; mapping proposes Policy -> diff
        doc = self._make_org_doc(chapter.name, source_folder_id=9, document_type="Other")
        mapping = {9: self._mapping_row(9, chapter=chapter.name, document_type="Policy")}
        result = recl_mod._process_doc(doc, mapping, lambda: {}, dry_run=True)
        self.assertEqual(result["status"], "changed")
        self.assertIn("document_type", result["change"]["diff_fields"])
        self.assertEqual(result["change"]["proposed"]["document_type"], "Policy")
        # Dry run must not persist
        self.assertEqual(frappe.db.get_value("Organization Document", doc.name, "document_type"), "Other")

    def test_process_doc_unchanged_skips(self):
        chapter = self.create_test_chapter()
        # applies_on_precision must match the proposed default ("Day" when no
        # date is present) for the doc to register as genuinely unchanged.
        doc = self._make_org_doc(
            chapter.name, source_folder_id=11, document_type="Policy", applies_on_precision="Day"
        )
        # mapping proposes the same Policy / same chapter, no date in name -> unchanged
        mapping = {
            11: self._mapping_row(11, chapter=chapter.name, document_type="Policy", folder_path="Landelijk")
        }
        result = recl_mod._process_doc(doc, mapping, lambda: {}, dry_run=True)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "unchanged")

    def test_reclassify_documents_apply_writes_fields(self):
        chapter = self.create_test_chapter()
        doc = self._make_org_doc(chapter.name, source_folder_id=13, document_type="Other")
        # Stub the settings single's mapping by patching get_single
        stub_settings = frappe._dict(
            document_folder_mapping=[self._mapping_row(13, chapter=chapter.name, document_type="Policy")]
        )
        with patch.object(frappe, "get_single", return_value=stub_settings):
            result = recl_mod.reclassify_documents([doc.name], dry_run=False)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["total"], 1)
        # Persisted
        self.assertEqual(frappe.db.get_value("Organization Document", doc.name, "document_type"), "Policy")

    def test_reclassify_documents_missing_doc_skipped(self):
        stub_settings = frappe._dict(document_folder_mapping=[])
        with patch.object(frappe, "get_single", return_value=stub_settings):
            result = recl_mod.reclassify_documents(["NONEXISTENT-DOC-ZZZ"], dry_run=True)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "document not found")

    def test_reclassify_documents_rejects_oversized_batch(self):
        stub_settings = frappe._dict(document_folder_mapping=[])
        with patch.object(frappe, "get_single", return_value=stub_settings):
            with self.assertRaises(frappe.ValidationError):
                recl_mod.reclassify_documents(["x"] * (recl_mod.MAX_BATCH + 1), dry_run=True)

    def test_reclassify_documents_json_string_names(self):
        """HTTP path passes names as a JSON-encoded string."""
        chapter = self.create_test_chapter()
        doc = self._make_org_doc(chapter.name, source_folder_id=15, document_type="Other")
        stub_settings = frappe._dict(
            document_folder_mapping=[self._mapping_row(15, chapter=chapter.name, document_type="Policy")]
        )
        import json as _json

        with patch.object(frappe, "get_single", return_value=stub_settings):
            result = recl_mod.reclassify_documents(_json.dumps([doc.name]), dry_run="true")
        # dry_run coerced from "true" -> no write, but a change is detected
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["changes"]), 1)


# ──────────────────────────────────────────────────────────────────────────
# #2512: a failure BEFORE the SFTP loop must reach the status staff look at
# ──────────────────────────────────────────────────────────────────────────
class TestImportAllEarlyFailureReachesStatus(EnhancedTestCase):
    """Drives the module-level ``import_all`` the enqueued job runs (its return value is discarded).

    Probe shortcut, stated: ``document_import_status`` is set to what ``import_documents`` writes at enqueue
    time instead of calling that endpoint, and ``_load_folder_mapping`` is patched to inject the mapping
    (as the neighbouring tests do). Stubbed boundary: ``MijnRoodDatabaseClient`` (the SSH/DB connection).
    """

    FAILED_TITLE = "MijnRood Document Import Failed"

    def setUp(self):
        super().setUp()
        self._orig_status = frappe.db.get_single_value("MijnRood Sync Settings", "document_import_status")
        frappe.db.set_single_value("MijnRood Sync Settings", "document_import_status", "Import job enqueued")

    def tearDown(self):
        frappe.db.set_single_value("MijnRood Sync Settings", "document_import_status", self._orig_status)
        super().tearDown()

    def _status(self):
        return frappe.db.get_single_value("MijnRood Sync Settings", "document_import_status")

    def _failed_logs(self):
        return frappe.get_all("Error Log", filters={"method": self.FAILED_TITLE}, pluck="name")

    def _run_job(self, dry_run=False):
        from verenigingen.mijnrood_sync.services import document_import_service as mod

        return mod.import_all(dry_run=dry_run)

    def test_unreachable_mijnrood_db_is_reported_on_the_status_and_error_log(self):
        before = len(self._failed_logs())
        with (
            patch.object(
                DocumentImportService,
                "_load_folder_mapping",
                lambda s: setattr(s, "folder_mapping", {1: {}}),
            ),
            _patch_db_client(_FakeDBClient(raise_on_enter=True)),
        ):
            result = self._run_job()
        self.assertFalse(result["success"])
        self.assertIn("DB unreachable", self._status())
        self.assertNotEqual(self._status(), "Import job enqueued")
        self.assertEqual(len(self._failed_logs()), before + 1)

    def test_no_folder_mappings_is_reported_on_the_status(self):
        with patch.object(
            DocumentImportService, "_load_folder_mapping", lambda s: setattr(s, "folder_mapping", {})
        ):
            result = self._run_job()
        self.assertFalse(result["success"])
        self.assertIn("No folder mappings configured", self._status())

    def test_dry_run_failure_leaves_the_status_alone(self):
        """Control: a dry run is interactive (bench execute prints the dict); it must not stamp the status."""
        before = len(self._failed_logs())
        with (
            patch.object(
                DocumentImportService,
                "_load_folder_mapping",
                lambda s: setattr(s, "folder_mapping", {1: {}}),
            ),
            _patch_db_client(_FakeDBClient(raise_on_enter=True)),
        ):
            result = self._run_job(dry_run=True)
        self.assertFalse(result["success"])
        self.assertEqual(self._status(), "Import job enqueued")
        self.assertEqual(len(self._failed_logs()), before)

    # ---- round 2 -------------------------------------------------------

    def test_a_job_that_fails_instantly_is_not_overwritten_by_the_enqueue_status(self):
        """Simulates the job finishing synchronously AT enqueue time (no real worker: bench RQ workers run
        develop's code). The request must have written "enqueued" BEFORE enqueueing, or its later write
        would bury the job's "Import failed" and bring back the stuck-status symptom.
        """
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.document_folder_mapping = [frappe._dict(organization_type="Chapter", document_type="Other")]

        def run_job_now(*args, **kwargs):
            with (
                patch.object(
                    DocumentImportService,
                    "_load_folder_mapping",
                    lambda s: setattr(s, "folder_mapping", {1: {}}),
                ),
                _patch_db_client(_FakeDBClient(raise_on_enter=True)),
            ):
                self._run_job()

        with patch.object(frappe, "enqueue", side_effect=run_job_now):
            result = settings.import_documents()
        self.assertTrue(result["success"])
        self.assertIn("Import failed", self._status())

    def test_exception_before_the_sftp_try_is_reported_on_the_status(self):
        """SFTP client construction sits outside import_all's own try."""
        folders = [{"id": 1, "name": "Landelijk", "parent_id": None}]
        documents = [{"id": 10, "folder_id": 1, "name": "a.pdf", "upload_file_name": "a.pdf"}]
        with (
            patch.object(
                DocumentImportService,
                "_load_folder_mapping",
                lambda s: setattr(s, "folder_mapping", {1: {}}),
            ),
            _patch_db_client(_FakeDBClient(folders=folders, documents=documents)),
            patch(
                "verenigingen.mijnrood_sync.sftp_client.MijnRoodSFTPClient",
                side_effect=RuntimeError("sftp settings broken"),
            ),
        ):
            result = self._run_job()
        self.assertFalse(result["success"])
        self.assertIn("sftp settings broken", self._status())
        self.assertNotEqual(self._status(), "Import job enqueued")

    def test_malformed_folder_row_is_reported_on_the_status(self):
        """Folder-tree build (step 3) is also outside the try."""
        with (
            patch.object(
                DocumentImportService,
                "_load_folder_mapping",
                lambda s: setattr(s, "folder_mapping", {1: {}}),
            ),
            _patch_db_client(_FakeDBClient(folders=[{"name": "no id"}], documents=[{"id": 1}])),
        ):
            result = self._run_job()
        self.assertFalse(result["success"])
        self.assertIn("Import failed", self._status())

    # ---- round 3 -------------------------------------------------------

    def test_a_deadlock_is_recorded_on_the_status_and_then_re_raised(self):
        """A 1213 destroys the transaction state; swallowing it into a dict hides it from the job runner.
        Fault injected at ``_import_all`` (the whole body), not at a real lock conflict.
        """
        before = len(self._failed_logs())
        # Mock justified: injects a lock-wait fault; a real 1213 needs two contending connections.
        with patch.object(
            DocumentImportService, "_import_all", side_effect=frappe.QueryDeadlockError("1213")
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._run_job()
        self.assertIn("Import failed", self._status())
        self.assertNotEqual(self._status(), "Import job enqueued")
        self.assertEqual(len(self._failed_logs()), before + 1)

    def test_a_lock_wait_timeout_is_also_re_raised(self):
        # Mock justified: injects a 1205 lock-wait fault (see the deadlock test).
        with patch.object(DocumentImportService, "_import_all", side_effect=frappe.QueryTimeoutError("1205")):
            with self.assertRaises(frappe.QueryTimeoutError):
                self._run_job()
        self.assertIn("Import failed", self._status())

    def test_enqueue_failure_is_written_to_the_status_and_re_raised(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.document_folder_mapping = [frappe._dict(organization_type="Chapter", document_type="Other")]
        # Mock justified: seam at the queue boundary; Redis being down cannot be provoked in a test.
        with patch.object(frappe, "enqueue", side_effect=RuntimeError("redis is down")):
            with self.assertRaises(RuntimeError):
                settings.import_documents()
        self.assertEqual(self._status(), "Import failed to enqueue: redis is down")
