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
        with self.assertRaisesRegex(frappe.ValidationError, "Verify and Activate"):
            self._button_save()
        self._assert_unchanged("Pending Verification")

    def test_button_refused_from_draft(self):
        self._as_web_request()
        with self.assertRaisesRegex(frappe.ValidationError, "Verify and Activate"):
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
        with self.assertRaisesRegex(frappe.ValidationError, "Verify and Activate"):
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

    # --- #1850: Completed/Cancelled only through the workflow. Accounts User holds doctype
    # write but no workflow transition, so a plain status write used to bypass the workflow's
    # roles and its end_date condition. Callers below are real least-privileged users, and the
    # entry points are the real dispatchers (frappe.client.*, run_doc_method), not doc.save().

    def _create_pda_user(self, role=None, profile=None):
        """A user holding `role`, or the roles of Role Profile `profile`.

        cancel_agreement sits behind a HIGH security tier that needs a role profile, so the
        realistic writer for it is Verenigingen Staff (its profile carries Accounts User).
        """
        name = (profile or role).lower().replace(" ", "-")
        email = f"pda-1850-{name}@example.com"
        if not frappe.db.exists("User", email):
            data = {"doctype": "User", "email": email, "first_name": "PDA1850", "send_welcome_email": 0}
            if profile:
                data["role_profile_name"] = profile
            else:
                data["roles"] = [{"role": role}]
            user = frappe.get_doc(data)
            user.flags.ignore_permissions = True
            user.insert()
            self.track_doc("User", email)
        return email

    def _as_admin_1850(self):
        frappe.set_user("Administrator")

    def _as_request(self, user):
        """Dispatcher-style call context: a POST request, then the given session user."""
        previous = getattr(frappe.local, "request", None)
        frappe.local.request = frappe._dict(  # Mock justified: Infrastructure - simulate a web request
            path="/api/method/x", method="POST", headers={}, environ={"REMOTE_ADDR": "127.0.0.1"}
        )
        self.addCleanup(lambda: setattr(frappe.local, "request", previous))
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user(user)

    def _pda_status(self):
        return frappe.db.get_value(DOCTYPE, self.agreement.name, ["status", "workflow_state"], as_dict=True)

    def _cancel_via_dispatcher(self, reason="donor request"):
        from frappe.handler import run_doc_method

        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        frappe.response.pop("message", None)
        run_doc_method(method="cancel_agreement", docs=doc.as_json(), args={"reason": reason})
        return frappe.response.get("message")

    def _make_end_date_reached(self):
        self._prepare(start_date=add_days(today(), -400), end_date=add_days(today(), -1))

    def _writer_refused(self, call):
        """Accounts User must be refused by the guard, and the row must not move."""
        before = self._pda_status()
        user = self._create_pda_user(role="Accounts User")
        self._as_request(user)
        with self.assertRaisesRegex(frappe.ValidationError, "matching workflow action"):
            call()
        self._as_admin_1850()
        self.assertEqual(self._pda_status(), before)

    def test_set_value_to_cancelled_refused_for_accounts_user(self):
        self._active()
        self._writer_refused(
            lambda: frappe.client.set_value(DOCTYPE, self.agreement.name, "status", "Cancelled")
        )

    def test_set_value_to_completed_refused_for_accounts_user(self):
        self._active()
        self._make_end_date_reached()
        self._writer_refused(
            lambda: frappe.client.set_value(DOCTYPE, self.agreement.name, "status", "Completed")
        )

    def test_client_save_to_cancelled_refused_for_accounts_user(self):
        self._active()

        def call():
            doc = frappe.get_doc(DOCTYPE, self.agreement.name).as_dict()
            doc["status"] = "Cancelled"
            frappe.client.save(doc)

        self._writer_refused(call)

    def test_flags_in_a_client_body_do_not_bypass(self):
        """A REST/client body can carry `flags`; they must not be an escape hatch.

        Measured: Frappe drops a body `flags` key when it builds the doc (the control below
        pins that), so a flags-keyed bypass in the guard would be unreachable from a body
        anyway; the refusal is asserted regardless."""
        self._active()
        probe = frappe.get_doc({"doctype": DOCTYPE, "flags": {"ignore_permissions": True, "in_import": True}})
        self.assertFalse(probe.flags.get("ignore_permissions") or probe.flags.get("in_import"))

        def call():
            doc = frappe.get_doc(DOCTYPE, self.agreement.name).as_dict()
            doc.update({"status": "Cancelled", "flags": {"ignore_permissions": True, "in_import": True}})
            frappe.client.save(doc)

        self._writer_refused(call)

    def test_cancel_agreement_refused_for_staff_with_accounts_user_write(self):
        """The whitelisted method used to cancel with a plain save for anyone with write."""
        self._active()
        before = self._pda_status()
        self._as_request(self._create_pda_user(profile="Verenigingen Staff"))
        with self.assertRaises(frappe.ValidationError):
            self._cancel_via_dispatcher()
        self._as_admin_1850()
        self.assertEqual(self._pda_status(), before)

    def test_cancel_agreement_works_for_verenigingen_administrator_from_active(self):
        """Control, real row: the workflow's own role cancels an Active agreement."""
        self._active()
        self._as_request(self._create_pda_user(profile="Verenigingen Administrator"))
        self.assertTrue(self._cancel_via_dispatcher("moved abroad"))
        self._as_admin_1850()
        state = self._pda_status()
        self.assertEqual((state.status, state.workflow_state), ("Cancelled", "Cancelled"))
        row = frappe.db.get_value(
            DOCTYPE,
            self.agreement.name,
            ["cancellation_reason", "cancellation_date", "cancellation_processed_by"],
            as_dict=True,
        )
        self.assertEqual(row.cancellation_reason, "moved abroad")
        self.assertEqual(str(row.cancellation_date), today())
        self.assertEqual(row.cancellation_processed_by, "pda-1850-verenigingen-administrator@example.com")

    def test_cancel_agreement_from_draft_needs_system_manager(self):
        """Workflow roles apply per source state: Draft -> Cancelled is System Manager only.
        Staff holds Accounts User write and passes the security tier, so only the workflow stops it."""
        self._as_request(self._create_pda_user(profile="Verenigingen Staff"))
        with self.assertRaises(frappe.ValidationError):
            self._cancel_via_dispatcher()
        self._as_admin_1850()
        self.assertEqual(self._pda_status().status, "Draft")
        self._as_request(self._create_pda_user(profile="Verenigingen System Administrator"))
        self.assertTrue(self._cancel_via_dispatcher())
        self._as_admin_1850()
        self.assertEqual(self._pda_status().status, "Cancelled")

    def test_owner_va_can_cancel_own_active_agreement(self):
        """Maintainer ruling: allow self-cancel. The agreement is OWNED by the very user who
        cancels it (the setUp owner is replaced by a stranger, so this must be set explicitly)."""
        va = self._create_pda_user(profile="Verenigingen Administrator")
        self._active()
        frappe.db.set_value(DOCTYPE, self.agreement.name, "owner", va, update_modified=False)
        self._as_request(va)
        self.assertTrue(self._cancel_via_dispatcher())
        self._as_admin_1850()
        self.assertEqual(self._pda_status().status, "Cancelled")

    def test_status_and_workflow_state_that_disagree_are_refused(self):
        """N1: workflow_state moved (to Cancelled) but status says Completed. Only an exact
        match passes; 'workflow_state changed at all' is the wrong guard."""
        self._active()
        self._make_end_date_reached()
        self._prepare(cancellation_reason="donor request")
        self._as_request(self._create_pda_user(profile="Verenigingen Administrator"))
        doc = frappe.get_doc(DOCTYPE, self.agreement.name).as_dict()
        doc.update({"status": "Completed", "workflow_state": "Cancelled"})
        with self.assertRaisesRegex(frappe.ValidationError, "matching workflow action"):
            frappe.client.save(doc)
        self._as_admin_1850()
        state = self._pda_status()
        self.assertEqual((state.status, state.workflow_state), ("Active", "Active"))

    def test_system_manager_completes_after_end_date_through_the_workflow(self):
        self._active()
        self._make_end_date_reached()
        self._as_request(self._create_pda_user(profile="Verenigingen System Administrator"))
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        apply_workflow(doc, "Complete Agreement")
        self._as_admin_1850()
        state = self._pda_status()
        self.assertEqual((state.status, state.workflow_state), ("Completed", "Completed"))

    def test_internal_python_may_still_write_closing_statuses(self):
        """Scope control: no request, no guard (jobs, scripts, the existing suite)."""
        self.assertIsNone(getattr(frappe.local, "request", None))
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        doc.status = "Completed"
        doc.save()
        self.assertEqual(self._pda_status().status, "Completed")

    def test_saving_without_a_status_change_is_unaffected(self):
        """Control: a Cancelled agreement edited again (status unchanged) is not re-refused."""
        self._prepare(cancellation_reason="donor request")
        self._step("Cancel Agreement")
        self._as_request(self._create_pda_user(role="Accounts User"))
        doc = frappe.get_doc(DOCTYPE, self.agreement.name)
        doc.annual_amount = 1300
        doc.save()
        self._as_admin_1850()
        self.assertEqual(frappe.db.get_value(DOCTYPE, self.agreement.name, "annual_amount"), 1300)

    def test_insert_as_cancelled_refused_in_a_request(self):
        self._as_request(self._create_pda_user(profile="Verenigingen Administrator"))
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
                "status": "Cancelled",
            }
        )
        with self.assertRaisesRegex(frappe.ValidationError, "matching workflow action"):
            agreement.insert()

    def test_without_an_active_workflow_cancel_agreement_still_works(self):
        """The workflow-less fallback keeps the old direct save, as the activation guard does."""
        frappe.db.set_value("Workflow", WORKFLOW, "is_active", 0)
        frappe.clear_document_cache("Workflow", WORKFLOW)
        frappe.cache.hdel("workflow", DOCTYPE)
        frappe.clear_cache(doctype=DOCTYPE)
        self._as_request(self._create_pda_user(profile="Verenigingen Staff"))
        self.assertTrue(self._cancel_via_dispatcher())
        self._as_admin_1850()
        self.assertEqual(self._pda_status().status, "Cancelled")
