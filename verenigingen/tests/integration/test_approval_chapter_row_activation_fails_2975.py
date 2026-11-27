"""#2975: an approval whose applied or reviewer chapter row cannot be activated FAILS and rolls back.

Maintainer ruling (2026-11-25, option a), consistent with #2133: the approval no longer continues with the row
Pending (member Active and billed, first invoice without a chapter).

Real flow: submit_application -> confirm -> approve_application. The refusal itself is REAL: the chapter is left
with a Default Board Role Profile that no longer exists (the stale profile of #738), so the real Chapter.validate
refuses the activation save. PROBE SHORTCUT, stated (CLAUDE.md rule 13): the fault is injected at the lowest
boundary that tells the activation save apart from the Pending-row save. `secure_document_operation` is wrapped;
for the activation of the chosen chapter it corrupts the chapter and then calls the REAL operation. (A chapter
corrupted from the start fails the earlier Pending-row write instead, which swallows its own failure and is a
separate path: #3204.) Nothing is mocked to return a canned answer,
except the two tests that pin the helper's falsy shape / a deadlock.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.integration.test_application_record_approval import SUBMISSION, ApprovalCase
from verenigingen.utils import secure_operations
from verenigingen.verenigingen.doctype.member.member import Member

STALE_PROFILE = "No Such Role Profile 2975"
ACTIVATION = "Activate chapter member"


class TestApprovalChapterRowActivationFails2975(ApprovalCase):
    def _break_activation_of_2975(self, chapter, error=None):
        """Fail the activation save of `chapter` only. Without `error` the real Chapter.validate refuses it."""
        real = secure_operations.secure_document_operation

        def wrapper(*args, **kwargs):
            doc = kwargs.get("doc")
            if kwargs.get("justification", "").startswith(ACTIVATION) and doc.name == chapter:
                if error:
                    raise error
                frappe.db.set_value("Chapter", chapter, "default_board_role_profile", STALE_PROFILE, update_modified=False)
                doc.default_board_role_profile = STALE_PROFILE
            return real(*args, **kwargs)

        # Mock justified: pass-through wrapper at the save boundary; the real operation (and the real
        # Chapter.validate that refuses) still runs. The deadlock variant raises what frappe raises for 1213.
        return patch.object(secure_operations, "secure_document_operation", side_effect=wrapper)

    def _applicant_rows_2975(self):
        return {
            "members": frappe.db.count("Member", {"email": self.email}),
            "memberships": frappe.db.count("Membership", {"member": ["like", "%"], "creation": [">=", self._t0]}),
            "invoices": frappe.db.count("Sales Invoice", {"creation": [">=", self._t0]}),
            "schedules": frappe.db.count("Membership Dues Schedule", {"creation": [">=", self._t0], "is_template": 0}),
            "chapter_rows": frappe.db.count("Chapter Member", {"creation": [">=", self._t0]}),
        }

    def _approve_and_expect_refusal_2975(self, application, chapter, exc=frappe.ValidationError, **fault):
        self._t0 = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=-1)
        if exc is frappe.ValidationError:
            self.expectErrorLog("Chapter Activation Error")
        target = fault.pop("target")
        core_calls = []
        real_core = Member.create_membership_on_approval

        def core_spy(member, *args, **kwargs):
            core_calls.append(member.name)
            return real_core(member, *args, **kwargs)

        # Mock justified: recording pass-through spy on the core; the real method still runs if it is reached.
        with patch.object(Member, "create_membership_on_approval", core_spy):
            with self._break_activation_of_2975(target, **fault):
                with self.assertRaises(exc) as ctx:
                    self._approve_as(
                        application, membership_type=self.membership_type.name, chapter=chapter, create_invoice=True
                    )
        # The failure must come BEFORE the core: _finish_reviewer_chapter_row re-activates after it and would also
        # fail the approval, but the core can commit (Pattern 1), leaving a committed half-approved Member.
        self.assertEqual(core_calls, [], "the core (create_membership_on_approval) must never run")
        if exc is not frappe.ValidationError:
            return ctx.exception  # a simulated 1213: the server's own rollback is not simulated, see the test
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Pending Review", "still pending")
        self.assertEqual(
            self._applicant_rows_2975(),
            {"members": 0, "memberships": 0, "invoices": 0, "schedules": 0, "chapter_rows": 0},
            "nothing the approval wrote survives: no member, membership, invoice, dues schedule or chapter row",
        )
        return ctx.exception

    def test_control_without_the_fault_the_approval_succeeds_and_the_row_is_active(self):
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        result = self._approve_as(application, membership_type=self.membership_type.name, create_invoice=True)

        self.assertTrue(result["success"], result)
        self.assertEqual(
            frappe.get_all("Chapter Member", {"parent": self.chapter.name, "member": result["member"]}, pluck="status"),
            ["Active"],
        )

    def test_the_applied_chapter_row_failing_to_activate_fails_the_approval(self):
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        error = self._approve_and_expect_refusal_2975(application, None, target=self.chapter.name)

        self.assertIn("Failed to activate chapter member", str(error))
        self.assertIn(STALE_PROFILE, str(error), "the real Chapter.validate refusal reached the approver")

    def test_the_reviewer_chapter_row_failing_to_activate_fails_the_approval(self):
        application = self._stage_without_chapter()

        error = self._approve_and_expect_refusal_2975(application, self.chapter.name, target=self.chapter.name)

        self.assertIn(STALE_PROFILE, str(error))

    def test_the_reviewer_chapter_failing_fails_the_approval_although_the_applied_chapter_activated(self):
        """Wrong fix: raise for the applied chapter only. Applied chapter A activates, reviewer chapter B fails."""
        other = self.create_test_chapter(published=1)
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        self._approve_and_expect_refusal_2975(application, other.name, target=other.name)

    def test_the_applied_chapter_failing_fails_the_approval_although_the_reviewer_chapter_is_fine(self):
        """Wrong fix: raise for the reviewer chapter only."""
        other = self.create_test_chapter(published=1)
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        self._approve_and_expect_refusal_2975(application, other.name, target=self.chapter.name)

    def test_a_deadlock_while_activating_propagates_as_a_deadlock(self):
        """1213 must not be turned into a ValidationError, a log line or a falsy answer. The exception is raised
        by the wrapper, so the server's own transaction discard (which the approval relies on) is not simulated and
        the rollback is not asserted here."""
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        self._approve_and_expect_refusal_2975(
            application, None, exc=frappe.QueryDeadlockError, target=self.chapter.name,
            error=frappe.QueryDeadlockError("deadlock"),
        )
