"""#2829: the endpoint optimizer must emit Frappe's real rate limiter, not a no-op stub.

The optimizer rewrites API source. It used to emit
``@rate_limit(max_requests=..., window_minutes=...)`` and import ``rate_limit`` from
``api_validators``, whose version logged and always called the endpoint. Anything it
generated therefore believed it was limited and was not.
"""

import importlib
import re
import unittest

from frappe.rate_limiter import rate_limit as frappe_rate_limit

from verenigingen.utils.api_endpoint_optimizer import APIEndpointOptimizer

_WHITELISTED = "@frappe.whitelist()\ndef {name}(x):\n    pass\n"


def _optimizer_without_site_dependencies():
    # __init__ resolves the api directory via the site; the rewriters need none of it.
    return APIEndpointOptimizer.__new__(APIEndpointOptimizer)


def _rate_limit_lines(source):
    return [line for line in source.splitlines() if line.startswith("@rate_limit")]


class TestOptimizerEmitsFrappeRateLimit2829(unittest.TestCase):
    def _generated(self, name):
        return _optimizer_without_site_dependencies()._optimize_endpoints(_WHITELISTED.format(name=name))

    def test_generated_decorator_is_accepted_by_frappes_rate_limit(self):
        for name, expected_limit in (("bulk_export_members", 5), ("validate_member_input", 30)):
            with self.subTest(endpoint=name):
                lines = _rate_limit_lines(self._generated(name))
                self.assertEqual(len(lines), 1, f"expected exactly one @rate_limit line, got {lines}")
                # Evaluating it against Frappe's own signature is the discriminating check:
                # the old max_requests/window_minutes spelling raises TypeError here.
                decorator = eval(lines[0][1:], {"rate_limit": frappe_rate_limit})  # noqa: S307 - our own fixed text
                self.assertTrue(callable(decorator))
                self.assertEqual(int(re.search(r"limit=(\d+)", lines[0]).group(1)), expected_limit)
                self.assertIn("seconds=3600", lines[0])

    def test_generated_import_binds_frappes_rate_limit(self):
        content = _optimizer_without_site_dependencies()._add_imports("import frappe\n")
        namespace = {}
        exec(content, namespace)  # noqa: S102 - the generated import block, run to see what it binds
        self.assertIs(namespace["rate_limit"], frappe_rate_limit)

    def test_the_no_op_stub_is_gone(self):
        api_validators = importlib.import_module("verenigingen.utils.validation.api_validators")

        self.assertFalse(hasattr(api_validators, "rate_limit"))
