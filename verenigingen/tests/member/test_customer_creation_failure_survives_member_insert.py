"""A failed ERPNext Customer must not take the Member with it (issue #254).

``Member.after_insert`` creates the member's ERPNext Customer. Every failure in
that path used to propagate out of ``after_insert`` and abort the whole Member
insert, so a problem in a *downstream* record destroyed the *upstream* one.

A Member without a Customer is a supported, repairable state in this app:

* ``Member.customer`` is not ``reqd``, and ``after_insert`` only attempts customer
  creation ``if ... self.email`` -- a member imported without an email address
  never gets one at all;
* ``member.js`` renders a "Create Customer" button precisely when
  ``!frm.doc.customer``, and ``Member.create_customer()`` is whitelisted for it;
* invoicing reports customer-less members as their own operator-facing bucket
  (``dues_invoice_workflow.py`` "no_customer": "cannot invoice") rather than as a
  corrupt state.

So the member is kept and the reason is surfaced -- but only where somebody is
listening. Two cases still propagate:

* a **non-resumable DB error** (1213/1205): the server has already destroyed the
  transaction, so continuing would report a Member that no longer exists;
* a **bulk import**: ``msgprint`` reaches nobody in a background job, and every
  importer already rolls its row back and reports the reason in its per-row
  status. Swallowing there would turn a reported failure into a reported
  success.

Failures are injected by swapping a module attribute rather than by mocking the
unit under test: the Member insert, the after_insert hook and the Customer/Contact
creation all really run.
"""

import frappe

import verenigingen.services.member.approval.application_payments as approval_payments
import verenigingen.utils.application_payments as application_payments_shim
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

CUSTOMER_KEPT_MESSAGE = "The member was saved, but no customer record could be created"


