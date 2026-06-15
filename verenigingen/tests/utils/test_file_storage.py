# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Tests for verenigingen.utils.file_storage.

Focus areas:
- Path-security sanitizers (sanitize_path_component, sanitize_filename) tested
  directly against traversal / null-byte / unicode / overlong inputs.
- Pure path builders (get_chapter_document_path, get_organization_document_path).
- Real integration of save_*/organize_* against the site filesystem + File doctype,
  asserting returned paths and created File records, with full cleanup.
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
    """Pure path-builder tests (no filesystem writes)."""

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
    """Shared setup/teardown that tracks created File docs + on-disk paths."""

    def setUp(self):
        super().setUp()
        self._created_files = []  # File doc names
        self._created_paths = []  # absolute on-disk paths

    def tearDown(self):
        for name in self._created_files:
            if frappe.db.exists("File", name):
                frappe.delete_doc("File", name, force=True, ignore_permissions=True)
        # Also sweep any File rows by url / basename that we know about
        for url in getattr(self, "_created_urls", []):
            for fname in frappe.get_all("File", filters={"file_url": url}, pluck="name"):
                frappe.delete_doc("File", fname, force=True, ignore_permissions=True)
            # File doctype flattens file_url to the basename on insert, so also
            # sweep by the flattened url to avoid leaking File rows.
            basename = url.rsplit("/", 1)[-1]
            flat = f"/private/files/{basename}"
            for fname in frappe.get_all("File", filters={"file_url": flat}, pluck="name"):
                frappe.delete_doc("File", fname, force=True, ignore_permissions=True)
        for path in self._created_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        super().tearDown()

    def _track_url(self, file_url):
        if not hasattr(self, "_created_urls"):
            self._created_urls = []
        self._created_urls.append(file_url)

    def _abs_from_url(self, file_url):
        if file_url.startswith("/private/files/"):
            return os.path.join(get_files_path(is_private=1), file_url.replace("/private/files/", ""))
        return os.path.join(get_files_path(is_private=0), file_url.replace("/files/", ""))

    def _find_file_record(self, file_name, attached_to_doctype, attached_to_name):
        """Find the File record created by file_storage.

        NOTE: Frappe's File doctype flattens file_url to the basename on insert
        (see handle_is_private_changed), so the record cannot be located by the
        hierarchical url returned from save_*; we look it up by file_name +
        attachment instead.
        """
        rows = frappe.get_all(
            "File",
            filters={
                "file_name": file_name,
                "attached_to_doctype": attached_to_doctype,
                "attached_to_name": attached_to_name,
            },
            pluck="name",
        )
        return rows[0] if rows else None


