# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#1983 victim for MODULE-order reproduction: run it behind a polluting module with

    scripts/testing/order_dependence_detector.py --modules \
        verenigingen.tests.payment.test_ing_ponto_webhook_response_minimal,\
verenigingen.tests.utils.test_run_doc_method_response_victim

It owns no response state itself, so it reddens only when an EARLIER module leaked a bare
``frappe.local.response`` past its own test (CI shard 2 on #1980).
"""

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.test_response_guard import _run_doc_method_victim


class TestRunDocMethodBehindAnotherModule(EnhancedTestCase):
    def test_run_doc_method_appends_to_docs(self):
        response = _run_doc_method_victim(self)
        self.assertEqual(len(response["docs"]), 1)
