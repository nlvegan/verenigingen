"""#1190: the ServiceError envelope must not replace a non-resumable DB error.

``handle_service_error(raise_error=True)`` used to wrap every exception in a new
``ServiceError``, so a caller's ``except NON_RESUMABLE_DB_ERRORS`` (deadlock 1213,
lock wait 1205) could never match a failure that passed through a service. The
envelope stays for every other exception; these two classes propagate unchanged.
"""

import frappe

import verenigingen.services.member.approval.application_payments as approval_payments
from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.services.infrastructure.base_service import StatefulService, StatelessService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_error_handler import ServiceError, handle_service_error
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

_FAULTS = {
    "deadlock": lambda: frappe.QueryDeadlockError("(1213, 'Deadlock found when trying to get lock')"),
    "lock_wait": lambda: frappe.QueryTimeoutError("(1205, 'Lock wait timeout exceeded')"),
}


def _envelope_1190_error_log_rows(title):
    return frappe.db.count("Error Log", {"method": title})


class TestServiceErrorEnvelopeNonResumable1190(EnhancedTestCase):
    def test_the_guard_classes_are_exactly_the_two_exercised_here(self):
        self.assertEqual(len(NON_RESUMABLE_DB_ERRORS), len(_FAULTS))
        for make in _FAULTS.values():
            self.assertIsInstance(make(), NON_RESUMABLE_DB_ERRORS)

    def test_handle_service_error_raises_the_original_object(self):
        for name, make in _FAULTS.items():
            with self.subTest(fault=name):
                err = make()
                with self.assertRaises(NON_RESUMABLE_DB_ERRORS) as ctx:
                    handle_service_error(err, "svc_1190", "op")
                self.assertIs(ctx.exception, err)

    def test_execute_operation_propagates_the_original_object(self):
        for name, make in _FAULTS.items():
            with self.subTest(fault=name):
                err = make()
                svc = StatelessService(f"stateless_1190_{name}")

                def op():
                    raise err

                with self.assertRaises(NON_RESUMABLE_DB_ERRORS) as ctx:
                    svc.execute_operation(op)
                self.assertIs(ctx.exception, err)
                self.assertEqual(svc.get_metrics()["errors"], 1)

    def test_execute_with_transaction_propagates_and_still_rolls_back(self):
        member = self.create_test_member(first_name="Env1190", last_name="Svc", email="env1190@verenigingen-test.nl")
        original_email = frappe.db.get_value("Member", member.name, "email")
        for name, make in _FAULTS.items():
            with self.subTest(fault=name):
                err = make()
                svc = StatefulService(f"stateful_1190_{name}")

                def write_then_fail():
                    frappe.db.set_value("Member", member.name, "email", "env1190.changed@verenigingen-test.nl", update_modified=False)
                    raise err

                with self.assertRaises(NON_RESUMABLE_DB_ERRORS) as ctx:
                    svc.execute_with_transaction(write_then_fail)
                self.assertIs(ctx.exception, err)
                self.assertFalse(svc._transaction_active)
                self.assertEqual(frappe.db.get_value("Member", member.name, "email"), original_email)

    def test_real_service_caller_propagates_below_its_own_handlers(self):
        """CustomerHandlingService catches ``Exception`` and calls handle_error.

        The fault is injected at the frame that really inserts the Customer, below
        create_customer_for_member's savepoint and below the service's handler.
        """
        member = self.create_test_member(first_name="EnvReal1190", last_name="Svc", email="envreal1190@verenigingen-test.nl")
        # create_test_member auto-creates a Customer; detach it so the service reaches the insert.
        for customer in frappe.get_all("Customer", filters={"member": member.name}, pluck="name"):
            frappe.db.set_value("Customer", customer, "member", None, update_modified=False)
        frappe.db.set_value("Member", member.name, "customer", None, update_modified=False)
        member.reload()
        original = approval_payments.insert_customer_with_duplicate_retry
        self.addCleanup(setattr, approval_payments, "insert_customer_with_duplicate_retry", original)
        for name, make in _FAULTS.items():
            with self.subTest(fault=name):
                err = make()

                def _fail(customer_doc, max_attempts=3):
                    raise err

                approval_payments.insert_customer_with_duplicate_retry = _fail
                self.expectErrorLog()
                with self.assertRaises(NON_RESUMABLE_DB_ERRORS):
                    CustomerHandlingService().create_customer_for_member(member, suppress_messages=True)

    def test_control_an_ordinary_error_is_still_wrapped_and_logged(self):
        self.expectErrorLog("env_ctrl_1190 Error")
        before = _envelope_1190_error_log_rows("env_ctrl_1190 Error")
        boom = ValueError("ordinary")
        with self.assertRaises(ServiceError) as ctx:
            handle_service_error(boom, "env_ctrl_1190", "op")
        self.assertIs(ctx.exception.original_error, boom)
        self.assertEqual(_envelope_1190_error_log_rows("env_ctrl_1190 Error"), before + 1)

    def test_control_raise_error_false_keeps_returning_the_envelope(self):
        self.expectErrorLog("env_nr_1190 Error")
        result = handle_service_error(_FAULTS["deadlock"](), "env_nr_1190", "op", raise_error=False)
        self.assertFalse(result["success"])
