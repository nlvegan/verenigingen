# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import contextlib
import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import _UserSwitcher


class TestChapterJoinRequest(EnhancedTestCase):
    def setUp(self):
        """Set up test data using enhanced test factory"""
        super().setUp()

        # Set Administrator context for test setup
        frappe.set_user("Administrator")

        # Create test member with realistic data
        self.test_member = self.create_test_member(
            first_name="Test", last_name="Member", birth_date="1990-01-01", status="Active"
        )

        # Unique per test: ensure_test_chapter() is a get-or-create keyed on the
        # document name, and this class both appends roster rows and flips the
        # chapter's status. "Test Chapter" was claimed by four files and
        # "Inactive Chapter" by two, so whichever ran first owned the row (#533).
        # Every use below goes through .name, so there is no literal to break.
        self.test_chapter = self.factory.ensure_test_chapter(
            f"Test Chapter {frappe.generate_hash(length=6)}",
            {
                "status": "Active",
                "published": 1,
                "introduction": "Test chapter for chapter join request testing",
                "contact_email": self.factory.generate_test_email("chapter"),
            },
        )

        # Create another member for multi-member tests
        self.test_member2 = self.create_test_member(
            first_name="Second", last_name="Member", birth_date="1985-01-01", status="Active"
        )

        # Create suspended member for status validation tests
        self.suspended_member = self.create_test_member(
            first_name="Suspended", last_name="Member", birth_date="1995-01-01", status="Suspended"
        )

        # Create inactive chapter for status validation tests
        self.inactive_chapter = self.factory.ensure_test_chapter(
            f"Inactive Chapter {frappe.generate_hash(length=6)}",
            {
                "status": "Inactive",
                "published": 0,
                "introduction": "Inactive test chapter",
                "contact_email": self.factory.generate_test_email("inactive_chapter"),
            },
        )

    def test_field_validation(self):
        """Test that field references are validated properly"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Test introduction for field validation",
            }
        )

        # This should not throw an error if all fields exist
        try:
            join_request.validate()
        except Exception as e:
            self.fail(f"Field validation failed: {str(e)}")

    def test_join_request_creation(self):
        """Test creating a chapter join request"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Test introduction for joining chapter with realistic data",
            }
        )

        join_request.insert()
        self.assertEqual(join_request.status, "Pending")
        self.assertEqual(join_request.request_date, today())
        self.assertEqual(join_request.member_name, self.test_member.full_name)
        self.assertEqual(join_request.member_email, self.test_member.email)

    def test_duplicate_request_validation(self):
        """Test that duplicate requests are prevented"""
        # Create first request
        join_request1 = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "First request with realistic test data",
            }
        )
        join_request1.insert()
        join_request1.submit()

        # Try to create duplicate request
        join_request2 = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Duplicate request - should be prevented",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request2.insert()

    def test_permission_validation(self):
        """Test chapter approval permission validation"""
        # TODO: This test requires proper security framework authentication
        # The has_chapter_approval_permission() function requires authentication
        # Error: "Authentication required for this endpoint"
        # Needs investigation of proper test user role setup for API security framework
        self.skipTest("API security framework authentication needs proper test user role configuration")

        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            has_chapter_approval_permission,
        )

        # Test with Administrator (should have permission)
        frappe.set_user("Administrator")
        self.assertTrue(has_chapter_approval_permission(self.test_chapter.name))

        # Test with Guest (should not have permission)
        frappe.set_user("Guest")
        self.assertFalse(has_chapter_approval_permission(self.test_chapter.name))

    def test_transaction_rollback(self):
        """Test that failed approvals don't leave partial data"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Test for transaction rollback with realistic data",
            }
        )
        join_request.insert()
        join_request.submit()

        # Count existing chapter members before approval
        initial_count = frappe.db.count(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member.name}
        )

        # Try to approve with invalid chapter (should fail and rollback)
        try:
            join_request.chapter = "Invalid Chapter"
            join_request.approve_request()
        except:
            pass  # Expected to fail

        # Verify no partial data was created
        final_count = frappe.db.count(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member.name}
        )

        self.assertEqual(initial_count, final_count, "Transaction rollback failed - partial data created")

    def _pending_request_that_cannot_be_assigned(self, member):
        """A submitted Pending request whose approval's assignment step must fail (#1632).

        Real writers only (no set_value): the member is put in the chapter, then
        disable_chapter_memberships_safe disables the row, a request is submitted while the
        member is still Active, and suspend_member_safe suspends the member. Approval then
        reaches assign_member_to_chapter, which refuses to re-enable a suspended member's row.
        """
        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
            suspend_member_safe,
        )

        chapter = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter.append(
            "members",
            {"member": member.name, "status": "Active", "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()
        disable_chapter_memberships_safe(member.name, today(), "test leave")
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Rejoin while suspended",
            }
        )
        request.insert()
        request.submit()
        suspend_member_safe(member.name, "test suspension", suspend_user=False, suspend_teams=False)
        return request

    def _chapter_member_rows(self, member):
        return frappe.get_all(
            "Chapter Member",
            filters={"parent": self.test_chapter.name, "member": member.name},
            fields=["enabled", "status"],
        )

    def test_failed_assignment_leaves_request_pending_via_wrapper(self):
        """#1632: the wrapper swallows the failure, so the Approved save must not outlive it."""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            approve_join_request,
        )

        self.expectErrorLog("Failed to approve join request")
        request = self._pending_request_that_cannot_be_assigned(self.test_member)

        result = approve_join_request(request.name)

        self.assertFalse(result["success"])
        self.assertEqual(frappe.db.get_value("Chapter Join Request", request.name, "status"), "Pending")
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member)], [0])

    def test_failed_assignment_raises_and_resets_in_memory_status(self):
        request = self._pending_request_that_cannot_be_assigned(self.test_member)
        doc = frappe.get_doc("Chapter Join Request", request.name)

        with self.assertRaises(frappe.ValidationError):
            doc.approve_request()

        self.assertEqual(doc.status, "Pending")
        self.assertIsNone(frappe.db.get_value("Chapter Join Request", request.name, "reviewed_by"))

    def test_bulk_approve_one_failure_keeps_the_successes(self):
        """#1632: in bulk, a failing request is undone alone; its siblings stay Approved."""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        bad = self._pending_request_that_cannot_be_assigned(self.test_member)
        good = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Healthy request",
            }
        )
        good.insert()
        good.submit()

        bulk_approve_requests([good.name, bad.name])
        self._assert_good_approved_bad_pending(good, bad)

    def _assert_good_approved_bad_pending(self, good, bad):
        self.assertEqual(frappe.db.get_value("Chapter Join Request", good.name, "status"), "Approved")
        self.assertTrue(frappe.db.get_value("Chapter Join Request", good.name, "reviewed_by"))
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member2)], [1])
        self.assertEqual(frappe.db.get_value("Chapter Join Request", bad.name, "status"), "Pending")
        self.assertIsNone(frappe.db.get_value("Chapter Join Request", bad.name, "reviewed_by"))
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member)], [0])

    def test_bulk_approve_failing_request_first_keeps_the_successes(self):
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        bad = self._pending_request_that_cannot_be_assigned(self.test_member)
        good = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Healthy request",
            }
        )
        good.insert()
        good.submit()

        bulk_approve_requests([bad.name, good.name])
        self._assert_good_approved_bad_pending(good, bad)

    def test_lock_timeout_during_assignment_leaves_request_pending(self):
        """#1632 review F1: a 1205 keeps the transaction live, so it must be rolled back too."""
        from unittest.mock import patch

        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            approve_join_request,
        )

        self.expectErrorLog("Failed to approve join request")
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Timeout request",
            }
        )
        request.insert()
        request.submit()

        target = (
            "verenigingen.services.chapter.chapter_membership_manager."
            "ChapterMembershipManager.assign_member_to_chapter"
        )
        # Mock justified: fault injection of a DB error no fixture can produce; the assertions
        # exercise approve_request's rollback, not the stub.
        with patch(target, side_effect=frappe.QueryTimeoutError("1205")):
            result = approve_join_request(request.name)

        self.assertFalse(result["success"])
        self.assertEqual(frappe.db.get_value("Chapter Join Request", request.name, "status"), "Pending")

    def test_member_status_validation(self):
        """Test that only active members can create join requests"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.suspended_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request from suspended member - should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request.insert()

    def test_chapter_status_validation(self):
        """Test that requests can only be made to active chapters"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.inactive_chapter.name,
                "introduction": "Request to inactive chapter - should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request.insert()

    def test_approval_workflow_basic(self):
        """Test basic approval workflow without complex transaction management"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request for approval workflow testing",
            }
        )
        join_request.insert()
        join_request.submit()

        # Approval goes through approve_request: a bare status edit is refused (#1704)
        join_request.approve_request(approved_by="Administrator", notes="Approved for testing purposes")

        # Verify basic approval fields
        self.assertEqual(join_request.status, "Approved")
        self.assertEqual(join_request.reviewed_by, "Administrator")
        self.assertEqual(join_request.review_notes, "Approved for testing purposes")

    def test_rejection_workflow(self):
        """Test rejection workflow"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request for rejection workflow testing",
            }
        )
        join_request.insert()
        join_request.submit()

        # Reject the request
        result = join_request.reject_request(
            rejected_by="Administrator", reason="Not suitable for testing purposes"
        )

        # Verify rejection was successful
        self.assertTrue(result.get("success"))
        self.assertEqual(join_request.status, "Rejected")
        self.assertEqual(join_request.reviewed_by, "Administrator")
        self.assertEqual(join_request.rejection_reason, "Not suitable for testing purposes")

        # Verify no chapter membership was created
        chapter_member = frappe.db.exists(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member2.name}
        )
        self.assertIsNone(chapter_member, "No chapter membership should be created upon rejection")

    def test_already_member_validation(self):
        """Test that existing members cannot create duplicate requests"""
        # First, manually add member to chapter
        chapter = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter.reload()  # Ensure fresh data

        # Ensure Department sync is up to date (may have been created by previous test)
        chapter._sync_department()

        # Clear any members from previous tests (no per-method rollback)
        chapter.members = []

        # Verify member exists before adding
        if not frappe.db.exists("Member", self.test_member.name):
            self.fail(f"Test member {self.test_member.name} does not exist")

        chapter.append(
            "members",
            {"member": self.test_member.name, "status": "Active", "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()

        # Try to create join request
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request from existing member - should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request.insert()

    def test_api_integration(self):
        """Test the chapter join API integration"""
        # TODO: This test requires proper security framework authentication
        # The API requires medium security level but test user has only Guest role
        # Error: "Access denied. Required security level: medium. Your access: Individual roles: All, Guest"
        # Needs investigation of proper test user role setup for API security framework
        self.skipTest("API security framework authentication needs proper test user role configuration")

    def test_edge_case_long_introduction(self):
        """Test edge case with very long introduction text"""
        long_introduction = (
            "This is a very long introduction text that contains many words and sentences to test how the system handles long text inputs. "
            * 50
        )

        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": long_introduction,
            }
        )

        # Should handle long text without issues
        join_request.insert()
        self.assertEqual(join_request.status, "Pending")

    def test_edge_case_special_characters(self):
        """Test edge case with special characters in introduction"""
        special_introduction = (
            "Mijn introductie bevat speciale tekens: ëïö, àáâã, ñ, ç, ü! @#$%^&*()_+-={}[]|\\:;\"'<>,.?/"
        )

        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": special_introduction,
            }
        )

        # Should handle special characters without issues
        join_request.insert()
        self.assertEqual(join_request.introduction, special_introduction)

    # ----- #1704: status is writable only through approve/reject ---------------------------

    WRITE_ROLES = (
        "Verenigingen Administrator",
        "Verenigingen Staff",
        "Verenigingen Member",
        "Verenigingen Chapter Board Member",
    )

    def _submitted_request(self, member=None):
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": (member or self.test_member).name,
                "chapter": self.test_chapter.name,
                "introduction": "Status guard request",
            }
        )
        request.insert()
        request.submit()
        return request

    def _role_user_email(self, role):
        """Email of a fresh user holding exactly *role* (via the shared factory)."""
        return self.factory.create_user_with_roles(roles=[role]).email

    @contextlib.contextmanager
    def _as_user_with_role(self, role):
        frappe.set_user(self._role_user_email(role))
        try:
            yield
        finally:
            frappe.set_user("Administrator")

    def _member_only_user(self, role="Verenigingen Member", extra_roles=()):
        """(email, Member) for a fresh user holding exactly *role*, linked to its own Active member.

        Probe shortcut: Member.user is set with db.set_value, standing in for the account-creation
        flow; identity is read from that field only (#1546), so the link is the thing under test.
        """
        email = self.factory.create_user_with_roles(roles=[role, *extra_roles]).email
        member = self.create_test_member(status="Active")
        frappe.db.set_value("Member", member.name, "user", email, update_modified=False)
        return email, member

    def _status_in_db(self, request):
        return frappe.db.get_value("Chapter Join Request", request.name, "status")

    def test_writer_roles_can_open_a_write_on_the_doc(self):
        """Control for the guard tests below: each role really passes the doctype write check,
        and a role outside the permission table does not. Without this, a refusal below could
        be the permission layer rather than the status guard."""
        request = self._submitted_request()
        for role in self.WRITE_ROLES:
            with self.subTest(role=role):
                self.assertTrue(
                    frappe.has_permission(
                        "Chapter Join Request", "write", doc=request, user=self._role_user_email(role)
                    )
                )
        self.assertFalse(
            frappe.has_permission(
                "Chapter Join Request", "write", doc=request, user=self._role_user_email("System Manager")
            )
        )

    def test_a_form_save_cannot_set_approved_for_any_writer_role(self):
        """#1704: the form/REST save path (get_doc + set + save, permission-checked) must not
        move status by itself. No Chapter Member row exists, so Approved here would be a lie."""
        for role in self.WRITE_ROLES:
            with self.subTest(role=role):
                request = self._submitted_request(self.create_test_member(status="Active"))
                with self._as_user_with_role(role):
                    doc = frappe.get_doc("Chapter Join Request", request.name)
                    doc.status = "Approved"
                    with self.assertRaises(frappe.ValidationError) as ctx:
                        doc.save()
                self.assertIn("approving or rejecting", str(ctx.exception))
                self.assertEqual(self._status_in_db(request), "Pending")

    def test_rest_set_value_cannot_set_approved_or_rejected(self):
        """#1704: the frappe.client.set_value channel is the REST PUT shape."""
        from frappe.client import set_value

        request = self._submitted_request()
        with self._as_user_with_role("Verenigingen Member"):
            for target in ("Approved", "Rejected"):
                with self.assertRaises(frappe.ValidationError):
                    set_value("Chapter Join Request", request.name, "status", target)
        self.assertEqual(self._status_in_db(request), "Pending")

    def test_a_new_request_cannot_be_inserted_already_approved(self):
        """#1704: a REST insert with status Approved is the same harm without needing an edit."""
        user, own_member = self._member_only_user()
        with _UserSwitcher(user):
            doc = frappe.get_doc(
                {
                    "doctype": "Chapter Join Request",
                    "member": own_member.name,
                    "chapter": self.test_chapter.name,
                    "introduction": "Born approved",
                    "status": "Approved",
                }
            )
            with self.assertRaises(frappe.ValidationError):
                doc.insert()

    def test_a_post_submit_save_that_changes_no_review_field_still_works(self):
        """Control: the guards key on a CHANGE to a review field, not on any post-submit save.
        (Replaces a control that saved review_notes by hand; #1745 makes that a refusal, as the
        notes are audit data - the premise "a bare notes edit is fine" was the defect.)"""
        request = self._submitted_request()
        doc = frappe.get_doc("Chapter Join Request", request.name)
        doc.save()
        self.assertEqual(self._status_in_db(request), "Pending")

    # ----- #1745: the review audit trail is writable only through approve/reject ----------

    def test_saving_an_already_reviewed_request_unchanged_still_works(self):
        """Control with a real row for the wrong behaviour: the review fields are POPULATED here,
        so a guard that refuses "any review field set" (instead of "changed") would fire."""
        request = self._submitted_request()
        request.reject_request(reason="no")
        before = self._review_fields_in_db(request)
        self.assertTrue(all(before[:2]) and before[3])
        doc = frappe.get_doc("Chapter Join Request", request.name)
        doc.save()
        self.assertEqual(self._review_fields_in_db(request), before)

    REVIEW_AUDIT_FIELDS = ("reviewed_by", "review_date", "review_notes", "rejection_reason")

    def _review_fields_in_db(self, request):
        return frappe.db.get_value("Chapter Join Request", request.name, list(self.REVIEW_AUDIT_FIELDS))

    def _forged_value(self, field):
        return {"reviewed_by": "Guest", "review_date": "2001-01-01"}.get(field, "forged")

    def test_a_form_save_cannot_write_a_review_field_for_any_writer_role(self):
        """#1745: get_doc + set + save, permission-checked, on a Pending AND on a reviewed request."""
        pending = self._submitted_request()
        reviewed = self._submitted_request(self.test_member2)
        reviewed.approve_request(notes="genuine note")
        for request in (pending, reviewed):
            before = self._review_fields_in_db(request)
            for role in self.WRITE_ROLES:
                for field in self.REVIEW_AUDIT_FIELDS:
                    with self.subTest(request=request.name, role=role, field=field):
                        with self._as_user_with_role(role):
                            doc = frappe.get_doc("Chapter Join Request", request.name)
                            doc.set(field, self._forged_value(field))
                            with self.assertRaises(frappe.ValidationError) as ctx:
                                doc.save()
                        self.assertIn("approving or rejecting", str(ctx.exception))
                        self.assertEqual(self._review_fields_in_db(request), before)

    def test_an_empty_string_for_a_null_review_field_is_not_a_review_change(self):
        """#1745 review F1: a form round-trip sends "" for a field the DB holds as NULL. A rejected
        request has review_notes NULL (only rejection_reason is written), so saving "" there is
        not a change and must not be refused."""
        request = self._submitted_request()
        request.reject_request(reason="no")
        self.assertIsNone(self._review_fields_in_db(request)[2])  # review_notes really NULL
        for role in self.WRITE_ROLES:
            with self.subTest(role=role):
                with self._as_user_with_role(role):
                    doc = frappe.get_doc("Chapter Join Request", request.name)
                    doc.review_notes = ""
                    doc.save()

    def test_rest_set_value_cannot_write_a_review_field(self):
        """#1745: the frappe.client.set_value channel is the REST PUT shape."""
        from frappe.client import set_value

        request = self._submitted_request()
        before = self._review_fields_in_db(request)
        with self._as_user_with_role("Verenigingen Staff"):
            for field in self.REVIEW_AUDIT_FIELDS:
                with self.assertRaises(frappe.ValidationError):
                    set_value("Chapter Join Request", request.name, field, self._forged_value(field))
        self.assertEqual(self._review_fields_in_db(request), before)

    def test_a_new_request_cannot_be_inserted_with_a_review_trail(self):
        """#1745: a REST insert can write review fields as easily as an edit can."""
        for field in self.REVIEW_AUDIT_FIELDS:
            with self.subTest(field=field):
                # The caller's OWN member, so the #1786 ownership refusal cannot be what raises.
                user, own_member = self._member_only_user()
                with _UserSwitcher(user):
                    doc = frappe.get_doc(
                        {
                            "doctype": "Chapter Join Request",
                            "member": own_member.name,
                            "chapter": self.test_chapter.name,
                            "introduction": "Born reviewed",
                            field: self._forged_value(field),
                        }
                    )
                    with self.assertRaises(frappe.ValidationError):
                        doc.insert()

    def test_approve_and_reject_still_write_the_review_trail(self):
        """The legitimate writers, through the real controller methods as a Staff user."""
        to_approve = self._submitted_request(self.test_member)
        to_reject = self._submitted_request(self.test_member2)
        with self._as_user_with_role("Verenigingen Staff"):
            reviewer = frappe.session.user
            frappe.get_doc("Chapter Join Request", to_approve.name).approve_request(notes="welcome")
            frappe.get_doc("Chapter Join Request", to_reject.name).reject_request(reason="not eligible")
        approved = frappe.db.get_value(
            "Chapter Join Request",
            to_approve.name,
            ["reviewed_by", "review_date", "review_notes"],
            as_dict=True,
        )
        self.assertEqual(
            (approved.reviewed_by, str(approved.review_date), approved.review_notes),
            (reviewer, today(), "welcome"),
        )
        rejected = frappe.db.get_value(
            "Chapter Join Request",
            to_reject.name,
            ["reviewed_by", "review_date", "rejection_reason"],
            as_dict=True,
        )
        self.assertEqual(
            (rejected.reviewed_by, str(rejected.review_date), rejected.rejection_reason),
            (reviewer, today(), "not eligible"),
        )

    def test_an_amendment_does_not_inherit_the_cancelled_requests_review_trail(self):
        """#1745: amend copies the cancelled request, review fields included; the amendment needs a
        fresh review, as status already does (#1704). Without clearing, the new insert's blank-
        trail rule would refuse every amendment of a reviewed request."""
        request = self._submitted_request()
        request.reject_request(reason="first review")  # (an approval would make them a member)
        request.reload()
        self.assertTrue(request.rejection_reason and request.reviewed_by and request.review_date)
        request.cancel()
        amended = frappe.copy_doc(frappe.get_doc("Chapter Join Request", request.name))
        amended.amended_from = request.name
        amended.docstatus = 0  # what the Amend button does; copy_doc keeps the cancelled 2
        amended.insert()
        self.assertEqual(
            [amended.get(f) for f in self.REVIEW_AUDIT_FIELDS], [None] * len(self.REVIEW_AUDIT_FIELDS)
        )

    def test_approve_and_reject_still_move_status_for_a_non_admin_reviewer(self):
        """The legitimate paths, through the real controller methods as a Staff user. (The
        whitelisted wrappers need a security role profile a bare-role test user lacks.)"""
        to_approve = self._submitted_request(self.test_member)
        to_reject = self._submitted_request(self.test_member2)
        with self._as_user_with_role("Verenigingen Staff"):
            frappe.get_doc("Chapter Join Request", to_approve.name).approve_request()
            frappe.get_doc("Chapter Join Request", to_reject.name).reject_request(reason="no")
        self.assertEqual(self._status_in_db(to_approve), "Approved")
        self.assertEqual(self._status_in_db(to_reject), "Rejected")
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member)], [1])

    # ----- #1703: a destroyed transaction in bulk approval ---------------------------------

    def _deadlock_on_assign_for(self, member_name, below_assign=False):
        """Context manager: assign_member_to_chapter for *member_name* destroys the open
        savepoint (as a real 1213 does server-side: the rollback itself cannot be performed in
        a test without taking the fixtures) and raises QueryDeadlockError; others run for real.
        With below_assign the fault is injected in MemberManager.add_member, beneath the
        `except Exception` in assign_member_to_chapter that turns it into a failure dict, as a
        real deadlock in the roster write arrives."""
        from contextlib import contextmanager
        from unittest.mock import patch

        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
        from verenigingen.verenigingen.doctype.chapter.managers.member_manager import MemberManager

        real_assign = ChapterMembershipManager.assign_member_to_chapter
        real_add_member = MemberManager.add_member
        savepoints = []
        real_savepoint = frappe.local.db.savepoint

        def recording_savepoint(name):
            savepoints.append(name)
            return real_savepoint(name)

        def assign(member_id, *args, **kwargs):
            if member_id != member_name:
                return real_assign(member_id, *args, **kwargs)
            frappe.db.sql(f"RELEASE SAVEPOINT {savepoints[-1]}")
            raise frappe.QueryDeadlockError("1213")

        def add_member(manager, member_id, *args, **kwargs):
            if member_id != member_name:
                return real_add_member(manager, member_id, *args, **kwargs)
            frappe.db.sql(f"RELEASE SAVEPOINT {savepoints[-1]}")
            raise frappe.QueryDeadlockError("1213")

        target, replacement = (
            (MemberManager, dict(attribute="add_member", new=add_member))
            if below_assign
            else (ChapterMembershipManager, dict(attribute="assign_member_to_chapter", side_effect=assign))
        )

        @contextmanager
        def ctx():
            # Mock justified: fault injection of a DB deadlock no fixture can produce; the
            # assertions exercise bulk_approve_requests / approve_request, not the stub.
            with patch.object(frappe.local.db, "savepoint", recording_savepoint), patch.object(
                target, **replacement
            ):
                yield

        return ctx()

    def test_bulk_approve_stops_at_a_deadlock_and_does_not_claim_the_rolled_back(self):
        """#1703: after a 1213 the server has rolled the transaction back, so the earlier
        'approved' request is NOT applied and the loop must not carry on in a fresh one."""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        first = self._submitted_request(self.test_member)
        victim = self._submitted_request(self.test_member2)
        later = self._submitted_request(self.create_test_member(status="Active"))

        with self._deadlock_on_assign_for(self.test_member2.name):
            message = bulk_approve_requests([first.name, victim.name, later.name])

        self.assertNotIn("Successfully approved 1 request(s)", message)
        self.assertIn("Successfully approved 0 request(s)", message)
        self.assertIn(first.name, message.split("rolled back")[-1])
        self.assertIn(later.name, message.split("not processed")[-1])
        self.assertEqual(self._status_in_db(later), "Pending")

    def test_bulk_approve_stops_at_a_deadlock_swallowed_below_assign_member(self):
        """#1703 review F1: a real 1213 in the roster write is swallowed by
        assign_member_to_chapter into a failure dict, so approve_request sees a plain
        ValidationError. The vanished savepoint, not the exception type, must stop the loop."""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        self.expectErrorLog("Error in assign_member_to_chapter")
        first = self._submitted_request(self.test_member)
        victim = self._submitted_request(self.test_member2)
        later = self._submitted_request(self.create_test_member(status="Active"))

        with self._deadlock_on_assign_for(self.test_member2.name, below_assign=True):
            message = bulk_approve_requests([first.name, victim.name, later.name])

        self.assertIn("Successfully approved 0 request(s)", message)
        self.assertIn(first.name, message.split("rolled back")[-1])
        self.assertIn(later.name, message.split("not processed")[-1])
        self.assertEqual(self._status_in_db(later), "Pending")

    def test_a_swallowed_deadlock_resets_the_in_memory_doc_and_clears_the_flag(self):
        request = self._submitted_request(self.test_member)
        doc = frappe.get_doc("Chapter Join Request", request.name)
        self.expectErrorLog("Error in assign_member_to_chapter")

        with self._deadlock_on_assign_for(self.test_member.name, below_assign=True):
            with self.assertRaises(frappe.QueryDeadlockError):
                doc.approve_request()

        self.assertEqual(doc.status, "Pending")
        self.assertFalse(doc.flags.review_in_progress)

    def test_the_review_flag_does_not_outlive_approve_or_reject(self):
        """#1704 review F3: a doc object reused after a review must not stay privileged."""
        approved = frappe.get_doc("Chapter Join Request", self._submitted_request(self.test_member).name)
        approved.approve_request()
        self.assertFalse(approved.flags.review_in_progress)
        approved.status = "Rejected"
        with self.assertRaises(frappe.ValidationError):
            approved.save()

        rejected = frappe.get_doc("Chapter Join Request", self._submitted_request(self.test_member2).name)
        rejected.reject_request(reason="no")
        self.assertFalse(rejected.flags.review_in_progress)

    def test_bulk_approve_stops_at_a_lock_timeout_but_keeps_the_earlier_approvals(self):
        """#1703 control: a 1205 leaves the transaction and the earlier savepoints alive
        (innodb_rollback_on_timeout is OFF here), so only the deadlock path may call earlier
        approvals rolled back. The loop still stops."""
        from unittest.mock import patch

        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        first = self._submitted_request(self.test_member)
        victim = self._submitted_request(self.test_member2)
        later = self._submitted_request(self.create_test_member(status="Active"))
        real_assign = ChapterMembershipManager.assign_member_to_chapter

        def assign(member_id, *args, **kwargs):
            if member_id == self.test_member2.name:
                raise frappe.QueryTimeoutError("1205")
            return real_assign(member_id, *args, **kwargs)

        # Mock justified: fault injection of a lock-wait timeout no fixture can produce.
        with patch.object(ChapterMembershipManager, "assign_member_to_chapter", side_effect=assign):
            message = bulk_approve_requests([first.name, victim.name, later.name])

        self.assertIn("Successfully approved 1 request(s)", message)
        self.assertNotIn("rolled back", message)
        self.assertIn(later.name, message.split("not processed")[-1])
        self.assertEqual(self._status_in_db(first), "Approved")
        self.assertEqual(self._status_in_db(victim), "Pending")
        self.assertEqual(self._status_in_db(later), "Pending")

    def test_approve_request_resets_the_in_memory_doc_after_a_deadlock(self):
        """#1703: on the deadlock path there is no savepoint to roll back to, so the doc used
        to keep status Approved in memory."""
        request = self._submitted_request(self.test_member)
        doc = frappe.get_doc("Chapter Join Request", request.name)

        with self._deadlock_on_assign_for(self.test_member.name):
            with self.assertRaises(frappe.QueryDeadlockError):
                doc.approve_request()

        self.assertEqual(doc.status, "Pending")
        self.assertFalse(doc.reviewed_by)

    # ----- #1786: the request must name the caller's own member ----------------------------

    def _cjr_values(self, member_name, introduction="Ownership"):
        return {
            "doctype": "Chapter Join Request",
            "member": member_name,
            "chapter": self.test_chapter.name,
            "introduction": introduction,
        }

    def _victim(self):
        return self.create_test_member(status="Active")

    def _exists_for(self, member_name):
        return frappe.db.exists("Chapter Join Request", {"member": member_name})

    OWNERSHIP_MESSAGE = "own membership"

    def test_member_only_user_cannot_insert_a_request_naming_another_member(self):
        """#1786 through the doc insert path (REST POST /api/resource and the form both land here)."""
        user, _own = self._member_only_user()
        victim = self._victim()
        with _UserSwitcher(user):
            with self.assertRaises(frappe.PermissionError) as ctx:
                frappe.get_doc(self._cjr_values(victim.name)).insert()
        self.assertIn(self.OWNERSHIP_MESSAGE, str(ctx.exception))
        self.assertFalse(self._exists_for(victim.name))

    def test_member_only_user_cannot_insert_for_another_member_through_frappe_client(self):
        """#1786 through the whitelisted frappe.client.insert dispatch."""
        import json

        from frappe.client import insert

        user, _own = self._member_only_user()
        victim = self._victim()
        with _UserSwitcher(user):
            with self.assertRaises(frappe.PermissionError) as ctx:
                insert(json.dumps(self._cjr_values(victim.name)))
        self.assertIn(self.OWNERSHIP_MESSAGE, str(ctx.exception))
        self.assertFalse(self._exists_for(victim.name))

    def test_member_only_user_cannot_repoint_a_draft_request_at_another_member(self):
        """#1786 on change: a draft saved for the caller's own member then edited to another."""
        user, own = self._member_only_user()
        victim = self._victim()
        with _UserSwitcher(user):
            doc = frappe.get_doc(self._cjr_values(own.name)).insert()
            doc.member = victim.name
            with self.assertRaises(frappe.PermissionError) as ctx:
                doc.save()
        self.assertIn(self.OWNERSHIP_MESSAGE, str(ctx.exception))
        self.assertEqual(frappe.db.get_value("Chapter Join Request", doc.name, "member"), own.name)

    def test_refusal_discloses_nothing_about_the_named_member(self):
        """Existence-oracle channels for the FORBIDDEN id, by a caller without blanket Member access:
        the refusal must not carry the member's name or status in the exception or message_log, and
        must happen before validate_member_exists (an inactive victim is refused the same way).

        Measured limit, not fixed here: an UNKNOWN id is refused earlier by Frappe's own
        _validate_links ("Could not find Member"), before any controller hook runs, so the two ids
        are distinguishable on that one channel for every doctype with a Member link."""
        user, _own = self._member_only_user()
        active = self._victim()
        suspended = self.suspended_member
        messages = []
        with _UserSwitcher(user):
            for victim in (active, suspended):
                before = len(frappe.local.message_log)
                with self.assertRaises(frappe.PermissionError) as ctx:
                    frappe.get_doc(self._cjr_values(victim.name)).insert()
                messages.append(str(ctx.exception))
                raised = str(frappe.local.message_log[before:])
                del frappe.local.message_log[before:]
                self.assertNotIn(victim.name, raised)
                self.assertNotIn("Suspended", raised + str(ctx.exception))
                self.assertNotIn("active members", raised)
        self.assertEqual(messages[0], messages[1])
        self.assertIn(self.OWNERSHIP_MESSAGE, messages[0])

    def test_email_match_without_a_user_link_is_not_ownership(self):
        """#1546: identity is Member.user only. The caller has NO linked member (a linked one would
        be found first and hide the fallback); a member whose email equals the caller's, with its
        user link unset, is not the caller's member."""
        user = self._role_user_email("Verenigingen Member")
        lookalike = self.create_test_member(status="Active", email=user)
        self.assertEqual(frappe.db.get_value("Member", lookalike.name, "email"), user)
        self.assertFalse(frappe.db.get_value("Member", {"user": user}, "name"))
        with _UserSwitcher(user):
            with self.assertRaises(frappe.PermissionError) as ctx:
                frappe.get_doc(self._cjr_values(lookalike.name)).insert()
        self.assertIn(self.OWNERSHIP_MESSAGE, str(ctx.exception))

    def test_board_member_and_other_non_admin_roles_are_not_exempt(self):
        """#1101: only Roles.ADMIN_ROLES act for a member; a chapter board member does not."""
        victim = self._victim()
        # Board members are also members; the Board role alone cannot create a request at all.
        for extra in ("Verenigingen Chapter Board Member", None):
            with self.subTest(extra_role=extra):
                user, _own = self._member_only_user(extra_roles=(extra,) if extra else ())
                with _UserSwitcher(user):
                    with self.assertRaises(frappe.PermissionError) as ctx:
                        frappe.get_doc(self._cjr_values(victim.name)).insert()
                # The specific message: a doctype-level refusal would also be a PermissionError.
                self.assertIn(self.OWNERSHIP_MESSAGE, str(ctx.exception))

    def test_a_seated_chapter_board_member_cannot_file_for_another_member(self):
        """#1101/#1546: a REAL board seat (user -> member -> volunteer -> Chapter Board Member row on
        the target chapter) is not an exemption. Control: the seat exists, so a fix of the shape
        "allow when the caller manages the chapter" would let this through."""
        from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters

        board = self.create_test_board_member(self.test_chapter.name)
        # A board member is also a member, so the doctype's create right is held.
        frappe.get_doc("User", board.user).add_roles("Verenigingen Member")
        victim = self._victim()
        with _UserSwitcher(board.user):
            self.assertTrue(get_user_board_chapters(board.user))  # control: the seat is real
            with self.assertRaises(frappe.PermissionError) as ctx:
                frappe.get_doc(self._cjr_values(victim.name)).insert()
        self.assertIn(self.OWNERSHIP_MESSAGE, str(ctx.exception))
        self.assertFalse(self._exists_for(victim.name))

    def test_member_can_still_file_and_submit_a_request_for_their_own_member(self):
        """Opposite harm: the legitimate self-service insert and submit keep working."""
        user, own = self._member_only_user()
        with _UserSwitcher(user):
            doc = frappe.get_doc(self._cjr_values(own.name)).insert()
            doc.submit()
        self.assertEqual(frappe.db.get_value("Chapter Join Request", doc.name, "docstatus"), 1)

    def test_staff_and_administrator_can_still_file_for_a_member(self):
        """Opposite harm, #1101: staff acting for a member, and Administrator/system contexts."""
        for role in ("Verenigingen Staff", "Verenigingen Administrator"):
            with self.subTest(role=role):
                victim = self._victim()
                with _UserSwitcher(self._role_user_email(role)):
                    doc = frappe.get_doc(self._cjr_values(victim.name)).insert()
                    doc.submit()
                self.assertEqual(frappe.db.get_value("Chapter Join Request", doc.name, "member"), victim.name)
        admin_victim = self._victim()
        frappe.get_doc(self._cjr_values(admin_victim.name)).insert().submit()
        self.assertTrue(self._exists_for(admin_victim.name))

    def test_join_chapter_still_works_for_a_member_resolved_by_email_fallback(self):
        """join_chapter resolves the caller with the email fallback; the Member.user-only doctype
        check must not re-refuse a request the endpoint built for the caller's own member."""
        from verenigingen.api import chapter_join

        user = self._role_user_email("Verenigingen Member")
        member = self.create_test_member(status="Active", email=user)
        self.assertFalse(frappe.db.get_value("Member", member.name, "user"))
        with _UserSwitcher(user):
            result = chapter_join.join_chapter(chapter_name=self.test_chapter.name, introduction="Hello")
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(
            frappe.db.exists(
                "Chapter Join Request", {"member": member.name, "chapter": self.test_chapter.name}
            )
        )


if __name__ == "__main__":
    unittest.main()
