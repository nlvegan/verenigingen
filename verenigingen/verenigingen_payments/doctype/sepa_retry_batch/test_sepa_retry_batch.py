# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPARetryBatch(EnhancedTestCase):
    """SEPA Retry Operation's own validate() never runs -- Frappe never calls a child
    DocType's validate(). SEPARetryBatch.validate() -> validate_operations() already
    iterates ``self.operations`` and replicates most of the dead child checks (operation
    type required, error category allow-list, retry_attempts <= max_retries, max_retries
    default), but NOT the reference-document existence check or the next_retry_time
    backoff computation. See #596.
    """

    def _make_retry_batch(self, **operation_overrides):
        operation = {
            "operation_type": "Invoice Creation",
            "status": "Pending",
            "retry_attempts": 1,
            "max_retries": 3,
        }
        operation.update(operation_overrides)

        batch = frappe.get_doc(
            {
                "doctype": "SEPA Retry Batch",
                "batch_date": today(),
                "operations": [operation],
            }
        )
        return batch

    def tearDown(self):
        super().tearDown()

    def test_reference_document_that_does_not_exist_is_rejected(self):
        """A retry operation pointing at a nonexistent reference document must be rejected."""
        batch = self._make_retry_batch(
            reference_doctype="Sales Invoice",
            reference_document="SINV-DOES-NOT-EXIST-596",
        )

        with self.assertRaises(frappe.ValidationError):
            batch.insert()

    def test_next_retry_time_is_computed_for_a_pending_retry(self):
        """A Pending operation with retry_attempts > 0 must get a next_retry_time,
        computed as exponential backoff: base_delay_minutes(5) * 2**(attempts-1).

        Without it, should_retry_now() ("if not self.next_retry_time: return True")
        retries immediately with no backoff -- the exponential-backoff throttling the
        dead validate() implemented never actually applies today. Asserting only
        `assertTrue(next_retry_time)` would pass whether the delay is 5 minutes or
        5000 -- the backoff VALUE is the point of this rule, so pin it.
        """
        batch = self._make_retry_batch(status="Pending", retry_attempts=1, max_retries=3)
        before = now_datetime()
        batch.insert()

        next_retry_time = batch.operations[0].next_retry_time
        self.assertIsNotNone(next_retry_time)
        delay_minutes = (next_retry_time - before).total_seconds() / 60
        # retry_attempts=1 -> 5 * 2**(1-1) = 5 minutes. Allow a little slack for
        # the wall-clock gap between `before` and the save's own now_datetime().
        self.assertAlmostEqual(delay_minutes, 5.0, delta=0.5)
