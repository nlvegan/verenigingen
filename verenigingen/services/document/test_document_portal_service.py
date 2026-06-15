# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for DocumentPortalService.

Exercises the real upload-eligibility resolution (which organizations a user
may upload to / view), the listing transforms, document upload requests, and
permission gating against real DB state.

Uses real Member/Volunteer/Chapter/Team/Movement docs. File uploads create
real File docs which are force-deleted in tearDown.
"""

import base64

import frappe

from verenigingen.services.document.document_portal_service import (
    DocumentPortalService,
    DocumentUploadRequest,
    get_document_portal_service,
    get_organization_documents_for_template,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _png_bytes() -> bytes:
    """A tiny valid PNG file (1x1) for upload tests."""
    # Minimal 1x1 transparent PNG
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


class TestDocumentPortalService(EnhancedTestCase):
    """Integration tests for DocumentPortalService."""

    def setUp(self):
        super().setUp()
        self.service = DocumentPortalService()
        # Track created Organization Document / File names for cleanup
        self._org_docs = []
        self._files = []
        self._extra_docs = []  # (doctype, name) tuples

    def tearDown(self):
        # Force-delete Organization Documents and any File docs we created.
        for name in self._org_docs:
            if frappe.db.exists("Organization Document", name):
                frappe.delete_doc("Organization Document", name, force=True, ignore_permissions=True)
        for name in self._files:
            if frappe.db.exists("File", name):
                frappe.delete_doc("File", name, force=True, ignore_permissions=True)
        for dt, name in self._extra_docs:
            if frappe.db.exists(dt, name):
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
        super().tearDown()

    # ---------------------------------------------------------------------
    # Helpers (allowed to use ignore_permissions / set_user)
    # ---------------------------------------------------------------------

    def _as_user(self, email):
        frappe.set_user(email)

    def _as_admin(self):
        frappe.set_user("Administrator")

    def _make_member_with_user(self, roles=None):
        """Create a Member linked to a real User account."""
        roles = roles or ["Verenigingen Member"]
        user = self.factory.create_user_with_roles(roles=roles)
        member = self.factory.create_member(
            first_name="Portal",
            last_name="Tester",
            email=f"member_{frappe.generate_hash(length=8)}@test.invalid",
        )
        member.user = user.email
        member.save()
        return member, user

    def _make_volunteer_for(self, member):
        return self.factory.create_volunteer(member_name=member.name)

    def _ensure_chapter_role(self):
        role_name = "TEST-Board-Role"
        if not frappe.db.exists("Chapter Role", role_name):
            doc = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Basic",
                    "is_active": 1,
                }
            )
            doc.insert(ignore_permissions=True)
        return role_name

    def _setup_board_member(self, chapter, volunteer_name, is_active=1):
        role_name = self._ensure_chapter_role()
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role_name,
                "from_date": frappe.utils.today(),
                "is_active": is_active,
            },
        )
        chapter.save(ignore_permissions=True)

    def _setup_chapter_member(self, chapter, member_name, status="Active", enabled=1):
        chapter.append(
            "members",
            {
                "member": member_name,
                "chapter_join_date": frappe.utils.today(),
                "status": status,
                "enabled": enabled,
            },
        )
        chapter.save(ignore_permissions=True)

    def _make_movement(self, with_volunteer=None):
        name = f"TEST-Movement-{frappe.generate_hash(length=8)}"
        doc = frappe.get_doc(
            {
                "doctype": "Movement",
                "movement_name": name,
                "status": "Active",
            }
        )
        if with_volunteer:
            doc.append(
                "members",
                {
                    "volunteer": with_volunteer,
                    "status": "Active",
                    "join_date": frappe.utils.today(),
                },
            )
        doc.insert(ignore_permissions=True)
        self._extra_docs.append(("Movement", doc.name))
        return doc

    def _make_upload_request(self, org_type, org_name, **overrides):
        defaults = dict(
            organization_type=org_type,
            organization_name=org_name,
            document_name="Annual Report 2024",
            document_type="Policy",
            file_name="report.png",
            file_content=base64.b64encode(_png_bytes()).decode(),
            content_type="image/png",
            description="A test document",
        )
        defaults.update(overrides)
        return DocumentUploadRequest(**defaults)

    def _persist_upload(self, result):
        """Track created Org Document + its File for cleanup."""
        if result.get("success") and result.get("document_name"):
            self._org_docs.append(result["document_name"])
            file_url = result.get("file_url")
            if file_url:
                fn = frappe.db.get_value("File", {"file_url": file_url}, "name")
                if fn:
                    self._files.append(fn)

    # =====================================================================
    # Dataclass + factory tests
    # =====================================================================

    def test_singleton_factory(self):
        s1 = get_document_portal_service()
        s2 = get_document_portal_service()
        self.assertIs(s1, s2)
        self.assertIsInstance(s1, DocumentPortalService)

    def test_upload_request_dataclass_defaults(self):
        req = DocumentUploadRequest(
            organization_type="Chapter",
            organization_name="X",
            document_name="D",
            document_type="Policy",
            file_name="f.pdf",
            file_content="abc",
            content_type="application/pdf",
        )
        self.assertIsNone(req.description)
        self.assertIsNone(req.year)

    # =====================================================================
    # Authorization: can_upload_to / get_upload_context
    # =====================================================================

    def test_admin_can_upload_anywhere(self):
        chapter = self.factory.create_chapter()
        # System Manager session
        self._as_admin()
        try:
            self.assertTrue(self.service.can_upload_to("Administrator", "Chapter", chapter.name))
        finally:
            self._as_admin()

    def test_board_member_can_upload_to_chapter(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self.assertTrue(self.service.can_upload_to(user.email, "Chapter", chapter.name))

    def test_inactive_board_member_cannot_upload(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=0)

        self.assertFalse(self.service.can_upload_to(user.email, "Chapter", chapter.name))

    def test_non_member_cannot_upload(self):
        member, user = self._make_member_with_user()
        # No volunteer record at all -> cannot upload
        chapter = self.factory.create_chapter()
        self.assertFalse(self.service.can_upload_to(user.email, "Chapter", chapter.name))

    def test_team_member_can_upload(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        team = self.factory.create_team()
        self.factory.create_team_member(team.name, volunteer.name)
        self.assertTrue(self.service.can_upload_to(user.email, "Team", team.name))

    def test_movement_member_can_upload(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        movement = self._make_movement(with_volunteer=volunteer.name)
        self.assertTrue(self.service.can_upload_to(user.email, "Movement", movement.name))

    def test_can_upload_to_unknown_type_returns_false(self):
        member, user = self._make_member_with_user()
        self.assertFalse(self.service.can_upload_to(user.email, "Bogus", "X"))

    def test_get_upload_context_for_board_member(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)
        team = self.factory.create_team()
        self.factory.create_team_member(team.name, volunteer.name)

        ctx = self.service.get_upload_context(user.email)
        self.assertTrue(ctx["success"])
        self.assertEqual(ctx["member_name"], member.name)
        self.assertEqual(ctx["volunteer_name"], volunteer.name)
        chapter_names = [c["name"] for c in ctx["organizations"]["chapters"]]
        team_names = [t["name"] for t in ctx["organizations"]["teams"]]
        self.assertIn(chapter.name, chapter_names)
        self.assertIn(team.name, team_names)
        self.assertTrue(len(ctx["categories"]) > 0)

    def test_get_upload_context_no_member(self):
        # A plain user with no Member record
        user = self.factory.create_user_with_roles(roles=["Verenigingen Member"])
        ctx = self.service.get_upload_context(user.email)
        self.assertTrue(ctx["success"])
        self.assertIsNone(ctx["member_name"])
        self.assertEqual(ctx["organizations"]["chapters"], [])

    # =====================================================================
    # upload_document (real File creation)
    # =====================================================================

    def test_upload_document_success(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        req = self._make_upload_request("Chapter", chapter.name)
        self._as_user(user.email)
        try:
            result = self.service.upload_document(req)
        finally:
            self._as_admin()
        self._persist_upload(result)

        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["document_name"])
        # Real DB state
        doc = frappe.get_doc("Organization Document", result["document_name"])
        self.assertEqual(doc.organization_type, "Chapter")
        self.assertEqual(doc.chapter, chapter.name)
        self.assertEqual(doc.uploaded_by, user.email)
        self.assertTrue(doc.file_hash)
        self.assertTrue(doc.document_file)

    def test_upload_permission_denied(self):
        member, user = self._make_member_with_user()
        # No volunteer -> denied
        chapter = self.factory.create_chapter()
        req = self._make_upload_request("Chapter", chapter.name)
        self._as_user(user.email)
        try:
            result = self.service.upload_document(req)
        finally:
            self._as_admin()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "permission_denied")

    def test_upload_duplicate_name_rejected(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            r1 = self.service.upload_document(self._make_upload_request("Chapter", chapter.name))
            self._persist_upload(r1)
            self.assertTrue(r1["success"], msg=r1)
            # Same document_name (case/whitespace normalised) -> duplicate
            r2 = self.service.upload_document(
                self._make_upload_request(
                    "Chapter",
                    chapter.name,
                    document_name="annual   report 2024",
                    file_name="report2.png",
                    file_content=base64.b64encode(b"different content").decode(),
                )
            )
            self._persist_upload(r2)
        finally:
            self._as_admin()
        self.assertFalse(r2["success"])
        self.assertEqual(r2["error"], "duplicate_document")

    def test_upload_duplicate_content_hash_rejected(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            r1 = self.service.upload_document(self._make_upload_request("Chapter", chapter.name))
            self._persist_upload(r1)
            self.assertTrue(r1["success"], msg=r1)
            # Different name, identical content -> duplicate_content
            r2 = self.service.upload_document(
                self._make_upload_request(
                    "Chapter",
                    chapter.name,
                    document_name="Different Name 2023",
                    file_name="other.png",
                )
            )
            self._persist_upload(r2)
        finally:
            self._as_admin()
        self.assertFalse(r2["success"])
        self.assertEqual(r2["error"], "duplicate_content")

    def test_upload_invalid_file_type(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        req = self._make_upload_request(
            "Chapter",
            chapter.name,
            file_name="malware.exe",
            content_type="application/octet-stream",
        )
        self._as_user(user.email)
        try:
            result = self.service.upload_document(req)
        finally:
            self._as_admin()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_file_type")

    def test_upload_mime_extension_mismatch(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        req = self._make_upload_request(
            "Chapter",
            chapter.name,
            file_name="report.pdf",
            content_type="image/png",  # mismatch
        )
        self._as_user(user.email)
        try:
            result = self.service.upload_document(req)
        finally:
            self._as_admin()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "mime_extension_mismatch")

    def test_upload_invalid_base64(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        # Valid extension/mime but content not valid base64.
        req = self._make_upload_request(
            "Chapter",
            chapter.name,
            file_content="!!!not base64!!!",
        )
        self._as_user(user.email)
        try:
            result = self.service.upload_document(req)
        finally:
            self._as_admin()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_encoding")

    # =====================================================================
    # delete_document
    # =====================================================================

    def test_delete_document_success(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            up = self.service.upload_document(self._make_upload_request("Chapter", chapter.name))
            self.assertTrue(up["success"], msg=up)
            doc_name = up["document_name"]
            result = self.service.delete_document(doc_name)
        finally:
            self._as_admin()
        self.assertTrue(result["success"], msg=result)
        self.assertFalse(frappe.db.exists("Organization Document", doc_name))

    def test_delete_document_not_found(self):
        self._as_admin()
        result = self.service.delete_document("DOC-Chapter-NOTREAL-9999")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "not_found")

    def test_delete_permission_denied(self):
        # Board member uploads, then a different unprivileged user tries to delete.
        owner_member, owner_user = self._make_member_with_user()
        owner_vol = self._make_volunteer_for(owner_member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, owner_vol.name, is_active=1)

        self._as_user(owner_user.email)
        try:
            up = self.service.upload_document(self._make_upload_request("Chapter", chapter.name))
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        other_member, other_user = self._make_member_with_user()
        self._as_user(other_user.email)
        try:
            result = self.service.delete_document(up["document_name"])
        finally:
            self._as_admin()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "permission_denied")
        # Document must still exist
        self.assertTrue(frappe.db.exists("Organization Document", up["document_name"]))

    # =====================================================================
    # get_organization_documents + template formatter
    # =====================================================================

    def test_get_organization_documents_grouped(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            up = self.service.upload_document(
                self._make_upload_request("Chapter", chapter.name, document_name="Policy 2024", year="2024")
            )
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        result = self.service.get_organization_documents("Chapter", chapter.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 1)
        self.assertIn("Policy", result["documents"])
        self.assertIn("2024", result["documents"]["Policy"]["years"])

    def test_get_organization_documents_for_template(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            up = self.service.upload_document(
                self._make_upload_request("Chapter", chapter.name, document_name="Policy 2024", year="2024")
            )
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        result = get_organization_documents_for_template("Chapter", chapter.name)
        self.assertEqual(result["total_count"], 1)
        self.assertIn("by_type_and_year", result)
        self.assertIn("category_icons", result)
        # The category keys should be real category names, not single chars
        for cat in result["by_type_and_year"].keys():
            self.assertTrue(len(cat) > 1)
        self.assertIn("Policy", result["by_type_and_year"])
        self.assertIn("2024", result["by_type_and_year"]["Policy"])

    def test_template_formatter_empty_org(self):
        chapter = self.factory.create_chapter()
        result = get_organization_documents_for_template("Chapter", chapter.name)
        self.assertEqual(result["total_count"], 0)
        # All default categories present, even if empty
        self.assertTrue(len(result["category_icons"]) > 0)

    # =====================================================================
    # View permissions: can_view_organization_documents / get_all_accessible
    # =====================================================================

    def test_view_published_chapter_for_member(self):
        member, user = self._make_member_with_user()
        chapter = self.factory.create_chapter(published=1)
        # Member (Verenigingen Member role) can view a published chapter
        self.assertTrue(self.service.can_view_organization_documents(user.email, "Chapter", chapter.name))

    def test_view_unpublished_chapter_denied_for_nonmember(self):
        member, user = self._make_member_with_user()
        chapter = self.factory.create_chapter(published=0)
        self.assertFalse(self.service.can_view_organization_documents(user.email, "Chapter", chapter.name))

    def test_view_chapter_member_can_view_unpublished(self):
        member, user = self._make_member_with_user()
        chapter = self.factory.create_chapter(published=0)
        self._setup_chapter_member(chapter, member.name)
        self.assertTrue(self.service.can_view_organization_documents(user.email, "Chapter", chapter.name))

    def test_admin_can_view_anything(self):
        chapter = self.factory.create_chapter(published=0)
        self.assertTrue(
            self.service.can_view_organization_documents("Administrator", "Chapter", chapter.name)
        )

    def test_get_all_accessible_documents_for_board_member(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter(published=0)
        self._setup_chapter_member(chapter, member.name)
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            up = self.service.upload_document(self._make_upload_request("Chapter", chapter.name))
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        result = self.service.get_all_accessible_documents(user.email)
        self.assertTrue(result["success"], msg=result)
        names = [d["name"] for d in result["documents"]]
        self.assertIn(up["document_name"], names)
        # organization_name annotation must be populated
        for d in result["documents"]:
            if d["name"] == up["document_name"]:
                self.assertEqual(d["organization_name"], chapter.name)

    def test_get_all_accessible_invalid_org_type(self):
        member, user = self._make_member_with_user()
        result = self.service.get_all_accessible_documents(user.email, org_type="Bogus")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_org_type")

    def test_get_all_accessible_no_orgs_returns_empty(self):
        member, user = self._make_member_with_user()
        # No memberships at all
        result = self.service.get_all_accessible_documents(user.email)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["documents"], [])

    def test_get_all_accessible_search_filter(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter(published=0)
        self._setup_chapter_member(chapter, member.name)
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        self._as_user(user.email)
        try:
            up = self.service.upload_document(
                self._make_upload_request("Chapter", chapter.name, document_name="Findable Policy 2024")
            )
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        # Matching search term
        hit = self.service.get_all_accessible_documents(user.email, search_term="Findable")
        self.assertTrue(hit["success"])
        self.assertTrue(any(d["name"] == up["document_name"] for d in hit["documents"]))

        # Non-matching search term
        miss = self.service.get_all_accessible_documents(user.email, search_term="ZZZ_NoMatch_ZZZ")
        self.assertEqual(miss["total_count"], 0)

    # =====================================================================
    # Pure-logic units (no DB)
    # =====================================================================

    def test_clean_document_title(self):
        s = self.service
        self.assertEqual(
            s._clean_document_title("20250524-Intern-Bulletin-39"),
            "20250524 Intern Bulletin 39",
        )
        self.assertEqual(s._clean_document_title("Annual_Report_2024"), "Annual Report 2024")
        # Already has spaces -> unchanged
        self.assertEqual(s._clean_document_title("Report - 2024"), "Report - 2024")
        # No latin letters -> unchanged
        self.assertEqual(s._clean_document_title("年度報告_2024"), "年度報告_2024")
        # All separators -> would be empty, preserve original
        self.assertEqual(s._clean_document_title("---"), "---")
        # Empty
        self.assertEqual(s._clean_document_title(""), "")

    def test_normalize_document_name(self):
        s = self.service
        self.assertEqual(s._normalize_document_name("Annual  Report  2024"), "annual report 2024")
        self.assertEqual(s._normalize_document_name(""), "")

    def test_compute_file_hash(self):
        h = self.service._compute_file_hash(b"hello")
        self.assertEqual(len(h), 64)
        self.assertRegex(h, r"^[a-f0-9]{64}$")

    def test_extract_year(self):
        s = self.service
        self.assertEqual(s._extract_year("Report 2023"), "2023")
        # Falls back to current year when no year present
        current = str(frappe.utils.now_datetime().year)
        self.assertEqual(s._extract_year("No year here"), current)

    def test_validate_file_missing_filename(self):
        req = self._make_upload_request("Chapter", "X", file_name="")
        result = self.service._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "missing_filename")

    def test_validate_file_too_large(self):
        # Build a base64 string longer than MAX_FILE_SIZE * 4/3
        big = "A" * (DocumentPortalService.MAX_FILE_SIZE * 2)
        req = self._make_upload_request(
            "Chapter",
            "X",
            file_content=big,
            file_name="big.pdf",
            content_type="application/pdf",
        )
        result = self.service._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "file_too_large")

    def test_validate_file_invalid_mime(self):
        req = self._make_upload_request(
            "Chapter",
            "X",
            file_name="report.pdf",
            content_type="application/x-bogus",
        )
        result = self.service._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "invalid_mime_type")

    def test_validate_file_valid(self):
        req = self._make_upload_request("Chapter", "X")
        result = self.service._validate_file(req)
        self.assertTrue(result["valid"])

    # =====================================================================
    # Additional view-permission + accessible-documents branches
    # =====================================================================

    def test_admin_get_all_accessible_documents_sees_all_org_types(self):
        # Upload one doc to a chapter as a board member
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_board_member(chapter, volunteer.name, is_active=1)
        self._as_user(user.email)
        try:
            up = self.service.upload_document(self._make_upload_request("Chapter", chapter.name))
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        # Administrator (admin path) sees all orgs (Chapter/Team/Movement)
        result = self.service.get_all_accessible_documents("Administrator")
        self.assertTrue(result["success"], msg=result)
        org_types = {o["organization_type"] for o in result["organizations"]}
        self.assertIn("Chapter", org_types)
        names = [d["name"] for d in result["documents"]]
        self.assertIn(up["document_name"], names)

    def test_get_all_accessible_org_type_filter_no_match(self):
        # Board member of a Chapter, filter by Team -> no accessible team orgs
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_chapter_member(chapter, member.name)
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        result = self.service.get_all_accessible_documents(user.email, org_type="Team")
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["documents"], [])

    def test_get_all_accessible_organization_filter_no_match(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter()
        self._setup_chapter_member(chapter, member.name)
        self._setup_board_member(chapter, volunteer.name, is_active=1)

        result = self.service.get_all_accessible_documents(user.email, organization="No-Such-Chapter-XYZ")
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 0)

    def test_get_all_accessible_with_category_filter(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        chapter = self.factory.create_chapter(published=0)
        self._setup_chapter_member(chapter, member.name)
        self._setup_board_member(chapter, volunteer.name, is_active=1)
        self._as_user(user.email)
        try:
            up = self.service.upload_document(
                self._make_upload_request("Chapter", chapter.name, document_type="Policy")
            )
        finally:
            self._as_admin()
        self._persist_upload(up)
        self.assertTrue(up["success"], msg=up)

        # Matching category
        hit = self.service.get_all_accessible_documents(user.email, category="Policy")
        self.assertTrue(any(d["name"] == up["document_name"] for d in hit["documents"]))
        # Non-matching category
        miss = self.service.get_all_accessible_documents(user.email, category="Meeting Minutes")
        self.assertEqual(miss["total_count"], 0)

    def test_can_view_team_member(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        team = self.factory.create_team()
        self.factory.create_team_member(team.name, volunteer.name)
        self.assertTrue(self.service.can_view_organization_documents(user.email, "Team", team.name))
        # A team the user is NOT on
        other_team = self.factory.create_team()
        self.assertFalse(self.service.can_view_organization_documents(user.email, "Team", other_team.name))

    def test_can_view_movement_member(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for(member)
        movement = self._make_movement(with_volunteer=volunteer.name)
        self.assertTrue(self.service.can_view_organization_documents(user.email, "Movement", movement.name))

    def test_can_view_unknown_org_type(self):
        member, user = self._make_member_with_user()
        self.assertFalse(self.service.can_view_organization_documents(user.email, "Bogus", "X"))
