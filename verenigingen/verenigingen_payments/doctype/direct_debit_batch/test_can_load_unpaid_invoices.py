"""
Tests for DirectDebitBatch.can_load_unpaid_invoices (#1221).

The "Load Unpaid Invoices" button on a Draft Direct Debit Batch is shown to
anyone who can create/write the DocType -- which the "Verenigingen Staff"
role (bare role OR role profile) can. But the button calls
``load_unpaid_invoices``, gated at CRITICAL, which per
``AuthorizationPolicy.PROFILE_ONLY_LEVELS`` is only reachable via an assigned
Role Profile of Treasurer / National Board Member / Verenigingen Admin /
Verenigingen System Administrator -- never via a bare role, and never via the
Staff role profile itself (Staff's own mapping tops out at HIGH). So a Staff
user of either shape sees the button and is refused every time.

``can_load_unpaid_invoices`` exists so the client can hide the button for
users who could never use it. These tests exercise the REAL authorization
boundary: real User records, real Role/Role Profile assignments, real session
switching -- no mocking of the function under test or of frappe.get_roles.

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.verenigingen_payments.doctype.direct_debit_batch.test_can_load_unpaid_invoices
"""

import frappe

from verenigingen.tests.security.test_authorization_coverage import AuthorizationTestBase
from verenigingen.utils.security.authorization_engine import get_authorization_engine
from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
    can_load_unpaid_invoices,
)


class TestCanLoadUnpaidInvoices(AuthorizationTestBase):
    """Reuses AuthorizationTestBase's `_make_user_with_role_profile` /
    `_make_user_with_roles` helpers (real User + Role/Role Profile records)
    rather than redefining them -- see that module's docstring for why these
    build REAL users instead of mocking frappe.get_roles."""

    def test_staff_bare_role_cannot_load_unpaid_invoices(self):
        """A user holding only the "Verenigingen Staff" ROLE (no Role Profile)
        can create/write/submit a Direct Debit Batch -- so they see the
        button -- but must be refused by the CRITICAL gate underneath it."""
        user = self._make_user_with_roles(["Verenigingen Staff"], prefix="ddbstaffrole")
        self.assertEqual(
            get_authorization_engine().get_user_role_profiles(user.name),
            [],
            "precondition: this user must have no assigned Role Profile",
        )
        with self.as_user(user.name):
            self.assertTrue(frappe.has_permission("Direct Debit Batch", "create"))
            self.assertFalse(can_load_unpaid_invoices())

    def test_staff_role_profile_cannot_load_unpaid_invoices(self):
        """A user with the Staff ROLE PROFILE assigned still can't use the
        button: Staff's own mapping tops out at HIGH, and this endpoint is
        CRITICAL."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="ddbstaffprof")
        with self.as_user(user.name):
            self.assertTrue(frappe.has_permission("Direct Debit Batch", "create"))
            self.assertFalse(can_load_unpaid_invoices())

    def test_treasurer_role_profile_can_load_unpaid_invoices(self):
        """A Treasurer Role Profile grants CRITICAL (rule_4_role_profile), so
        the button's underlying call actually succeeds for them -- the
        positive control proving the check isn't just always-False."""
        user = self._make_user_with_role_profile("Verenigingen Treasurer", prefix="ddbtreasurer")
        with self.as_user(user.name):
            self.assertTrue(can_load_unpaid_invoices())
