# -*- coding: utf-8 -*-
"""
Coverage-focused integration tests for the Membership Termination Request controller.

Covers validation branches (date ordering, grace-period termination-date calculation,
member-status guards, disciplinary documentation/approver rules, commitment-period
enforcement) and the module-level reporting / disciplinary-initiation APIs that the
existing test files leave uncovered. Real-DB integration tests only.
"""

import unittest

import frappe
from frappe.utils import add_days, add_months, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
    generate_expulsion_report,
    get_member_termination_history,
    get_termination_statistics,
    initiate_disciplinary_termination,
)


class TestMembershipTerminationRequestCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Term",
            last_name="Coverage",
            status="Active",
            member_since=add_months(today(), -18),
        )

    def _new_request(self, **kwargs):
        data = {
            "doctype": "Membership Termination Request",
            "member": self.member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Test",
            "request_date": today(),
        }
        data.update(kwargs)
        return frappe.get_doc(data)

    # ------------------------------------------------------------------
    # calculate_termination_date
    # ------------------------------------------------------------------
    def test_termination_date_defaults_to_request_date(self):
        """Without grace period, termination_date defaults to the member request date."""
        req = self._new_request(member_request_date=add_days(today(), 2), apply_grace_period=0)
        req.insert()
        self.assertEqual(
            frappe.utils.getdate(req.termination_date), frappe.utils.getdate(add_days(today(), 2))
        )

    def test_termination_date_with_grace_period(self):
        """With grace period applied, termination_date = request date + grace days."""
        settings = frappe.get_cached_doc("Verenigingen Settings")
        grace_days = settings.default_grace_period_days or 30
        req_date = today()
        req = self._new_request(member_request_date=req_date, apply_grace_period=1)
        req.insert()
        self.assertEqual(
            frappe.utils.getdate(req.termination_date),
            frappe.utils.getdate(add_days(req_date, grace_days)),
        )

    def test_termination_date_defaults_to_today_without_request_date(self):
        """An Administrative termination with no member_request_date uses today()."""
        req = self._new_request(termination_type="Administrative", member_request_date=None)
        req.insert()
        self.assertEqual(frappe.utils.getdate(req.termination_date), frappe.utils.getdate(today()))

    # ------------------------------------------------------------------
    # validate_dates
    # ------------------------------------------------------------------
    def test_termination_before_request_date_throws(self):
        """A termination_date earlier than member_request_date is rejected."""
        req = self._new_request(
            member_request_date=today(),
            termination_date=add_days(today(), -5),
            apply_grace_period=0,
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            req.insert()
        self.assertIn("before member request date", str(ctx.exception).lower())

    # ------------------------------------------------------------------
    # validate_termination_request -- member status guards
    # ------------------------------------------------------------------
    def test_cannot_terminate_quit_member(self):
        """A member already in a terminal status (Quit) cannot be terminated again."""
        frappe.db.set_value("Member", self.member.name, "status", "Quit")
        frappe.db.commit()
        try:
            req = self._new_request()
            with self.assertRaises(frappe.ValidationError) as ctx:
                req.insert()
            self.assertIn("cannot terminate", str(ctx.exception).lower())
        finally:
            frappe.db.set_value("Member", self.member.name, "status", "Active")
            frappe.db.commit()

    def test_nonexistent_member_throws(self):
        req = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": "NO-SUCH-MEMBER-XYZ",
                "termination_type": "Voluntary",
                "termination_reason": "x",
                "request_date": today(),
            }
        )
        with self.assertRaises(frappe.ValidationError):
            req.insert()

    # ------------------------------------------------------------------
    # validate_termination_request -- disciplinary rules
    # ------------------------------------------------------------------
    def test_disciplinary_requires_documentation(self):
        """A disciplinary termination without documentation is rejected."""
        req = self._new_request(
            termination_type="Policy Violation",
            termination_reason="Misconduct",
            disciplinary_documentation=None,
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            req.insert()
        self.assertIn("documentation is required", str(ctx.exception).lower())

    def test_disciplinary_with_documentation_inserts(self):
        """A disciplinary termination WITH documentation inserts cleanly in Draft."""
        req = self._new_request(
            termination_type="Disciplinary Action",
            termination_reason="Misconduct",
            disciplinary_documentation="Evidence attached",
        )
        with self.assertNoErrorLog():
            req.insert()
        self.assertEqual(req.status, "Draft")
        self.assertEqual(req.termination_type, "Disciplinary Action")

    # ------------------------------------------------------------------
    # validate_commitment_period
    # ------------------------------------------------------------------
    def test_voluntary_before_commitment_end_throws(self):
        """A voluntary termination before the membership commitment end date is rejected."""
        # Create an active membership with a commitment_end_date in the future
        mt = self.create_test_membership_type(membership_type_name="Term Commit", amount=25.0)
        membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=mt.name,
            start_date=today(),  # commitment ends ~1 year out
        )
        frappe.db.set_value("Member", self.member.name, "current_membership_plan", membership.name)
        frappe.db.commit()

        req = self._new_request(
            termination_type="Voluntary",
            member_request_date=today(),
            termination_date=today(),  # well before commitment end (1 year out)
            apply_grace_period=0,
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            req.insert()
        self.assertIn("commitment", str(ctx.exception).lower())

    def test_voluntary_allowed_when_no_commitment(self):
        """A voluntary termination is allowed when the member has no commitment period."""
        # Member has no current_membership_plan -> no commitment -> allowed
        frappe.db.set_value("Member", self.member.name, "current_membership_plan", None)
        frappe.db.commit()
        req = self._new_request(termination_type="Voluntary")
        with self.assertNoErrorLog():
            req.insert()
        self.assertTrue(req.name)

    # ------------------------------------------------------------------
    # get_member_termination_history
    # ------------------------------------------------------------------
    def test_get_member_termination_history(self):
        """History returns inserted requests for the member with audit trails."""
        req = self._new_request(termination_reason="History test")
        req.insert()
        with self.assertNoErrorLog():
            result = get_member_termination_history(self.member.name)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["total_requests"], 1)
        names = [r["name"] for r in result["termination_requests"]]
        self.assertIn(req.name, names)
        # The inserted request must carry a NON-EMPTY audit trail: after_insert logs
        # a "request created" entry, so an empty trail would signal lost audit logging.
        our_request = next(r for r in result["termination_requests"] if r["name"] == req.name)
        self.assertIsInstance(our_request["audit_trail"], list)
        self.assertGreaterEqual(
            len(our_request["audit_trail"]), 1, "Inserted request should have an audit-trail entry"
        )

    # ------------------------------------------------------------------
    # get_termination_statistics
    # ------------------------------------------------------------------
    def test_get_termination_statistics(self):
        """Statistics aggregate counts by status and type and include recent counts."""
        req = self._new_request(termination_type="Voluntary", termination_reason="Stats test")
        req.insert()
        with self.assertNoErrorLog():
            result = get_termination_statistics()
        self.assertTrue(result["success"])
        stats = result["statistics"]
        self.assertIn("total_requests", stats)
        self.assertIn("by_status", stats)
        self.assertIn("by_type", stats)
        self.assertIn("recent_requests", stats)
        self.assertIn("pending_approvals", stats)
        self.assertGreaterEqual(stats["total_requests"], 1)
        # Our Draft Voluntary request must be reflected in the breakdowns
        self.assertGreaterEqual(stats["by_status"].get("Draft", 0), 1)
        self.assertGreaterEqual(stats["by_type"].get("Voluntary", 0), 1)

    # ------------------------------------------------------------------
    # generate_expulsion_report
    # ------------------------------------------------------------------
    def test_generate_expulsion_report_includes_disciplinary(self):
        """The expulsion report includes disciplinary requests and summarises by type."""
        req = self._new_request(
            termination_type="Expulsion",
            termination_reason="Serious violation",
            disciplinary_documentation="Documented",
            member_request_date=None,
        )
        req.insert()
        with self.assertNoErrorLog():
            result = generate_expulsion_report({})
        self.assertTrue(result["success"])
        names = [e["termination_request"] for e in result["expulsions"]]
        self.assertIn(req.name, names)
        self.assertGreaterEqual(result["summary"]["total_expulsions"], 1)
        self.assertGreaterEqual(result["summary"]["by_type"].get("Expulsion", 0), 1)

    def test_generate_expulsion_report_filters_by_type(self):
        """Filtering by a disciplinary type returns only that type."""
        req = self._new_request(
            termination_type="Policy Violation",
            termination_reason="Policy breach",
            disciplinary_documentation="Documented",
            member_request_date=None,
        )
        req.insert()
        result = generate_expulsion_report({"termination_type": "Policy Violation"})
        self.assertTrue(result["success"])
        # The filtered request must be present...
        self.assertIn(req.name, [e["termination_request"] for e in result["expulsions"]])
        # ...and every returned row must match the requested type.
        for e in result["expulsions"]:
            self.assertEqual(e["termination_type"], "Policy Violation")

    # ------------------------------------------------------------------
    # initiate_disciplinary_termination
    # ------------------------------------------------------------------
    def test_initiate_disciplinary_creates_draft_request(self):
        """initiate_disciplinary_termination creates a Draft disciplinary request with evidence."""
        with self.assertNoErrorLog():
            result = initiate_disciplinary_termination(
                member=self.member.name,
                reason="Repeated misconduct",
                evidence="Photographic evidence",
                termination_type="Disciplinary Action",
            )
        self.assertTrue(result["success"], result)
        req_name = result["request_id"]
        self.assertEqual(result["termination_request"], req_name)
        req = frappe.get_doc("Membership Termination Request", req_name)
        self.assertEqual(req.status, "Draft")
        self.assertEqual(req.termination_type, "Disciplinary Action")
        self.assertEqual(req.disciplinary_documentation, "Photographic evidence")
        self.assertEqual(req.termination_reason, "Repeated misconduct")

    def test_initiate_disciplinary_invalid_type_fails(self):
        """A non-disciplinary termination type is rejected by initiate_disciplinary_termination."""
        result = initiate_disciplinary_termination(
            member=self.member.name,
            reason="x",
            termination_type="Voluntary",
        )
        self.assertFalse(result["success"])
        self.assertIn("not a disciplinary type", result["error"].lower())

    def test_initiate_disciplinary_missing_reason_fails(self):
        result = initiate_disciplinary_termination(
            member=self.member.name,
            reason=None,
            termination_type="Expulsion",
        )
        self.assertFalse(result["success"])
        self.assertIn("reason is required", result["error"].lower())

    def test_initiate_disciplinary_duplicate_blocked(self):
        """A second disciplinary request while one is in progress is blocked."""
        first = initiate_disciplinary_termination(
            member=self.member.name,
            reason="First incident",
            evidence="ev",
            termination_type="Disciplinary Action",
        )
        self.assertTrue(first["success"], first)
        # Second attempt should be blocked because a Draft disciplinary request exists
        second = initiate_disciplinary_termination(
            member=self.member.name,
            reason="Second incident",
            evidence="ev2",
            termination_type="Expulsion",
        )
        self.assertFalse(second["success"])
        self.assertIn("already a pending disciplinary", second["error"].lower())


if __name__ == "__main__":
    unittest.main()
