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

    def test_pending_verification_writes_no_status(self):
        """Pins the design choice: Pending Verification has no Select value of its own,
        so it must not write `status` at all (mapping it to "Draft" would also pass the
        lifecycle tests but hide the state's intent)."""
        workflow = frappe.get_doc("Workflow", WORKFLOW)
        state = next(s for s in workflow.states if s.state == "Pending Verification")
        self.assertFalse(state.update_field)
        self.assertFalse(state.update_value)

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

    # --- #1811: the form's "Activate Agreement" button must not bypass the workflow. It did
    # `frm.set_value('status', 'Active'); frm.save()`, a plain save skipping the "Verify and
    # Activate" transition and its condition; the server must refuse it while a workflow is active.

    def _as_web_request(self):
        """The guard applies to saves made inside a web request. The suite runs without one,
        so give frappe.local a request for the duration of the test (restored on cleanup)."""
        previous = getattr(frappe.local, "request", None)
        frappe.local.request = frappe._dict(  # Mock justified: Infrastructure - simulate a web request
            path="/api/method/frappe.desk.form.save.savedocs"
        )
        self.addCleanup(lambda: setattr(frappe.local, "request", previous))

    def _button_save(self):
        """What the button does server-side: set status Active on the loaded doc, save."""
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        doc.status = "Active"
        doc.save()

    def _assert_unchanged(self, workflow_state):
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        self.assertEqual((doc.workflow_state, doc.status), (workflow_state, "Draft"))

    def test_button_refused_in_pending_verification_without_signature(self):
        self._as_web_request()
        self._step("Submit for Verification")
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        # Control: the real transition's own condition is NOT met, so it is not offered.
        from frappe.model.workflow import get_transitions

        self.assertNotIn("Verify and Activate", [t.action for t in get_transitions(doc)])
        with self.assertRaises(frappe.ValidationError):
            self._button_save()
        self._assert_unchanged("Pending Verification")

    def test_button_refused_from_draft(self):
        self._as_web_request()
        with self.assertRaises(frappe.ValidationError):
            self._button_save()
        self._assert_unchanged("Draft")

    def test_insert_as_active_refused(self):
        self._as_web_request()
        agreement = frappe.new_doc(DOCTYPE)
        agreement.update(
            {
                "donor": self.agreement.donor,
                "start_date": today(),
                "annual_amount": 1200,
                "payment_frequency": "Monthly",
                "payment_method": "Bank Transfer",
                "agreement_duration_years": "1 Year (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,
                "status": "Active",
            }
        )
        with self.assertRaises(frappe.ValidationError):
            agreement.insert()

    def test_real_transition_still_activates(self):
        self._as_web_request()
        doc = self._active()
        self._assert_at(doc, "Active", "Active")

    def test_editing_an_active_agreement_is_not_blocked(self):
        """Control against over-blocking: status is already Active and does not change."""
        self._as_web_request()
        self._active()
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        doc.annual_amount = 1300
        doc.save()
        self.assertEqual(frappe.db.get_value(DOCTYPE, self.agreement.name, "status"), "Active")

    def test_editing_a_legacy_active_agreement_is_not_blocked(self):
        """Control: an agreement that is Active but whose workflow_state is still Draft (a
        row from before the workflow existed) must stay editable. PROBE SHORTCUT: the state is
        set with db.set_value, standing in for legacy data, because no real flow produces it
        any more. Without the was-Active check the guard would lock every such row."""
        self._as_web_request()
        frappe.db.set_value(DOCTYPE, self.agreement.name, "status", "Active", update_modified=False)
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        self.assertEqual((doc.status, doc.workflow_state), ("Active", "Draft"))
        doc.annual_amount = 1300
        doc.save()
        self.assertEqual(frappe.db.get_value(DOCTYPE, self.agreement.name, "annual_amount"), 1300)

    def test_without_an_active_workflow_a_plain_save_may_activate(self):
        """The guard is conditional on the workflow: with none active, status is the only
        state machine and a direct save is the legitimate way to move it."""
        self._as_web_request()
        frappe.db.set_value("Workflow", WORKFLOW, "is_active", 0)
        frappe.clear_document_cache("Workflow", WORKFLOW)
        frappe.cache.hdel("workflow", DOCTYPE)
        frappe.clear_cache(doctype=DOCTYPE)
        self._button_save()
        self.assertEqual(frappe.db.get_value(DOCTYPE, self.agreement.name, "status"), "Active")

    def test_internal_python_save_is_outside_the_guard(self):
        """Scope control: with no web request (scripts, jobs, the existing suite) the guard does
        not apply. Pins the documented scope so widening or narrowing it is a visible choice."""
        self.assertIsNone(getattr(frappe.local, "request", None))
        self._button_save()
        self.assertEqual(frappe.db.get_value(DOCTYPE, self.agreement.name, "status"), "Active")
