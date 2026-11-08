"""#2282: a critical operation must not proceed when its business-rule check ERRORS.

``validate_critical_operation_business_rules`` used to catch every exception and return ``[]``,
which the decorator reads as "no violations". The realistic trigger is caller-controlled: the
only rule the registry evaluates is the amount threshold, and it does ``float(amount)`` on a
request kwarg, so ``amount="abc"`` raised and the threshold was skipped for exactly the
request that should not be trusted.

The tests drive a real ``@critical_api`` function whose Critical Operation Rule has
``security_level=critical`` and ``enable_business_validation=1``. The side effect is a list
append inside the endpoint body.
"""

import frappe
from frappe.exceptions import QueryDeadlockError

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import ValidationError as VValidationError
from verenigingen.utils.secure_operations import get_critical_operations_registry
from verenigingen.utils.security.api_security_framework import critical_api
from verenigingen.utils.security.types import OperationType

OPERATION = "probe_2282_credit_account"
THRESHOLD = 100
SIDE_EFFECTS = []


@critical_api(OperationType.FINANCIAL)
def probe_2282_credit_account(amount=None):
    SIDE_EFFECTS.append(amount)
    return {"credited": amount}


class TestCriticalBusinessRulesFailClosed(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        SIDE_EFFECTS.clear()
        self._drop_rule()
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": OPERATION,
                "operation_type": "financial",
                "security_level": "critical",
                "enabled": 1,
                "enable_business_validation": 1,
                "amount_threshold": THRESHOLD,
                "audit_level": "minimal",
            }
        )
        rule.flags.ignore_permissions = True
        rule.insert()
        self._reset_caches()

    def tearDown(self):
        self._drop_rule()
        self._reset_caches()
        super().tearDown()

    def _drop_rule(self):
        for name in frappe.get_all("Critical Operation Rule", {"operation_name": OPERATION}, pluck="name"):
            frappe.delete_doc("Critical Operation Rule", name, force=True)

    def _reset_caches(self):
        registry = get_critical_operations_registry()
        registry.operation_configs.pop(OPERATION, None)
        frappe.cache().delete_value("critical_operation_rules")
        frappe.cache().delete_value(f"critical_operation_rule:{OPERATION}")
        frappe.cache.delete_value(f"critical_op_check:{__name__}.{OPERATION}")

    def _call(self, amount):
        with self.set_user("Administrator"):
            return probe_2282_credit_account(amount=amount)

    def test_control_the_rule_is_really_wired_to_the_endpoint(self):
        config = get_critical_operations_registry().get_operation_config(OPERATION)
        self.assertEqual(config["security_level"], "critical")
        self.assertTrue(config["business_rules"]["enabled"])
        self.assertEqual(float(config["business_rules"]["amount_threshold"]), THRESHOLD)

    def test_clean_evaluation_with_no_violation_allows(self):
        self.assertEqual(self._call(THRESHOLD - 1), {"credited": THRESHOLD - 1})
        self.assertEqual(SIDE_EFFECTS, [THRESHOLD - 1])

    def test_real_violation_still_refuses_with_its_normal_message(self):
        with self.assertRaises(VValidationError) as ctx:
            self._call(THRESHOLD + 1)
        self.assertIn("Critical business rule violations", str(ctx.exception))
        self.assertIn(f"exceeds threshold {THRESHOLD}", str(ctx.exception))
        self.assertEqual(SIDE_EFFECTS, [])

    def test_errored_evaluation_refuses_and_the_side_effect_does_not_happen(self):
        # "abc" makes the registry's float(amount) raise ValueError, for real.
        self.expectErrorLog("Critical business rule evaluation failed")
        with self.assertRaises(VValidationError) as ctx:
            self._call("abc")
        self.assertEqual(SIDE_EFFECTS, [], "the critical operation ran although its rule check errored")
        message = str(ctx.exception)
        self.assertNotIn(OPERATION, message, "refusal leaks the operation name")
        self.assertNotIn("abc", message, "refusal leaks the input / error text")
        self.assertNotIn("float", message)

    def test_errored_evaluation_is_recorded_in_the_error_log(self):
        self.expectErrorLog("Critical business rule evaluation failed")
        before = frappe.db.count("Error Log", {"method": ["like", "%critical business rule%"]})
        with self.assertRaises(VValidationError):
            self._call("abc")
        after = frappe.db.count("Error Log", {"method": ["like", "%critical business rule%"]})
        self.assertEqual(after, before + 1)

    def test_a_deadlock_propagates_unflattened(self):
        registry = get_critical_operations_registry()
        original = registry.validate_business_rules

        def deadlock(*args, **kwargs):
            raise QueryDeadlockError("1213")

        registry.validate_business_rules = deadlock  # Mock justified: a real 1213 needs two sessions
        try:
            with self.assertRaises(QueryDeadlockError):
                self._call(1)
        finally:
            registry.validate_business_rules = original
        self.assertEqual(SIDE_EFFECTS, [])
