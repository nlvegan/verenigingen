"""
SubscriptionService.cancel_subscription() member/donor bookkeeping (#873), with the
Mollie SDK boundary faked (the live counterpart needs credentials CI never has).

The bookkeeping used to set `subscription_cancel_reason` / `subscription_canceled_at`
on Member and Donor, which neither doctype declares, so Frappe dropped them silently
(and Donor had none of the three fields, so its save was a no-op). It now routes
through CompletePaymentService's field-filtering owner update, which writes the
real Member field `subscription_cancelled_date` and skips what a doctype lacks.
"""

from types import SimpleNamespace

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService


class _FakeMollieClient:
    """Only the SDK boundary: cancel returns the subscription with the given metadata."""

    def __init__(self, metadata):
        self.metadata = metadata

    def cancel_subscription(self, customer_id, subscription_id):
        return SimpleNamespace(id=subscription_id, status="canceled", metadata=self.metadata)

    def is_test_mode(self):
        return True


class TestSubscriptionCancelBookkeeping(EnhancedTestCase):
    def _cancel(self, metadata):
        service = SubscriptionService(client=_FakeMollieClient(metadata))
        return service.cancel_subscription("cst_fake", "sub_fake", reason="member asked")

    def _active_member(self, last_name):
        member = self.create_test_member(first_name="CancelBook", last_name=last_name)
        frappe.db.set_value(
            "Member",
            member.name,
            {"subscription_status": "active", "subscription_cancelled_date": None},
            update_modified=False,
        )
        return member

    def test_membership_dues_cancel_records_status_and_date_on_member(self):
        member = self._active_member("Dues")
        bystander = self._active_member("Bystander")

        result = self._cancel({"subscription_type": "membership_dues", "member_id": member.name})

        self.assertEqual(result["status"], "success")
        row = frappe.db.get_value(
            "Member", member.name, ["subscription_status", "subscription_cancelled_date"], as_dict=True
        )
        self.assertEqual(row.subscription_status, "canceled")
        self.assertEqual(str(row.subscription_cancelled_date), today())
        # Control: a different member with a live subscription is untouched.
        self.assertEqual(frappe.db.get_value("Member", bystander.name, "subscription_status"), "active")
        self.assertIsNone(frappe.db.get_value("Member", bystander.name, "subscription_cancelled_date"))

    def test_recurring_donation_cancel_does_not_touch_donor(self):
        """Donor declares none of the subscription fields, so there is nothing to write;
        the old code still re-saved the Donor (bumping `modified`) for nothing."""
        donor = self.create_test_donor(
            donor_name="Cancel Book Donor",
            donor_email=f"cancel-book-{frappe.generate_hash(length=8)}@example.org",
            donor_type="Individual",
        )
        meta = frappe.get_meta("Donor")
        for fieldname in ("subscription_status", "subscription_cancel_reason", "subscription_canceled_at"):
            self.assertFalse(meta.has_field(fieldname), fieldname)
        modified_before = frappe.db.get_value("Donor", donor.name, "modified")

        result = self._cancel({"subscription_type": "recurring_donation", "donor_id": donor.name})

        self.assertEqual(result["status"], "success")
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "modified"), modified_before)

    def test_undeclared_names_stay_undeclared_on_member(self):
        """Control for the premise: the two names the old code wrote still are not
        Member fields, so a test reading them could never have seen a value."""
        meta = frappe.get_meta("Member")
        self.assertFalse(meta.has_field("subscription_cancel_reason"))
        self.assertFalse(meta.has_field("subscription_canceled_at"))
        self.assertTrue(meta.has_field("subscription_cancelled_date"))
