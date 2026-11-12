# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for services/member/identification/member_id_service.py.

This is the MemberIDService class (OperationResult-based admin utility),
distinct from the core module-level functions. Covers single assignment,
bulk assignment, and the debug diagnostic, all against real Member docs.
"""

import unittest
from unittest.mock import patch

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.identification.member_id_service import (
    MemberIDService,
    get_member_id_service,
)


class TestAssignMemberId(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberIDService()

    def test_empty_name_fails(self):
        result = self.service.assign_member_id("")
        self.assertFalse(result.success)
        self.assertIn("required", result.error_message.lower())

    def test_nonexistent_member_fails(self):
        result = self.service.assign_member_id("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result.success)
        self.assertIn("does not exist", result.error_message.lower())

    def test_already_has_id_fails_with_existing(self):
        member = self.create_test_member(
            first_name="Assign",
            last_name="Has",
            email="assign.has@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", "445566")
        result = self.service.assign_member_id(member.name)
        self.assertFalse(result.success)
        self.assertEqual(result.metadata.get("existing_member_id"), "445566")

    def test_assigns_numeric_id_to_eligible_member(self):
        """A non-application member without an ID is assigned a numeric ID."""
        member = self.create_test_member(
            first_name="Assign",
            last_name="New",
            email="assign.new@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        result = self.service.assign_member_id(member.name)
        self.assertTrue(result.success)
        self.assertTrue(str(result.data).isdigit())
        # Verify persisted on the member
        self.assertEqual(frappe.db.get_value("Member", member.name, "member_id"), str(result.data))


class TestAssignMissingMemberIds(EnhancedTestCase):
    def test_bulk_assigns_to_eligible_members(self):
        """Bulk assignment fills IDs for eligible members lacking them."""
        member = self.create_test_member(
            first_name="Bulk",
            last_name="Eligible",
            email="bulk.eligible@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        frappe.db.commit()

        result = get_member_id_service().assign_missing_member_ids()
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.data["assigned"], 1)
        self.assertGreaterEqual(result.data["total_checked"], 1)
        # Our member should now have an id
        member.reload()
        self.assertTrue(member.member_id)

    def test_result_shape(self):
        """Seed one eligible member so the bulk op reports the standard keys."""
        member = self.create_test_member(
            first_name="Bulk",
            last_name="Shape",
            email="bulk.shape@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        frappe.db.commit()

        result = get_member_id_service().assign_missing_member_ids()
        # At least our seeded member is assigned -> success path with data dict
        self.assertTrue(result.success)
        self.assertIn("total_checked", result.data)
        self.assertIn("assigned", result.data)
        self.assertIn("errors", result.data)


class TestDebugMemberIdAssignment(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberIDService()

    def test_empty_name_fails(self):
        result = self.service.debug_member_id_assignment("")
        self.assertFalse(result.success)

    def test_nonexistent_member_fails(self):
        result = self.service.debug_member_id_assignment("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result.success)

    def test_member_with_id_explains_already_has(self):
        member = self.create_test_member(
            first_name="Debug",
            last_name="Has",
            email="debug.has@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", "112233")
        member.reload()
        result = self.service.debug_member_id_assignment(member.name)
        self.assertTrue(result.success)
        info = result.data
        self.assertTrue(info["has_member_id"])
        self.assertEqual(info["current_member_id"], "112233")
        self.assertFalse(info["can_assign_id"])
        self.assertIn("already has ID", info["explanation"])

    def test_eligible_member_can_assign(self):
        member = self.create_test_member(
            first_name="Debug",
            last_name="Eligible",
            email="debug.eligible@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        member.reload()
        result = self.service.debug_member_id_assignment(member.name)
        self.assertTrue(result.success)
        info = result.data
        self.assertFalse(info["has_member_id"])
        # Non-application member is eligible -> can assign
        self.assertTrue(info["should_have_member_id"])
        self.assertTrue(info["can_assign_id"])
        self.assertIn("eligible", info["explanation"].lower())


class TestBulkAssignmentDatabaseLockError(EnhancedTestCase):
    """#2388: a 1213/1205 inside the bulk loop must stop the batch and report the truth.

    The fault is injected at ``frappe.db.sql`` on the counter's ``FOR UPDATE`` read,
    i.e. below every layer that catches on the real path (the decorator, the
    per-member ``except``). For a deadlock the injection also rolls back the
    assignments made so far, which is what MariaDB does to the transaction
    (see _seed_unassigned_members).
    """

    COUNTER_READ = "FOR UPDATE"
    SAVEPOINT = "bulk_member_id_2388"

    def _seed_unassigned_members(self, n):
        names = []
        for i in range(n):
            member = self.create_test_member(
                first_name="Lock",
                last_name=f"Loop{i}",
                email=f"lock.loop{i}@example.com",
            )
            frappe.db.set_value("Member", member.name, "member_id", None)
            names.append(member.name)
        # The injected rollback must not take the fixtures with it; only assignments are
        # at risk. A bare commit would grow the order-dependence baseline (hard gate), so
        # the "rollback" below is a rollback TO this savepoint: it discards exactly the
        # assignments made after it, which is the part of a 1213 under test. (A real 1213
        # also destroys the savepoint and the fixtures; that is why this is an emulation
        # of the rollback's effect on the assignments, not of the whole server behaviour.)
        frappe.db.savepoint(self.SAVEPOINT)
        return names

    def _run_with_fault_on_nth_counter_read(self, nth, exc_class, rollback):
        real_sql = frappe.db.sql
        counter_reads = []

        def faulty_sql(query, *args, **kwargs):
            if isinstance(query, str) and self.COUNTER_READ in query and "tabSingles" in query:
                counter_reads.append(1)
                if len(counter_reads) == nth:
                    if rollback:
                        frappe.db.rollback(save_point=self.SAVEPOINT)
                    raise exc_class("injected below the per-member except")
            return real_sql(query, *args, **kwargs)

        with patch.object(frappe.db, "sql", side_effect=faulty_sql):
            result = get_member_id_service().assign_missing_member_ids()
        return result, len(counter_reads)

    def _persisted(self, names):
        return len(frappe.get_all("Member", filters={"name": ["in", names], "member_id": ["is", "set"]}))

    def test_deadlock_stops_the_batch_and_does_not_count_rolled_back_members(self):
        names = self._seed_unassigned_members(4)
        result, counter_reads = self._run_with_fault_on_nth_counter_read(3, frappe.QueryDeadlockError, True)
        frappe.db.rollback(save_point=self.SAVEPOINT)  # discard what a (wrongly) continuing loop wrote

        self.assertEqual(counter_reads, 3, "the loop kept taking IDs after a 1213")
        self.assertFalse(result.success)
        reported = result.metadata["assigned"]
        self.assertEqual(reported, 0, "the 1213 rolled back every uncommitted assignment")
        self.assertEqual(self._persisted(names), 0)
        self.assertTrue(any("QueryDeadlockError" in e for e in result.errors))

    def test_lock_timeout_stops_the_batch_but_keeps_what_persisted(self):
        """A 1205 rolls back only the failing statement: earlier assignments survive and are counted."""
        self._seed_unassigned_members(4)
        result, counter_reads = self._run_with_fault_on_nth_counter_read(3, frappe.QueryTimeoutError, False)
        frappe.db.rollback(save_point=self.SAVEPOINT)  # discard the assignments; keep the fixtures

        self.assertEqual(counter_reads, 3, "the loop kept taking IDs after a lock timeout")
        self.assertFalse(result.success)
        # Two members were assigned before the 3rd counter read failed; a 1205 keeps them.
        self.assertEqual(result.metadata["assigned"], 2)


class TestBulkAssignmentNothingAssigned(EnhancedTestCase):
    """#2424: the zero-assigned branch must return a failure that carries the real facts.

    It used to pass ``errors=`` AND ``**results`` (which holds ``errors``), so Python
    raised TypeError and the outer ``except`` replaced the result with a generic one,
    losing the per-member errors and ``total_checked``.
    """

    def _seed_unassigned_member(self):
        member = self.create_test_member(
            first_name="Nothing",
            last_name="Assigned",
            email="nothing.assigned@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        return member

    def test_per_member_errors_and_total_checked_survive_when_nothing_is_assigned(self):
        self._seed_unassigned_member()
        with patch(
            "verenigingen.verenigingen.doctype.member.member.Member.should_have_member_id",
            return_value=True,
        ), patch(
            "verenigingen.verenigingen.doctype.member.member.Member.ensure_member_id",
            side_effect=frappe.ValidationError("counter exploded"),
        ):
            result = get_member_id_service().assign_missing_member_ids()

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "No member IDs were assigned")
        self.assertNotIn("multiple values", str(result.error_message))
        self.assertTrue(result.errors)
        self.assertTrue(all("counter exploded" in e for e in result.errors), result.errors)
        self.assertGreaterEqual(result.metadata["total_checked"], 1)
        self.assertEqual(result.metadata["assigned"], 0)

    def test_nobody_eligible_reports_the_placeholder_error_and_total_checked(self):
        """A Pending applicant without a member_id is genuinely not eligible.

        Probe shortcut: application_id/application_status are written with
        ``db.set_value`` on a factory member, not through the application flow.
        """
        member = self._seed_unassigned_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {"application_id": f"APP-2424-{member.name}", "application_status": "Pending"},
        )
        result = get_member_id_service().assign_missing_member_ids()

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "No member IDs were assigned")
        self.assertEqual(result.errors, ["No eligible members found"])
        self.assertGreaterEqual(result.metadata["total_checked"], 1)
        self.assertEqual(result.metadata["assigned"], 0)
        self.assertFalse(frappe.db.get_value("Member", member.name, "member_id"))


if __name__ == "__main__":
    unittest.main()
