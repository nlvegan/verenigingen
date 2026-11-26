"""#1299: one failure inside CustomerHandlingService.create_customer_for_member
writes exactly ONE Error Log row, whichever exception type it is.

The fault is injected at ``insert_customer_with_duplicate_retry``, the frame that
really inserts the Customer, so the real inner handler
(``application_payments.create_customer_for_member``) and the real outer handler
(the service's ``except`` + ``handle_error``) both run. Rows are counted by a
marker unique to each case (Error Log is MyISAM: totals are not rolled back).
"""

import uuid

import frappe

import verenigingen.services.member.approval.application_payments as approval_payments
from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_error_handler import ServiceError


class TestCustomerHandlingServiceSingleErrorLog1299(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Log1299", last_name="Svc", email="log1299@verenigingen-test.nl"
        )
        # create_test_member auto-creates a Customer; detach it so the service reaches the insert.
        for customer in frappe.get_all("Customer", filters={"member": self.member.name}, pluck="name"):
            frappe.db.set_value("Customer", customer, "member", None, update_modified=False)
        frappe.db.set_value("Member", self.member.name, "customer", None, update_modified=False)
        self.member.reload()
        original = approval_payments.insert_customer_with_duplicate_retry
        self.addCleanup(setattr, approval_payments, "insert_customer_with_duplicate_retry", original)
        self.expectErrorLog("Customer Creation Error")
        self.expectErrorLog("customer_handling Error")

    def _fail_with(self, make_error):
        marker = f"marker1299-{uuid.uuid4().hex}"
        error = make_error(marker)

        def _fail(customer_doc, max_attempts=3):
            raise error

        approval_payments.insert_customer_with_duplicate_retry = _fail
        return marker

    def _error_rows_1299(self, marker):
        return frappe.get_all("Error Log", filters={"error": ["like", f"%{marker}%"]}, pluck="method")

    def test_non_validation_failure_writes_exactly_one_row(self):
        marker = self._fail_with(lambda m: ValueError(m))
        with self.assertRaises(ServiceError):
            CustomerHandlingService().create_customer_for_member(self.member, suppress_messages=True)
        self.assertEqual(self._error_rows_1299(marker), ["customer_handling Error"])

    def test_control_validation_failure_still_writes_exactly_one_row(self):
        marker = self._fail_with(lambda m: frappe.ValidationError(m))
        with self.assertRaises(frappe.ValidationError):
            CustomerHandlingService().create_customer_for_member(self.member, suppress_messages=True)
        self.assertEqual(len(self._error_rows_1299(marker)), 1)

    def test_control_does_not_exist_failure_still_writes_exactly_one_row(self):
        marker = self._fail_with(lambda m: frappe.DoesNotExistError(m))
        with self.assertRaises(frappe.DoesNotExistError):
            CustomerHandlingService().create_customer_for_member(self.member, suppress_messages=True)
        self.assertEqual(len(self._error_rows_1299(marker)), 1)
