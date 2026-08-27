"""
Integration coverage for the expense-claim event chain.

Covers:
  * ``verenigingen/events/expense_events.py`` -- the emitters, action derivation,
    the subscriber registry, the ``_emit_expense_event`` enqueue logic, and the
    three ``*_background`` wrappers.
  * ``verenigingen/events/subscribers/expense_history_subscriber.py`` -- the five
    ``handle_expense_claim_*`` / ``handle_expense_payment_made`` handlers.
  * ``verenigingen/events/delayed_expense_hooks.py`` -- the
    ``schedule_member_expense_history_*`` doc-event handlers + the retry helpers.

Real Member / Volunteer / Employee / Expense Claim documents are built (no
business-logic mocking). The ONLY mocked boundary is ``frappe.enqueue`` -- the
emitters always enqueue (they do not honour ``run_events_synchronously``), so to
observe the event payload that would reach a subscriber we capture the enqueue
call. The subscribers themselves are then driven directly with real docs.

Subscribers swallow-and-log, so happy paths are wrapped in ``assertNoErrorLog``
and assert a real outcome; documented failure branches use ``expectErrorLog``.

NOTE: the Member ``volunteer_expenses`` child table was restored
(2026-06-22). The member-expense-history persistence path is now exercised by
``test_volunteer_expenses_history_restore.py``; this module covers the event
emitters, subscribers, and doc-event scheduling around it.
"""

from contextlib import contextmanager

import frappe
from frappe.utils import today

