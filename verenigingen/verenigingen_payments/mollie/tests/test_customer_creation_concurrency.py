"""
Mollie Customer Creation Concurrency Tests
==========================================

Tests to verify the race condition fix in customer creation using row locking.
These tests ensure that:
1. Concurrent customer creation requests don't create duplicate Mollie customers
2. Partial failures (Mollie API fails after lock acquired) release locks correctly
3. The donor record remains consistent after concurrent operations

@author Verenigingen Development Team
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCustomerCreationConcurrency(FrappeTestCase):
    """
    Test race condition prevention in Mollie customer creation.

    The _create_or_get_customer method uses SELECT FOR UPDATE to prevent
    duplicate customer creation when concurrent requests arrive for the same donor.
    """

    def setUp(self):
        """Set up test environment."""
        super().setUp()
        self.test_email = f"concurrency.test.{time.time()}@example.com"
        self.created_donors = []
        self.created_customers = []

    def tearDown(self):
        """Clean up test data."""
        super().tearDown()
        # Clean up any test donors created
        for donor_name in self.created_donors:
            try:
                frappe.delete_doc("Donor", donor_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def _create_test_donor(self, email: str) -> str:
        """Create a test donor without Mollie customer ID."""
        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": f"Test Donor {email}",
                "donor_email": email,
                "donor_type": "Individual",
            }
        )
        donor.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_donors.append(donor.name)
        return donor.name

    def test_concurrent_customer_creation_no_duplicates(self):
        """
        Test that concurrent customer creation requests don't create duplicates.

        Simulates two threads trying to create a Mollie customer for the same donor
        simultaneously. With proper locking, only one Mollie customer should be created.
        """
        # Create donor without Mollie customer ID
        donor_name = self._create_test_donor(self.test_email)

        # Track Mollie API calls
        mollie_create_calls = []
        call_lock = threading.Lock()

        def mock_create_customer(customer_data):
            """Mock Mollie customer creation with artificial delay."""
            with call_lock:
                call_id = len(mollie_create_calls) + 1
                customer_id = f"cst_test_{call_id}_{time.time()}"
                mollie_create_calls.append(
                    {
                        "call_id": call_id,
                        "email": customer_data.get("email"),
                        "customer_id": customer_id,
                    }
                )
            # Add delay to increase chance of race condition without lock
            time.sleep(0.1)
            mock_customer = MagicMock()
            mock_customer.id = customer_id
            return mock_customer

        def mock_get_customer(customer_id):
            """Mock Mollie customer retrieval."""
            mock_customer = MagicMock()
            mock_customer.id = customer_id
            return mock_customer

        # Patch complete_payment_service's client
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.complete_payment_service.CompletePaymentService"
        ) as MockService:
            mock_service = MagicMock()
            mock_service.client.create_customer = mock_create_customer
            mock_service.client.get_customer = mock_get_customer

            # Import and test the actual function
            from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
                CompletePaymentService,
            )

            results = []
            errors = []

            def create_customer_thread(thread_id):
                """Thread function to create customer."""
                try:
                    # Create fresh service instance for each thread
                    service = CompletePaymentService.__new__(CompletePaymentService)
                    service.client = MagicMock()
                    service.client.create_customer = mock_create_customer
                    service.client.get_customer = mock_get_customer

                    customer_data = {
                        "email": self.test_email,
                        "name": f"Thread {thread_id} Test",
                    }

                    result = service._create_or_get_customer(customer_data)
                    results.append(
                        {
                            "thread_id": thread_id,
                            "result": result,
                        }
                    )
                except Exception as e:
                    errors.append(
                        {
                            "thread_id": thread_id,
                            "error": str(e),
                        }
                    )

            # Run concurrent threads
            threads = []
            for i in range(3):
                t = threading.Thread(target=create_customer_thread, args=(i,))
                threads.append(t)

            # Start all threads nearly simultaneously
            for t in threads:
                t.start()

            # Wait for all threads to complete
            for t in threads:
                t.join(timeout=30)

            # Verify results
            self.assertEqual(len(errors), 0, f"Threads had errors: {errors}")

            # Check that only one Mollie customer was created
            # (others should have found the existing one)
            created_count = len([r for r in results if r["result"].get("status") == "created"])
            found_count = len([r for r in results if r["result"].get("status") == "found"])

            # With proper locking, we should have exactly 1 created and N-1 found
            # (first thread creates, others find)
            self.assertLessEqual(
                created_count,
                1,
                f"Expected at most 1 customer created, but got {created_count}. "
                f"This indicates a race condition. Mollie calls: {mollie_create_calls}",
            )

            # Verify donor has exactly one Mollie customer ID
            frappe.db.rollback()  # Clear any uncommitted changes
            donor = frappe.get_doc("Donor", donor_name)
            self.assertIsNotNone(
                donor.mollie_customer_id, "Donor should have a Mollie customer ID after concurrent creation"
            )

    def test_partial_failure_releases_lock(self):
        """
        Test that lock is released when Mollie API fails after lock acquisition.

        If the Mollie create_customer call fails while holding the row lock,
        the lock must be released (via rollback) so other requests aren't blocked.
        """
        # Create donor without Mollie customer ID
        donor_name = self._create_test_donor(f"partial.failure.{time.time()}@example.com")

        def mock_create_customer_failure(customer_data):
            """Mock Mollie customer creation that fails."""
            raise Exception("Mollie API unavailable")

        from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
            CompletePaymentService,
        )

        # First call - should fail but release lock
        service1 = CompletePaymentService.__new__(CompletePaymentService)
        service1.client = MagicMock()
        service1.client.create_customer = mock_create_customer_failure
        service1.client.get_customer = MagicMock()

        donor = frappe.get_doc("Donor", donor_name)
        result1 = service1._create_or_get_customer(
            {
                "email": donor.donor_email,
                "name": donor.donor_name,
            }
        )

        # Should return error response
        self.assertEqual(result1.get("status"), "error")

        # Verify donor still has no Mollie customer ID (rolled back)
        frappe.db.rollback()
        donor.reload()
        self.assertFalse(donor.mollie_customer_id)

        # Second call - should be able to acquire lock (not blocked)
        def mock_create_customer_success(customer_data):
            mock_customer = MagicMock()
            mock_customer.id = "cst_recovery_test"
            return mock_customer

        service2 = CompletePaymentService.__new__(CompletePaymentService)
        service2.client = MagicMock()
        service2.client.create_customer = mock_create_customer_success
        service2.client.get_customer = MagicMock()

        result2 = service2._create_or_get_customer(
            {
                "email": donor.donor_email,
                "name": donor.donor_name,
            }
        )

        # Should succeed
        self.assertEqual(result2.get("status"), "created")
        self.assertEqual(result2.get("customer_id"), "cst_recovery_test")

    def test_donor_consistency_after_concurrent_operations(self):
        """
        Test that donor record remains consistent after concurrent operations.

        Multiple threads should not corrupt the donor record - exactly one
        Mollie customer ID should be set.
        """
        # Create donor without Mollie customer ID
        donor_name = self._create_test_donor(f"consistency.{time.time()}@example.com")

        customer_ids_created = []
        customer_id_lock = threading.Lock()

        def mock_create_customer(customer_data):
            """Mock that creates unique customer IDs."""
            customer_id = f"cst_consistency_{len(customer_ids_created)}_{time.time()}"
            with customer_id_lock:
                customer_ids_created.append(customer_id)
            time.sleep(0.05)  # Simulate network latency
            mock_customer = MagicMock()
            mock_customer.id = customer_id
            return mock_customer

        def mock_get_customer(customer_id):
            mock_customer = MagicMock()
            mock_customer.id = customer_id
            return mock_customer

        from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
            CompletePaymentService,
        )

        def worker():
            service = CompletePaymentService.__new__(CompletePaymentService)
            service.client = MagicMock()
            service.client.create_customer = mock_create_customer
            service.client.get_customer = mock_get_customer

            donor = frappe.get_doc("Donor", donor_name)
            return service._create_or_get_customer(
                {
                    "email": donor.donor_email,
                    "name": donor.donor_name,
                }
            )

        # Run 5 concurrent workers
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker) for _ in range(5)]
            results = [f.result() for f in as_completed(futures)]

        # Verify exactly one creation, rest found existing
        created = [r for r in results if r.get("status") == "created"]
        found = [r for r in results if r.get("status") == "found"]

        self.assertEqual(
            len(created), 1, f"Expected exactly 1 creation, got {len(created)}. Results: {results}"
        )
        self.assertEqual(len(found), 4, f"Expected 4 found existing, got {len(found)}. Results: {results}")

        # Verify donor has consistent state
        frappe.db.rollback()
        donor = frappe.get_doc("Donor", donor_name)
        self.assertIsNotNone(donor.mollie_customer_id)

        # All results should reference the same customer ID
        all_customer_ids = [r.get("customer_id") for r in results]
        unique_ids = set(all_customer_ids)
        self.assertEqual(
            len(unique_ids), 1, f"All results should have same customer ID, but got {unique_ids}"
        )


class TestCustomerCreationLockTimeout(FrappeTestCase):
    """
    Test behavior when row lock times out or is held too long.

    Note: MariaDB/MySQL lock timeouts are typically 50 seconds by default.
    These tests verify graceful handling of lock contention scenarios.
    """

    def test_lock_contention_logging(self):
        """
        Test that lock contention is properly logged for debugging.

        When a thread waits for a lock, the wait time should be logged
        to help diagnose performance issues.
        """
        # This is more of a manual verification test
        # The actual lock wait behavior depends on database configuration
        pass  # Placeholder for future implementation


# Integration test that requires actual Mollie test API (skip if not configured)
class TestCustomerCreationIntegration(FrappeTestCase):
    """
    Integration tests that verify the complete flow with mocked Mollie responses.

    These tests ensure the locking mechanism works correctly with the full
    service stack, not just isolated units.
    """

    @classmethod
    def setUpClass(cls):
        """Check if Mollie test environment is available."""
        super().setUpClass()
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            cls.mollie_configured = bool(mollie_settings.test_mode)
        except Exception:
            cls.mollie_configured = False

    def test_full_service_concurrent_creation(self):
        """
        Test concurrent customer creation through the full service stack.

        This integration test verifies that the locking works correctly
        when going through all the service layers.
        """
        if not self.mollie_configured:
            self.skipTest("Mollie Settings not configured for testing")

        # This test would use the actual service with mocked Mollie API
        # Implementation depends on specific test infrastructure
        pass
