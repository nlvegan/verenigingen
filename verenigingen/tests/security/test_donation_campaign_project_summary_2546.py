"""#2546: ``DonationCampaign.get_project_summary`` read Expense Claims (and the Project row and its
Tasks) with ``get_all``, so any reader of a campaign (Donation Campaign grants read to ``All``) got
other chapters' submitted claims: name, amount, date.

Driven through the real doc-method dispatch (``frappe.handler.run_doc_method``, which is what
``/api/method/run_doc_method`` calls) as a seated, non-admin Chapter Board Member of chapter A. The
claim under test belongs to chapter B. Fixture-built, no shortcuts besides: the claim's ``project``
is set by a real ``save`` before it is approved and submitted.
"""

import json
from types import SimpleNamespace

import frappe
from frappe.utils import flt

from verenigingen.tests.security.test_staff_expense_approval_1606 import StaffExpenseBase


class TestCampaignProjectSummaryClaimLeak(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        self.project = self._project_2546()
        self.campaign = self._campaign_2546(self.project)
        self.board_a = self.create_test_board_member(self.chapter_a.name, permissions_level="Financial")
        self.claim_b = self._submitted_claim_2546(self.volunteer_emp, self.chapter_b)

    # ---------------------------------------------------------------- fixtures
    def _project_2546(self):
        doc = frappe.get_doc(
            {
                "doctype": "Project",
                "project_name": f"P2546 {self.token}",
                "company": self.company,
                "status": "Open",
            }
        ).insert()
        self._track_test_document("Project", doc.name, priority=7)
        return doc

    def _campaign_2546(self, project):
        doc = frappe.get_doc(
            {
                "doctype": "Donation Campaign",
                "campaign_name": f"C2546 {project.name} {self.token}",
                "campaign_type": "Project Funding",
                "status": "Active",
                "start_date": frappe.utils.today(),
                "project": project.name,
            }
        ).insert()
        self._track_test_document("Donation Campaign", doc.name, priority=8)
        return doc

    def _submitted_claim_2546(self, employee, chapter):
        claim = self.claim(employee, chapter=chapter)
        claim.project = self.project.name
        claim.save()
        claim.approval_status = "Approved"
        claim.submit()
        return claim

    def _summary_as_2546(self, user, campaign=None, forge_owner=False):
        """The browser's call: run_doc_method builds the doc from the client's dict, as `user`."""
        from frappe.handler import run_doc_method

        doc = frappe.get_doc("Donation Campaign", (campaign or self.campaign).name).as_dict()
        if forge_owner:
            doc["owner"] = user if isinstance(user, str) else user.name
        request = SimpleNamespace(  # Mock justified: Infrastructure (security decorator reads it)
            method="POST", path="/api/method/run_doc_method", headers={}, remote_addr="127.0.0.1",
            environ={}, args={}, form={}, get_data=lambda *a, **k: b"{}", content_length=2,
        )
        previous_user, previous_request = frappe.session.user, getattr(frappe.local, "request", None)
        previous_response = frappe.local.response
        frappe.set_user(user if isinstance(user, str) else user.name)
        frappe.local.request = request  # Mock justified: Infrastructure
        frappe.local.response = frappe._dict(docs=[])
        try:
            run_doc_method(method="get_project_summary", docs=json.dumps(doc, default=str))
            # serialised as the HTTP layer does, so the test sees the wire shape
            return json.loads(frappe.as_json(frappe.local.response.get("message")))
        finally:
            frappe.set_user(previous_user)
            frappe.local.request = previous_request  # Mock justified: Infrastructure (restore)
            frappe.local.response = previous_response  # Mock justified: Infrastructure (restore)

    def _claim_names_2546(self, summary):
        return [e.get("name") for e in (summary or {}).get("expenses", [])]

    # ---------------------------------------------------------------- tests
    def test_precondition_board_member_of_a_cannot_read_the_claim_of_b(self):
        self.assertFalse(
            frappe.has_permission("Expense Claim", "read", doc=self.claim_b.name, user=self.board_a.user),
            "control: the premise of the issue",
        )

    def test_a_board_member_of_a_sees_no_claim_of_chapter_b(self):
        summary = self._summary_as_2546(self.board_a.user)
        self.assertNotIn(self.claim_b.name, self._claim_names_2546(summary))
        self.assertNotIn(self.claim_b.name, json.dumps(summary, default=str))
        self.assertEqual(flt(summary["total_expenses"]), 0)

    def test_a_caller_with_read_on_the_claim_still_sees_it(self):
        # control: Verenigingen Administrator (reads every claim and the campaign) must still list it
        summary = self._summary_as_2546(self.admin)
        self.assertIn(self.claim_b.name, self._claim_names_2546(summary))
        self.assertEqual(flt(summary["total_expenses"]), flt(self.claim_b.total_claimed_amount))

    def test_a_board_member_of_b_sees_the_claim_of_b(self):
        # control with a real row for the wrong fix (hide-everything) to find
        board_b = self.create_test_board_member(self.chapter_b.name, permissions_level="Financial")
        self.assertTrue(
            frappe.has_permission("Expense Claim", "read", doc=self.claim_b.name, user=board_b.user),
            "precondition",
        )
        self.assertIn(self.claim_b.name, self._claim_names_2546(self._summary_as_2546(board_b.user)))

    def test_a_volunteer_forging_the_owner_in_the_posted_doc_sees_no_claim_of_chapter_b(self):
        """run_doc_method builds the campaign from the CLIENT's dict, and Donation Campaign grants
        read to All with if_owner, so a caller who lacks the Accounts User role passes the doc check
        by posting owner=themselves. Measured on develop: they got the claim."""
        caller = self._staffexp_user("Verenigingen Volunteer", "forger")
        self.assertFalse(
            frappe.has_permission("Expense Claim", "read", doc=self.claim_b.name, user=caller.name),
            "precondition: the caller cannot read the claim",
        )
        summary = self._summary_as_2546(caller.name, forge_owner=True)
        self.assertNotIn(self.claim_b.name, json.dumps(summary, default=str))
        self.assertEqual(flt(summary["total_expenses"]), 0)

    def test_a_caller_without_expense_claim_read_gets_an_empty_list_not_an_error(self):
        """The doctype-level pre-check: get_list would raise for a caller with no Expense Claim role,
        which would also tell them apart from a project without claims. Only roles that pass the
        security tier and the campaign check (via the forged owner) are in play here."""
        caller = self.create_test_user(
            email=f"x2546-noread-{self.token}@test.com", roles=["Verenigingen Volunteer"]
        )
        self.assertFalse(
            self.act_as(caller, lambda: frappe.has_permission("Expense Claim", "read")),
            "precondition: no doctype-level Expense Claim read",
        )
        summary = self._summary_as_2546(caller.name, forge_owner=True)
        self.assertEqual(summary["expenses"], [])
        self.assertEqual(flt(summary["total_expenses"]), 0)

    def test_guest_cannot_reach_the_method_even_with_a_forged_owner(self):
        with self.assertRaises(frappe.PermissionError):
            self._summary_as_2546("Guest", forge_owner=True)

    def test_the_project_row_does_not_carry_the_claim_rollup(self):
        """Project.total_expense_claim is the sum of EVERY submitted claim on the project, and
        gross_margin / per_gross_margin are derived from it (HRMS EmployeeProject)."""
        stored = frappe.db.get_value("Project", self.project.name, "total_expense_claim")
        self.assertEqual(flt(stored), flt(self.claim_b.total_sanctioned_amount), "precondition: it is rolled up")
        project = self._summary_as_2546(self.board_a.user)["project"]
        for fieldname in ("total_expense_claim", "gross_margin", "per_gross_margin"):
            self.assertNotIn(fieldname, project, fieldname)
        self.assertEqual(project.get("name"), self.project.name, "control: the project is still described")

    def test_summary_does_not_differ_by_whether_foreign_claims_exist(self):
        """Existence oracle, on every channel: a second campaign whose project has NO claim."""
        other_project = frappe.get_doc(
            {"doctype": "Project", "project_name": f"P2546b {self.token}", "company": self.company,
             "status": "Open"}
        ).insert()
        self._track_test_document("Project", other_project.name, priority=7)
        other_campaign = self._campaign_2546(other_project)

        def observe(campaign):
            log_before = len(frappe.local.message_log)
            errors_before = frappe.db.count("Error Log")
            summary = self._summary_as_2546(self.board_a.user, campaign=campaign)
            return {
                "expenses": summary["expenses"],
                "total_expenses": summary["total_expenses"],
                "tasks": summary["tasks"],
                "project_keys": sorted(summary["project"]),
                "rollup": [flt(summary["project"].get(k)) for k in ("gross_margin", "per_gross_margin")],
                "message_log": len(frappe.local.message_log) - log_before,
                "error_logs": frappe.db.count("Error Log") - errors_before,
            }

        self.assertEqual(observe(self.campaign), observe(other_campaign))
