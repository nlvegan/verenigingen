"""#1782: a test that skips in setUp must not leave the rate-limit stub installed.

unittest does not run tearDown when setUp raises (SkipTest included), so a stub
started in setUp and stopped only in tearDown outlives the test. Every later
test in the process then runs with validate_rate_limits stubbed, and a test that
needs the real limiter (test_mollie_subscription_webhook_rate_limit) counts
nothing. CI hit this when test_payment_processing_http_integration skipped
(server unreachable) ahead of it.
"""

import unittest

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.api_security_framework import APISecurityFramework


def _skipping_case(base):
    class _Skips(base):
        def setUp(self):
            super().setUp()
            self.skipTest("simulated: server unreachable")

        def test_noop(self):
            pass

    return _Skips


class TestRateLimitStubDoesNotLeak(unittest.TestCase):
    def _leaves_validate_rate_limits_alone(self, base):
        before = APISecurityFramework.validate_rate_limits
        result = unittest.TextTestRunner(stream=open("/dev/null", "w")).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(_skipping_case(base))
        )
        after = APISecurityFramework.validate_rate_limits
        try:
            # Control: the case really skipped in setUp (otherwise this proves nothing).
            self.assertEqual(len(result.skipped), 1)
            self.assertIs(after, before, "validate_rate_limits stub leaked past a setUp skip")
        finally:
            APISecurityFramework.validate_rate_limits = before

    def test_enhanced_test_case(self):
        self._leaves_validate_rate_limits_alone(EnhancedTestCase)

    def test_vereningingen_test_case(self):
        self._leaves_validate_rate_limits_alone(VereningingenTestCase)
