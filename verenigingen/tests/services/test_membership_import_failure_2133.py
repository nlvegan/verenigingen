# -*- coding: utf-8 -*-
"""
#2133 round 2: the unified CSV membership path must not leave a Membership behind when the approval
pipeline refuses (below-minimum dues rate -> the dues schedule cannot be created), and its two MijnRood
callers must report the row/step as FAILED instead of treating the old `None` as "nothing to do".

Real rows: a real Member, a real Membership Type with minimum 24, dues_rate 0.5. The refusal is the real
`MembershipDuesSchedule.create_from_template` minimum check. No probe shortcuts except `member.status`
which is Active by default.
"""

import frappe

from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.services.csv_import.membership_import_service import get_membership_import_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipImportFailure2133(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        suffix = frappe.generate_hash(length=6)
        self.member = self.create_test_member(first_name="Below", last_name=f"Minimum{suffix}")
        self.membership_type = self.create_test_membership_type("Min24 2133", minimum_amount=24)
        self.row = {
            "member_id": self.member.name,
            "membership_type": self.membership_type.name,
            "dues_rate": 0.5,
            "member_since": frappe.utils.today(),
            "payment_period": "Maandelijks",
        }
        self.expectErrorLog("CSV Import - Membership Creation Failed")
        self.expectErrorLog("Dues Schedule Creation Failed")
        self.expectErrorLog("Membership Creation Failed")
        self.expectErrorLog("CSV Import - Membership Error")

    def _rows_for_member_2133(self, doctype):
        return frappe.db.count(doctype, {"member": self.member.name})

    def _assert_refused_row_left_nothing_2133(self):
        self.assertEqual(self._rows_for_member_2133("Membership"), 0, "a refused approval must leave no Membership")
        self.assertEqual(
            frappe.db.count("Membership Dues Schedule", {"member": self.member.name, "is_template": 0}), 0
        )

    def test_service_raises_and_leaves_no_membership(self):
        with self.assertRaises(frappe.ValidationError):
            get_membership_import_service().create_membership_from_csv(
                frappe.get_doc("Member", self.member.name), dict(self.row)
            )
        self._assert_refused_row_left_nothing_2133()

    def test_mijnrood_csv_row_is_reported_failed_and_leaves_no_membership(self):
        doc = frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "encoding": "utf-8", "import_date": frappe.utils.today()}
        )
        failed = doc._create_related_records_via_services(self.member.name, dict(self.row))
        self.assertIn("membership", failed)
        self._assert_refused_row_left_nothing_2133()

    def test_mijnrood_sync_step_is_reported_failed_and_leaves_no_membership(self):
        orchestrator = get_related_records_orchestrator()
        result = orchestrator._ensure_membership_and_dues(self.member.name, dict(self.row))
        self.assertIn("Membership creation failed", result or "")
        self.assertEqual(len(orchestrator._pending_alerts), 1, "one step-failure alert must be queued")
        self._assert_refused_row_left_nothing_2133()
