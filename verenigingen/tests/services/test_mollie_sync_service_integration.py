# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for MollieSyncService.

The companion test_mollie_sync_service.py exercises the service through
``unittest.mock.patch(... .frappe)``, so the actual DB writes, customer
creation, and the validate_mollie_data_preservation() audit loop are never
covered. This module fills those gaps with real Member / Customer fixtures and
derives every expectation from the data it creates.

The only mock boundary is the Mollie *validator* import seam inside
_validate_mollie_data (an external utility), and only where a test specifically
targets the ImportError fallback path.
"""

import frappe

from verenigingen.services.csv_import.mollie_sync_service import (
    MollieSyncService,
    get_mollie_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieSyncServiceIntegration(EnhancedTestCase):
    """Real-DB coverage for MollieSyncService.sync_mollie_data + helpers."""

    def setUp(self):
        super().setUp()
        self.service = MollieSyncService()

    def _ensure_customer(self, member):
        """Return the member's customer, creating one via the real path if absent."""
        if not member.customer:
            member._suppress_customer_messages = True
            member.customer = member.create_customer()
            member.save()
        return member.customer

    # ------------------------------------------------------------------
    # sync_mollie_data — full real path (Member + Customer round trip)
    # ------------------------------------------------------------------
    def test_sync_creates_customer_and_writes_ids_to_both_records(self):
        """Both Member and Customer records receive the Mollie IDs.

        create_test_member may or may not have populated member.customer; either
        way sync_mollie_data must ensure a customer exists and write to both.
        """
        member = self.create_test_member(
            first_name="Mollie", last_name="Sync", email="mollie.sync@example.com"
        )

        self.service.sync_mollie_data(
            member,
            {
                "custom_mollie_customer_id": "cst_realsync01x",
                "custom_mollie_subscription_id": "sub_realsync01x",
                "custom_subscription_status": "active",
            },
        )

        # Member record persisted with the IDs and status
        self.assertTrue(member.customer)
        member_row = frappe.db.get_value(
            "Member",
            member.name,
            ["mollie_customer_id", "mollie_subscription_id", "subscription_status"],
            as_dict=True,
        )
        self.assertEqual(member_row.mollie_customer_id, "cst_realsync01x")
        self.assertEqual(member_row.mollie_subscription_id, "sub_realsync01x")
        self.assertEqual(member_row.subscription_status, "active")

        # Customer record received only the two real columns (no status column)
        cust_row = frappe.db.get_value(
            "Customer",
            member.customer,
            ["custom_mollie_customer_id", "custom_mollie_subscription_id"],
            as_dict=True,
        )
        self.assertEqual(cust_row.custom_mollie_customer_id, "cst_realsync01x")
        self.assertEqual(cust_row.custom_mollie_subscription_id, "sub_realsync01x")

    def test_sync_honors_canceled_status_on_real_member(self):
        """Caller-supplied 'canceled' status is what lands in the DB, not 'active'."""
        member = self.create_test_member(
            first_name="Cancel", last_name="Sub", email="cancel.sub@example.com"
        )
        self.service.sync_mollie_data(
            member,
            {
                "custom_mollie_customer_id": "cst_cancel0001x",
                "custom_mollie_subscription_id": "sub_cancel0001x",
                "custom_subscription_status": "canceled",
            },
        )
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "canceled"
        )

    def test_sync_reuses_existing_customer(self):
        """When the member already has a customer, no new customer is created."""
        member = self.create_test_member(
            first_name="Has", last_name="Customer", email="has.customer@example.com"
        )
        # Establish a customer first via the real controller path (if not already set).
        if not member.customer:
            member._suppress_customer_messages = True
            member.customer = member.create_customer()
            member.save()
        existing_customer = member.customer

        self.service.sync_mollie_data(
            member,
            {
                "custom_mollie_customer_id": "cst_reuse00001x",
                "custom_mollie_subscription_id": "sub_reuse00001x",
            },
        )
        member.reload()
        self.assertEqual(member.customer, existing_customer)
        self.assertEqual(member.mollie_customer_id, "cst_reuse00001x")

    def test_sync_invalid_id_format_raises_and_logs(self):
        """An invalid Mollie ID format makes the validator throw, which propagates."""
        member = self.create_test_member(
            first_name="Bad", last_name="Format", email="bad.format@example.com"
        )
        self.expectErrorLog("Failed to update Customer with Mollie data", "Invalid Mollie data")
        with self.assertRaises(frappe.ValidationError):
            self.service.sync_mollie_data(
                member,
                {
                    # Wrong prefix -> validator marks invalid -> frappe.throw
                    "custom_mollie_customer_id": "WRONG_prefix",
                    "custom_mollie_subscription_id": "sub_ok1",
                },
            )

    # ------------------------------------------------------------------
    # _update_customer_mollie_fields — real DB write
    # ------------------------------------------------------------------
    def test_update_customer_writes_real_columns_only(self):
        member = self.create_test_member(
            first_name="Cust", last_name="Update", email="cust.update@example.com"
        )
        customer = self._ensure_customer(member)

        self.service._update_customer_mollie_fields(
            customer,
            {
                "custom_mollie_customer_id": "cst_upd000001x",
                "custom_mollie_subscription_id": "sub_upd000001x",
                # not a Customer column - must be ignored, no MySQL 1054
                "custom_subscription_status": "active",
            },
        )
        row = frappe.db.get_value(
            "Customer",
            customer,
            ["custom_mollie_customer_id", "custom_mollie_subscription_id"],
            as_dict=True,
        )
        self.assertEqual(row.custom_mollie_customer_id, "cst_upd000001x")
        self.assertEqual(row.custom_mollie_subscription_id, "sub_upd000001x")

    def test_update_customer_noop_when_no_real_ids(self):
        """Only a status key present -> nothing written, no error."""
        member = self.create_test_member(
            first_name="NoOp", last_name="Customer", email="noop.customer@example.com"
        )
        customer = self._ensure_customer(member)

        self.service._update_customer_mollie_fields(
            customer, {"custom_subscription_status": "canceled"}
        )
        self.assertIsNone(
            frappe.db.get_value("Customer", customer, "custom_mollie_customer_id")
        )

    # ------------------------------------------------------------------
    # _validate_mollie_data — real validator (no mock)
    # ------------------------------------------------------------------
    def test_validate_accepts_well_formed_ids(self):
        """A well-formed payload passes the real validator without throwing."""
        # Should not raise
        self.service._validate_mollie_data(
            {
                "custom_mollie_customer_id": "cst_valid0001x",
                "custom_mollie_subscription_id": "sub_valid0001x",
            }
        )

    def test_validate_rejects_malformed_customer_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_mollie_data(
                {"custom_mollie_customer_id": "not_a_cst_id"}
            )


