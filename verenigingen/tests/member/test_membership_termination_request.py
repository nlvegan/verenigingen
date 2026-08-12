"""
Real-integration tests for the Membership Termination Request controller and its
module-level whitelisted endpoints in
``verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py``.

The module holds the termination workflow (Draft -> Pending -> Approved ->
Executed / Rejected) plus a set of dashboard/report endpoints. It was ~51%
covered; these tests create real Members, Memberships and Termination Requests
(no business-logic mocking) and run as Administrator.

Executing a termination mutates the member (status, SEPA mandates, etc.). Those
paths are exercised on members the tests create, and the durable side effects are
asserted (member status flips, request status becomes Executed, execution_date
set).
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership_termination_request import (
    membership_termination_request as mtr,
)


class TestMembershipTerminationRequest(VereningingenTestCase):
    """Exercise the termination request controller + module endpoints end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Terminate",
            last_name="Target",
            email=f"terminate.target.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------------ helpers

    def _make_request(self, **kwargs):
        """Create a real Membership Termination Request for self.member."""
        defaults = {
            "doctype": "Membership Termination Request",
            "member": self.member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Member moved abroad",
            "member_request_date": today(),
        }
        defaults.update(kwargs)
        doc = frappe.get_doc(defaults)
        doc.insert()
        self.track_doc("Membership Termination Request", doc.name)
        return doc

    def _make_disciplinary_request(self, **kwargs):
        defaults = {
            "termination_type": "Policy Violation",
            "termination_reason": "Serious breach of code of conduct",
            "disciplinary_documentation": "<p>Documented incident report attached.</p>",
        }
        defaults.update(kwargs)
        # disciplinary requests have no member_request_date
        defaults.setdefault("member_request_date", None)
        return self._make_request(**defaults)

    # ============================================================ insert / defaults

    def test_insert_sets_defaults_and_status_draft(self):
        # Bracket the insert with the controller's own date source: request_date is
        # stamped during insert, so a midnight rollover between that stamp and the
        # assertion would otherwise fail a same-day comparison spuriously.
        before = getdate(today())
        doc = self._make_request()
        after = getdate(today())
        self.assertEqual(doc.status, "Draft")
        self.assertEqual(doc.requested_by, frappe.session.user)
        self.assertIn(getdate(doc.request_date), (before, after))
        # member_name fetched from the linked member
        self.assertEqual(doc.member_name, self.member.full_name)

    def test_calculate_termination_date_from_member_request_date(self):
        # No grace period: termination date equals member request date.
        doc = self._make_request(member_request_date="2024-01-15", apply_grace_period=0)
        self.assertEqual(str(doc.termination_date), "2024-01-15")

    def test_calculate_termination_date_with_grace_period(self):
        grace = mtr.MembershipTerminationRequest.get_grace_period_days(
            frappe.get_doc("Membership Termination Request", self._make_request().name)
        )
        doc = self._make_request(member_request_date="2024-01-15", apply_grace_period=1)
        self.assertEqual(str(doc.termination_date), str(add_days("2024-01-15", grace)))

    # ============================================================ validate_dates

    def test_validate_dates_rejects_termination_before_request(self):
        # termination_date earlier than member_request_date must throw.
        with self.assertRaises(frappe.ValidationError):
            self._make_request(
                member_request_date="2024-06-01",
                termination_date="2024-05-01",
                apply_grace_period=0,
            )

    # ============================================================ validate_termination_request

    def test_validate_rejects_nonexistent_member(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Membership Termination Request",
                    "member": "NONEXISTENT-MEMBER-XYZ",
                    "termination_type": "Administrative",
                    "termination_reason": "x",
                }
            ).insert()

    def test_validate_rejects_already_terminal_member(self):
        # A member already Deceased/Banned/Quit cannot be terminated again.
        frappe.db.set_value("Member", self.member.name, "status", "Deceased")
        with self.assertRaises(frappe.ValidationError):
            self._make_request(termination_type="Administrative", member_request_date=None)

    def test_validate_disciplinary_requires_documentation(self):
        with self.assertRaises(frappe.ValidationError):
            self._make_request(
                termination_type="Expulsion",
                termination_reason="grave misconduct",
                disciplinary_documentation=None,
                member_request_date=None,
            )

    def test_disciplinary_request_sets_requires_secondary_approval(self):
        doc = self._make_disciplinary_request()
        self.assertEqual(doc.requires_secondary_approval, 1)

    def test_voluntary_request_does_not_require_secondary_approval(self):
        doc = self._make_request()
        self.assertEqual(doc.requires_secondary_approval, 0)

    # ============================================================ approval workflow

    def test_submit_for_approval_voluntary_goes_to_approved(self):
        doc = self._make_request()
        result = doc.submit_for_approval()
        self.assertEqual(result["status"], "Approved")
        doc.reload()
        self.assertEqual(doc.status, "Approved")
        self.assertEqual(doc.approved_by, frappe.session.user)

    def test_submit_for_approval_rejects_non_draft(self):
        doc = self._make_request()
        doc.submit_for_approval()  # now Approved
        with self.assertRaises(frappe.ValidationError):
            doc.submit_for_approval()

    def test_approve_request_decision_approved(self):
        # Draft requests can be directly approved via approve_request.
        doc = self._make_request()
        result = doc.approve_request("approved", notes="ok to proceed")
        self.assertEqual(result["status"], "Approved")
        doc.reload()
        self.assertEqual(doc.status, "Approved")
        self.assertEqual(doc.approver_notes, "ok to proceed")

    def test_approve_request_decision_rejected(self):
        doc = self._make_request()
        result = doc.approve_request("rejected", notes="not eligible")
        self.assertEqual(result["status"], "Rejected")
        doc.reload()
        self.assertEqual(doc.status, "Rejected")

    def test_approve_request_invalid_decision_throws(self):
        doc = self._make_request()
        with self.assertRaises(frappe.ValidationError):
            doc.approve_request("maybe")

    # ============================================================ execution (real member mutation)

    def test_execute_termination_full_path_mutates_member(self):
        # Approve, then execute via the doc method; assert the member is mutated
        # and the request becomes Executed with an execution_date.
        doc = self._make_request(termination_type="Administrative", member_request_date=None)
        doc.approve_request("approved")
        doc.reload()
        self.assertEqual(doc.status, "Approved")

        result = doc.execute_termination()
        self.assertEqual(result["status"], "Executed")

        doc.reload()
        self.assertEqual(doc.status, "Executed")
        self.assertTrue(doc.execution_date)
        self.assertEqual(doc.executed_by, frappe.session.user)

        # Member status was changed away from Active by the execution.
        member_status = frappe.db.get_value("Member", self.member.name, "status")
        self.assertNotEqual(member_status, "Active")

    def test_execute_termination_request_module_wrapper(self):
        # List-view bulk wrapper executes the same way as the doc method.
        doc = self._make_request(termination_type="Administrative", member_request_date=None)
        doc.approve_request("approved")
        doc.reload()

        result = mtr.execute_termination_request(doc.name)
        self.assertEqual(result["status"], "Executed")
        doc.reload()
        self.assertEqual(doc.status, "Executed")

    def test_execute_termination_rejects_unapproved(self):
        # execute_from_api guards on status == Approved.
        doc = self._make_request()
        with self.assertRaises(frappe.ValidationError):
            doc.execute_termination()

    def test_execute_termination_idempotent(self):
        # Re-executing an already-executed request must not raise and must not
        # double-execute (execution_date preserved).
        doc = self._make_request(termination_type="Administrative", member_request_date=None)
        doc.approve_request("approved")
        doc.reload()
        doc.execute_termination()
        doc.reload()
        first_exec_date = doc.execution_date

        # Drive idempotency via the internal entry-point (returns True when skipped).
        already = doc.execute_termination_internal()
        self.assertTrue(already)
        doc.reload()
        self.assertEqual(doc.execution_date, first_exec_date)

    def test_execute_safe_member_termination_api(self):
        # Module-level convenience API that creates + executes in one call.
        result = mtr.execute_safe_member_termination(
            member=self.member.name,
            termination_type="Administrative",
        )
        self.assertIsInstance(result, dict)
        # The member should no longer be Active afterwards.
        member_status = frappe.db.get_value("Member", self.member.name, "status")
        self.assertNotEqual(member_status, "Active")

    # ============================================================ preview / simulate

    def test_get_termination_preview_shape(self):
        doc = self._make_request()
        preview = doc.get_termination_preview()
        self.assertIn("impact", preview)
        self.assertIn("ready", preview)

    def test_simulate_execution_shape(self):
        doc = self._make_request()
        sim = doc.simulate_execution()
        self.assertIn("total_items_affected", sim)
        self.assertIn("categories", sim)

    def test_get_termination_impact_preview_module(self):
        impact = mtr.get_termination_impact_preview(self.member.name)
        # Fallback or real impact both carry customer_linked.
        self.assertIn("customer_linked", impact)
        self.assertIn("active_memberships", impact)

    # ============================================================ status / history / statistics

    def test_get_member_termination_status_module(self):
        result = mtr.get_member_termination_status(self.member.name)
        self.assertIn("pending_requests", result)
        self.assertIn("executed_requests", result)
        self.assertFalse(result["is_terminated"])

    def test_get_member_termination_history(self):
        doc = self._make_request()
        result = mtr.get_member_termination_history(self.member.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_requests"], 1)
        names = {r["name"] for r in result["termination_requests"]}
        self.assertIn(doc.name, names)
        # audit_trail is attached per request.
        self.assertIn("audit_trail", result["termination_requests"][0])

    def test_get_member_termination_history_empty(self):
        result = mtr.get_member_termination_history(self.member.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_requests"], 0)

    def test_get_termination_statistics_shape_and_counts(self):
        self._make_request()
        self._make_disciplinary_request()
        result = mtr.get_termination_statistics()
        self.assertTrue(result["success"])
        stats = result["statistics"]
        self.assertGreaterEqual(stats["total_requests"], 2)
        self.assertIn("by_status", stats)
        self.assertIn("by_type", stats)
        self.assertIn("Draft", stats["by_status"])
        self.assertGreaterEqual(stats["by_type"].get("Voluntary", 0), 1)
        self.assertGreaterEqual(stats["recent_requests"], 2)

    def test_get_termination_statistics_counts_pending_approvals(self):
        # Regression: pending_approvals used to filter on the impossible status
        # values ["Pending Approval", "Under Review"] and was always 0. A real
        # request in the actual "Pending" status must now be counted.
        doc = self._make_disciplinary_request()
        # Drive it into the real awaiting-approval status without going through the
        # heavy approval/notification path. set_value bypasses validation, which is
        # what we want here (we only care about the statistics query).
        approver = self.create_test_user(
            f"sec.approver.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Administrator"],
        )
        frappe.db.set_value(
            "Membership Termination Request",
            doc.name,
            {"status": "Pending", "secondary_approver": approver.name},
        )

        result = mtr.get_termination_statistics()
        self.assertTrue(result["success"])
        stats = result["statistics"]
        self.assertGreaterEqual(stats["pending_approvals"], 1)
        # And the by_status breakdown reflects the Pending request too.
        self.assertGreaterEqual(stats["by_status"].get("Pending", 0), 1)

    def test_get_termination_statistics_pending_excludes_terminal(self):
        # A request that is NOT awaiting approval (e.g. Draft) must not inflate the
        # pending_approvals count for that record's status.
        self._make_request()  # stays Draft
        result = mtr.get_termination_statistics()
        stats = result["statistics"]
        # Draft is counted under by_status but not under pending_approvals.
        self.assertIn("Draft", stats["by_status"])
        # pending_approvals counts only "Pending"; with no Pending rows created here
        # it equals the number of Pending rows in by_status (0 from this test).
        self.assertEqual(stats["pending_approvals"], stats["by_status"].get("Pending", 0))

    # ============================================================ disciplinary duplicate guard

    def _seed_disciplinary_request(self, status):
        """Create a real disciplinary request (type 'Disciplinary Action') at `status`.

        The duplicate guard in initiate_disciplinary_termination blocks a new request
        when any in-progress request of a disciplinary type
        (Policy Violation / Disciplinary Action / Expulsion) exists.
        """
        doc = self._make_disciplinary_request(termination_type="Disciplinary Action")
        frappe.db.set_value("Membership Termination Request", doc.name, "status", status)
        return doc

    def test_disciplinary_guard_blocks_when_pending_exists(self):
        self._seed_disciplinary_request(status="Pending")
        result = mtr.initiate_disciplinary_termination(member=self.member.name, reason="repeat offence")
        self.assertFalse(result["success"])
        self.assertIn("already a pending disciplinary", result["error"].lower())

    def test_disciplinary_guard_blocks_when_approved_exists(self):
        # Approved-but-not-yet-Executed counts as still in progress.
        self._seed_disciplinary_request(status="Approved")
        result = mtr.initiate_disciplinary_termination(member=self.member.name, reason="repeat offence")
        self.assertFalse(result["success"])
        self.assertIn("already a pending disciplinary", result["error"].lower())

    def test_disciplinary_guard_blocks_when_draft_exists(self):
        self._seed_disciplinary_request(status="Draft")
        result = mtr.initiate_disciplinary_termination(member=self.member.name, reason="repeat offence")
        self.assertFalse(result["success"])
        self.assertIn("already a pending disciplinary", result["error"].lower())

    def test_disciplinary_guard_allows_when_only_finished_exist(self):
        # Rejected / Executed / Cancelled requests are finished and must NOT block
        # a fresh disciplinary request: the new request must be created successfully.
        for finished in ("Rejected", "Executed", "Cancelled"):
            with self.subTest(status=finished):
                doc = self._seed_disciplinary_request(status=finished)
                result = mtr.initiate_disciplinary_termination(
                    member=self.member.name,
                    reason="fresh case",
                    evidence="<p>Documented incident report.</p>",
                )
                self.assertTrue(result["success"], msg=result.get("error"))
                self.track_doc("Membership Termination Request", result["termination_request"])
                # Clean up so the next subTest's member has no in-progress request.
                frappe.db.set_value(
                    "Membership Termination Request",
                    result["termination_request"],
                    "status",
                    "Cancelled",
                )
                frappe.db.set_value("Membership Termination Request", doc.name, "status", "Cancelled")

    # ============================================================ validate invariant (Pending)

    def test_validate_pending_disciplinary_requires_secondary_approver(self):
        # Regression: validate_termination_request compared status to the
        # impossible "Pending Approval", so the secondary-approver invariant for a
        # Pending disciplinary request never fired. Saving a Pending disciplinary
        # request with no secondary_approver must now raise.
        doc = self._make_disciplinary_request()
        doc.status = "Pending"
        doc.secondary_approver = None
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_validate_pending_disciplinary_passes_with_secondary_approver(self):
        approver = self.create_test_user(
            f"sec.ok.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Administrator"],
        )
        doc = self._make_disciplinary_request()
        doc.status = "Pending"
        doc.secondary_approver = approver.name
        # Must not raise.
        doc.save()
        doc.reload()
        self.assertEqual(doc.status, "Pending")
        self.assertEqual(doc.secondary_approver, approver.name)

    # ============================================================ eligible approvers

    def test_get_eligible_approvers_returns_admin(self):
        user = self.create_test_user(
            f"approver.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Administrator"],
        )
        approvers = mtr.get_eligible_approvers(txt=user.name)
        ids = {row[0] for row in approvers}
        self.assertIn(user.name, ids)

    def test_get_eligible_approvers_empty_for_unknown(self):
        approvers = mtr.get_eligible_approvers(txt="zzz-no-such-user-zzz")
        self.assertEqual(approvers, [])

    # ============================================================ expulsion report

    def test_generate_expulsion_report_includes_disciplinary(self):
        doc = self._make_disciplinary_request(termination_type="Expulsion")
        # Give it a termination_date so the date filters can match it.
        report = mtr.generate_expulsion_report({})
        self.assertTrue(report["success"])
        names = {e["termination_request"] for e in report["expulsions"]}
        self.assertIn(doc.name, names)
        self.assertIn("summary", report)
        self.assertGreaterEqual(report["summary"]["total_expulsions"], 1)

    def test_generate_expulsion_report_filter_by_type(self):
        self._make_disciplinary_request(termination_type="Expulsion")
        report = mtr.generate_expulsion_report({"termination_type": "Disciplinary Action"})
        # No Disciplinary Action requests created -> our Expulsion row excluded.
        self.assertTrue(report["success"])
        types = {e["termination_type"] for e in report["expulsions"]}
        self.assertNotIn("Expulsion", types)

    # ============================================================ disciplinary initiation

    def test_initiate_disciplinary_termination_honors_type_and_approver(self):
        """The chosen disciplinary subtype and secondary approver (collected by the
        dialog) must be applied, and the result must expose request_id for the UI."""
        with self.assertNoErrorLog():
            result = mtr.initiate_disciplinary_termination(
                member=self.member.name,
                reason="Grave misconduct",
                evidence="<p>Documented incident report.</p>",
                termination_type="Expulsion",
                secondary_approver="Administrator",
            )
        self.assertTrue(result["success"], msg=result.get("error"))
        self.track_doc("Membership Termination Request", result["termination_request"])
        doc = frappe.get_doc("Membership Termination Request", result["termination_request"])
        self.assertEqual(doc.termination_type, "Expulsion")
        self.assertEqual(doc.secondary_approver, "Administrator")
        self.assertEqual(result["request_id"], result["termination_request"])

    def test_initiate_disciplinary_termination_rejects_non_disciplinary_type(self):
        """A non-disciplinary termination_type must be rejected, not silently created."""
        result = mtr.initiate_disciplinary_termination(
            member=self.member.name, reason="x", termination_type="Voluntary"
        )
        self.assertFalse(result["success"])

    def test_initiate_disciplinary_termination_requires_member(self):
        result = mtr.initiate_disciplinary_termination(member="", reason="x")
        self.assertFalse(result["success"])

    def test_initiate_disciplinary_termination_requires_reason(self):
        result = mtr.initiate_disciplinary_termination(member=self.member.name, reason="")
        self.assertFalse(result["success"])

    def test_initiate_disciplinary_termination_creates_valid_request(self):
        """The happy path must actually create a disciplinary request (Draft).

        Regression: the function set termination_type='Disciplinary' (not a valid
        Select option) and wrote evidence to a non-existent 'supporting_documentation'
        field, so every call failed on insert/validation and silently returned
        {"success": False} into the Error Log. It must produce a real Draft request
        whose type is recognised by the disciplinary workflow.
        """
        with self.assertNoErrorLog():
            result = mtr.initiate_disciplinary_termination(
                member=self.member.name,
                reason="Serious breach of code of conduct",
                evidence="<p>Documented incident report attached.</p>",
            )
        self.assertTrue(result["success"], msg=result.get("error"))
        name = result["termination_request"]
        self.track_doc("Membership Termination Request", name)
        doc = frappe.get_doc("Membership Termination Request", name)
        # type must be one the disciplinary workflow recognises
        self.assertIn(doc.termination_type, ["Policy Violation", "Disciplinary Action", "Expulsion"])
        self.assertTrue(doc.disciplinary_documentation)
        self.assertEqual(doc.status, "Draft")

    # ============================================================ permission guard

    def test_validate_permissions_denies_unprivileged_user(self):
        # A plain member with no termination rights must be blocked from creating
        # a termination request (validate_permissions throws).
        unprivileged = self.create_test_user(
            f"plain.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        with self.as_user(unprivileged.name):
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(
                    {
                        "doctype": "Membership Termination Request",
                        "member": self.member.name,
                        "termination_type": "Voluntary",
                        "termination_reason": "self-requested",
                        "member_request_date": today(),
                    }
                ).insert()
