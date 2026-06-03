"""
Transaction Boundary Test Framework

Provides specialized test case classes for testing transaction boundaries,
rollback behavior, and error recovery in the Verenigingen system.

This framework extends the EnhancedTestCase to provide additional functionality
for testing complex transaction scenarios, external API integration failures,
and concurrency edge cases.

Key Features:
- Transaction boundary testing and rollback validation
- External API failure simulation and recovery testing
- Concurrency and race condition testing utilities
- Error injection and recovery pattern testing
- Database state validation before/after operations

@author Verenigingen Development Team
@version 1.0.0
"""

import frappe
from frappe.utils import now_datetime, flt
from contextlib import contextmanager
import time
import threading
from unittest.mock import patch, Mock

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TransactionBoundaryError(Exception):
    """
    Custom exception for transaction boundary test failures

    Raised when transaction boundaries are not properly maintained
    or when rollback operations fail during testing.
    """
    pass


class ConcurrencyTestError(Exception):
    """
    Custom exception for concurrency-related test failures

    Raised when race conditions or concurrent access patterns
    fail to behave as expected during testing.
    """
    pass


class TransactionBoundaryTestCase(EnhancedTestCase):
    """
    Enhanced test case for transaction boundary and error recovery testing

    Extends EnhancedTestCase with specialized utilities for:
    - Testing transaction rollback behavior
    - Simulating external API failures
    - Validating error recovery patterns
    - Testing concurrent operation safety
    """

    def setUp(self):
        """Initialize transaction boundary test environment"""
        super().setUp()
        self._transaction_markers = []
        self._external_api_mocks = {}
        self._concurrency_test_data = {}

    def tearDown(self):
        """Clean up transaction boundary test environment"""
        # Clear any transaction markers
        self._transaction_markers.clear()

        # Reset external API mocks
        for mock_name, mock_obj in self._external_api_mocks.items():
            if hasattr(mock_obj, 'reset_mock'):
                mock_obj.reset_mock()
        self._external_api_mocks.clear()

        # Clear concurrency test data
        self._concurrency_test_data.clear()

        super().tearDown()

    @contextmanager
    def assert_transaction_rollback(self, operation_description="operation"):
        """
        Context manager to assert that database changes are rolled back on error

        Usage:
            with self.assert_transaction_rollback("payment creation"):
                # Perform operation that should fail and rollback
                create_payment_that_fails()
        """
        # Capture initial database state
        initial_db_state = self._capture_database_state()

        try:
            yield
            # If we get here, the operation didn't fail as expected
            raise TransactionBoundaryError(
                f"Expected {operation_description} to fail and trigger rollback, but it succeeded"
            )
        except Exception as e:
            # Expected failure occurred - now verify rollback
            if isinstance(e, TransactionBoundaryError):
                raise  # Re-raise our own errors

            # Check that database state was properly rolled back
            current_db_state = self._capture_database_state()
            if not self._compare_database_states(initial_db_state, current_db_state):
                raise TransactionBoundaryError(
                    f"Database state was not properly rolled back after {operation_description} failure. "
                    f"Original error: {str(e)}"
                )

    def _capture_database_state(self, doctypes_to_monitor=None):
        """
        Capture current database state for comparison

        Returns a snapshot of relevant database tables and counts
        for validating rollback behavior.

        Args:
            doctypes_to_monitor: Optional explicit list of doctypes to snapshot.
                When omitted, a default set of core Verenigingen doctypes is used.
        """
        state = {}

        # Core Verenigingen doctypes to monitor (default when caller passes none)
        if doctypes_to_monitor is None:
            doctypes_to_monitor = [
                'Member',
                'Sales Invoice',
                'Payment Entry',
                'SEPA Mandate',
                'Direct Debit Batch',
                'Member Payment History',
                'Membership Dues Schedule'
            ]

        for doctype in doctypes_to_monitor:
            try:
                count = frappe.db.count(doctype)
                state[doctype] = {
                    'count': count,
                    'last_modified': frappe.db.sql(
                        f"SELECT MAX(modified) FROM `tab{doctype}`"
                    )[0][0] if count > 0 else None
                }
            except Exception:
                # Doctype might not exist in test environment
                state[doctype] = {'count': 0, 'last_modified': None}

        return state

    def _compare_database_states(self, state1, state2):
        """
        Compare two database states to detect changes

        Returns True if states are equivalent (no changes detected)
        """
        for doctype in state1:
            if state1[doctype]['count'] != state2[doctype]['count']:
                return False
            # Note: We don't compare last_modified since that can change
            # even with the same count due to updates

        return True

    def execute_concurrent_operations_with_validation(self, operations):
        """Run a batch of operations concurrently and collect their outcomes.

        Each operation is a ``(callable, args, kwargs)`` tuple. Every operation
        runs on its own thread with its own Frappe DB connection (Frappe state
        is thread-local), so the callables may freely use the ORM. Operation
        callables are expected to handle their own errors and return a dict
        (commonly ``{"success": bool, ...}``); any uncaught exception is
        captured and reported as a failed result.

        Returns:
            list[dict]: One result per operation, in input order, each shaped as
                ``{"success": bool, "result": <callable return>, "error": <str|None>}``.
                ``success`` mirrors the callable's own ``success`` flag when it
                returns one, otherwise defaults to True for a clean return.

        Note: operations must commit their own writes if they need to be visible
        to other threads or asserted after join; the per-thread connection is
        torn down when the operation finishes.
        """
        results = [None] * len(operations)
        site = frappe.local.site

        def _run(index, func, args, kwargs):
            frappe.init(site=site)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                ret = func(*args, **kwargs)
                if isinstance(ret, dict) and "success" in ret:
                    results[index] = {
                        "success": bool(ret.get("success")),
                        "result": ret,
                        "error": ret.get("error"),
                    }
                else:
                    results[index] = {"success": True, "result": ret, "error": None}
            except Exception as e:  # noqa: BLE001 - capture per-operation failure
                results[index] = {"success": False, "result": None, "error": str(e)}
            finally:
                try:
                    frappe.db.commit()
                except Exception:
                    pass
                frappe.destroy()

        threads = []
        for i, (func, args, kwargs) in enumerate(operations):
            t = threading.Thread(target=_run, args=(i, func, args, kwargs or {}))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # The worker threads committed their writes on separate connections. The
        # calling thread is inside an open transaction (REPEATABLE READ), so its
        # snapshot predates those commits. Commit here to refresh the snapshot so
        # callers can observe the concurrently-committed rows.
        frappe.db.commit()

        return results

    def mock_external_api_failure(self, api_name, method_name, exception_class=Exception,
                                  exception_message="Simulated API failure"):
        """
        Mock an external API to simulate failure conditions

        Args:
            api_name: Name of the API module (e.g., 'mollie_api', 'eboekhouden_api')
            method_name: Name of the method to mock
            exception_class: Exception class to raise
            exception_message: Exception message

        Returns:
            Mock object for additional configuration if needed
        """
        # Create mock that raises exception
        mock_obj = Mock(side_effect=exception_class(exception_message))

        # Store mock for cleanup
        mock_key = f"{api_name}.{method_name}"
        self._external_api_mocks[mock_key] = mock_obj

        return mock_obj

    def simulate_network_timeout(self, api_name, method_name, timeout_seconds=5):
        """
        Simulate network timeout for external API calls

        Args:
            api_name: Name of the API module
            method_name: Name of the method to mock
            timeout_seconds: How long to delay before timing out
        """
        def timeout_side_effect(*args, **kwargs):
            time.sleep(timeout_seconds)
            raise TimeoutError(f"Simulated timeout for {api_name}.{method_name}")

        mock_obj = Mock(side_effect=timeout_side_effect)
        mock_key = f"{api_name}.{method_name}"
        self._external_api_mocks[mock_key] = mock_obj

        return mock_obj

    def create_test_mollie_webhook_scenario(self):
        """
        Create a realistic test scenario for Mollie webhook testing

        Returns a dictionary with test data including member, mandate,
        and invoice setup for webhook processing tests.
        """
        # Create test member with SEPA mandate
        member = self.create_test_member(
            first_name="WebhookTest",
            last_name="van Mollie",
            birth_date="1985-03-15"
        )

        # Create SEPA mandate for the member
        mandate = self.create_test_sepa_mandate(
            member.name,
            iban="NL91ABNA0417164300",
            bic="ABNANL2A"
        )

        # Create unpaid sales invoice
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            amount=25.00,
            description="Membership dues"
        )

        return {
            'member': member,
            'mandate': mandate,
            'invoice': invoice,
            'mollie_payment_id': 'tr_test_webhook_' + str(int(time.time()))
        }

    def create_test_eboekhouden_sync_scenario(self):
        """
        Create a realistic test scenario for eBoekhouden sync testing

        Returns test data setup for testing eBoekhouden integration
        and sync failure recovery.
        """
        # Create member with financial transactions
        member = self.create_test_member(
            first_name="EBoekhoudenSync",
            last_name="van Test",
            birth_date="1980-07-22"
        )

        # Create sales invoice that would sync to eBoekhouden
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            amount=50.00,
            description="Membership dues for eBoekhouden sync test"
        )

        # Create payment entry
        payment = self.create_test_payment_entry(
            invoice=invoice,
            amount=50.00
        )

        return {
            'member': member,
            'invoice': invoice,
            'payment': payment,
            'sync_reference': f'TEST_SYNC_{int(time.time())}'
        }

    @contextmanager
    def concurrent_operation_test(self, operation_name, thread_count=2):
        """
        Context manager for testing concurrent operations

        Usage:
            with self.concurrent_operation_test("payment_processing", thread_count=3):
                # Define operations that will run concurrently
                def create_payment():
                    # Payment creation logic
                    pass

                # Operations will be executed concurrently
                yield create_payment
        """
        test_data_key = f"concurrent_{operation_name}_{int(time.time())}"
        self._concurrency_test_data[test_data_key] = {
            'threads': [],
            'results': [],
            'errors': []
        }

        def run_concurrent_operation(operation_func):
            """Execute operation and capture results/errors"""
            try:
                result = operation_func()
                self._concurrency_test_data[test_data_key]['results'].append(result)
            except Exception as e:
                self._concurrency_test_data[test_data_key]['errors'].append(e)

        try:
            yield lambda op_func: self._execute_concurrent_operations(
                test_data_key, op_func, thread_count
            )
        finally:
            # Wait for all threads to complete
            for thread in self._concurrency_test_data[test_data_key]['threads']:
                thread.join(timeout=10)  # 10 second timeout

    def _execute_concurrent_operations(self, test_data_key, operation_func, thread_count):
        """Execute operation function concurrently in multiple threads"""
        threads = []

        for i in range(thread_count):
            def thread_wrapper():
                try:
                    result = operation_func()
                    self._concurrency_test_data[test_data_key]['results'].append(result)
                except Exception as e:
                    self._concurrency_test_data[test_data_key]['errors'].append(e)

            thread = threading.Thread(target=thread_wrapper)
            threads.append(thread)
            self._concurrency_test_data[test_data_key]['threads'] = threads

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        return {
            'results': self._concurrency_test_data[test_data_key]['results'],
            'errors': self._concurrency_test_data[test_data_key]['errors']
        }

    def assert_error_recovery_pattern(self, operation_func, expected_error_type,
                                     recovery_validation_func=None):
        """
        Assert that an operation follows proper error recovery patterns

        Args:
            operation_func: Function that should fail with expected error
            expected_error_type: Exception type that should be raised
            recovery_validation_func: Optional function to validate recovery state
        """
        initial_state = self._capture_database_state()

        # Execute operation and expect it to fail
        with self.assertRaises(expected_error_type):
            operation_func()

        # Validate database state after error
        post_error_state = self._capture_database_state()

        if not self._compare_database_states(initial_state, post_error_state):
            raise TransactionBoundaryError(
                "Database state changed after error - proper rollback may not have occurred"
            )

        # Run additional recovery validation if provided
        if recovery_validation_func:
            recovery_validation_func()

    def create_test_payment_entry(self, invoice, amount, mode_of_payment="Bank Transfer"):
        """
        Create a test payment entry for transaction testing

        Args:
            invoice: Sales Invoice document
            amount: Payment amount
            mode_of_payment: Payment mode

        Returns:
            Payment Entry document
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Create payment entry from invoice
        payment_entry = get_payment_entry(invoice.doctype, invoice.name)
        payment_entry.paid_amount = amount
        payment_entry.received_amount = amount
        payment_entry.mode_of_payment = mode_of_payment
        payment_entry.reference_no = f"TEST_PAYMENT_{int(time.time())}"
        payment_entry.reference_date = frappe.utils.today()

        payment_entry.insert()
        payment_entry.submit()

        return payment_entry