class TestValidateMollieDataPreservation(EnhancedTestCase):
    """Real-DB coverage for validate_mollie_data_preservation()."""

    def setUp(self):
        super().setUp()
        self.service = get_mollie_sync_service()

    def _member_with_mollie_customer(self, *, status="Active", payment_method=None, **mollie):
        member = self.create_test_member(
            first_name="Preserve",
            last_name="Check",
            email=f"preserve.{frappe.generate_hash(length=6)}@example.com",
            status=status,
        )
        if not member.customer:
            member._suppress_customer_messages = True
            member.customer = member.create_customer()
        customer = member.customer
        if payment_method:
            member.payment_method = payment_method
        member.save()
        if mollie:
            frappe.db.set_value("Customer", customer, mollie)
        return member, customer

    def test_skips_members_without_customer(self):
        """A member with no customer contributes no issues."""
        member = self.create_test_member(
            first_name="NoCust", last_name="Skip", email="nocust.skip@example.com"
        )
        issues, fixed, critical = self.service.validate_mollie_data_preservation([member.name])
        self.assertEqual(issues, [])
        self.assertEqual(fixed, [])
        self.assertEqual(critical, [])

    def test_skips_customer_without_mollie_data(self):
        """A customer with no Mollie IDs is skipped entirely."""
        member, _ = self._member_with_mollie_customer()
        issues, fixed, critical = self.service.validate_mollie_data_preservation([member.name])
        self.assertEqual(issues, [])
        self.assertEqual(critical, [])

    def test_flags_invalid_id_formats(self):
        """Malformed customer/subscription IDs are reported as issues."""
        member, _ = self._member_with_mollie_customer(
            payment_method="Mollie",
            custom_mollie_customer_id="bad_cust",
            custom_mollie_subscription_id="bad_sub",
        )
        issues, fixed, critical = self.service.validate_mollie_data_preservation([member.name])
        joined = " ".join(issues)
        self.assertIn(member.name, joined)
        self.assertIn("Invalid Mollie Customer ID format", joined)
        self.assertIn("Invalid Mollie Subscription ID format", joined)

    def test_auto_fixes_payment_method_mismatch(self):
        """A non-Mollie payment method on a Mollie customer is auto-corrected."""
        member, _ = self._member_with_mollie_customer(
            payment_method="Bank Transfer",
            custom_mollie_customer_id="cst_pm1",
        )
        issues, fixed, critical = self.service.validate_mollie_data_preservation(
            [member.name], auto_fix_payment_method=True
        )
        self.assertTrue(any(member.name in f and "Mollie" in f for f in fixed))
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "payment_method"), "Mollie"
        )

    def test_reports_payment_method_mismatch_when_autofix_disabled(self):
        """With auto-fix off, the mismatch is an issue and nothing is changed."""
        member, _ = self._member_with_mollie_customer(
            payment_method="Bank Transfer",
            custom_mollie_customer_id="cst_pm2",
        )
        issues, fixed, critical = self.service.validate_mollie_data_preservation(
            [member.name], auto_fix_payment_method=False
        )
        self.assertEqual(fixed, [])
        self.assertTrue(any("Payment method should be 'Mollie'" in i for i in issues))
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "payment_method"), "Bank Transfer"
        )

    def test_critical_active_subscription_on_quit_member(self):
        """An active subscription on a Quit member is a CRITICAL issue."""
        member, _ = self._member_with_mollie_customer(
            status="Quit",
            payment_method="Mollie",
            custom_mollie_subscription_id="sub_quit1",
        )
        issues, fixed, critical = self.service.validate_mollie_data_preservation([member.name])
        self.assertEqual(len(critical), 1)
        self.assertIn("MANUAL CANCELLATION REQUIRED", critical[0])
        self.assertIn(member.name, critical[0])
        # Critical issues also surface in the per-member issues list.
        self.assertTrue(any("CRITICAL" in i for i in issues))

    def test_handles_nonexistent_member_gracefully(self):
        """A bad member name is caught and reported as an issue, not raised."""
        self.expectErrorLog("Error validating Mollie data")
        issues, fixed, critical = self.service.validate_mollie_data_preservation(
            ["MEMBER-DOES-NOT-EXIST"]
        )
        self.assertTrue(any("MEMBER-DOES-NOT-EXIST" in i for i in issues))
        self.assertTrue(any("Validation failed" in i for i in issues))
