# #1784: the Periodic Donation Agreement Workflow could not leave Draft. Its
# "Pending Verification" state wrote update_field=status / update_value="Pending
# Verification", but the `status` Select only allows Draft/Active/Completed/Cancelled,
# so apply_workflow raised on the very first transition.
#
# Every workflow state below is driven through the REAL apply_workflow, never by
# setting `status` or `workflow_state` directly.

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, today

from verenigingen.tests.backend.components.test_workflow_action_masters import (
    _shipped_workflows,
    _wf1700_load_fixture as _fixture_rows,
)
from verenigingen.tests.utils.base import VereningingenTestCase

WORKFLOW = "Periodic Donation Agreement Workflow"
DOCTYPE = "Periodic Donation Agreement"


class TestShippedWorkflowStatusValues(VereningingenTestCase):
    """Static sweep: update_value must be an option of the Select it writes."""

    def test_every_update_value_is_an_option_of_its_select(self):
        workflows = _shipped_workflows()
        self.assertTrue(workflows, "control: the sweep must find at least one shipped workflow")
        checked = 0
        bad = []
        for wf in workflows:
            meta = frappe.get_meta(wf["document_type"])
            for state in wf["states"]:
                field = state.get("update_field")
                if not field:
                    continue
                df = meta.get_field(field)
                if df is None or df.fieldtype != "Select":
                    continue
                checked += 1
                options = (df.options or "").split("\n")
                if state["update_value"] not in options:
                    bad.append((wf["name"], state["state"], field, state["update_value"]))
        self.assertGreater(checked, 0, "control: no Select-writing state was checked")
        self.assertFalse(bad, f"workflow states writing a value their Select rejects: {bad}")


class TestPeriodicDonationAgreementWorkflow(VereningingenTestCase):
    """Lifecycle through apply_workflow, with the shipped fixture as the workflow."""

    def _load_shipped_workflow(self):
        # Per test, not per class: the harness rolls back after EVERY test method, which
        # would otherwise revert this load after the first test and leave the site's
        # (possibly pre-fix) workflow in place for the rest.
        # Load the shipped fixture over whatever the site holds.
        if frappe.db.exists("Workflow", WORKFLOW):
            frappe.delete_doc("Workflow", WORKFLOW, force=True, ignore_permissions=True)
        for row in _fixture_rows("workflow_action_master.json"):
            frappe.get_doc(row).insert(ignore_if_duplicate=True)
        for row in _shipped_workflows():
            if row["name"] == WORKFLOW:
                frappe.get_doc(row).insert(ignore_links=True)
        # get_workflow() reads through the document cache; drop what the old row left there.
        frappe.clear_document_cache("Workflow", WORKFLOW)
        frappe.cache.hdel("workflow", DOCTYPE)

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._load_shipped_workflow()
        # Non-ANBI pledge: the ANBI path needs a consenting, BSN-verified donor, which the
        # workflow does not care about.
        self.agreement = self.create_test_periodic_donation_agreement(
            anbi_eligible=0, agreement_duration_years="1 Year (Pledge - No ANBI benefits)"
        )
        # allow_self_approval=0 transitions are hidden from the document's owner.
        frappe.db.set_value(DOCTYPE, self.agreement.name, "owner", "guest@example.com", update_modified=False)

    def _step(self, action):
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        apply_workflow(doc, action)
        return frappe.get_doc(DOCTYPE, self.agreement.name)

    def _prepare(self, **values):
        for key, value in values.items():
            frappe.db.set_value(DOCTYPE, self.agreement.name, key, value, update_modified=False)

    def _assert_at(self, doc, workflow_state, status):
        self.assertEqual(doc.workflow_state, workflow_state)
        self.assertEqual(doc.status, status)
        self.assertEqual(doc.docstatus, 0)

    def test_fixture_precondition_draft_start(self):
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        self._assert_at(doc, "Draft", "Draft")

    def test_full_lifecycle_to_completed(self):
        doc = self._step("Submit for Verification")
        # Pending Verification has no Select value of its own: status stays Draft.
        self._assert_at(doc, "Pending Verification", "Draft")
        self._prepare(donor_signature_received=1)
        doc = self._step("Verify and Activate")
        self._assert_at(doc, "Active", "Active")
        self._prepare(start_date=add_days(today(), -400), end_date=add_days(today(), -1))
        doc = self._step("Complete Agreement")
        self._assert_at(doc, "Completed", "Completed")

    def test_return_to_draft(self):
        self._step("Submit for Verification")
        doc = self._step("Return to Draft")
        self._assert_at(doc, "Draft", "Draft")

    def test_cancel_from_draft(self):
        self._prepare(cancellation_reason="donor request")
        doc = self._step("Cancel Agreement")
        self._assert_at(doc, "Cancelled", "Cancelled")

    def test_cancel_from_pending_verification(self):
        self._step("Submit for Verification")
        self._prepare(cancellation_reason="donor request")
        doc = self._step("Cancel Agreement")
        self._assert_at(doc, "Cancelled", "Cancelled")

    def test_cancel_from_active(self):
        self._step("Submit for Verification")
        self._prepare(donor_signature_received=1)
        self._step("Verify and Activate")
        self._prepare(cancellation_reason="donor request")
        doc = self._step("Cancel Agreement")
        self._assert_at(doc, "Cancelled", "Cancelled")

    def _active(self):
        self._step("Submit for Verification")
        self._prepare(donor_signature_received=1)
        return self._step("Verify and Activate")

    def test_complete_is_offered_only_once_the_end_date_is_reached(self):
        """Control for the Complete Agreement condition: a future end_date must NOT offer it,
        an end_date of today (or earlier) must."""
        from frappe.model.workflow import get_transitions

        self._active()
        self._prepare(start_date=add_days(today(), -400), end_date=add_days(today(), 30))
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        self.assertNotIn("Complete Agreement", [t.action for t in get_transitions(doc)])
        self._prepare(end_date=today())
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        self.assertIn("Complete Agreement", [t.action for t in get_transitions(doc)])