class TestSaveChapterDocument(_FileStorageIntegrationBase):
    """Real integration: save_chapter_document writes a file + File record."""

    def test_save_private_chapter_document_creates_file_and_record(self):
        result = save_chapter_document(
            content=b"hello world",
            filename="meeting.txt",
            chapter_name="Test Chapter Storage",
            category="Meeting Minutes",
            year="2026",
            is_private=1,
        )
        self._track_url(result["file_url"])
        self.assertEqual(result["file_name"], "meeting.txt")
        self.assertTrue(result["file_url"].startswith("/private/files/documents/chapters/"))

        abs_path = self._abs_from_url(result["file_url"])
        self._created_paths.append(abs_path)
        self.assertTrue(os.path.exists(abs_path))
        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), b"hello world")

        # File record exists and is attached to the Chapter. NOTE: it is located
        # by file_name + attachment because the File doctype flattens file_url.
        file_name = self._find_file_record("meeting.txt", "Chapter", "Test Chapter Storage")
        self.assertTrue(file_name)
        self._created_files.append(file_name)
        attached = frappe.db.get_value(
            "File", file_name, ["attached_to_doctype", "is_private", "file_url"], as_dict=True
        )
        self.assertEqual(attached.attached_to_doctype, "Chapter")
        self.assertEqual(attached.is_private, 1)
        # PRODUCT-BUG WITNESS: the File record url does NOT match the hierarchical
        # url that save_chapter_document returned (Frappe flattens it to basename).
        self.assertNotEqual(attached.file_url, result["file_url"])
        self.assertEqual(attached.file_url, "/private/files/meeting.txt")

    def test_save_public_chapter_document_uses_public_url(self):
        result = save_chapter_document(
            content=b"public data",
            filename="public.txt",
            chapter_name="Test Chapter Public",
            category="Policy",
            year="2026",
            is_private=0,
        )
        self._track_url(result["file_url"])
        self.assertTrue(result["file_url"].startswith("/files/documents/chapters/"))
        abs_path = self._abs_from_url(result["file_url"])
        self._created_paths.append(abs_path)
        self.assertTrue(os.path.exists(abs_path))
        fn = self._find_file_record("public.txt", "Chapter", "Test Chapter Public")
        if fn:
            self._created_files.append(fn)

    def test_save_with_file_object_content(self):
        import io

        result = save_chapter_document(
            content=io.BytesIO(b"streamed bytes"),
            filename="stream.bin",
            chapter_name="Test Chapter Stream",
            category="Other",
            year="2026",
            is_private=1,
        )
        self._track_url(result["file_url"])
        abs_path = self._abs_from_url(result["file_url"])
        self._created_paths.append(abs_path)
        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), b"streamed bytes")
        fn = self._find_file_record("stream.bin", "Chapter", "Test Chapter Stream")
        if fn:
            self._created_files.append(fn)

    def test_save_neutralises_traversal_in_filename(self):
        # A hostile filename must not escape the chapter document tree
        result = save_chapter_document(
            content=b"x",
            filename="../../../../etc/evil.txt",
            chapter_name="Test Chapter Traversal",
            category="Policy",
            year="2026",
            is_private=1,
        )
        self._track_url(result["file_url"])
        abs_path = self._abs_from_url(result["file_url"])
        self._created_paths.append(abs_path)
        # The stored path must remain under documents/chapters and contain no '..'
        self.assertNotIn("..", result["file_url"])
        self.assertIn("/documents/chapters/", result["file_url"])
        norm = os.path.normpath(abs_path)
        self.assertIn(os.path.join("documents", "chapters"), norm)
        # The on-disk file must stay within the hierarchical chapter tree, never
        # at /etc. Verify the realpath is under the private files documents dir.
        files_root = os.path.realpath(get_files_path(is_private=1))
        self.assertTrue(os.path.realpath(abs_path).startswith(files_root))
        fn = self._find_file_record(
            "../../../../etc/evil.txt", "Chapter", "Test Chapter Traversal"
        )
        if fn:
            self._created_files.append(fn)


class TestSaveOrganizationDocument(_FileStorageIntegrationBase):
    """Real integration: save_organization_document."""

    def test_save_team_document_attaches_to_team_type(self):
        result = save_organization_document(
            content=b"team data",
            filename="charter.txt",
            organization_type="Team",
            organization_name="Test Team Storage",
            category="Policy",
            year="2026",
            is_private=1,
        )
        self._track_url(result["file_url"])
        self.assertIn("/documents/teams/", result["file_url"])
        abs_path = self._abs_from_url(result["file_url"])
        self._created_paths.append(abs_path)
        self.assertTrue(os.path.exists(abs_path))
        fn = self._find_file_record("charter.txt", "Team", "Test Team Storage")
        self.assertTrue(fn)
        self._created_files.append(fn)
        attached = frappe.db.get_value("File", fn, "attached_to_doctype")
        self.assertEqual(attached, "Team")

    def test_save_with_document_name_attaches_to_org_document(self):
        # When document_name is provided, attaches to "Organization Document".
        # We pass a name that need not resolve to a real doc because
        # ignore_file_validate skips link validation; assert the attachment
        # target on the created File record.
        result = save_organization_document(
            content=b"doc",
            filename="ref.txt",
            organization_type="Chapter",
            organization_name="Test Chapter OrgDoc",
            category="Policy",
            year="2026",
            is_private=1,
            document_name="ORG-DOC-TEST-0001",
        )
        self._track_url(result["file_url"])
        abs_path = self._abs_from_url(result["file_url"])
        self._created_paths.append(abs_path)
        fn = self._find_file_record("ref.txt", "Organization Document", "ORG-DOC-TEST-0001")
        self.assertTrue(fn)
        self._created_files.append(fn)
        rec = frappe.db.get_value(
            "File", fn, ["attached_to_doctype", "attached_to_name"], as_dict=True
        )
        self.assertEqual(rec.attached_to_doctype, "Organization Document")
        self.assertEqual(rec.attached_to_name, "ORG-DOC-TEST-0001")


