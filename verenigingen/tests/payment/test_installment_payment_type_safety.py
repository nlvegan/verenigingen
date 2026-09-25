# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Dispatch-level type-safety regression tests for #1380.

initiate_installment_payment and calculate_payment_plan_preview
(verenigingen.api.payment_plan_management) were whitelisted with no type
annotations on their parameters, so Frappe's whitelist type-coercion layer
(frappe.utils.typing_validations.transform_parameter_types) never ran for
them: frappe.whitelist() short-circuits validation whenever a function's
__annotations__ holds only "return"
(transform_parameter_types: `len(annotations) == 1 and "return" in
annotations`). A dict- or list-typed `plan` was therefore accepted and
flowed into frappe.db.get_value("Payment Plan", plan, "member") as a QUERY
FILTER, not a document name lookup -- confirmed empirically on this bench
(2026-09-26): crafting `plan` as a dict filter matching the caller's own
Payment Plan satisfied the ownership check via filter semantics rather than
identity and reached a real (test-mode) gateway call. Not a NEW oracle
introduced by #1358 (both frappe.db.get_value and the prior frappe.get_doc
resolve identically for a dict filter), but real input-validation debt this
issue closes.

Frappe validates argument types INSIDE the frappe.whitelist() decorator
itself (frappe/__init__.py:457-466): `innerfn` wraps `fn` with
`validate_argument_types(fn, apply_condition=_in_request_or_test)` and
REPLACES the module-level function object with the wrapped one. So a plain
Python call to the (already-wrapped) function goes through the exact same
validation as an HTTP dispatch, as long as `_in_request_or_test()` is true
(frappe/__init__.py:429: `local.request or frappe.in_test`) -- and
`frappe.in_test` is always true under `bench run-tests`. This is the
established pattern for this class of test elsewhere in this repo
(test_balance_transaction_processing.py, test_payment_processing_recovery.py,
test_payment_entry_cleanup.py all assert FrappeTypeError this way): it is
the real dispatch path, not a bypass of it.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin

_GATEWAY_FACTORY_PATH = (
    "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway"
)
_MOLLIE_CONFIG_PATH = "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_mollie_config"


class TestInitiateInstallmentPaymentTypeSafety(PortalSelfServiceTestMixin, EnhancedTestCase):
    def _make_plan(self, member_name, total=90.0, n=3):
        plan = frappe.get_doc(
            {
                "doctype": "Payment Plan",
                "member": member_name,
                "plan_type": "Equal Installments",
                "total_amount": total,
                "number_of_installments": n,
                "frequency": "Monthly",
                "start_date": today(),
                "status": "Active",
                "payment_method": "Bank Transfer",
            }
        )
        plan.insert(ignore_permissions=True)
        self.track_doc("Payment Plan", plan.name)
        return plan

    def test_dict_plan_is_refused_at_dispatch(self):
        """A dict-typed `plan` must be rejected by Frappe's whitelist
        type-coercion BEFORE the function body runs -- not merely fail the
        ownership check inside the function (which would still execute a
        frappe.db.get_value query using the dict as a FILTER, per #1380)."""
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)
        self._make_plan(member.name)

        with self._as_user(user.name):
            with self.assertRaises(frappe.exceptions.FrappeTypeError):
                initiate_installment_payment(
                    plan={"member": member.name}, installment_number=1, method="mollie"
                )

    def test_list_plan_is_refused_at_dispatch(self):
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            with self.assertRaises(frappe.exceptions.FrappeTypeError):
                initiate_installment_payment(plan=["a", "b"], installment_number=1, method="mollie")

    def test_string_installment_number_from_a_real_caller_still_works(self):
        """payment_plan_pay.html's frappe.call sends installment_number as an
        unquoted JS number literal, but frappe.call/HTTP form-encoding turns
        every scalar argument into a string on the wire -- so the real
        caller's value arrives server-side as "1", not 1. The int annotation
        must COERCE this, not reject it, or the fix breaks the only real
        caller."""
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)
        plan = self._make_plan(member.name)

        gateway = MagicMock()
        gateway.process_payment.return_value = {
            "status": "redirect_required",
            "payment_url": "https://pay.example.test/checkout/installment",
            "payment_id": "tr_installment_stub",
        }

        with self._as_user(user.name):
            with patch(_MOLLIE_CONFIG_PATH, return_value={"available": True, "subscriptions_enabled": False}):
                with patch(_GATEWAY_FACTORY_PATH, return_value=gateway):
                    result = initiate_installment_payment(
                        plan=plan.name, installment_number="1", method="mollie"
                    )

        self.assertTrue(result["success"], result)
        gateway.process_payment.assert_called_once()


class TestCalculatePaymentPlanPreviewTypeSafety(EnhancedTestCase):
    """calculate_payment_plan_preview is the other unannotated function found
    by the #1380 class sweep in the same file. No JS or template caller
    exists for it (grep confirmed), so all real callers are the Python test
    suite itself, verified below to send only int/float/str -- annotating is
    caller-safe."""

    def test_dict_total_amount_is_refused_at_dispatch(self):
        from verenigingen.api.payment_plan_management import calculate_payment_plan_preview

        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            calculate_payment_plan_preview(total_amount={"$gt": 0}, installments=3, frequency="Monthly")

    def test_string_numeric_inputs_still_work(self):
        """Any future form/URL caller would send numeric fields as strings;
        the annotations must coerce, not reject, these."""
        from verenigingen.api.payment_plan_management import calculate_payment_plan_preview

        result = calculate_payment_plan_preview(total_amount="180.0", installments="6", frequency="Monthly")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["preview"]["number_of_installments"], 6)
