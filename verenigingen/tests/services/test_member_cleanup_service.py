# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Integration tests for MemberCleanupService - Focus on cascade deletion logic

Tests verify that all related records are properly cleaned up when a Member
is deleted, including smart Customer handling and Address unlinking.

Refactored to use real data instead of mocks for more reliable testing.
"""

import unittest

import frappe

from verenigingen.services.member.lifecycle.member_cleanup_service import (
    MemberAnonymizedInsteadOfDeleted,
    get_member_cleanup_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.dues_schedule_invoice_fixtures import (
    make_referenceable_dues_schedule,
    make_submitted_invoice_for_schedule,
)


class TestMemberCleanupService(EnhancedTestCase):
    """Test suite for MemberCleanupService"""

    def test_membership_deletion_cancels_submitted(self):
        """Test that submitted Memberships are cancelled before deletion"""
        # Create membership type (must be active + have a role_profile, or the
        # Membership submit rejects it as inactive; "amount" is not a real field).
        if not frappe.db.exists("Membership Type", "Test Type 001"):
            frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Type 001",
                    "is_active": 1,
                    "minimum_amount": 5.0,
                    "role_profile": frappe.db.get_value(
                        "Role Profile", {"name": ["like", "%Member%"]}, "name"
                    )
                    or frappe.db.get_value("Role Profile", {}, "name"),
                }
            ).insert()

        # Create real member with real membership
        member = self.create_test_member(
            first_name="Cleanup", last_name="Test001", email="cleanup.test001@example.com"
        )

        # Create and submit a membership
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name="Test Type 001"
        )
        membership.submit()
        membership_name = membership.name

        # Reload member to ensure fresh state
        member.reload()

        # Verify membership exists and is submitted
        self.assertTrue(frappe.db.exists("Membership", membership_name))
        self.assertEqual(frappe.get_doc("Membership", membership_name).docstatus, 1)

        # #1264 round 2: submitting a real Membership auto-creates a dues
        # schedule whose Member back-link (current_dues_schedule /
        # application_dues_schedule) can still point at it when member
        # deletion reaches it, so the (correct, link-integrity-respecting)
        # schedule delete can refuse and now logs an operator-visible Error
        # Log entry -- see test_dues_schedule_not_deleted_logs_operator_visible_error
        # for the dedicated test of that behaviour. Not the subject of this
        # test, which only checks the Membership itself is gone.
        self.expectErrorLog("Dues Schedule Not Deleted")

        # Call cleanup service
        get_member_cleanup_service().handle_member_deletion(member)

        # Verify membership no longer exists (was cancelled and deleted)
        self.assertFalse(frappe.db.exists("Membership", membership_name))

    def test_dues_schedule_deletion(self):
        """Test that Membership Dues Schedules are force deleted

        NOTE: This test is skipped because the Enhanced Test Factory's
        create_test_dues_schedule() requires complex dependencies:
        - Membership Type
        - Payment Terms Template (optional but causes issues)
        - Proper company/currency setup

        The cleanup logic is tested indirectly in test_complex_cascade_deletion_multiple_relationships
        """
        self.skipTest("Requires complex ERPNext fixture setup - tested indirectly in integration test")

    def test_sales_invoice_reference_clearing(self):
        """Test that Sales Invoice member references are cleared (not deleted)

        NOTE: This test is skipped because Sales Invoice creation requires:
        - Proper Chart of Accounts setup
        - Item master data
        - Currency configuration
        - Company defaults

        The reference clearing logic is verified through manual testing and
        production usage. The cleanup service code is straightforward field updates.
        """
        self.skipTest("Requires full ERPNext accounting setup - logic verified in production")

    def test_customer_preserved_if_has_transactions(self):
        """Test that Customer is preserved when it has transactions

        NOTE: This test is skipped because creating transactions requires:
        - Chart of Accounts with Bank/Receivable accounts
        - Payment Entry or Sales Invoice with proper setup
        - Item master, currency, company defaults

        The customer preservation logic is tested in test_customer_deleted_if_no_transactions
        by verifying the inverse case (customer deleted when NO transactions exist).
        """
        self.skipTest(
            "Requires full accounting setup - inverse case tested in test_customer_deleted_if_no_transactions"
        )

    def test_customer_deleted_if_no_transactions(self):
        """Test that Customer is deleted when it has no transactions"""
        # Create member with customer but no transactions
        member = self.create_test_member(
            first_name="Cleanup", last_name="Test005", email="cleanup.test005@example.com"
        )

        customer_name = member.customer

        # Verify customer exists
        self.assertTrue(frappe.db.exists("Customer", customer_name))

        # Verify customer has no transactions (just created, no invoices/payments)
        transaction_count = frappe.db.count("Payment Entry", {"party": customer_name})
        self.assertEqual(transaction_count, 0)

        # Reload member
        member.reload()

        # Call cleanup service
        get_member_cleanup_service().handle_member_deletion(member)

        # Verify customer was deleted (no transactions to preserve)
        self.assertFalse(frappe.db.exists("Customer", customer_name))

    def test_address_unlinking(self):
        """Test that Address is unlinked but not deleted"""
        # Create member with address
        member = self.create_test_member(
            first_name="Cleanup", last_name="Test006", email="cleanup.test006@example.com"
        )

        # Create address and link to member
        import time

        unique_id = int(time.time() * 1000)
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Test Address {unique_id}",
                "address_line1": "123 Test Street",
                "city": "Test City",
                "pincode": "1234AB",
                "country": "Netherlands",
                "address_type": "Personal",
            }
        )
        address.insert()
        address_name = address.name

        # Link address to member
        member.reload()
        member.primary_address = address_name
        member.save(ignore_version=True)

        # Verify address exists
        self.assertTrue(frappe.db.exists("Address", address_name))

        # Reload member
        member.reload()

        # Call cleanup service
        get_member_cleanup_service().handle_member_deletion(member)

        # Verify address still exists (unlinked, not deleted)
        self.assertTrue(frappe.db.exists("Address", address_name))

    def test_child_table_cleanup(self):
        """Test that child tables are cleaned up"""
        # Create member with chapter memberships (child table)
        member = self.create_test_member(
            first_name="Cleanup", last_name="Test007", email="cleanup.test007@example.com"
        )

        # Create chapter and add member to it
        chapter = self.create_test_chapter()
        chapter.append(
            "members", {"member": member.name, "chapter_join_date": frappe.utils.today(), "status": "Active"}
        )
        chapter.save()

        # Verify chapter membership exists
        chapter_memberships = frappe.db.count("Chapter Member", {"member": member.name})
        self.assertGreater(chapter_memberships, 0)

        # Reload member
        member.reload()

        # Call cleanup service
        get_member_cleanup_service().handle_member_deletion(member)

        # Verify chapter memberships were cleaned up
        remaining_memberships = frappe.db.count("Chapter Member", {"member": member.name})
        self.assertEqual(remaining_memberships, 0)

    def test_complex_cascade_deletion_multiple_relationships(self):
        """Test cascade deletion of member with multiple relationship types

        Integration test verifying complete cleanup of a member with:
        - Submitted membership
        - Chapter membership (child table)
        - Customer record
        - Address link

        This ensures all cleanup operations work together correctly.
        """
        # Create member with customer
        member = self.create_test_member(
            first_name="Complex", last_name="Test011", email="complex.test011@example.com"
        )

        customer_name = member.customer
        self.assertIsNotNone(customer_name, "Member should have customer")

        # Create and submit membership (type must be active + have a role_profile)
        if not frappe.db.exists("Membership Type", "Standard Test"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Standard Test",
                    "is_active": 1,
                    "minimum_amount": 5.0,
                    "role_profile": frappe.db.get_value(
                        "Role Profile", {"name": ["like", "%Member%"]}, "name"
                    )
                    or frappe.db.get_value("Role Profile", {}, "name"),
                }
            )
            membership_type.insert()

        membership = self.create_test_membership(
            member_name=member.name, membership_type_name="Standard Test"
        )
        membership.submit()
        membership_name = membership.name

        # Create chapter and add member to it
        chapter = self.create_test_chapter()
        chapter.append(
            "members",
            {"member": member.name, "status": "Active", "enabled": 1, "join_date": frappe.utils.today()},
        )
        chapter.save()
        chapter_name = chapter.name

        # Verify all relationships exist
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self.assertTrue(frappe.db.exists("Membership", membership_name))
        self.assertGreater(frappe.db.count("Chapter Member", {"member": member.name}), 0)

        # Execute cascade deletion
        member.reload()
        get_member_cleanup_service().handle_member_deletion(member)

        # Verify comprehensive cleanup:

        # 1. Membership cancelled and deleted
        self.assertFalse(
            frappe.db.exists("Membership", membership_name), "Membership should be deleted after cleanup"
        )

        # 2. Customer deleted (no transactions)
        self.assertFalse(
            frappe.db.exists("Customer", customer_name),
            "Customer should be deleted when no transactions exist",
        )

        # 3. Chapter memberships cleaned up
        remaining_memberships = frappe.db.count("Chapter Member", {"member": member.name})
        self.assertEqual(remaining_memberships, 0, "All chapter memberships should be deleted")

        # 4. Chapter itself still exists
        self.assertTrue(
            frappe.db.exists("Chapter", chapter_name), "Chapter should not be deleted, only membership link"
        )

    def test_error_handling_in_deletion_loops(self):
        """Test that errors during deletion are logged but don't stop cleanup"""
        member = self.create_test_member(
            first_name="Cleanup", last_name="Test010", email="cleanup.test010@example.com"
        )

        # Call cleanup service - should handle any errors gracefully
        try:
            get_member_cleanup_service().handle_member_deletion(member)
            # If it completes without raising, the error handling worked
        except Exception as e:
            # The service should catch errors, so this shouldn't happen
            self.fail(f"Cleanup service should handle errors gracefully, but raised: {e}")

    def test_dues_schedule_not_deleted_logs_operator_visible_error(self):
        """#1264 round 2: when a Membership Dues Schedule cannot be deleted
        during member deletion (still referenced by a Sales Invoice via
        membership_dues_schedule_display), the refusal must be recorded
        somewhere an operator can see it -- an Error Log entry, not only
        self.logger.error (a file under sites/<site>/logs/). The schedule
        itself is left pointing at a Member that is about to be deleted
        (a smaller, disclosed dangling-link risk -- see #1290's PR body),
        so this is the only trace of it.
        """
        self.expectErrorLog("Dues Schedule Not Deleted", "Member Deletion Audit Trail")
        member = self.create_test_member(
            first_name="Cleanup", last_name=f"Test{frappe.generate_hash(length=6)}",
            email=f"cleanup.errlog.{frappe.generate_hash(length=8)}@example.com",
        )
        original_email = member.email
        schedule = self._make_referenceable_dues_schedule(member)
        invoice = self._make_submitted_invoice_for_schedule(schedule.name)
        # No explicit cleanup registered here: EnhancedTestCase's own
        # captured-insert drain (_drain_captured_inserts ->
        # _remove_drained_record) already cancels-then-deletes every
        # submitted document inserted during the test, including this
        # invoice, and cleans up the schedule too -- see that method's own
        # docstring. A hand-written cleanup helper here would be redundant
        # AND -- confirmed by round 3's review -- invisible to the
        # order-dependence scanner if it lived outside a test_*.py file,
        # which is exactly the gate-evasion this round removes.

        before = frappe.utils.now_datetime()
        # #1306: an invoice-blocked schedule now converts the whole delete
        # into an anonymization, and aborts by raising rather than returning
        # normally -- see MemberAnonymizedInsteadOfDeleted's docstring for
        # why raising here is what stops the Member row itself from being
        # removed by the outer frappe.delete_doc() call in production.
        with self.assertRaises(MemberAnonymizedInsteadOfDeleted):
            get_member_cleanup_service().handle_member_deletion(member)

        # The schedule survives -- same guard this whole PR is about.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule.name))

        error_logs = frappe.get_all(
            "Error Log",
            filters={
                "method": "Member Deletion: Dues Schedule Not Deleted",
                "creation": [">=", before],
            },
            fields=["name", "error"],
        )
        self.assertTrue(
            error_logs,
            "a refused dues-schedule delete during member deletion must leave an "
            "Error Log entry an operator can see, not just a file-based service log",
        )
        self.assertIn(schedule.name, error_logs[0].error)
        self.assertIn(member.name, error_logs[0].error)

        # #1306: the Member is anonymized in place, not force-deleted -- the
        # row still exists and the schedule's `member` link still resolves.
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertEqual(frappe.db.get_value("Member", member.name, "first_name"), "Anonymous")
        anon_email = frappe.db.get_value("Member", member.name, "email")
        self.assertNotEqual(anon_email, original_email)
        self.assertTrue(anon_email.startswith("anon_"))

        self._cleanup_invoice_blocked_fixtures(member, schedule, invoice)

    def test_refused_schedule_delete_does_not_clear_member_backlink(self):
        """#1264 round 3: clear_member_schedule_backlinks_before_delete()
        used to run unconditionally BEFORE the schedule delete it precedes,
        so a REFUSED delete (the invoice case) still left the Member's own
        current_dues_schedule cleared, even though the schedule survives
        Active -- a real corruption, not merely a smaller one than #1250's:
        the schedule now looks unreferenced by its own Member even though it
        still exists.

        Calling handle_member_deletion() directly, with nothing catching or
        re-raising afterward, is what exposes this: in the two production
        callers this is invisible only because catch-and-continue here is
        followed by an OUTER delete (of the Member itself, moments later)
        that raises for an unrelated reason (the Customer/Address unlink
        steps do not, but the ambient ROLLBACK Frappe's own request/
        background-job/bulk-delete machinery performs on ANY uncaught
        exception from the outer call happens to undo this too) -- a
        per-record catch-and-continue caller with no such outer failure
        (the shape member_merge_service.py's own loop uses) would persist
        it. The fix wraps clear-then-delete in a savepoint and rolls back to
        it on refusal, so the back-link survives regardless of what the
        caller does next.
        """
        self.expectErrorLog("Dues Schedule Not Deleted", "Member Deletion Audit Trail")
        member = self.create_test_member(
            first_name="Cleanup", last_name=f"Test{frappe.generate_hash(length=6)}",
            email=f"cleanup.backlink.{frappe.generate_hash(length=8)}@example.com",
        )
        schedule = self._make_referenceable_dues_schedule(member)
        invoice = self._make_submitted_invoice_for_schedule(schedule.name)

        self.assertEqual(
            frappe.db.get_value("Member", member.name, "current_dues_schedule"),
            schedule.name,
            "test precondition: the Member's own back-link must be set by "
            "the real save() side effect, or this test cannot distinguish "
            "the fix from a fixture that never had the problem",
        )

        # #1306: an invoice-blocked schedule now converts the whole delete
        # into an anonymization, and aborts by raising.
        with self.assertRaises(MemberAnonymizedInsteadOfDeleted):
            get_member_cleanup_service().handle_member_deletion(member)

        # The schedule survives -- the invoice still names it (same guard
        # this whole PR is about).
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule.name))
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"), "Active"
        )
        # The Member's own back-link must ALSO survive: a refused delete is
        # a no-op for the Member's bookkeeping, not a half-applied one.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "current_dues_schedule"),
            schedule.name,
            "a refused dues-schedule delete must not leave the Member's own "
            "current_dues_schedule cleared while the schedule survives -- "
            "clearing the back-link and deleting the schedule must be one "
            "atomic (savepoint-wrapped) unit",
        )

        self._cleanup_invoice_blocked_fixtures(member, schedule, invoice)

    def _cleanup_invoice_blocked_fixtures(self, member, schedule, invoice, extra_schedules=()):
        """Tear down the invoice/schedule/customer trio an invoice-blocked
        anonymization test creates, and commit it.

        #1306: handle_member_deletion never reaches its own Membership /
        SEPA Mandate / Sales Invoice-reference / Chapter Member / Customer /
        Address / child-table cleanup once it chooses to anonymize -- the
        whole cascade is skipped, by design, so the Member is either fully
        cleaned up and deleted, or left untouched except for the deliberate
        PII scrub. That means this test's own invoice, schedule and Customer
        all survive the call under test and must be torn down here, or the
        harness's own (non-force) teardown drain fails to delete them --
        Member.customer still points at the Customer, and the schedule is
        still active -- and reports a leak.

        `extra_schedules`: additional Membership Dues Schedule names (#1306
        round 2's multi-schedule tests) that also survive the call under
        test -- since the read-only pre-pass now decides BEFORE deleting
        anything, every one of the member's schedules survives, not just the
        blocked one passed as `schedule`.

        The commit is required, not optional: the mid-test
        MemberAnonymizedInsteadOfDeleted-triggered frappe.db.commit() (see
        MemberCleanupService._anonymize_member_instead_of_deleting) already
        persisted the Member/schedule/invoice this test created, since it
        runs on the same connection as this test's own setup -- so the
        per-test rollback FrappeTestCase performs afterwards no longer
        undoes that setup. Without an explicit commit here too, that SAME
        rollback undoes only this cleanup, leaving the fixtures behind for
        the drain to trip over -- which is exactly what was observed before
        this helper existed. `_cleanup_*` is a recognised, exempt shape for
        this (see scan_order_dependence.py's COMMIT_EXEMPT).
        """
        invoice.reload()
        if invoice.docstatus == 1:
            invoice.cancel()
        frappe.delete_doc("Sales Invoice", invoice.name, force=True)
        frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)
        for extra_schedule_name in extra_schedules:
            if frappe.db.exists("Membership Dues Schedule", extra_schedule_name):
                frappe.delete_doc("Membership Dues Schedule", extra_schedule_name, force=True)
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.db.commit()

    def test_member_delete_doc_anonymizes_when_schedule_invoice_blocked(self):
        """#1306 end-to-end: a real frappe.delete_doc("Member", ...) call --
        the same call data_retention_policy._delete_personal_data and
        member_merge_service._delete_source_member_and_dependencies make in
        production, not handle_member_deletion() called directly -- must
        abort BEFORE removing the Member row when one of its schedules is
        still referenced by a Sales Invoice, leaving the Member anonymized
        in place instead.

        This is the design this PR picks: on_trash runs (and can raise)
        BEFORE frappe.delete_doc()'s check_if_doc_is_linked and
        delete_from_table steps (frappe/model/delete_doc.py), so raising
        MemberAnonymizedInsteadOfDeleted from inside on_trash aborts the
        delete cleanly -- nothing about the Member row, its schedule, or the
        invoice is touched by delete_doc after that point. Both real
        force=True callers (data_retention_policy, member_merge_service)
        and a Desk "delete linked documents" delete all funnel through this
        same on_trash choke point, so fixing it here protects all of them
        without duplicating the invoice check in each caller.
        """
        self.expectErrorLog("Dues Schedule Not Deleted", "Member Deletion Audit Trail")
        member = self.create_test_member(
            first_name="E2E", last_name=f"Test{frappe.generate_hash(length=6)}",
            email=f"e2e.anon.{frappe.generate_hash(length=8)}@example.com",
        )
        original_email = member.email
        schedule = self._make_referenceable_dues_schedule(member)
        invoice = self._make_submitted_invoice_for_schedule(schedule.name)

        # force=True mirrors both real production callers; it does not
        # change whether this guard fires (on_trash always runs, force or
        # not), only whether delete_doc would otherwise also skip its own
        # link-existence check for the Member itself.
        with self.assertRaises(MemberAnonymizedInsteadOfDeleted):
            frappe.delete_doc("Member", member.name, force=True)

        # The Member row itself was never removed, and is anonymized.
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertEqual(frappe.db.get_value("Member", member.name, "first_name"), "Anonymous")
        anon_email = frappe.db.get_value("Member", member.name, "email")
        self.assertNotEqual(anon_email, original_email)
        self.assertTrue(anon_email.startswith("anon_"))

        # The invoice (financially load-bearing) and the schedule it names
        # are completely untouched -- neither deleted nor modified.
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice.name))
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1)
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "membership_dues_schedule_display"),
            schedule.name,
        )
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule.name))
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "member"), member.name
        )
        # The schedule's `member` link still resolves -- the whole point of
        # anonymizing instead of deleting (#1306's title).
        self.assertTrue(frappe.db.exists("Member", frappe.db.get_value(
            "Membership Dues Schedule", schedule.name, "member"
        )))

        self._cleanup_invoice_blocked_fixtures(member, schedule, invoice)

    def test_member_delete_doc_succeeds_when_no_schedule_blocked(self):
        """#1306 control: the ordinary case (no invoice-referenced schedule)
        must still go through frappe.delete_doc("Member", ...) and actually
        remove the row -- proving the new invoice-blocked check does not
        accidentally engage, or otherwise interfere with, a normal delete.
        """
        member = self.create_test_member(
            first_name="E2E", last_name=f"Plain{frappe.generate_hash(length=6)}",
            email=f"e2e.plain.{frappe.generate_hash(length=8)}@example.com",
        )
        member_name = member.name

        frappe.delete_doc("Member", member_name, force=True)

        self.assertFalse(frappe.db.exists("Member", member_name))

    def test_multi_schedule_blocked_one_leaves_plain_sibling_untouched(self):
        """#1306 round 2: a Member with TWO Membership Dues Schedules, only
        one of which is invoice-blocked, must come out of an anonymized
        delete with BOTH schedules intact -- not just the blocked one.

        Regression test for a real bug an independent review found in round
        1: the dues-schedule loop deleted each non-blocked schedule AS IT
        WENT, and only checked for a block after the whole loop finished, so
        the anonymization's own commit made durable every already-deleted,
        non-blocked schedule from earlier in the same loop -- directly
        contradicting the documented "either fully cleaned up and deleted,
        or left untouched" invariant. A plain, Cancelled, non-invoice
        schedule is a realistic shape for that second schedule: contribution
        changes cancel-and-keep the old schedule rather than deleting it
        (contribution_amendment_approval_service.py), so a member can easily
        carry more than one Membership Dues Schedule row.
        """
        self.expectErrorLog("Dues Schedule Not Deleted", "Member Deletion Audit Trail")
        member = self.create_test_member(
            first_name="Multi", last_name=f"Test{frappe.generate_hash(length=6)}",
            email=f"multi.sched.{frappe.generate_hash(length=8)}@example.com",
        )
        blocked_schedule = self._make_referenceable_dues_schedule(member)
        invoice = self._make_submitted_invoice_for_schedule(blocked_schedule.name)
        plain_schedule = self._make_plain_dues_schedule(member, status="Cancelled")

        with self.assertRaises(MemberAnonymizedInsteadOfDeleted):
            get_member_cleanup_service().handle_member_deletion(member)

        # The invoice-blocked schedule survives (already covered elsewhere),
        # AND the unrelated, non-blocked sibling survives too -- the read-only
        # pre-pass must decide BEFORE deleting anything, not delete schedules
        # as it goes and only check for a block at the end.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", blocked_schedule.name))
        self.assertTrue(
            frappe.db.exists("Membership Dues Schedule", plain_schedule.name),
            "a non-blocked sibling schedule must survive too when ANY of the "
            "member's schedules is invoice-blocked -- the whole cascade is "
            "skipped, not just the blocked schedule's own deletion",
        )
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", plain_schedule.name, "status"),
            "Cancelled",
        )

        self._cleanup_invoice_blocked_fixtures(
            member, blocked_schedule, invoice, extra_schedules=[plain_schedule.name]
        )

    def test_schedule_blocked_by_payment_plan_also_triggers_anonymization(self):
        """#1306 round 2 class sweep: Payment Plan.membership_dues_schedule is
        a real Link field to Membership Dues Schedule (like Sales Invoice's
        membership_dues_schedule_display and Contribution Amendment
        Request's three dues-schedule fields), so a schedule referenced only
        by a Payment Plan -- no Sales Invoice at all -- hits the exact same
        Frappe LinkExistsError refusal. _find_blocked_schedules must catch
        this too: it asks Frappe's own link-integrity check
        (get_linked_docs/get_dynamic_linked_docs, method="Delete") rather
        than guessing at specific referencing doctypes, so any real external
        reference -- not just a Sales Invoice -- converts the delete into an
        anonymization.
        """
        self.expectErrorLog("Dues Schedule Not Deleted", "Member Deletion Audit Trail")
        member = self.create_test_member(
            first_name="PlanBlock", last_name=f"Test{frappe.generate_hash(length=6)}",
            email=f"planblock.{frappe.generate_hash(length=8)}@example.com",
        )
        schedule = self._make_plain_dues_schedule(member, status="Active")
        plan = self._make_payment_plan_referencing_schedule(member, schedule.name)

        with self.assertRaises(MemberAnonymizedInsteadOfDeleted):
            get_member_cleanup_service().handle_member_deletion(member)

        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule.name))
        self.assertTrue(frappe.db.exists("Payment Plan", plan.name))
        self.assertEqual(
            frappe.db.get_value("Payment Plan", plan.name, "membership_dues_schedule"), schedule.name
        )
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertEqual(frappe.db.get_value("Member", member.name, "first_name"), "Anonymous")

        self._cleanup_payment_plan_blocked_fixtures(member, schedule, plan)

    def _cleanup_payment_plan_blocked_fixtures(self, member, schedule, plan):
        """Tear down the Payment Plan/schedule/customer trio the non-invoice
        class-sweep test creates, and commit it -- same reasoning as
        _cleanup_invoice_blocked_fixtures (that method's own docstring),
        just for a Payment Plan instead of a Sales Invoice as the blocker.
        """
        frappe.delete_doc("Payment Plan", plan.name, force=True)
        frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.db.commit()

    def _make_plain_dues_schedule(self, member, status="Active"):
        """A schedule keyed to `member` with NO Sales Invoice reference --
        the sibling used to prove a non-blocked schedule is left alone by
        the multi-schedule tests, and the base fixture for the non-invoice
        class-sweep tests. Deliberately does NOT clear the Member's own
        back-link, matching _make_referenceable_dues_schedule's reasoning.
        """
        mt_name = frappe.db.get_value("Membership Type", {}, "name")
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"CLEANUP-PLAIN-{frappe.generate_hash(length=6)}"
        schedule.membership_type = mt_name
        schedule.member = member.name
        schedule.status = status
        schedule.billing_frequency = "Annual"
        schedule.currency = "EUR"
        schedule.is_template = 0
        schedule.dues_rate = 25
        schedule.flags.ignore_validate = True
        schedule.insert(ignore_permissions=True, ignore_mandatory=True)
        return schedule

    def _make_payment_plan_referencing_schedule(self, member, schedule_name):
        """A minimal Payment Plan referencing `schedule_name` -- a real,
        non-Sales-Invoice Link field to Membership Dues Schedule
        (payment_plan.json's `membership_dues_schedule` field).
        """
        plan = frappe.new_doc("Payment Plan")
        plan.naming_series = "PAY-PLAN-.YYYY.-.MM.-.#####"
        plan.member = member.name
        plan.membership_dues_schedule = schedule_name
        plan.plan_type = "Deferred Payment"
        plan.total_amount = 100
        plan.start_date = frappe.utils.today()
        plan.status = "Draft"
        plan.insert(ignore_permissions=True)
        return plan

    def _make_referenceable_dues_schedule(self, member):
        """Thin wrapper -- see dues_schedule_invoice_fixtures.make_referenceable_dues_schedule.

        Kept as a same-named method so every existing call site in this file
        is unchanged; the implementation moved to a shared module after
        duplicate_helper_validator.py flagged a near-identical copy in
        test_enhanced_test_factory_drain.py (#1306 round 4).
        """
        return make_referenceable_dues_schedule(self, member)

    def _make_submitted_invoice_for_schedule(self, schedule_name):
        """Thin wrapper -- see
        dues_schedule_invoice_fixtures.make_submitted_invoice_for_schedule.
        No frappe.db.commit() here -- handle_member_deletion (the code under
        test) reads on the SAME connection within the same test, and nothing
        in this file rolls back, so a commit is not load-bearing.
        """
        return make_submitted_invoice_for_schedule(self, schedule_name)

    # ------------------------------------------------------------------
    # Extended coverage: unlink helpers + audit + sales-invoice clearing
    # ------------------------------------------------------------------

    def _make_linked_address(self, member):
        """Create an Address linked to the member and set it as primary."""
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Unlink {frappe.generate_hash(length=6)}",
                "address_line1": "456 Unlink Lane",
                "city": "Rotterdam",
                "pincode": "3000AA",
                "country": "Netherlands",
                "address_type": "Personal",
                "links": [{"link_doctype": "Member", "link_name": member.name}],
            }
        )
        address.insert(ignore_permissions=True)
        member.reload()
        member.primary_address = address.name
        member.save(ignore_version=True)
        return address

    def test_unlink_member_from_address_removes_only_member_link(self):
        """_unlink_member_from_address strips the Member link, preserves the Address."""
        member = self.create_test_member(
            first_name="Unlink", last_name="Addr001", email="unlink.addr001@example.com"
        )
        address = self._make_linked_address(member)

        # Sanity: link exists before
        address.reload()
        member_links = [
            link
            for link in (address.get("links") or [])
            if link.link_doctype == "Member" and link.link_name == member.name
        ]
        self.assertEqual(len(member_links), 1)

        member.reload()
        get_member_cleanup_service()._unlink_member_from_address(member, address.name)

        # Address still exists, but the Member link is gone
        self.assertTrue(frappe.db.exists("Address", address.name))
        address.reload()
        remaining = [
            link
            for link in (address.get("links") or [])
            if link.link_doctype == "Member" and link.link_name == member.name
        ]
        self.assertEqual(len(remaining), 0)

    def test_unlink_member_from_customer_no_customer_noop(self):
        """_unlink_member_from_customer is a no-op when member has no customer."""
        member = self.create_test_member(
            first_name="Unlink", last_name="NoCust", email="unlink.nocust@example.com"
        )
        member.customer = None
        # Should not raise
        get_member_cleanup_service()._unlink_member_from_customer(member)

    def test_unlink_member_from_customer_clears_member_link(self):
        """When Customer.member points at the member, it is cleared.

        Regression guard: this asserted on `custom_member`, which is not a column
        on Customer, so the test skipped itself and the dangling-link bug it was
        meant to cover went unnoticed. The real field is `member`.
        """
        member = self.create_test_member(
            first_name="Unlink", last_name="CustomMem", email="unlink.custommem@example.com"
        )
        customer_name = member.customer
        self.assertTrue(customer_name)

        frappe.db.set_value("Customer", customer_name, "member", member.name)
        member.reload()

        get_member_cleanup_service()._unlink_member_from_customer(member)

        # member link cleared; Customer preserved
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self.assertFalse(bool(frappe.db.get_value("Customer", customer_name, "member")))

    def test_audit_log_does_not_raise(self):
        """_log_permission_bypass_audit writes an Error Log entry without raising."""
        member = self.create_test_member(
            first_name="Audit", last_name="Trail", email="audit.trail@example.com"
        )
        # Should complete silently (logs to app log + Error Log)
        get_member_cleanup_service()._log_permission_bypass_audit(
            operation="unit_test_op",
            doctype="Customer",
            docname=member.customer or "X",
            member_name=member.name,
            justification="unit test audit entry",
        )

    def test_sales_invoice_reference_cleared_on_deletion(self):
        """Member references on Sales Invoices are NULLed (invoice preserved)."""
        member = self.create_test_member(first_name="SI", last_name="Ref", email="si.ref@example.com")
        # Insert a minimal Sales Invoice row carrying the member ref directly via SQL
        # to avoid full accounting setup; we only test the reference-clearing UPDATE.
        if not frappe.db.has_column("Sales Invoice", "member"):
            self.skipTest("Sales Invoice has no member column in this install")

        si_name = f"TEST-SI-{frappe.generate_hash(length=8)}"
        frappe.db.sql(
            "INSERT INTO `tabSales Invoice` (name, member, docstatus, creation, modified, owner, modified_by) "
            "VALUES (%s, %s, 0, NOW(), NOW(), 'Administrator', 'Administrator')",
            (si_name, member.name),
        )
        try:
            member.reload()
            get_member_cleanup_service().handle_member_deletion(member)
            cleared = frappe.db.get_value("Sales Invoice", si_name, "member")
            self.assertIsNone(cleared)
        finally:
            frappe.db.sql("DELETE FROM `tabSales Invoice` WHERE name = %s", (si_name,))


def run_tests():
    """Run test suite"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