class TestOrganizeExistingChapterDocument(_FileStorageIntegrationBase):
    """Real integration: moving a flat file into the hierarchy."""

    def _write_flat_private_file(self, rel_name, content=b"flat"):
        base = get_files_path(is_private=1)
        abs_path = os.path.join(base, rel_name)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(content)
        return abs_path, f"/private/files/{rel_name}"

    def test_already_organized_url_returned_unchanged(self):
        url = "/private/files/documents/chapters/x/policy/2026/a.pdf"
        self.assertEqual(
            organize_existing_chapter_document(url, "X", "Policy", "2026"), url
        )

    def test_empty_url_returned_unchanged(self):
        self.assertEqual(organize_existing_chapter_document("", "X", "Policy", "2026"), "")

    def test_unrecognized_url_prefix_returned_unchanged(self):
        url = "https://external/file.pdf"
        self.assertEqual(
            organize_existing_chapter_document(url, "X", "Policy", "2026"), url
        )

    def test_missing_file_returns_original_url(self):
        url = "/private/files/does-not-exist-xyz.pdf"
        self.assertEqual(
            organize_existing_chapter_document(url, "X", "Policy", "2026"), url
        )

    def test_moves_flat_file_into_hierarchy(self):
        abs_old, old_url = self._write_flat_private_file("organize-me-test.txt", b"move me")
        self._created_paths.append(abs_old)
        new_url = organize_existing_chapter_document(
            old_url, "Test Chapter Organize", "Policy", "2026"
        )
        self._track_url(new_url)
        self.assertIn("/documents/chapters/", new_url)
        new_abs = self._abs_from_url(new_url)
        self._created_paths.append(new_abs)
        # The hierarchical copy is created with the right content.
        self.assertTrue(os.path.exists(new_abs))
        with open(new_abs, "rb") as f:
            self.assertEqual(f.read(), b"move me")
        # PRODUCT-BUG WITNESS: because _create_file_record's File doc re-writes a
        # copy at the flattened (basename) url, the original flat file is
        # re-created at abs_old instead of being consolidated away.
        self.assertTrue(os.path.exists(abs_old))
        fn = self._find_file_record(
            "organize-me-test.txt", "Chapter", "Test Chapter Organize"
        )
        if fn:
            self._created_files.append(fn)


