# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Tests for verenigingen.utils.file_storage.

Focus areas:
- Path-security sanitizers (sanitize_path_component, sanitize_filename) tested
  directly against traversal / null-byte / unicode / overlong inputs.
- Pure path builders (get_chapter_document_path, get_organization_document_path)
  which still build hierarchical *path strings* used as metadata.
- Real integration of save_* against the site filesystem + File doctype.

NEW CONTRACT (after the storage fix):
- ``_create_file_record(content, filename, is_private, attached_to_doctype,
  attached_to_name)`` lets the framework own storage. It stores ``content`` and
  returns the inserted File *document* whose ``.file_url`` is the real, served
  (flat) url, e.g. ``/private/files/<basename>``.
- ``save_chapter_document`` / ``save_organization_document`` return
  ``{"file_name", "file_url", "name"}``. The returned ``file_url`` MATCHES the
  stored File record's url and is flat (``/private/files/<basename>``), never
  hierarchical. A private saved file always has a covering File record (not
  Forbidden).
- ``organize_existing_chapter_document`` / ``organize_organization_document`` are
  no-ops that return the url unchanged.
"""

import os

import frappe
from frappe.utils import get_files_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import file_storage
from verenigingen.utils.file_storage import (
    FileRecordCreationError,
    _create_file_record,
    cleanup_empty_directories,
    get_chapter_document_path,
    get_organization_document_path,
    organize_existing_chapter_document,
    organize_organization_document,
    sanitize_filename,
    sanitize_path_component,
    save_chapter_document,
    save_organization_document,
)


class TestSanitizePathComponent(EnhancedTestCase):
    """Pure security tests for sanitize_path_component (directory segments)."""

    def test_empty_and_none_fall_back_to_unknown(self):
        self.assertEqual(sanitize_path_component(""), "unknown")
        self.assertEqual(sanitize_path_component(None), "unknown")

    def test_simple_name_lowercased_and_dashed(self):
        # frappe.scrub lowercases & underscores spaces; then underscores -> dashes
        self.assertEqual(sanitize_path_component("Amsterdam Chapter"), "amsterdam-chapter")

    def test_dot_dot_traversal_neutralised(self):
        # '..' segments must never survive
        result = sanitize_path_component("../../etc/passwd")
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)
        # The remaining letters get scrubbed into a safe slug
        self.assertEqual(result, "etcpasswd")

    def test_quad_dot_bypass_neutralised(self):
        # '....' would become '..' under a single non-iterative replace; the
        # iterative loop must fully strip it.
        result = sanitize_path_component("....")
        self.assertNotIn("..", result)
        # Nothing printable remains -> 'unknown'
        self.assertEqual(result, "unknown")

    def test_absolute_path_separators_stripped(self):
        result = sanitize_path_component("/etc/passwd")
        self.assertNotIn("/", result)
        self.assertEqual(result, "etcpasswd")

    def test_backslash_windows_path_stripped(self):
        result = sanitize_path_component("..\\..\\windows\\system32")
        self.assertNotIn("\\", result)
        self.assertNotIn("..", result)
        self.assertEqual(result, "windowssystem32")

    def test_null_byte_removed(self):
        result = sanitize_path_component("safe\x00name")
        self.assertNotIn("\x00", result)
        self.assertEqual(result, "safename")

    def test_special_chars_stripped(self):
        result = sanitize_path_component("na;me&$|`rm`")
        # Only alphanumerics + dash survive
        self.assertTrue(all(c.isalnum() or c == "-" for c in result))
        self.assertNotIn(";", result)
        self.assertNotIn("$", result)

    def test_unicode_normalised(self):
        # Composed vs decomposed should both reduce to a safe slug; the result
        # must be ascii alnum/dash only.
        result = sanitize_path_component("café")
        self.assertTrue(all(c.isalnum() or c == "-" for c in result))

    def test_only_special_chars_falls_back_to_unknown(self):
        self.assertEqual(sanitize_path_component("!@#$%^&*()"), "unknown")

    def test_result_never_contains_path_separators(self):
        for hostile in ["a/b", "a\\b", "..", "../x", "x/..", "/", "\\", "..\\.."]:
            result = sanitize_path_component(hostile)
            self.assertNotIn("/", result)
            self.assertNotIn("\\", result)
            self.assertNotIn("..", result)


class TestSanitizeFilename(EnhancedTestCase):
    """Pure security tests for sanitize_filename (file leaf segment)."""

    def test_empty_and_none_fall_back_to_unknown(self):
        self.assertEqual(sanitize_filename(""), "unknown")
        self.assertEqual(sanitize_filename(None), "unknown")

    def test_preserves_extension(self):
        self.assertEqual(sanitize_filename("report.pdf"), "report.pdf")

    def test_strips_directory_components(self):
        result = sanitize_filename("/etc/passwd")
        self.assertNotIn("/", result)
        self.assertEqual(result, "passwd")

    def test_traversal_filename_neutralised(self):
        result = sanitize_filename("../../secret.txt")
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)
        self.assertEqual(result, "secret.txt")

    def test_quad_dot_neutralised(self):
        # basename of '....x' is '....x'; iterative strip removes '..' pairs
        result = sanitize_filename("....evil")
        self.assertNotIn("..", result)

    def test_backslash_stripped(self):
        result = sanitize_filename("..\\..\\evil.exe")
        self.assertNotIn("\\", result)
        self.assertNotIn("..", result)
        self.assertEqual(result, "evil.exe")

    def test_null_byte_truncation_blocked(self):
        # A null byte must not allow "image.jpg\x00.php" style truncation tricks
        result = sanitize_filename("image.php\x00.jpg")
        self.assertNotIn("\x00", result)

    def test_leading_dot_hidden_file_blocked(self):
        result = sanitize_filename(".bashrc")
        self.assertFalse(result.startswith("."))
        self.assertEqual(result, "bashrc")

    def test_trailing_space_and_dot_stripped(self):
        result = sanitize_filename("file.txt. ")
        self.assertFalse(result.endswith(" "))
        self.assertFalse(result.endswith("."))

    def test_special_chars_stripped_keeps_safe_set(self):
        result = sanitize_filename("my file;rm -rf.pdf")
        # Allowed: alnum, dot, dash, underscore, space
        self.assertTrue(all(c.isalnum() or c in "._- " for c in result))
        self.assertNotIn(";", result)

    def test_overlong_name_truncated_preserving_extension(self):
        long_stem = "a" * 500
        result = sanitize_filename(f"{long_stem}.pdf", max_length=200)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.endswith(".pdf"))

    def test_overlong_with_huge_extension_truncated_plainly(self):
        # ext >= 16 chars -> no special extension preservation
        result = sanitize_filename("a" * 300 + "." + "z" * 30, max_length=50)
        self.assertLessEqual(len(result), 50)


class TestDocumentPathBuilders(EnhancedTestCase):
    """Pure path-builder tests (no filesystem writes).

    NOTE: these builders still produce hierarchical *path strings*. They are now
    used to derive logical metadata, not the on-disk storage path (the framework
    owns storage and flattens to the basename). The builder contract is unchanged.
    """

    def test_chapter_document_path_structure(self):
        path = get_chapter_document_path("Amsterdam", "Policy", "2025", "rules.pdf")
        parts = path.split(os.sep)
        self.assertEqual(parts[0], "documents")
        self.assertEqual(parts[1], "chapters")
        self.assertEqual(parts[2], "amsterdam")
        self.assertEqual(parts[3], "policy")
        self.assertEqual(parts[4], "2025")
        self.assertEqual(parts[5], "rules.pdf")

    def test_chapter_document_path_sanitizes_traversal(self):
        path = get_chapter_document_path("../../etc", "../cat", "2025", "../../passwd")
        self.assertNotIn("..", path)
        # leaf filename comes from sanitize_filename
        self.assertTrue(path.endswith("passwd"))

    def test_organization_document_path_pluralises_type(self):
        path = get_organization_document_path("Team", "Finance", "Minutes", "2024", "notes.txt")
        parts = path.split(os.sep)
        self.assertEqual(parts[0], "documents")
        self.assertEqual(parts[1], "teams")  # Team -> teams
        self.assertEqual(parts[2], "finance")
        self.assertEqual(parts[5], "notes.txt")

    def test_organization_document_path_chapter_type(self):
        path = get_organization_document_path("Chapter", "Rotterdam", "Policy", "2025", "x.pdf")
        self.assertIn(os.path.join("documents", "chapters", "rotterdam"), path)

    def test_organization_document_path_sanitizes(self):
        path = get_organization_document_path("../Team", "../org", "../cat", "../2025", "../../f.pdf")
        self.assertNotIn("..", path)


class _FileStorageIntegrationBase(EnhancedTestCase):
    """Shared setup/teardown that tracks created File docs + on-disk paths.

    The framework owns storage now, so the File record is locatable directly by
    the returned (flat, served) ``file_url`` — no basename guessing needed.
    """

    def setUp(self):
        super().setUp()
        self._created_files = []  # File doc names
        self._created_paths = []  # absolute on-disk paths
        self._created_urls = []  # served urls returned by save_*

    def tearDown(self):
        for name in self._created_files:
            if frappe.db.exists("File", name):
                frappe.delete_doc("File", name, force=True, ignore_permissions=True)
        # Sweep any File rows still pointing at urls we created.
        for url in self._created_urls:
            for fname in frappe.get_all("File", filters={"file_url": url}, pluck="name"):
                frappe.delete_doc("File", fname, force=True, ignore_permissions=True)
        for path in self._created_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        super().tearDown()

    def _track(self, result):
        """Track a save_* result dict for cleanup and return it."""
        self._created_urls.append(result["file_url"])
        if result.get("name"):
            self._created_files.append(result["name"])
        self._created_paths.append(self._abs_from_url(result["file_url"]))
        return result

    def _abs_from_url(self, file_url):
        if file_url.startswith("/private/files/"):
            return os.path.join(get_files_path(is_private=1), file_url.replace("/private/files/", ""))
        return os.path.join(get_files_path(is_private=0), file_url.replace("/files/", ""))


class TestSaveChapterDocument(_FileStorageIntegrationBase):
    """Real integration: save_chapter_document writes a file + File record."""

    def test_save_private_chapter_document_creates_file_and_record(self):
        result = self._track(
            save_chapter_document(
                content=b"hello world",
                filename="meeting.txt",
                chapter_name="Test Chapter Storage",
                category="Meeting Minutes",
                year="2026",
                is_private=1,
            )
        )
        # NEW CONTRACT: file_name + flat served url + File record name returned.
        self.assertTrue(result["file_name"].endswith(".txt"))
        self.assertTrue(result["name"])
        # Flat url, NOT hierarchical — the bug fix.
        self.assertTrue(result["file_url"].startswith("/private/files/"))
        self.assertNotIn("/documents/", result["file_url"])

        # The on-disk file exists with the right content.
        abs_path = self._abs_from_url(result["file_url"])
        self.assertTrue(os.path.exists(abs_path))
        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), b"hello world")

        # A covering File record exists, is attached to the Chapter, and its
        # stored url EQUALS the returned url (this is the bug fix: no dangling
        # reference, private file not Forbidden).
        rec = frappe.db.get_value(
            "File",
            result["name"],
            ["attached_to_doctype", "attached_to_name", "is_private", "file_url"],
            as_dict=True,
        )
        self.assertEqual(rec.attached_to_doctype, "Chapter")
        self.assertEqual(rec.attached_to_name, "Test Chapter Storage")
        self.assertEqual(rec.is_private, 1)
        self.assertEqual(rec.file_url, result["file_url"])
        self.assertTrue(frappe.db.exists("File", {"file_url": result["file_url"]}))

    def test_save_public_chapter_document_uses_public_url(self):
        result = self._track(
            save_chapter_document(
                content=b"public data",
                filename="public.txt",
                chapter_name="Test Chapter Public",
                category="Policy",
                year="2026",
                is_private=0,
            )
        )
        # Public files are served from /files/<basename> (flat).
        self.assertTrue(result["file_url"].startswith("/files/"))
        self.assertNotIn("/documents/", result["file_url"])
        self.assertTrue(os.path.exists(self._abs_from_url(result["file_url"])))
        # Returned url matches the stored record.
        self.assertEqual(
            frappe.db.get_value("File", result["name"], "file_url"), result["file_url"]
        )

    def test_save_with_file_object_content(self):
        import io

        result = self._track(
            save_chapter_document(
                content=io.BytesIO(b"streamed bytes"),
                filename="stream.txt",
                chapter_name="Test Chapter Stream",
                category="Other",
                year="2026",
                is_private=1,
            )
        )
        abs_path = self._abs_from_url(result["file_url"])
        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), b"streamed bytes")
        self.assertEqual(
            frappe.db.get_value("File", result["name"], "file_url"), result["file_url"]
        )

    def test_save_neutralises_traversal_in_filename(self):
        # A hostile filename must not escape the files root. The framework
        # flattens to the basename and we sanitize first, so '..' cannot survive.
        result = self._track(
            save_chapter_document(
                content=b"x",
                filename="../../../../etc/evil.txt",
                chapter_name="Test Chapter Traversal",
                category="Policy",
                year="2026",
                is_private=1,
            )
        )
        self.assertNotIn("..", result["file_url"])
        self.assertNotIn("/etc/", result["file_url"])
        self.assertTrue(result["file_url"].startswith("/private/files/"))

        # The realpath of the stored file must stay UNDER the private files root.
        abs_path = self._abs_from_url(result["file_url"])
        files_root = os.path.realpath(get_files_path(is_private=1))
        self.assertTrue(os.path.realpath(abs_path).startswith(files_root + os.sep))
        self.assertTrue(os.path.exists(abs_path))


class TestSaveOrganizationDocument(_FileStorageIntegrationBase):
    """Real integration: save_organization_document."""

    def test_save_team_document_attaches_to_team_type(self):
        result = self._track(
            save_organization_document(
                content=b"team data",
                filename="charter.txt",
                organization_type="Team",
                organization_name="Test Team Storage",
                category="Policy",
                year="2026",
                is_private=1,
            )
        )
        # Flat served url; returned url == stored record url.
        self.assertTrue(result["file_url"].startswith("/private/files/"))
        self.assertNotIn("/documents/", result["file_url"])
        self.assertTrue(os.path.exists(self._abs_from_url(result["file_url"])))
        rec = frappe.db.get_value(
            "File", result["name"], ["attached_to_doctype", "file_url"], as_dict=True
        )
        self.assertEqual(rec.attached_to_doctype, "Team")
        self.assertEqual(rec.file_url, result["file_url"])

    def test_save_with_document_name_attaches_to_org_document(self):
        # When document_name is provided, attaches to "Organization Document".
        # ignore-link semantics: the framework does not require the link target to
        # exist for the attachment fields; assert the attachment target.
        result = self._track(
            save_organization_document(
                content=b"doc",
                filename="ref.txt",
                organization_type="Chapter",
                organization_name="Test Chapter OrgDoc",
                category="Policy",
                year="2026",
                is_private=1,
                document_name="ORG-DOC-TEST-0001",
            )
        )
        rec = frappe.db.get_value(
            "File",
            result["name"],
            ["attached_to_doctype", "attached_to_name", "file_url"],
            as_dict=True,
        )
        self.assertEqual(rec.attached_to_doctype, "Organization Document")
        self.assertEqual(rec.attached_to_name, "ORG-DOC-TEST-0001")
        self.assertEqual(rec.file_url, result["file_url"])


class TestOrganizeExistingChapterDocument(_FileStorageIntegrationBase):
    """organize_existing_chapter_document is now a no-op returning the url."""

    def test_returns_hierarchical_url_unchanged(self):
        url = "/private/files/documents/chapters/x/policy/2026/a.pdf"
        self.assertEqual(organize_existing_chapter_document(url, "X", "Policy", "2026"), url)

    def test_returns_flat_url_unchanged(self):
        url = "/private/files/already-flat.txt"
        self.assertEqual(organize_existing_chapter_document(url, "X", "Policy", "2026"), url)

    def test_empty_url_returned_unchanged(self):
        self.assertEqual(organize_existing_chapter_document("", "X", "Policy", "2026"), "")

    def test_external_url_returned_unchanged(self):
        url = "https://external/file.pdf"
        self.assertEqual(organize_existing_chapter_document(url, "X", "Policy", "2026"), url)

    def test_noop_does_not_create_file_records(self):
        # A no-op must not touch the File table or the filesystem.
        before = frappe.db.count("File")
        url = "/private/files/noop-witness.txt"
        out = organize_existing_chapter_document(url, "Some Chapter", "Policy", "2026")
        self.assertEqual(out, url)
        self.assertEqual(frappe.db.count("File"), before)


class TestOrganizeOrganizationDocument(_FileStorageIntegrationBase):
    """organize_organization_document is now a no-op returning the url."""

    def test_returns_hierarchical_url_unchanged(self):
        url = "/private/files/documents/teams/x/policy/2026/a.pdf"
        self.assertEqual(organize_organization_document(url, "Team", "X", "Policy", "2026"), url)

    def test_returns_flat_url_unchanged(self):
        url = "/private/files/already-flat-org.txt"
        self.assertEqual(organize_organization_document(url, "Team", "X", "Policy", "2026"), url)

    def test_empty_url_returned_unchanged(self):
        self.assertEqual(organize_organization_document("", "Team", "X", "Policy", "2026"), "")

    def test_noop_does_not_create_file_records(self):
        before = frappe.db.count("File")
        url = "/private/files/noop-org-witness.txt"
        out = organize_organization_document(url, "Team", "Some Team", "Policy", "2026")
        self.assertEqual(out, url)
        self.assertEqual(frappe.db.count("File"), before)


class TestCreateFileRecord(_FileStorageIntegrationBase):
    """_create_file_record stores content via the framework and returns a File doc."""

    def test_returns_file_doc_with_real_served_url(self):
        # NEW CONTRACT: returns the File *document* (not a name string); its
        # file_url is the real, flat, served url.
        file_doc = _create_file_record(
            content=b"create me",
            filename="flat-create-test.txt",
            is_private=1,
            attached_to_doctype="Chapter",
            attached_to_name="Test Chapter Create",
        )
        self._created_files.append(file_doc.name)
        self._created_urls.append(file_doc.file_url)
        self._created_paths.append(self._abs_from_url(file_doc.file_url))

        # It is a Document, not a bare name.
        self.assertTrue(hasattr(file_doc, "file_url"))
        self.assertTrue(file_doc.file_url.startswith("/private/files/"))
        self.assertNotIn("/documents/", file_doc.file_url)
        self.assertTrue(frappe.db.exists("File", file_doc.name))
        # The on-disk file actually contains our bytes.
        abs_path = self._abs_from_url(file_doc.file_url)
        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), b"create me")

    def test_returned_url_matches_stored_record(self):
        # The bug fix: the returned url is exactly what is stored (no dangling
        # reference, private file is served, not Forbidden).
        file_doc = _create_file_record(
            content=b"served bytes",
            filename="served-test.txt",
            is_private=1,
            attached_to_doctype="Chapter",
            attached_to_name="Test Chapter Served",
        )
        self._created_files.append(file_doc.name)
        self._created_urls.append(file_doc.file_url)
        self._created_paths.append(self._abs_from_url(file_doc.file_url))

        stored_url = frappe.db.get_value("File", file_doc.name, "file_url")
        self.assertEqual(stored_url, file_doc.file_url)
        # A covering File record exists for the served (private) url.
        self.assertTrue(frappe.db.exists("File", {"file_url": file_doc.file_url}))

    def test_same_content_twice_dedups_by_content_hash(self):
        # FIXED behaviour: saving identical content twice does NOT produce a
        # dangling/mismatched url. The framework dedups identical content by
        # content hash, so both records resolve to the SAME served url (a private
        # file that is always covered by a File record — never Forbidden).
        doc1 = _create_file_record(
            content=b"dedupe payload",
            filename="dedupe-a.txt",
            is_private=1,
            attached_to_doctype="Chapter",
            attached_to_name="Test Chapter Dedupe",
        )
        doc2 = _create_file_record(
            content=b"dedupe payload",
            filename="dedupe-b.txt",
            is_private=1,
            attached_to_doctype="Chapter",
            attached_to_name="Test Chapter Dedupe",
        )
        for d in (doc1, doc2):
            self._created_files.append(d.name)
            self._created_urls.append(d.file_url)
            self._created_paths.append(self._abs_from_url(d.file_url))

        # Both stored urls equal their returned urls (no flattening mismatch).
        self.assertEqual(frappe.db.get_value("File", doc1.name, "file_url"), doc1.file_url)
        self.assertEqual(frappe.db.get_value("File", doc2.name, "file_url"), doc2.file_url)
        # Identical content is deduped to the same physical (served) url, and
        # that url is covered by a File record (private -> not Forbidden).
        self.assertEqual(doc1.file_url, doc2.file_url)
        self.assertTrue(frappe.db.exists("File", {"file_url": doc1.file_url}))

    def test_stored_file_stays_under_files_root(self):
        # Security: even with a traversal-laden filename, the framework flattens
        # to the basename so the stored file cannot escape the files root.
        file_doc = _create_file_record(
            content=b"x",
            filename=sanitize_filename("../../../../etc/escape.txt"),
            is_private=1,
            attached_to_doctype="Chapter",
            attached_to_name="Test Chapter Escape",
        )
        self._created_files.append(file_doc.name)
        self._created_urls.append(file_doc.file_url)
        self._created_paths.append(self._abs_from_url(file_doc.file_url))

        self.assertNotIn("..", file_doc.file_url)
        self.assertNotIn("/etc/", file_doc.file_url)
        abs_path = self._abs_from_url(file_doc.file_url)
        files_root = os.path.realpath(get_files_path(is_private=1))
        self.assertTrue(os.path.realpath(abs_path).startswith(files_root + os.sep))


class TestCleanupEmptyDirectories(EnhancedTestCase):
    def test_removes_empty_nested_directories(self):
        base = get_files_path(is_private=1)
        root = os.path.join(base, "cleanup-test-root")
        nested = os.path.join(root, "a", "b", "c")
        os.makedirs(nested, exist_ok=True)
        try:
            cleanup_empty_directories(root)
            # All empty subdirs should be gone
            self.assertFalse(os.path.exists(nested))
        finally:
            # Remove the root (cleanup_empty_directories leaves the top dir)
            if os.path.exists(root):
                import shutil

                shutil.rmtree(root, ignore_errors=True)

    def test_keeps_directories_with_files(self):
        base = get_files_path(is_private=1)
        root = os.path.join(base, "cleanup-keep-root")
        nested = os.path.join(root, "keep")
        os.makedirs(nested, exist_ok=True)
        marker = os.path.join(nested, "keep.txt")
        with open(marker, "wb") as f:
            f.write(b"x")
        try:
            cleanup_empty_directories(root)
            self.assertTrue(os.path.exists(marker))
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_nonexistent_base_does_not_raise(self):
        # os.walk on a missing dir yields nothing; must not raise
        cleanup_empty_directories("/tmp/this-dir-should-not-exist-vereniging-xyz")