class TestCustomerCreationFailureSurvivesMemberInsert(EnhancedTestCase):
    # ------------------------------------------------------------------ helpers

    def _member_payload(self, with_email=True):
        h = frappe.generate_hash(length=6)
        payload = {
            "doctype": "Member",
            "first_name": "CustFail",
            "last_name": h,
            "birth_date": "1990-01-01",
            "contact_number": "+31612345678",
        }
        if with_email:
            payload["email"] = f"custfail.{h}@test.invalid"
        return payload

    def _insert_member(self, with_email=True):
        member = frappe.get_doc(self._member_payload(with_email=with_email))
        member.insert()
        return member

    def _break_customer_group(self):
        """Realistic fault: Customer.customer_group points at a group that is gone.

        The real ``Customer.insert()`` runs and raises ``LinkValidationError`` -- a
        ``frappe.ValidationError`` subclass, which is what most real customer
        failures are (missing link, missing mandatory field, a ``frappe.throw`` for
        insufficient permissions).
        """
        original = approval_payments.resolve_non_group_customer_group
        approval_payments.resolve_non_group_customer_group = lambda: "No Such Customer Group ZZZ"
        self.addCleanup(setattr, approval_payments, "resolve_non_group_customer_group", original)

    def _raise_from_customer_creation(self, error):
        """Fault: customer creation raises ``error`` (for the non-ValidationError cases)."""
        original = application_payments_shim.create_customer_for_member

        def _boom(member):
            raise error

        application_payments_shim.create_customer_for_member = _boom
        self.addCleanup(setattr, application_payments_shim, "create_customer_for_member", original)

    def _fail_the_customer_insert_with(self, error_factory):
        """Fault at the frame that really inserts the Customer, savepoint untouched.

        Unlike ``_raise_from_customer_creation`` this keeps
        ``create_customer_for_member`` -- and therefore its savepoint and its
        handlers -- in the picture, which is what the savepoint assertions need.
        """
        original = approval_payments.insert_customer_with_duplicate_retry

        def _fail(customer_doc, max_attempts=3):
            raise error_factory()

        approval_payments.insert_customer_with_duplicate_retry = _fail
        self.addCleanup(setattr, approval_payments, "insert_customer_with_duplicate_retry", original)

    def _deadlock_that_destroyed_the_savepoint(self):
        """Inject a 1213 at the frame that really raises one, savepoint already gone.

        A real 1213 rolls the victim's ENTIRE transaction back, savepoints
        included. Measured on test_site_1 with two contending connections::

            a_err:                 QueryDeadlockError [(1213, 'Deadlock found ...')]
            a_savepoint_after:     GONE -- OperationalError (1305, 'SAVEPOINT sp_a
                                   does not exist')
            b (non-victim control): no error; savepoint still alive

        Issuing a real ``ROLLBACK`` inside a test would take the fixtures with it,
        so this reproduces the half that matters: the enclosing savepoint is
        really released, which makes the handler's ``rollback(save_point=...)``
        raise a **real** 1305 from the driver rather than a stand-in for one. That
        1305 is what replaces the deadlock as the propagating exception -- and it
        is neither ``QueryDeadlockError`` nor ``ValidationError``, so every guard
        downstream evaluates False.

        Injecting a bare ``QueryDeadlockError`` here is NOT enough: with the
        savepoint intact the handler's rollback succeeds and the deadlock reaches
        the caller unchanged, so the guard fires and the test passes either way.
        """
        taken = []
        real_savepoint = frappe.local.db.savepoint

        def _recording_savepoint(save_point):
            taken.append(save_point)
            return real_savepoint(save_point)

        frappe.local.db.savepoint = _recording_savepoint
        self.addCleanup(frappe.local.db.__dict__.pop, "savepoint", None)

        original = approval_payments.insert_customer_with_duplicate_retry

        def _deadlock(customer_doc, max_attempts=3):
            if taken:
                frappe.db.sql(f"RELEASE SAVEPOINT {taken[-1]}")
            raise frappe.QueryDeadlockError(
                "Deadlock found when trying to get lock; try restarting transaction"
            )

        approval_payments.insert_customer_with_duplicate_retry = _deadlock
        self.addCleanup(
            setattr, approval_payments, "insert_customer_with_duplicate_retry", original
        )

    def _spy_on_savepoint_rollbacks(self):
        """Record every ``rollback(save_point=...)`` so a test can assert it happened -- or did not."""
        rolled_back = []
        real_rollback = frappe.local.db.rollback

        def _recording_rollback(*, save_point=None, chain=False):
            if save_point:
                rolled_back.append(save_point)
            return real_rollback(save_point=save_point, chain=chain)

        frappe.local.db.rollback = _recording_rollback
        self.addCleanup(frappe.local.db.__dict__.pop, "rollback", None)
        return rolled_back

    def _error_log_watch(self):
        start = frappe.utils.now()
        before = {row.name for row in self._error_logs_since(start, use_expected=False)}
        return start, before

    def _error_logs_written(self, watch):
        start, before = watch
        return self._error_logs_since(start, before_names=before, use_expected=False)

    def _assert_member_survived_without_customer(self, member):
        self.assertTrue(
            frappe.db.exists("Member", member.name),
            "the Member row must survive a failed Customer creation",
        )
        self.assertFalse(member.customer, "in-memory customer must stay empty")
        self.assertFalse(
            frappe.db.get_value("Member", member.name, "customer"),
            "persisted customer must stay empty",
        )
        self.assertEqual(
            frappe.db.count("Customer", {"member": member.name}),
            0,
            "a half-built Customer must not be left behind",
        )

    # ------------------------------------------------------------------ control

    def test_control_customer_is_created_when_nothing_is_broken(self):
        """Without an injected fault the insert really does produce a Customer.

        Without this, the failure tests below would also pass if customer creation
        had silently stopped happening altogether.
        """
        member = self._insert_member()
        self.assertTrue(member.customer, "after_insert should have created a Customer")
        self.assertEqual(frappe.db.get_value("Customer", member.customer, "member"), member.name)

    # ------------------------------------------------------- ValidationError path

    def test_link_validation_failure_keeps_the_member(self):
        """The dominant real failure shape (a ValidationError subclass)."""
        self.expectErrorLog("Member customer creation failed", "Customer Creation Error")
        self._break_customer_group()
        watch = self._error_log_watch()
        frappe.clear_messages()

        member = self._insert_member()

        self._assert_member_survived_without_customer(member)
        # Assert this handler's OWN wording, not the underlying frappe.throw text:
        # frappe.throw appends its message to the log before after_insert's handler
        # ever runs, so asserting only the reason is satisfied whether or not the
        # member was kept and whether or not anything was re-surfaced.
        messages = str(frappe.get_message_log())
        self.assertIn(CUSTOMER_KEPT_MESSAGE, messages, "the user must be told the member was kept")
        self.assertIn(
            "No Such Customer Group ZZZ",
            messages,
            "a deliberate validation message is the user's to read, so it is echoed",
        )
        self.assertTrue(
            any("Member customer creation failed" in (row.method or "") for row in self._error_logs_written(watch)),
            "the failure must leave an Error Log row for whoever can act on it",
        )

    # ----------------------------------------------------- unexpected-error path

    def test_unexpected_error_keeps_the_member_without_leaking_its_text(self):
        """A non-Frappe error is the path issue #254's `return None` aimed at.

        ``after_insert`` runs on the public application form, so the message the
        applicant sees must not carry internal detail. Only a ValidationError --
        a deliberate, translated ``frappe.throw`` -- is echoed verbatim.
        """
        self.expectErrorLog("Member customer creation failed", "customer_handling Error")
        self._raise_from_customer_creation(RuntimeError("ERPNext Customer insert exploded"))
        watch = self._error_log_watch()
        frappe.clear_messages()

        member = self._insert_member()

        self._assert_member_survived_without_customer(member)
        messages = str(frappe.get_message_log())
        self.assertIn(CUSTOMER_KEPT_MESSAGE, messages, "the user must be told the member was kept")
        self.assertNotIn(
            "ERPNext Customer insert exploded",
            messages,
            "an unexpected error's text must not be rendered to a public applicant",
        )
        self.assertTrue(
            any(
                "ERPNext Customer insert exploded" in (row.error or "")
                for row in self._error_logs_written(watch)
            ),
            "the reason must still reach the Error Log",
        )

    # --------------------------------------------------------- must NOT be caught

    def test_a_deadlock_that_destroyed_the_savepoint_still_aborts_the_insert(self):
        """1213 has already rolled the whole transaction back.

        Keeping the Member here would hand the caller a document naming a row
        that does not exist -- on the guest application path, an applicant told
        they were registered when nothing was committed.

        This is the case the handler's ``NON_RESUMABLE_DB_ERRORS`` guard exists
        for, and the case it could not see: the ``rollback(save_point=...)`` in
        ``create_customer_for_member``'s own handler raised 1305 and *replaced*
        the deadlock, so the guard was handed an ``OperationalError`` and let it
        through.
        """
        self.expectErrorLog("customer_handling Error", "Customer Creation Error")
        self._deadlock_that_destroyed_the_savepoint()

        with self.assertRaises(Exception) as caught:
            self._insert_member()

        raised = caught.exception
        self.assertTrue(
            isinstance(raised, frappe.QueryDeadlockError)
            or isinstance(getattr(raised, "original_error", None), frappe.QueryDeadlockError),
            f"expected the deadlock to propagate, got {type(raised).__name__}: {raised}",
        )
        # Deliberately not asserted: that the Member row is gone. A real 1213 is the
        # server rolling the transaction back; this fault is injected, so nothing
        # rolled anything back here. Asserting it would test MariaDB, not this code.

    def test_a_deadlock_is_not_replaced_by_the_savepoint_error(self):
        """The guard has to sit ABOVE the rollback, not after it.

        Asserted at the frame that owns the savepoint, so the test names the
        defect rather than one symptom of it.
        """
        member = self._insert_member(with_email=False)
        self.assertFalse(member.customer, "an email-less member gets no Customer, so none is in the way")
        rolled_back = self._spy_on_savepoint_rollbacks()
        self._deadlock_that_destroyed_the_savepoint()

        with self.assertRaises(Exception) as caught:
            approval_payments.create_customer_for_member(member)

        self.assertIsInstance(
            caught.exception,
            frappe.QueryDeadlockError,
            f"the deadlock must propagate unchanged, got {type(caught.exception).__name__}",
        )
        self.assertEqual(
            rolled_back, [], "nothing may be rolled back to a savepoint the deadlock already destroyed"
        )

    def test_a_validation_error_still_rolls_the_savepoint_back(self):
        """Control for the test above: the savepoint discipline is intact otherwise.

        Without this, "no rollback happened" would be equally consistent with the
        guard being right and with the rollback having been deleted outright.
        """
        self.expectErrorLog("Customer Creation Error")
        member = self._insert_member(with_email=False)
        rolled_back = self._spy_on_savepoint_rollbacks()
        self._break_customer_group()

        with self.assertRaises(frappe.ValidationError):
            approval_payments.create_customer_for_member(member)

        self.assertEqual(
            len(rolled_back), 1, f"a resumable failure must roll its savepoint back, got {rolled_back}"
        )

    # ------------------------------------------------------------- bulk imports

    def test_a_bulk_import_reports_the_row_failed_when_the_customer_cannot_be_created(self):
        """Keeping the member is only an improvement where somebody reads the message.

        ``msgprint`` goes nowhere in a background job. If ``after_insert`` swallowed
        here, ``member.insert()`` would return normally and the importer would
        commit the row and report it "created" -- so a systematic misconfiguration
        (customer group, territory, import-user permissions) hits every row and a
        5,000-row import goes green with one Error Log row per member.
        """
        self.expectErrorLog("Customer Creation Error", "CSV Import Validation Error", "customer_handling Error")
        self._break_customer_group()

        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        h = frappe.generate_hash(length=6)
        status, member_name = get_member_import_service().create_or_update_member(
            row_data={
                "row_number": 1,
                "first_name": "BulkCustFail",
                "last_name": h,
                "email": f"bulk.custfail.{h}@test.invalid",
                "membership_type": "lid",
            },
            import_doc_name="TEST-CUSTOMER-FAILURE",
            create_volunteer_records=False,
        )

        self.assertTrue(
            status.startswith("failed"),
            f"a row whose Customer could not be created must not be reported created, got {status!r}",
        )
        self.assertIn(
            "No Such Customer Group ZZZ",
            status,
            "the reason has to travel back to the operator's import summary",
        )
        self.assertIsNone(member_name)

    # ----------------------------------------------------------- the repair path

    def test_the_create_customer_button_still_raises(self):
        """``Member.create_customer()`` is the documented way to fix a missing Customer.

        It must stay loud: a silent failure there leaves the operator pressing a
        button that reports nothing and changes nothing.
        """
        self.expectErrorLog("Customer Creation Error")
        member = self._insert_member(with_email=False)
        self._break_customer_group()

        with self.assertRaises(frappe.ValidationError):
            member.create_customer()

        self.assertFalse(frappe.db.get_value("Member", member.name, "customer"))

    # ------------------------------------------- 1205 is not the same shape as 1213

    def test_a_lock_timeout_rolls_its_savepoint_back_and_still_aborts_the_insert(self):
        """The other member of NON_RESUMABLE_DB_ERRORS behaves differently at the savepoint.

        With ``innodb_rollback_on_timeout=OFF`` -- the default, and measured OFF on
        this deployment -- a 1205 rolls back only the failed statement. The
        savepoint SURVIVES, so a Customer inserted before the Contact step timed
        out is still there to undo, and skipping the rollback the way a 1213
        requires would leave it behind. The unit of work is still half-applied, so
        the insert must abort either way.

        Without this, narrowing the guard in ``create_customer_for_member`` to 1213
        would be indistinguishable from widening it to both.
        """
        self.expectErrorLog("Customer Creation Error", "customer_handling Error")
        rolled_back = self._spy_on_savepoint_rollbacks()
        self._fail_the_customer_insert_with(
            lambda: frappe.QueryTimeoutError("Lock wait timeout exceeded; try restarting transaction")
        )

        with self.assertRaises(Exception) as caught:
            self._insert_member()

        raised = caught.exception
        self.assertTrue(
            isinstance(raised, frappe.QueryTimeoutError)
            or isinstance(getattr(raised, "original_error", None), frappe.QueryTimeoutError),
            f"a 1205 must still abort the insert, got {type(raised).__name__}: {raised}",
        )
        self.assertEqual(
            len(rolled_back),
            1,
            f"a 1205 leaves its savepoint alive, so the half-built Customer must be undone, got {rolled_back}",
        )

    # ---------------------------------------------- the per-document bulk flag

    def test_the_per_document_bulk_flag_also_aborts_the_insert(self):
        """VIP import sets the flag on the document, not globally (vip_import.py:298).

        The global half of the condition is exercised by the import-service test
        above; without this one, deleting ``self.flags.get("bulk_member_operations")``
        leaves the whole suite green.
        """
        self.expectErrorLog("Customer Creation Error")
        self._break_customer_group()
        self.assertFalse(
            getattr(frappe.flags, "bulk_member_operations", False),
            "this test is about the per-doc flag, so the global one must be off",
        )

        member = frappe.get_doc(self._member_payload())
        member.flags.bulk_member_operations = True

        with self.assertRaises(frappe.ValidationError):
            member.insert()

    # ------------------------------------- a framework permission failure is a message

    def test_a_framework_permission_failure_still_reaches_the_user(self):
        """``raise_no_permission_to()`` raises PermissionError BARE.

        It is not a ValidationError and ``str(error)`` is empty; the human sentence
        is left in ``frappe.flags.error_message``. Discarding it would send the one
        operator-actionable failure to the Error Log and show the user nothing.
        """
        self.expectErrorLog("Member customer creation failed", "customer_handling Error", "Customer Creation Error")
        sentence = "You need the 'create' permission on Customer to perform this action."

        def _no_permission():
            frappe.flags.error_message = sentence
            return frappe.PermissionError()

        self._fail_the_customer_insert_with(_no_permission)
        self.addCleanup(frappe.flags.pop, "error_message", None)
        frappe.clear_messages()

        member = self._insert_member()

        self._assert_member_survived_without_customer(member)
        messages = str(frappe.get_message_log())
        self.assertIn(CUSTOMER_KEPT_MESSAGE, messages)
        self.assertIn(sentence, messages, "the framework's own permission sentence must not be discarded")