class TestOrganizeOrganizationDocument(_FileStorageIntegrationBase):
    def _write_flat_private_file(self, rel_name, content=b"flat"):
        base = get_files_path(is_private=1)
        abs_path = os.path.join(base, rel_name)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(content)
        return abs_path, f"/private/files/{rel_name}"

    def test_already_organized_for_type_returned_unchanged(self):
        url = "/private/files/documents/teams/x/policy/2026/a.pdf"
        self.assertEqual(
            organize_organization_document(url, "Team", "X", "Policy", "2026"), url
        )

    def test_empty_url_returned_unchanged(self):
        self.assertEqual(
            organize_organization_document("", "Team", "X", "Policy", "2026"), ""
        )

    def test_missing_file_returns_original(self):
        url = "/private/files/missing-org-file-xyz.pdf"
        self.assertEqual(
            organize_organization_document(url, "Team", "X", "Policy", "2026"), url
        )

    def test_moves_flat_file_into_org_hierarchy(self):
        abs_old, old_url = self._write_flat_private_file("organize-org-test.txt", b"org move")
        self._created_paths.append(abs_old)
        new_url = organize_organization_document(
            old_url, "Team", "Test Team Organize", "Policy", "2026"
        )
        self._track_url(new_url)
        self.assertIn("/documents/teams/", new_url)
        new_abs = self._abs_from_url(new_url)
        self._created_paths.append(new_abs)
        # Hierarchical copy created (organize's intended on-disk effect).
        self.assertTrue(os.path.exists(new_abs))
        # PRODUCT-BUG WITNESS: flat duplicate re-created (see chapter variant).
        self.assertTrue(os.path.exists(abs_old))
        fn = self._find_file_record(
            "organize-org-test.txt", "Team", "Test Team Organize"
        )
        if fn:
            self._created_files.append(fn)


class TestCreateFileRecord(_FileStorageIntegrationBase):
    """_create_file_record dedup + creation."""

    def test_create_file_record_returns_a_name(self):
        # Basic creation contract: a File record name is returned for a valid file.
        base = get_files_path(is_private=1)
        abs_path = os.path.join(base, "flat-create-test.txt")
        with open(abs_path, "wb") as f:
            f.write(b"create")
        self._created_paths.append(abs_path)
        url = "/private/files/flat-create-test.txt"

        name1 = _create_file_record(url, "flat-create-test.txt", 1, "Chapter", "Test Chapter Create")
        self.assertTrue(name1)
        self._created_files.append(name1)
        self.assertTrue(frappe.db.exists("File", name1))

    def test_dedup_by_url_never_matches_due_to_content_hash_suffix(self):
        # PRODUCT-BUG WITNESS: _create_file_record dedups via
        # frappe.db.exists("File", {"file_url": file_url}), but the File doctype
        # suffixes the stored filename with a content-hash (and flattens the
        # path), so the stored url never equals the input url. The dedup check is
        # therefore effectively dead — a second call creates a NEW record.
        base = get_files_path(is_private=1)
        abs_path = os.path.join(base, "flat-dedupe-test.txt")
        with open(abs_path, "wb") as f:
            f.write(b"dedupe")
        self._created_paths.append(abs_path)
        url = "/private/files/flat-dedupe-test.txt"

        name1 = _create_file_record(url, "flat-dedupe-test.txt", 1, "Chapter", "Test Chapter Dedupe")
        name2 = _create_file_record(url, "flat-dedupe-test.txt", 1, "Chapter", "Test Chapter Dedupe")
        self._created_files.extend([name1, name2])
        self.assertNotEqual(name1, name2)
        # The stored url carries a hash suffix, not the input url.
        self.assertNotEqual(frappe.db.get_value("File", name1, "file_url"), url)

    def test_hierarchical_url_dedup_is_broken_by_url_flattening(self):
        # PRODUCT-BUG WITNESS: because the File doctype flattens file_url to the
        # basename on insert, a second _create_file_record call with the SAME
        # hierarchical url no longer matches the stored (flattened) url, so the
        # dedup check misses and a DUPLICATE File record is created.
        url = "/private/files/documents/chapters/test-dedupe/policy/2026/dedupe.txt"
        abs_path = self._abs_from_url(url)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(b"dedupe")
        self._created_paths.append(abs_path)

        name1 = _create_file_record(url, "dedupe.txt", 1, "Chapter", "Test Chapter Dedupe2")
        name2 = _create_file_record(url, "dedupe.txt", 1, "Chapter", "Test Chapter Dedupe2")
        self._created_files.extend([name1, name2])
        # Documents the current (buggy) behaviour: two distinct records.
        self.assertNotEqual(name1, name2)


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
