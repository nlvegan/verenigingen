"""EnhancedTestCase must unwind its own patches AFTER a test's nested patches (#2221).

unittest runs ``tearDown`` BEFORE ``addCleanup`` callbacks. The harness used to stop its
email and rate-limit patches in ``tearDown``, so a test that started its own
``patch(<same target>)`` in ``setUp`` with ``addCleanup(p.stop)`` recorded the HARNESS
mock as the "original", saw the real function restored by ``tearDown``, and then put the
harness mock back permanently with ``p.stop()`` (the #2197 develop red).

Driven through a real ``EnhancedTestCase`` subclass run via a manually built
``TestSuite``; the subclass has no ``test_*`` methods so bench does not collect it.
"""

import importlib
import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase

SENDMAIL = "frappe.sendmail"
QUEUE_SEND = "frappe.email.doctype.email_queue.email_queue.EmailQueue.send"
COMM_MAKE = "frappe.core.doctype.communication.email.make"
RATE_LIMIT = (
    "verenigingen.utils.security.api_security_framework.APISecurityFramework.validate_rate_limits"
)
# Every target EnhancedTestCase patches. A new harness patch must be added here.
HARNESS_TARGETS = [SENDMAIL, QUEUE_SEND, COMM_MAKE, RATE_LIMIT]


def _current_binding_at(dotted):
    """Fetch the object currently bound at a dotted path (class attributes included)."""
    parts = dotted.split(".")
    for i in range(len(parts) - 1, 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        for attr in parts[i:]:
            # Raw __dict__ first: getattr on a class unwraps functions, so identity differs
            obj = vars(obj)[attr] if attr in getattr(obj, "__dict__", {}) else getattr(obj, attr)
        return obj
    raise ImportError(dotted)


class _NestsHarnessPatches(EnhancedTestCase):
    """setUp nests a patch of EVERY harness target, each stopped via addCleanup."""

    def setUp(self):
        super().setUp()
        for target in HARNESS_TARGETS:
            nested = patch(target)
            nested.start()
            self.addCleanup(nested.stop)

    def step_noop(self):
        pass


class _NestsNothing(EnhancedTestCase):
    def step_noop(self):
        pass


VT_TARGETS = [
    "verenigingen.verenigingen_payments.mollie.utils.data_validator.validate_mollie_customer_data",
    "verenigingen.utils.security.csrf_protection.CSRFProtection.validate_request",
    RATE_LIMIT,
]


class _VtNestsHarnessPatches(VereningingenTestCase):
    """Same shape against VereningingenTestCase's own mocks (utils/base.py)."""

    def setUp(self):
        super().setUp()
        for target in VT_TARGETS:
            nested = patch(target)
            nested.start()
            self.addCleanup(nested.stop)

    def step_noop(self):
        pass


class _VtNestsNothing(VereningingenTestCase):
    def step_noop(self):
        pass


class TestHarnessPatchUnwindOrder(unittest.TestCase):
    def _hand_driven_leaves(self, case_class, targets):
        """Drive setUp()/tearDown() by hand, as tests that probe the harness do.

        No ``run()`` means ``doCleanups`` never fires, so the addCleanup stops (moved there
        by #2221) never run. Returns the targets still bound to a different object.
        """
        self._assert_all_real(targets)
        before = {t: _current_binding_at(t) for t in targets}
        probe = case_class("step_noop")
        try:
            probe.setUp()
        finally:
            probe.tearDown()
        stuck = [t for t in targets if _current_binding_at(t) is not before[t]]
        # Unwind whatever a failing run left behind so later modules are not polluted
        # by THIS test's own red.
        probe.doCleanups()
        return stuck

    def test_hand_driven_enhanced_setup_teardown_leaves_no_mock_bound(self):
        stuck = self._hand_driven_leaves(_NestsNothing, HARNESS_TARGETS)
        self.assertEqual(stuck, [], f"a hand-driven setUp/tearDown pair leaked mocks: {stuck}")

    def test_hand_driven_vereningingen_setup_teardown_leaves_no_mock_bound(self):
        stuck = self._hand_driven_leaves(_VtNestsNothing, VT_TARGETS)
        self.assertEqual(stuck, [], f"a hand-driven setUp/tearDown pair leaked mocks: {stuck}")

    def _assert_all_real(self, targets):
        """Each test checks its own starting state, so a leaked mock fails it cleanly."""
        from unittest.mock import NonCallableMock

        for target in targets:
            self.assertNotIsInstance(_current_binding_at(target), NonCallableMock, target)

    def test_nested_patch_of_every_harness_target_restores_the_real_object(self):
        self._assert_all_real(HARNESS_TARGETS)
        before = {t: _current_binding_at(t) for t in HARNESS_TARGETS}
        suite = unittest.TestSuite([_NestsHarnessPatches("step_noop")])
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.errors + result.failures, [], "the nested run itself must pass")

        after = {t: _current_binding_at(t) for t in HARNESS_TARGETS}
        stuck = [t for t in HARNESS_TARGETS if after[t] is not before[t]]
        self.assertEqual(
            stuck, [], f"targets left bound to a mock after the test finished: {stuck}"
        )

    def test_vereningingen_test_case_restores_the_real_object_for_every_mock_target(self):
        self._assert_all_real(VT_TARGETS)
        before = {t: _current_binding_at(t) for t in VT_TARGETS}
        result = unittest.TestResult()
        unittest.TestSuite([_VtNestsHarnessPatches("step_noop")]).run(result)
        self.assertEqual(result.errors + result.failures, [], "the nested run itself must pass")

        stuck = [t for t in VT_TARGETS if _current_binding_at(t) is not before[t]]
        self.assertEqual(stuck, [], f"targets left bound to a mock after the test finished: {stuck}")

    def test_control_the_real_objects_are_not_already_mocks(self):
        # A control for the test above: outside any harness run the targets are real,
        # so "restored to the original" is distinguishable from "stuck on a mock".
        from unittest.mock import NonCallableMock

        for target in HARNESS_TARGETS + VT_TARGETS:
            self.assertNotIsInstance(_current_binding_at(target), NonCallableMock, target)
        self.assertTrue(frappe.sendmail)
