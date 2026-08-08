"""A failure must not reach the caller disguised as a legitimate value.

Target: the six handlers changed alongside this file, all of which used to log an
exception and then return a falsy value the caller could not distinguish from a
real answer. They were found by ``scripts/validation/error_swallow_validator.py``
and picked out of its 432-site baseline on one criterion: the swallowed value is
also a *plausible* answer, so nothing downstream looks wrong.

``0`` is the dangerous case. ``None`` and ``[]`` at least look like "nothing"; a
monetary ``0.0`` looks like a settled account, and a failure count of ``0`` looks
like a healthy subscription.

Each test forces the *infrastructure* to fail (a DB call raising) rather than
mocking business logic, then asserts the exception propagates. The paired
happy-path assertions matter as much: these functions must still return 0.0 when
the answer genuinely is zero, which is what makes the swallow so easy to miss.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.infrastructure.field_validator import ServiceFieldValidator
from verenigingen.utils import financial_utils, membership_dues_integration
from verenigingen.verenigingen_payments.mollie.api import payment_webhook
from verenigingen.verenigingen_payments.utils.sepa_zabbix_enhanced import SEPAZabbixIntegration

_BOOM = RuntimeError("database is down")


class MoneyFiguresTest(FrappeTestCase):
    """A swallowed error here becomes a wrong number, not a missing one."""

    def test_outstanding_amount_raises_instead_of_reporting_zero_owed(self):
        """0.0 from this reads as 'this customer owes nothing'."""
        with patch.object(frappe.db, "sql", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                financial_utils.get_total_outstanding_amount("CUST-0001")

    def test_member_ytd_raises_when_both_paths_fail(self):
        """The SQL path already degrades to this fallback; if it fails too, that
        is infrastructure failure, and 0.0 would report 'paid nothing this year'."""
        with patch.object(frappe, "get_all", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                membership_dues_integration._calculate_member_paid_ytd_python("CUST-0001")

    def test_member_ytd_still_returns_zero_when_there_are_no_invoices(self):
        """The happy path must be untouched -- a genuine zero is still 0.0."""
        with patch.object(frappe, "get_all", return_value=[]):
            self.assertEqual(
                membership_dues_integration._calculate_member_paid_ytd_python("CUST-0001"), 0.0
            )


class MonitoringMetricsTest(FrappeTestCase):
    """0.0 reported to monitoring is a false all-clear, not a missing datapoint."""

    def setUp(self):
        super().setUp()
        self.integration = SEPAZabbixIntegration()

    def test_total_batch_amount_raises_rather_than_reporting_zero_volume(self):
        with patch.object(frappe, "get_all", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                self.integration._calculate_total_batch_amount_python()

    def test_daily_batch_amount_raises_rather_than_reporting_zero_volume(self):
        with patch.object(frappe, "get_all", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                self.integration._calculate_daily_batch_amount_python(frappe.utils.now_datetime())


class SubscriptionFailureCountTest(FrappeTestCase):
    """The caller does `current + 1`, so a swallowed 0 restarts the escalation."""

    def test_raises_instead_of_reporting_zero_failures(self):
        with patch.object(frappe.db, "count", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                payment_webhook._get_subscription_failure_count("MEM-0001", "sub_abc")

    def test_still_returns_zero_for_a_subscription_with_no_failures(self):
        """A genuine zero must survive; it is the reason the swallow looked safe."""
        with patch.object(frappe.db, "count", return_value=0):
            self.assertEqual(payment_webhook._get_subscription_failure_count("MEM-0001", "sub_abc"), 0)


class DocTypeMetaCacheTest(FrappeTestCase):
    """The failure was written INTO the cache, making it permanent."""

    def test_raises_instead_of_returning_none(self):
        """The caller reads a falsy result as 'DocType does not exist' -- a
        database error must not be reported as a confidently wrong diagnosis."""
        validator = ServiceFieldValidator()
        with patch.object(frappe, "get_meta", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                validator.get_doctype_meta("Member")

    def test_failure_is_not_cached(self):
        """One transient error must not answer for every later call."""
        validator = ServiceFieldValidator()
        with patch.object(frappe, "get_meta", side_effect=_BOOM):
            with self.assertRaises(RuntimeError):
                validator.get_doctype_meta("Member")

        self.assertNotIn(
            "Member",
            validator._doctype_cache,
            "the failed lookup was cached, so the next call returns the failure without retrying",
        )

        # A subsequent healthy call must succeed rather than replay the failure.
        self.assertTrue(validator.get_doctype_meta("Member"))


if __name__ == "__main__":
    unittest.main()
