# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/eligibility_checker.py

Strategy:
  - Fast-path checks (is_template/status/auto_generate/test_mode) read only
    attributes set in __init__, so a frappe._dict schedule stand-in faithfully
    exercises the real branch logic and EligibilityResult construction.
  - Member-status / customer / active-membership checks operate on REAL Member
    documents created by the factory (no business logic mocked).
  - EligibilityResult's own API (success/error_message/category/to_dict) is
    asserted directly.

NO permission bypass, NO mocking of the methods under test.
"""

import frappe

from verenigingen.services.billing.eligibility_checker import (
    EligibilityChecker,
    EligibilityResult,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _sched_stub(**kwargs):
    """Attribute stand-in for the schedule (EligibilityChecker only READS these in
    __init__). Real-doc-dependent methods are tested separately with real docs."""
    defaults = {
        "name": "TEST-ELIG-SCHED",
        "member": None,
        "billing_frequency": "Monthly",
        "status": "Active",
        "auto_generate": 1,
        "is_template": 0,
        "test_mode": 0,
        "membership_type": None,
        "next_invoice_date": None,
        "last_invoice_date": None,
        "invoice_days_before": None,
    }
    defaults.update(kwargs)
    return frappe._dict(defaults)


class TestEligibilityResult(EnhancedTestCase):
    def test_success_aliases_when_can_generate(self):
        r = EligibilityResult(True, "ok", "valid", extra=1)
        self.assertTrue(r.success)
        self.assertTrue(r.can_generate)
        self.assertIsNone(r.error_message)
        self.assertEqual(r.category, "valid")

    def test_error_message_set_on_failure(self):
        r = EligibilityResult(False, "blocked", "system")
        self.assertFalse(r.success)
        self.assertEqual(r.error_message, "blocked")

    def test_to_dict_flattens_metadata(self):
        r = EligibilityResult(False, "nope", "rate", rate_check_failed=True)
        d = r.to_dict()
        self.assertEqual(d["can_generate"], False)
        self.assertEqual(d["reason"], "nope")
        self.assertEqual(d["category"], "rate")
        self.assertTrue(d["rate_check_failed"])


class TestFastPathChecks(EnhancedTestCase):
    """check_eligibility fast-fail branches that need no DB I/O."""

    def test_template_blocked(self):
        checker = EligibilityChecker(_sched_stub(is_template=1))
        result = checker.check_eligibility()
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "system")
        self.assertEqual(result.reason, "Templates cannot generate invoices")

    def test_inactive_status_blocked(self):
        checker = EligibilityChecker(_sched_stub(status="Cancelled"))
        result = checker.check_eligibility()
        self.assertFalse(result.can_generate)
        self.assertEqual(result.reason, "Schedule is not active")

    def test_auto_generate_disabled_blocked(self):
        checker = EligibilityChecker(_sched_stub(auto_generate=0))
        result = checker.check_eligibility()
        self.assertFalse(result.can_generate)
        self.assertEqual(result.reason, "Auto generation is disabled")

    def test_test_mode_bypasses_remaining_checks(self):
        # test_mode True and no member -> short circuits to valid
        checker = EligibilityChecker(_sched_stub(test_mode=1, member=None))
        result = checker.check_eligibility()
        self.assertTrue(result.can_generate)
        self.assertEqual(result.category, "valid")
        self.assertEqual(result.reason, "Test mode - can generate")


class TestMemberStatusCheck(EnhancedTestCase):
    """check_member_status against REAL Member documents."""

    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        # Clear the batch-aggregation local set so it doesn't leak between tests
        if hasattr(frappe.local, "blocked_members"):
            frappe.local.blocked_members = {}
        for doctype, name in self._committed:
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _checker_for(self, member):
        return EligibilityChecker(_sched_stub(member=member.name))

    def test_active_member_status_valid(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        result = self._checker_for(member).check_member_status(member)
        self.assertTrue(result.can_generate)
        self.assertEqual(result.category, "valid")

    def test_quit_member_blocked(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        member.status = "Quit"
        result = self._checker_for(member).check_member_status(member)
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "member_status")
        self.assertEqual(result.metadata.get("member_status"), "Quit")
        # blocked member aggregated for batch reporting
        self.assertIn("Quit", frappe.local.blocked_members)

    def test_deceased_member_blocked(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        member.status = "Deceased"
        result = self._checker_for(member).check_member_status(member)
        self.assertFalse(result.can_generate)
        self.assertIn("Deceased", result.reason)

    def test_banned_member_blocked(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        member.status = "Banned"
        result = self._checker_for(member).check_member_status(member)
        self.assertFalse(result.can_generate)

    def test_suspended_member_can_be_billed(self):
        # Suspended is NOT in the ineligible list - they're still members
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        member.status = "Suspended"
        result = self._checker_for(member).check_member_status(member)
        self.assertTrue(result.can_generate)


class TestCustomerAndMembershipChecks(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        order = {"Membership": 0, "Customer": 1, "Member": 2}
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def test_customer_missing_blocked(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        # Explicitly clear any auto-created customer link to exercise the missing-customer branch
        member.customer = None
        checker = EligibilityChecker(_sched_stub(member=member.name))
        result = checker.check_customer_record(member)
        self.assertFalse(result.can_generate)
        self.assertTrue(result.metadata.get("missing_customer"))
        self.assertEqual(result.category, "system")

    def test_customer_present_valid(self):
        member = self.create_test_member()
        member.create_customer()
        member.reload()
        self._committed.append(("Member", member.name))
        self._committed.append(("Customer", member.customer))
        checker = EligibilityChecker(_sched_stub(member=member.name))
        result = checker.check_customer_record(member)
        self.assertTrue(result.can_generate)

    def test_no_active_membership_blocked(self):
        member = self.create_test_member()  # no membership submitted
        self._committed.append(("Member", member.name))
        checker = EligibilityChecker(_sched_stub(member=member.name))
        result = checker.check_active_membership(member)
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "membership")
        self.assertIn("no active membership", result.reason)

    def test_active_membership_present_valid(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        membership = self.create_test_membership(member_name=member.name)
        self._committed.append(("Membership", membership.name))
        checker = EligibilityChecker(_sched_stub(member=member.name))
        result = checker.check_active_membership(member)
        self.assertTrue(result.can_generate)


class TestCheckEligibilityOrphanedMember(EnhancedTestCase):
    def test_nonexistent_member_is_orphaned(self):
        # member name that does not exist -> DoesNotExistError -> orphaned result
        checker = EligibilityChecker(_sched_stub(member="DOES-NOT-EXIST-9999"))
        result = checker.check_eligibility()
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "member_status")
        self.assertTrue(result.metadata.get("orphaned"))