from verenigingen.events import delayed_expense_hooks as deh, expense_events as ee
from verenigingen.events.subscribers import expense_history_subscriber as ehs
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseEventsCoverage(EnhancedTestCase):
    """Real integration coverage for the expense event system."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _capture_enqueue(self):
        """Capture frappe.enqueue calls (infra boundary) instead of running jobs."""
        captured = []

        def fake_enqueue(method=None, **kw):
            captured.append({"method": method, **kw})

        saved = ee.frappe.enqueue
        ee.frappe.enqueue = fake_enqueue
        try:
            yield captured
        finally:
            ee.frappe.enqueue = saved

    def _company(self):
        return (
            "_Test Company"
            if frappe.db.exists("Company", "_Test Company")
            else (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        )

    def _accounts(self, company):
        expense = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        return expense, payable

    def _make_employee(self, company):
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Evt{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _make_volunteer_member_employee(self):
        """Member + Volunteer (linked to Employee via employee_id) + Employee."""
        company = self._company()
        if not company:
            self.skipTest("No Company available")
        member = self.create_test_member(first_name="Exp", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = self._make_employee(company)
        volunteer.db_set("employee_id", emp.name, update_modified=False)
        volunteer.reload()
        return member, volunteer, emp, company

    def _make_draft_expense_claim(self, employee, company):
        expense_acct, payable = self._accounts(company)
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available")
        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": 12.5,
                        "sanctioned_amount": 12.5,
                        "expense_date": today(),
                        "default_account": expense_acct,
                    }
                ],
            }
        )
        ec.insert(ignore_permissions=True)
        # Drained highest-first. Cancelling a submitted Expense Claim reads its
        # employee as the GL party, so the claim must outrank the Employee (2)
        # it points at -- see DRAIN_PRIORITY_BY_DOCTYPE.
        self._track_test_document("Expense Claim", ec.name, priority=6)
        return ec

    # ====================================================================
    # _resolve_volunteer_and_member
    # ====================================================================
    def test_resolve_returns_none_for_no_employee(self):
        self.assertEqual(ee._resolve_volunteer_and_member(None), (None, None))
        self.assertEqual(ee._resolve_volunteer_and_member(""), (None, None))

    def test_resolve_returns_none_for_unknown_employee(self):
        self.assertEqual(ee._resolve_volunteer_and_member("Employee-does-not-exist"), (None, None))

    def test_resolve_finds_volunteer_and_member(self):
        member, volunteer, emp, _company = self._make_volunteer_member_employee()
        vol_name, member_name = ee._resolve_volunteer_and_member(emp.name)
        self.assertEqual(vol_name, volunteer.name)
        self.assertEqual(member_name, member.name)

    # ====================================================================
    # emit_expense_claim_updated -- guards + payload + action derivation
    # ====================================================================
    def test_emit_updated_wrong_doctype_noop(self):
        fake = frappe._dict(doctype="Sales Invoice", docstatus=0)
        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                self.assertIsNone(ee.emit_expense_claim_updated(fake))
        self.assertEqual(cap, [])

    def test_emit_updated_cancelled_docstatus_noop(self):
        fake = frappe._dict(doctype="Expense Claim", docstatus=2, employee="x")
        with self._capture_enqueue() as cap:
            self.assertIsNone(ee.emit_expense_claim_updated(fake))
        self.assertEqual(cap, [])

    def test_emit_updated_non_volunteer_employee_noop(self):
        """An Expense Claim for an employee with NO volunteer link is skipped."""
        company = self._company()
        if not company:
            self.skipTest("No Company")
        emp = self._make_employee(company)  # no Volunteer points at this employee
        ec = self._make_draft_expense_claim(emp, company)
        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                ee.emit_expense_claim_updated(ec)
        self.assertEqual(cap, [], "non-volunteer expense must not enqueue history work")

    def test_emit_updated_draft_volunteer_claim_enqueues_with_payload(self):
        """A draft volunteer Expense Claim emits action='draft' with a full payload
        to the history subscriber.

        NOTE: ``_emit_expense_event`` has a member-serialized job-name branch gated
        on ``"payment_history" in subscriber``. None of the registered expense
        subscribers contain that substring (they are ``..._subscriber.handle_*``),
        so that branch is DEAD and the generic ``{event}_{claim}_{subscriber}``
        job name is always used. We assert the generic name to characterize the
        actual behaviour (see findings)."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)

        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                ee.emit_expense_claim_updated(ec)

        self.assertEqual(len(cap), 1)
        job = cap[0]
        self.assertEqual(
            job["method"],
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_claim_updated",
        )
        # Generic job name -- the member-serialized branch never fires here.
        self.assertTrue(job["job_name"].startswith(f"expense_claim_updated_{ec.name}_"))
        self.assertNotEqual(job["job_name"], f"expense_history_update_{member.name}")
        data = job["event_data"]
        self.assertEqual(data["expense_claim"], ec.name)
        self.assertEqual(data["member"], member.name)
        self.assertEqual(data["volunteer"], volunteer.name)
        self.assertEqual(data["employee"], emp.name)
        self.assertEqual(data["action"], "draft")
        self.assertEqual(data["docstatus"], 0)
        self.assertEqual(data["expense_type"], "Volunteer Expense")

    # ====================================================================
    # emit_expense_claim_approved -- guards
    # ====================================================================
    def test_emit_approved_draft_docstatus_noop(self):
        fake = frappe._dict(doctype="Expense Claim", docstatus=0)
        with self._capture_enqueue() as cap:
            self.assertIsNone(ee.emit_expense_claim_approved(fake))
        self.assertEqual(cap, [])

    def test_emit_approved_no_status_change_noop(self):
        """If approval_status did not change, nothing is emitted."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        # Simulate a submitted doc whose approval_status has NOT changed.
        ec.docstatus = 1
        ec.has_value_changed = lambda f: False
        with self._capture_enqueue() as cap:
            self.assertIsNone(ee.emit_expense_claim_approved(ec))
        self.assertEqual(cap, [])

    def test_emit_approved_changed_to_approved_enqueues(self):
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        ec.docstatus = 1
        ec.approval_status = "Approved"
        ec.has_value_changed = lambda f: f == "approval_status"
        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                ee.emit_expense_claim_approved(ec)
        self.assertEqual(len(cap), 1)
        self.assertEqual(cap[0]["event_data"]["action"], "approved")
        self.assertEqual(
            cap[0]["method"],
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_claim_approved",
        )

    def test_emit_approved_changed_to_rejected_enqueues_rejected(self):
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        ec.docstatus = 1
        ec.approval_status = "Rejected"
        ec.has_value_changed = lambda f: f == "approval_status"
        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                ee.emit_expense_claim_approved(ec)
        self.assertEqual(len(cap), 1)
        self.assertEqual(cap[0]["event_data"]["action"], "rejected")
        self.assertEqual(
            cap[0]["method"],
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_claim_rejected",
        )

    # ====================================================================
    # emit_expense_claim_cancelled
    # ====================================================================
    def test_emit_cancelled_wrong_docstatus_noop(self):
        fake = frappe._dict(doctype="Expense Claim", docstatus=1)
        with self._capture_enqueue() as cap:
            self.assertIsNone(ee.emit_expense_claim_cancelled(fake))
        self.assertEqual(cap, [])

    def test_emit_cancelled_volunteer_claim_enqueues(self):
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        ec.docstatus = 2
        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                ee.emit_expense_claim_cancelled(ec)
        self.assertEqual(len(cap), 1)
        data = cap[0]["event_data"]
        self.assertEqual(data["expense_claim"], ec.name)
        self.assertEqual(data["member"], member.name)
        self.assertEqual(data["expense_type"], "Volunteer Expense")
        self.assertIn("cancelled_on", data)

    # ====================================================================
    # emit_expense_payment_made
    # ====================================================================
    def test_emit_payment_wrong_doctype_noop(self):
        fake = frappe._dict(doctype="Journal Entry", docstatus=1, references=[])
        with self._capture_enqueue() as cap:
            self.assertIsNone(ee.emit_expense_payment_made(fake))
        self.assertEqual(cap, [])

    def test_emit_payment_no_expense_references_noop(self):
        """A Payment Entry with no Expense Claim references emits nothing."""
        fake = frappe._dict(
            doctype="Payment Entry",
            docstatus=1,
            references=[frappe._dict(reference_doctype="Sales Invoice", reference_name="SI-1")],
        )
        with self._capture_enqueue() as cap:
            self.assertIsNone(ee.emit_expense_payment_made(fake))
        self.assertEqual(cap, [])

    def test_emit_payment_with_expense_reference_enqueues(self):
        """A Payment Entry referencing a volunteer Expense Claim emits a
        payment-made event with the resolved member/volunteer."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        fake_pe = frappe._dict(
            doctype="Payment Entry",
            name="PE-TEST-1",
            docstatus=1,
            posting_date=today(),
            paid_amount=12.5,
            mode_of_payment="Cash",
            references=[frappe._dict(reference_doctype="Expense Claim", reference_name=ec.name)],
        )
        with self._capture_enqueue() as cap:
            with self.assertNoErrorLog():
                ee.emit_expense_payment_made(fake_pe)
        self.assertEqual(len(cap), 1)
        data = cap[0]["event_data"]
        self.assertEqual(data["payment_entry"], "PE-TEST-1")
        self.assertEqual(data["expense_claim"], ec.name)
        self.assertEqual(data["member"], member.name)
        self.assertEqual(data["paid_amount"], 12.5)

    # ====================================================================
    # _background wrappers
    # ====================================================================
    def test_payment_made_background_no_payments_found(self):
        """The background wrapper returns 'no_payments' when no Payment Entry
        references the given expense claim."""
        with self.assertNoErrorLog():
            result = ee.emit_expense_payment_made_background("EC-with-no-payments-xyz")
        self.assertEqual(result["status"], "no_payments")

    def test_approved_background_missing_claim_logs_and_returns_error(self):
        """Missing expense claim -> get_doc raises -> wrapper logs + returns error."""
        self.expectErrorLog("Expense Approval Background Job Error")
        result = ee.emit_expense_claim_approved_background("EC-missing-approve-xyz")
        self.assertEqual(result["status"], "error")

    def test_cancelled_background_missing_claim_logs_and_returns_error(self):
        self.expectErrorLog("Expense Cancellation Background Job Error")
        result = ee.emit_expense_claim_cancelled_background("EC-missing-cancel-xyz")
        self.assertEqual(result["status"], "error")

    def test_approved_background_real_claim_completes(self):
        """With a real (draft) claim the wrapper resolves it and reports completed.
        emit_expense_claim_approved early-returns (docstatus 0) -> no enqueue."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        with self.assertNoErrorLog():
            result = ee.emit_expense_claim_approved_background(ec.name)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["expense_claim"], ec.name)

    # ====================================================================
    # _get_expense_event_subscribers registry
    # ====================================================================
    def test_subscriber_registry_known_and_unknown(self):
        self.assertEqual(
            ee._get_expense_event_subscribers("expense_payment_made"),
            ["verenigingen.events.subscribers.expense_history_subscriber.handle_expense_payment_made"],
        )
        self.assertEqual(ee._get_expense_event_subscribers("bogus_event"), [])

    # ====================================================================
    # expense_history_subscriber handlers (guards + mixin no-op)
    # ====================================================================
    def test_handle_updated_no_event_data_returns(self):
        with self.assertNoErrorLog():
            self.assertIsNone(ehs.handle_expense_claim_updated())
            self.assertIsNone(ehs.handle_expense_claim_updated(event_data={}))

    def test_handle_updated_missing_links_returns(self):
        """Missing member/volunteer/expense_claim -> early return, no error."""
        with self.assertNoErrorLog():
            ehs.handle_expense_claim_updated(event_data={"member": "M"})  # no volunteer/claim
            ehs.handle_expense_claim_updated(event_data={"volunteer": "V", "expense_claim": "E"})

    # NOTE: tests that characterized the member-expense-history no-op (the chain
    # that wrote the previously-archived Member.volunteer_expenses child table)
    # were dropped. That history-tracking feature was RESTORED 2026-06-22 and is
    # now covered by test_volunteer_expenses_history_restore.py. Mechanics tests
    # (emitter dispatch, registry, deferral) below remain valid.

    def test_handle_approved_approved_action_defers(self):
        """The approved branch only logs a debug deferral; no error."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        with self.assertNoErrorLog():
            ehs.handle_expense_claim_approved(
                event_data={
                    "member": member.name,
                    "volunteer": volunteer.name,
                    "expense_claim": ec.name,
                    "action": "approved",
                }
            )

    def test_handle_rejected_delegates_to_approved(self):
        """handle_expense_claim_rejected is a thin delegate to the approved handler."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)
        with self.assertNoErrorLog():
            ehs.handle_expense_claim_rejected(
                event_data={
                    "member": member.name,
                    "volunteer": volunteer.name,
                    "expense_claim": ec.name,
                    "action": "rejected",
                }
            )

    def test_handle_cancelled_missing_data_returns(self):
        with self.assertNoErrorLog():
            self.assertIsNone(ehs.handle_expense_claim_cancelled())
            ehs.handle_expense_claim_cancelled(event_data={"member": "M"})

    def test_handle_payment_made_missing_data_returns(self):
        with self.assertNoErrorLog():
            self.assertIsNone(ehs.handle_expense_payment_made())
            ehs.handle_expense_payment_made(event_data={"member": "M"})

    # NOTE: test_handle_cancelled_real_member_noop and
    # test_handle_payment_made_real_member_noop were dropped — they asserted the
    # member-expense-history no-op (previously-archived volunteer_expenses child
    # table) now restored 2026-06-22 and covered by
    # test_volunteer_expenses_history_restore.py.

    # ====================================================================
    # delayed_expense_hooks
    # ====================================================================
    def test_schedule_update_wrong_doctype_noop(self):
        fake = frappe._dict(doctype="Sales Invoice", employee="x")
        with self.assertNoErrorLog():
            self.assertIsNone(deh.schedule_member_expense_history_update(fake))

    def test_schedule_update_no_employee_noop(self):
        fake = frappe._dict(doctype="Expense Claim", employee=None)
        with self.assertNoErrorLog():
            self.assertIsNone(deh.schedule_member_expense_history_update(fake))

    def test_schedule_update_non_volunteer_employee_noop(self):
        """An employee that is not a volunteer -> no queueing."""
        company = self._company()
        if not company:
            self.skipTest("No Company")
        emp = self._make_employee(company)
        fake = frappe._dict(doctype="Expense Claim", employee=emp.name, name="EC-x")
        with self.assertNoErrorLog():
            self.assertIsNone(deh.schedule_member_expense_history_update(fake))

    def test_schedule_update_volunteer_enqueues_add_drain_job(self):
        """A volunteer expense no longer routes into the batch processor inline.

        schedule_member_expense_history_update now defers the history write
        outside the Expense Claim save transaction by enqueuing the shared
        drain_member_expense_history job (operation="add") rather than calling
        queue_expense_update() directly. We patch frappe.enqueue at its use site
        in delayed_expense_hooks (an infra boundary, not business logic) and
        assert the routed job args, mirroring
        test_schedule_removal_volunteer_queues_remove_operation below and
        test_expense_hook_defers.test_update_after_submit_handler_enqueues_add
        (which covers the same behavior with fabricated ids; this test keeps
        the real volunteer/member/expense setup for an end-to-end check).
        """
        from unittest.mock import patch

        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)

        target = "verenigingen.events.delayed_expense_hooks.frappe.enqueue"
        with patch(target) as q:
            with self.assertNoErrorLog():
                deh.schedule_member_expense_history_update(
                    frappe._dict(doctype="Expense Claim", employee=emp.name, name=ec.name)
                )
            q.assert_called_once_with(
                "verenigingen.services.volunteer.expense_handlers.drain_member_expense_history",
                queue="short",
                job_id=f"fin_history_expense_{member.name}_{ec.name}_add",
                deduplicate=True,
                enqueue_after_commit=True,
                timeout=300,
                member=member.name,
                expense=ec.name,
                operation="add",
            )

    def test_schedule_removal_volunteer_queues_remove_operation(self):
        """schedule_member_expense_history_removal is now an intentional no-op.

        Removal ownership moved to expense_handlers.on_expense_claim_cancel, which
        enqueues the drain_member_expense_history(..., operation="remove") job
        itself (see test_expense_hook_defers.test_cancel_handler_enqueues_remove_once).
        This delayed-hook entrypoint is kept defined only so the on_cancel hook
        wiring in hooks/doc_events.py stays valid; it must NOT also queue a
        removal, or the two paths would race/duplicate.
        """
        from unittest.mock import patch

        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_draft_expense_claim(emp, company)

        target = "verenigingen.utils.financial_history_batch_processor.queue_expense_removal"
        with patch(target) as q:
            with self.assertNoErrorLog():
                deh.schedule_member_expense_history_removal(
                    frappe._dict(doctype="Expense Claim", employee=emp.name, name=ec.name)
                )
            q.assert_not_called()

    def test_update_with_retry_missing_claim_returns_quietly(self):
        """update_member_expense_history_with_retry no-ops if the claim is gone."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        with self.assertNoErrorLog():
            self.assertIsNone(
                deh.update_member_expense_history_with_retry(
                    "EC-gone-zzz", member.name, attempt=1, max_attempts=1
                )
            )

    # NOTE: test_remove_with_retry_real_member_noop dropped — asserted the
    # member-expense-history no-op for the previously-archived volunteer_expenses
    # child table, restored 2026-06-22 (see test_volunteer_expenses_history_restore.py).
