# Copyright (c) 2026, Verenigingen and contributors
import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanPayment(VereningingenTestCase):
    def _create_intent(self, installment_number, amount):
        # Shape guard only: skip mandatory/link validation so we don't need a real
        # plan (payment_plan is reqd; ignore_mandatory bypasses it for this check).
        intent = frappe.new_doc("Payment Plan Payment")
        intent.installment_number = installment_number
        intent.amount = amount
        intent.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def _persist_intent(self, intent):
        intent.save(ignore_permissions=True)

    def test_intent_defaults_and_fields(self):
        intent = self._create_intent(1, 40.0)

        intent.reload()
        self.assertEqual(intent.status, "Pending")
        self.assertEqual(intent.currency, "EUR")
        self.assertEqual(intent.paid, 0)
        self.assertEqual(intent.amount, 40.0)

    def test_status_transition_to_paid(self):
        intent = self._create_intent(1, 25.0)

        intent.status = "Paid"
        intent.paid = 1
        intent.payment_id = "tr_test123"
        self._persist_intent(intent)
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        self.assertEqual(intent.payment_id, "tr_test123")
