"""#3138: Suspended must be a reachable state in the SEPA mandate lifecycle.

Maintainer ruling 2026-11-24: allow exactly Active->Suspended, Suspended->Active and
Suspended->Cancelled. Draft and Pending cannot be suspended, and Suspended->Draft stays invalid.
``SEPAMandate`` itself sets Suspended whenever ``is_active`` is cleared, so the lifecycle map
reporting those moves as "Invalid status transition" was a false alarm waiting for a caller
that surfaces it.

Mandates are real (``create_mandate``). The in-memory ``status`` is assigned to stand in for the
edit that the doc hook would pass to ``handle_status_transition`` as ``old_status``; the
doctype's own status rules are not exercised here (probe shortcut, stated per brief).
"""

import frappe

from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
    SEPAMandateLifecycleService,
)


class TestSuspendedTransitions3138(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = SEPAMandateLifecycleService()
        member = self.create_test_member(
            first_name="Susp",
            last_name="Ended",
            birth_date="1990-01-01",
            email=f"susp.ended.{frappe.generate_hash(length=8)}@example.com",
        )
        mandate_id = f"M-3138-{frappe.generate_hash(length=8)}"
        result = get_sepa_mandate_manager().create_mandate(
            member=member.name,
            iban=generate_test_iban("RABO", "0123456789"),
            account_holder_name="Susp Ended",
            mandate_id=mandate_id,
        )
        self.assertTrue(result.valid, result.message)
        self.mandate = frappe.get_doc("SEPA Mandate", {"mandate_id": mandate_id})

    def _transition(self, old_status, new_status):
        self.mandate.status = new_status
        return self.service.handle_status_transition(self.mandate, old_status)

    def _assert_allowed(self, old_status, new_status):
        """Only the transition gate is under test: a Cancelled target also runs the cancellation
        handler, which fails on the unrelated #2989 field-name bug (PR #2999) until that merges."""
        result = self._transition(old_status, new_status)
        self.assertFalse(any("Invalid status transition" in e for e in result["errors"]), result)

    def _assert_refused(self, old_status, new_status):
        result = self._transition(old_status, new_status)
        self.assertFalse(result["success"], result)
        self.assertTrue(any("Invalid status transition" in e for e in result["errors"]), result)

    def test_active_to_suspended_is_allowed(self):
        self._assert_allowed("Active", "Suspended")

    def test_suspended_to_active_is_allowed(self):
        self._assert_allowed("Suspended", "Active")

    def test_suspended_to_cancelled_is_allowed(self):
        # TODO(#2999): once #2999 merges (cancelled_date fix), also assert
        # result["success"] is True and result["errors"] == [] here.
        self._assert_allowed("Suspended", "Cancelled")

    def test_control_draft_and_pending_cannot_be_suspended(self):
        self._assert_refused("Draft", "Suspended")
        self._assert_refused("Pending", "Suspended")

    def test_control_suspended_cannot_return_to_draft_or_pending_or_expire(self):
        for target in ("Draft", "Pending", "Expired", "Rejected"):
            with self.subTest(target=target):
                self._assert_refused("Suspended", target)

    def _link_row(self):
        rows = frappe.get_all(
            "Member SEPA Mandate Link",
            filters={"parent": self.mandate.member, "sepa_mandate": self.mandate.name},
            fields=["status", "is_current"],
        )
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_real_save_flow_syncs_the_member_link_for_suspend_and_reactivate(self):
        """Real flow: save() Active -> Suspended -> Active; the on_update hook syncs the link row."""
        self.mandate.reload()
        self.mandate.status = "Active"
        self.mandate.save()
        self.assertEqual(self._link_row().is_current, 1)

        self.mandate.status = "Suspended"
        self.mandate.save()
        row = self._link_row()
        self.assertEqual(row.status, "Suspended")
        self.assertEqual(row.is_current, 0)

        self.mandate.status = "Active"
        self.mandate.save()
        row = self._link_row()
        self.assertEqual(row.status, "Active")
        self.assertEqual(row.is_current, 1)
