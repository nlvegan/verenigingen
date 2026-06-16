# -*- coding: utf-8 -*-
# Copyright (c) 2025, Veganisme.org and contributors
# See license.txt

"""
Tests for verenigingen/api/document_portal.py

The document portal exposes member/volunteer-facing access to organization
documents (Chapter / Team / Movement). It is security-sensitive: documents are
stored as PRIVATE files and access is scoped to org membership/board role.

These tests focus on:
- Happy paths return the seeded documents the user is authorized for.
- Access-control boundaries: a non-member must NOT see/upload/delete another
  organization's documents (IDOR), and Guest is rejected where required.
- Validation/error paths: invalid org type, missing params, oversized input.

All whitelisted endpoints are decorated with @standard_api. The decorator
enforces authentication BEFORE the function body executes: an unauthenticated
(Guest) call raises frappe.PermissionError from the security framework, so the
in-body `if user == "Guest"` branches are effectively unreachable dead code
(see FINDING in the module-level docstring of the test for Guest behavior).

On success the decorator returns the body's dict (these endpoints already
return plain success/error dicts, which the framework passes through). We
normalize via _payload() for robustness.
"""

import base64

import frappe

from verenigingen.api import document_portal
from verenigingen.tests.utils.base import VereningingenTestCase


def _payload(result):
    """Normalize an endpoint return into the inner business dict.

    @standard_api wraps the returned dict as {"success", "data", "error", "meta"}.
    When the endpoint succeeded, the business dict lives under "data". When the
    business dict itself carries success=False (an in-body early return), the
    wrapper may surface it directly. This helper returns whichever dict actually
    contains the business keys (success / organizations / documents / etc.).
    """
    if not isinstance(result, dict):
        return result
    # Wrapped success: business dict under "data"
    data = result.get("data")
    if isinstance(data, dict) and ("success" in data or "documents" in data or "organizations" in data):
        return data
    return result


