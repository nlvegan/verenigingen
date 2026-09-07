# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Live-flow regression test for #1048.

verenigingen.api.payment_plan_management.initiate_installment_payment is the
REAL Payment Plan installment payment path: it calls
PaymentHook.initiate_payment directly (not through the guest-reachable
verenigingen_payments.hooks.api.initiate_payment wrapper that #1048 hardens),
under its own session + ownership checks (self_service_api, plan.member must
match the caller). The #1048 fix touches only the guest wrapper in
verenigingen_payments/hooks/api.py, not this function or
PaymentHook.initiate_payment itself -- this test exercises the installment
path end to end (gateway stubbed) to confirm that fix left it working.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin

_GATEWAY_FACTORY_PATH = (
    "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway"
)
_MOLLIE_CONFIG_PATH = (
    "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_mollie_config"
)


class TestInitiateInstallmentPaymentFlow(PortalSelfServiceTestMixin, EnhancedTestCase):
    def test_installment_payment_flow_still_works_with_stubbed_gateway(self):
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        plan = frappe.get_doc(
            {
                "doctype": "Payment Plan",
                "member": member.name,
                "plan_type": "Equal Installments",
                "total_amount": 90.0,
                "number_of_installments": 3,
                "frequency": "Monthly",
                "start_date": today(),
                "status": "Active",
                "payment_method": "Bank Transfer",
            }
        )
        plan.insert(ignore_permissions=True)
        self.track_doc("Payment Plan", plan.name)

        gateway = MagicMock()
        gateway.process_payment.return_value = {
            "status": "redirect_required",
            "payment_url": "https://pay.example.test/checkout/installment",
            "payment_id": "tr_installment_stub",
        }

        with self._as_user(user.name):
            with patch(_MOLLIE_CONFIG_PATH, return_value={"available": True, "subscriptions_enabled": False}):
                with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                    result = initiate_installment_payment(plan=plan.name, installment_number=1, method="mollie")

        self.assertTrue(result["success"], result)
        gateway.process_payment.assert_called_once()

        forwarded_form_data = gateway.process_payment.call_args[0][1]
        # Amount is server-derived from the installment, not caller input --
        # unaffected by #1048 (this path never went through the hardened
        # guest wrapper), confirmed here so a future refactor that merges
        # the two paths doesn't silently reintroduce a caller-controlled sum.
        self.assertEqual(float(forwarded_form_data["amount"]), 30.0)

        intent_name = result["data"]["intent"]
        self.assertEqual(
            frappe.db.get_value("Payment Plan Payment", intent_name, "status"), "Pending"
        )
