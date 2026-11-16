"""#2526: the Mollie test helpers must write values Member.subscription_status accepts.

The Select's options use the American spelling ("canceled"). The Emma persona
cleanup saved "cancelled", which Frappe's Select validation rejects; the
helper's own ``except Exception`` swallowed that, so the cleanup reported a
cancelled subscription it never recorded. The factory's edge-case scenario
carried the same invalid value as data.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.tests import subscription_persona
from verenigingen.verenigingen_payments.mollie.tests.fixtures.factory import MollieTestDataFactory

GATEWAY_FACTORY = "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory"


class _CancellingGateway:
    def cancel_subscription(self, customer_id, subscription_id):
        return True


def _unwrapped_cleanup():
    fn = subscription_persona.cleanup_emma_persona
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _status_options():
    field = frappe.get_meta("Member").get_field("subscription_status")
    return [o for o in (field.options or "").split("\n") if o]


class TestMollieTestHelpersCanceledSpelling(EnhancedTestCase):
    def test_select_options_use_american_spelling(self):
        # Control: the premise the two helpers are checked against.
        options = _status_options()
        self.assertIn("canceled", options)
        self.assertNotIn("cancelled", options)

    def test_cleanup_persona_records_canceled_on_the_member(self):
        member = self.create_test_member(
            first_name="Emma",
            last_name="van Subscription",
            email=f"emma.{frappe.generate_hash(length=8)}@example.com",
        )
        member.mollie_customer_id = "cst_2526"
        member.mollie_subscription_id = "sub_2526"
        member.subscription_status = "active"
        member.save(ignore_permissions=True)

        with patch(f"{GATEWAY_FACTORY}.get_gateway", return_value=_CancellingGateway()):
            result = _unwrapped_cleanup()(member.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "subscription_status"), "canceled")

    def test_edge_case_scenarios_only_carry_valid_subscription_statuses(self):
        scenarios = MollieTestDataFactory(seed=12345, use_faker=False).create_edge_case_scenarios()
        carried = [s["subscription_status"] for s in scenarios if "subscription_status" in s]
        # Control: the scenario that carries a status must exist, or this asserts nothing.
        self.assertTrue(carried, "no edge-case scenario carries a subscription_status")
        for value in carried:
            self.assertIn(value, _status_options())