class TestDocumentPortalAPI(VereningingenTestCase):
    """Access-control and behavior tests for the document portal API."""

    def setUp(self):
        super().setUp()
        # Reset the service singleton so no state leaks between tests.
        document_portal.get_document_portal_service.__globals__  # touch import
        from verenigingen.services.document import document_portal_service

        document_portal_service._document_portal_service = None

    # ------------------------------------------------------------------
    # Helpers (named _make_/_setup_ so test-quality-enforcer allows the
    # insert/save inside them).
    # ------------------------------------------------------------------

    def _make_board_member(self, email_prefix):
        """Create a User + Member + Volunteer who is an ACTIVE board member of a
        freshly created Chapter. Returns (user_email, chapter_name, volunteer)."""
        email = f"{email_prefix}.{frappe.generate_hash(length=6)}@example.com"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        member = self.create_test_member(
            chapter=False, email=email, first_name="Board", last_name="User"
        )
        # Link member to the user account so _get_member_for_user resolves.
        frappe.db.set_value("Member", member.name, "user", email)
        volunteer = self.create_test_volunteer(member=member.name)

        chapter = self.create_test_chapter()
        self._setup_chapter_board(chapter.name, volunteer.name)
        return email, chapter.name, volunteer

    def _setup_chapter_board(self, chapter_name, volunteer_name, is_active=1):
        """Append an active Chapter Board Member row for the volunteer."""
        chapter = frappe.get_doc("Chapter", chapter_name)
        # A board member also needs a chapter_role; pick or create one.
        role = frappe.db.get_value("Chapter Role", {}, "name")
        if not role:
            role_doc = frappe.get_doc(
                {"doctype": "Chapter Role", "role_name": "Test Board Role", "permissions_level": "Basic"}
            )
            role_doc.insert()
            self.track_doc("Chapter Role", role_doc.name)
            role = role_doc.name
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": is_active,
            },
        )
        chapter.save()

    def _persist_org_document(self, chapter_name, document_name, document_type="Policy"):
        """Persist an Organization Document for a chapter with a real private File.

        Mirrors what upload_document does so the read endpoints find a row.
        Returns the Organization Document name.
        """
        from verenigingen.utils.file_storage import save_organization_document

        # Use a .txt file: text/plain is an allowed type and avoids Frappe's
        # File before_insert PDF/image parsing ("EOF marker not found") that a
        # fake .pdf payload triggers.
        # Unique filename per doc: Frappe flattens private files to
        # /private/files/<basename>, so a shared basename would make multiple
        # File records collide on the same file_url and confuse delete-by-url.
        content = f"test content {frappe.generate_hash(length=8)}".encode()
        file_result = save_organization_document(
            content=content,
            filename=f"testdoc_{frappe.generate_hash(length=8)}.txt",
            organization_type="Chapter",
            organization_name=chapter_name,
            category=document_type,
            year="2024",
            is_private=1,
        )
        org_doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": "Chapter",
                "chapter": chapter_name,
                "document_name": document_name,
                "document_type": document_type,
                "document_file": file_result["file_url"],
                "upload_date": frappe.utils.today(),
                "uploaded_by": frappe.session.user,
            }
        )
        org_doc.insert()
        self.track_doc("Organization Document", org_doc.name)
        # Track the file too.
        file_name = frappe.db.get_value("File", {"file_url": file_result["file_url"]}, "name")
        if file_name:
            self.track_doc("File", file_name)
        return org_doc.name, file_result["file_url"]

    @staticmethod
    def _b64_text(body=b"hello world"):
        """Base64-encoded text payload (matches a .txt upload)."""
        return base64.b64encode(body).decode()

    # ==================================================================
    # get_upload_context
    # ==================================================================

    def test_get_upload_context_guest_rejected(self):
        # SECURITY: @standard_api denies Guest at the framework layer, raising
        # frappe.PermissionError before the body runs. (The body's own Guest
        # branch is therefore dead code — see test docstring FINDING.)
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                document_portal.get_upload_context()

    def test_get_upload_context_lists_only_own_board_chapter(self):
        email, chapter_name, _vol = self._make_board_member("ctx.owner")
        # A second, unrelated chapter the user is NOT a board member of.
        other_chapter = self.create_test_chapter()

        with self.as_user(email):
            result = document_portal.get_upload_context()
        payload = _payload(result)

        self.assertTrue(payload["success"])
        chapter_names = [c["name"] for c in payload["organizations"]["chapters"]]
        self.assertIn(chapter_name, chapter_names)
        # IDOR: must not surface a chapter the user has no board seat on.
        self.assertNotIn(other_chapter.name, chapter_names)

    # ==================================================================
    # can_upload_to_organization
    # ==================================================================

    def test_can_upload_guest_rejected_by_framework(self):
        # The body intends to return {success: True, can_upload: False} for
        # Guest, but @standard_api denies Guest first with PermissionError.
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                document_portal.can_upload_to_organization("Chapter", "anything")

    def test_can_upload_true_for_board_member(self):
        email, chapter_name, _vol = self._make_board_member("upl.board")
        with self.as_user(email):
            result = document_portal.can_upload_to_organization("Chapter", chapter_name)
        payload = _payload(result)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["can_upload"])

    def test_can_upload_false_for_nonmember_chapter(self):
        email, _own_chapter, _vol = self._make_board_member("upl.outsider")
        other_chapter = self.create_test_chapter()
        with self.as_user(email):
            result = document_portal.can_upload_to_organization("Chapter", other_chapter.name)
        payload = _payload(result)
        self.assertTrue(payload["success"])
        # IDOR: not a board member of other_chapter -> cannot upload.
        self.assertFalse(payload["can_upload"])

    def test_can_upload_false_for_inactive_board_seat(self):
        # Start from a proven-good active board member, then deactivate the seat
        # in the DB and confirm upload permission is revoked.
        email, chapter_name, volunteer = self._make_board_member("upl.inactive")
        # Sanity: active seat grants upload.
        with self.as_user(email):
            active = _payload(document_portal.can_upload_to_organization("Chapter", chapter_name))
        self.assertTrue(active["can_upload"])

        # Deactivate the board seat.
        frappe.db.set_value(
            "Chapter Board Member",
            {"parent": chapter_name, "volunteer": volunteer.name},
            "is_active",
            0,
        )

        with self.as_user(email):
            result = document_portal.can_upload_to_organization("Chapter", chapter_name)
        payload = _payload(result)
        # is_active=0 -> _is_chapter_board_member returns False.
        self.assertFalse(payload["can_upload"])

    # ==================================================================
    # upload_document
    # ==================================================================

    def test_upload_guest_rejected(self):
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                document_portal.upload_document(
                    organization_type="Chapter",
                    organization_name="x",
                    document_name="d",
                    document_type="Policy",
                    file_name="a.txt",
                    file_content=self._b64_text(),
                )

    def test_upload_invalid_organization_type_rejected(self):
        email, _chapter, _vol = self._make_board_member("upl.badtype")
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Hacker",
                organization_name="x",
                document_name="d",
                document_type="Policy",
                file_name="a.pdf",
                file_content=self._b64_text(),
            )
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "invalid_organization_type")

    def test_upload_missing_required_fields_rejected(self):
        email, chapter_name, _vol = self._make_board_member("upl.missing")
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Chapter",
                organization_name=chapter_name,
                document_name="",  # missing
                document_type="Policy",
                file_name="a.pdf",
                file_content=self._b64_text(),
            )
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "missing_required_fields")

    def test_upload_overlong_document_name_rejected(self):
        email, chapter_name, _vol = self._make_board_member("upl.long")
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Chapter",
                organization_name=chapter_name,
                document_name="x" * 300,
                document_type="Policy",
                file_name="a.pdf",
                file_content=self._b64_text(),
            )
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "document_name_too_long")

    def test_upload_denied_for_non_board_member_of_target(self):
        # SECURITY: a board member of chapter A must not be able to upload to
        # chapter B. The service re-validates can_upload_to (defense in depth).
        email, _own_chapter, _vol = self._make_board_member("upl.crossorg")
        other_chapter = self.create_test_chapter()
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Chapter",
                organization_name=other_chapter.name,
                document_name="Sneaky Doc",
                document_type="Policy",
                file_name="a.pdf",
                file_content=self._b64_text(),
            )
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "permission_denied")
        # And nothing was created.
        self.assertFalse(
            frappe.db.exists(
                "Organization Document", {"chapter": other_chapter.name, "document_name": "Sneaky Doc"}
            )
        )

    def test_upload_happy_path_creates_document(self):
        email, chapter_name, _vol = self._make_board_member("upl.happy")
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Chapter",
                organization_name=chapter_name,
                document_name="Annual Policy 2024",
                document_type="Policy",
                file_name="policy.txt",
                file_content=self._b64_text(),
                content_type="text/plain",
            )
        payload = _payload(result)
        self.assertTrue(payload["success"], msg=f"upload failed: {payload}")
        doc_name = payload["document_name"]
        self.track_doc("Organization Document", doc_name)
        # Track the created File for cleanup.
        file_url = payload["file_url"]
        file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if file_name:
            self.track_doc("File", file_name)

        # Assert the persisted record matches what was requested.
        org_doc = frappe.get_doc("Organization Document", doc_name)
        self.assertEqual(org_doc.chapter, chapter_name)
        self.assertEqual(org_doc.document_type, "Policy")
        self.assertEqual(org_doc.uploaded_by, email)
        # SECURITY: uploaded file must be private.
        self.assertEqual(frappe.db.get_value("File", file_name, "is_private"), 1)

    def test_upload_rejects_disallowed_extension(self):
        email, chapter_name, _vol = self._make_board_member("upl.exe")
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Chapter",
                organization_name=chapter_name,
                document_name="Malware",
                document_type="Policy",
                file_name="evil.exe",
                file_content=self._b64_text(),
            )
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "invalid_file_type")

    def test_upload_rejects_mime_extension_mismatch(self):
        # SECURITY: .pdf extension with a spoofed image MIME must be rejected.
        email, chapter_name, _vol = self._make_board_member("upl.spoof")
        with self.as_user(email):
            result = document_portal.upload_document(
                organization_type="Chapter",
                organization_name=chapter_name,
                document_name="Spoofed",
                document_type="Policy",
                file_name="doc.pdf",
                file_content=self._b64_text(),
                content_type="image/png",
            )
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "mime_extension_mismatch")

    # ==================================================================
    # get_organization_documents
    # ==================================================================

    def test_get_org_documents_guest_rejected(self):
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                document_portal.get_organization_documents("Chapter", "x")

    def test_get_org_documents_invalid_type_rejected(self):
        email, _chapter, _vol = self._make_board_member("getorg.badtype")
        with self.as_user(email):
            result = document_portal.get_organization_documents("Bogus", "x")
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "invalid_organization_type")

    def test_get_org_documents_returns_seeded_docs_for_board_member(self):
        email, chapter_name, _vol = self._make_board_member("getorg.owner")
        doc_name, _url = self._persist_org_document(chapter_name, "Board Minutes 2024", "Meeting Minutes")

        with self.as_user(email):
            result = document_portal.get_organization_documents("Chapter", chapter_name)
        payload = _payload(result)
        self.assertTrue(payload["success"], msg=f"{payload}")
        self.assertEqual(payload["total_count"], 1)
        # Document is grouped under its category.
        self.assertIn("Meeting Minutes", payload["documents"])

    def test_get_org_documents_denied_for_nonmember(self):
        # SECURITY / IDOR: a board member of chapter A passing chapter B's name
        # must be denied — not handed B's document list.
        email, _own_chapter, _vol = self._make_board_member("getorg.idor")
        other_email, other_chapter, _ov = self._make_board_member("getorg.victim")
        self._persist_org_document(other_chapter, "Victim Secret Doc", "Policy")

        with self.as_user(email):
            result = document_portal.get_organization_documents("Chapter", other_chapter)
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "permission_denied")
        # The attacker must NOT receive the victim's documents.
        self.assertNotIn("documents", payload)

    # ==================================================================
    # get_browsable_documents
    # ==================================================================

    def test_browse_guest_rejected(self):
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                document_portal.get_browsable_documents()

    def test_browse_invalid_org_type_rejected(self):
        email, _chapter, _vol = self._make_board_member("browse.badtype")
        with self.as_user(email):
            result = document_portal.get_browsable_documents(org_type="Nope")
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "invalid_org_type")

    def test_browse_returns_only_accessible_org_documents(self):
        # Board member of own chapter sees own chapter docs; must NOT see the
        # documents of an unrelated chapter they have no membership in.
        email, my_chapter, vol = self._make_board_member("browse.scope")
        # The board member must also be a Chapter MEMBER for view scope; seed it.
        self._setup_chapter_member(my_chapter, email)
        my_doc, _u1 = self._persist_org_document(my_chapter, "My Browsable Doc", "Policy")

        other_email, other_chapter, _ov = self._make_board_member("browse.other")
        self._persist_org_document(other_chapter, "Other Chapter Doc", "Policy")

        with self.as_user(email):
            result = document_portal.get_browsable_documents()
        payload = _payload(result)
        self.assertTrue(payload["success"], msg=f"{payload}")
        returned_names = {d["name"] for d in payload["documents"]}
        self.assertIn(my_doc, returned_names)
        # IDOR: other chapter's document must not leak.
        other_doc_names = frappe.get_all(
            "Organization Document",
            filters={"chapter": other_chapter, "document_name": "Other Chapter Doc"},
            pluck="name",
        )
        for od in other_doc_names:
            self.assertNotIn(od, returned_names)

    def test_browse_specific_inaccessible_org_returns_empty(self):
        # Filtering by an organization the user cannot access yields an empty,
        # successful result (not the org's documents).
        email, _my_chapter, _vol = self._make_board_member("browse.filterdenied")
        other_email, other_chapter, _ov = self._make_board_member("browse.filtervictim")
        self._persist_org_document(other_chapter, "Hidden Doc", "Policy")

        with self.as_user(email):
            result = document_portal.get_browsable_documents(
                org_type="Chapter", organization=other_chapter
            )
        payload = _payload(result)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total_count"], 0)
        self.assertEqual(payload["documents"], [])

    def _setup_chapter_member(self, chapter_name, user_email):
        """Add the user's Member as an active Chapter Member (view scope).

        Idempotent: skips if the member is already a chapter member to avoid the
        Chapter validation "listed more than once as an active chapter member".
        """
        member_name = frappe.db.get_value("Member", {"user": user_email}, "name")
        if frappe.db.exists("Chapter Member", {"parent": chapter_name, "member": member_name}):
            return
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append(
            "members",
            {
                "member": member_name,
                "enabled": 1,
                "chapter_join_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        chapter.save()

    # ==================================================================
    # delete_document
    # ==================================================================

    def test_delete_guest_rejected(self):
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                document_portal.delete_document("DOC-Chapter-0001")

    def test_delete_missing_name_rejected(self):
        email, _chapter, _vol = self._make_board_member("del.missing")
        with self.as_user(email):
            result = document_portal.delete_document("")
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "missing_document_name")

    def test_delete_nonexistent_document_returns_not_found(self):
        email, _chapter, _vol = self._make_board_member("del.notfound")
        with self.as_user(email):
            result = document_portal.delete_document("DOC-Chapter-9999999")
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "not_found")

    def test_delete_denied_for_nonmember_of_owning_org(self):
        # SECURITY / IDOR: a board member of chapter A must not be able to delete
        # chapter B's document. The doc must survive.
        attacker_email, _a_chapter, _av = self._make_board_member("del.attacker")
        _victim_email, victim_chapter, _vv = self._make_board_member("del.victim")
        victim_doc, victim_url = self._persist_org_document(victim_chapter, "Protected Doc", "Policy")

        with self.as_user(attacker_email):
            result = document_portal.delete_document(victim_doc)
        payload = _payload(result)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "permission_denied")
        # Document and its file must still exist.
        self.assertTrue(frappe.db.exists("Organization Document", victim_doc))
        self.assertTrue(frappe.db.exists("File", {"file_url": victim_url}))

    def test_delete_happy_path_removes_document(self):
        email, chapter_name, _vol = self._make_board_member("del.happy")
        doc_name, file_url = self._persist_org_document(chapter_name, "Disposable Doc", "Policy")

        # Setting the Organization Document's `document_file` Attach field causes
        # Frappe's attach_files_to_document hook to create a SECOND File record
        # (attached to the Organization Document) pointing at the same file_url,
        # in addition to the one save_organization_document attached to the
        # Chapter. So there are two File rows for this url before deletion. The
        # production upload_document flow sets document_file identically, so this
        # duplication exists in real uploads too.
        files_before = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
        self.assertGreaterEqual(len(files_before), 2)

        with self.as_user(email):
            result = document_portal.delete_document(doc_name)
        payload = _payload(result)
        self.assertTrue(payload["success"], msg=f"{payload}")
        # Primary contract: the Organization Document is gone.
        self.assertFalse(frappe.db.exists("Organization Document", doc_name))

        # delete_document iterates EVERY File row matching the document's
        # file_url (frappe.get_all(..., pluck="name")) and deletes each one, so
        # both File records (the one save_organization_document attached to the
        # Chapter and the one Frappe's Attach-field hook auto-created on
        # document_file) are removed. No orphaned File row may survive.
        files_after = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
        self.assertEqual(
            len(files_after),
            0,
            msg="delete_document must remove every File row for the document's file_url",
        )
