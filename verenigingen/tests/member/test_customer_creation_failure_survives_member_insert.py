"""A failed ERPNext Customer must not take the Member with it (issue #254).

``Member.after_insert`` creates the member's ERPNext Customer. Every failure in
that path used to propagate out of ``after_insert`` and abort the whole Member
insert, so a problem in a *downstream* record destroyed the *upstream* one.

A Member without a Customer is a supported, repairable state in this app:

* ``Member.customer`` is not ``reqd``, and ``after_insert`` only attempts customer
  creation ``if ... self.email`` -- an email-less member (the CSV/Procurios import
  path) never gets one at all;
* ``member.js`` renders a "Create Customer" button precisely when
  ``!frm.doc.customer``, and ``Member.create_customer()`` is whitelisted for it;
* invoicing reports customer-less members as their own operator-facing bucket
  (``dues_invoice_workflow.py`` "no_customer": "cannot invoice") rather than as a
  corrupt state.

So the member is kept and the reason is surfaced. The one exception is a
non-resumable DB error (1213/1205): the server has already destroyed the
transaction, so continuing would report a Member that no longer exists -- those
must still propagate.

Failures are injected by swapping a module attribute rather than by mocking the
unit under test: the Member insert, the after_insert hook and the Customer/Contact
creation all really run.
"""

import frappe

import verenigingen.services.member.approval.application_payments as approval_payments
import verenigingen.utils.application_payments as application_payments_shim
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCustomerCreationFailureSurvivesMemberInsert(EnhancedTestCase):
    def _member_payload(self):
        h = frappe.generate_hash(length=6)
        return {
            "doctype": "Member",
            "first_name": "CustFail",
            "last_name": h,
            "email": f"custfail.{h}@test.invalid",
            "birth_date": "1990-01-01",
            "contact_number": "+31612345678",
        }

    def _insert_member(self):
        member = frappe.get_doc(self._member_payload())
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
        frappe.clear_messages()

        member = self._insert_member()

        self._assert_member_survived_without_customer(member)
        self.assertIn(
            "No Such Customer Group ZZZ",
            str(frappe.get_message_log()),
            "the underlying reason must be shown to the user, not swallowed",
        )

    # ----------------------------------------------------- unexpected-error path

    def test_unexpected_error_keeps_the_member(self):
        """A non-Frappe error is the path issue #254's `return None` aimed at."""
        self.expectErrorLog("Member customer creation failed", "customer_handling Error")
        self._raise_from_customer_creation(RuntimeError("ERPNext Customer insert exploded"))
        frappe.clear_messages()

        member = self._insert_member()

        self._assert_member_survived_without_customer(member)
        self.assertIn(
            "ERPNext Customer insert exploded",
            str(frappe.get_message_log()),
            "the underlying reason must be shown to the user, not swallowed",
        )

    # --------------------------------------------------------- must NOT be caught

    def test_non_resumable_db_error_still_aborts_the_insert(self):
        """1213 has already rolled the whole transaction back.

        Keeping the Member here would report a row that no longer exists, so this
        one still propagates. It is also the control proving the handler above is
        not a blanket swallow.
        """
        self.expectErrorLog("customer_handling Error")
        self._raise_from_customer_creation(
            frappe.QueryDeadlockError("Deadlock found when trying to get lock")
        )
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
