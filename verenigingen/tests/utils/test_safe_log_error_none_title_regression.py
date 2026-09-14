# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Regression test for a defect #1121's fix introduced (found by CI, shard 8/12,
after both the author's own self-review and an independent review missed it).

This tree has 5 near-identical local helpers shaped
``safe_log_error(message, title=None)`` (``application_helpers.py``,
``account_creation_request.py``, ``volunteer.py``, ``employee_user_link.py``,
and ``admin_membership_operations.py``'s ``_safe_log_error``). Before #1121
they called ``frappe.log_error(safe_message, title)`` POSITIONALLY -- the
exact swap #1121 fixed. But that swap had an accidental side effect: with no
title supplied (``title=None``), the positional call put ``None`` in
frappe's own ``message`` slot, and frappe's ``if message:`` guard treated
``None`` as falsy and skipped straight past the branch that would have
touched it.

#1121 converted the call to keyword arguments,
``frappe.log_error(title=title, message=safe_message)`` -- correct when a
title IS given, but when it is not, this puts ``None`` in frappe's ``title``
slot with a TRUTHY ``message`` -- and frappe's own swap-detection heuristic
(``frappe/utils/error.py``) does ``if "\\n" in title:`` unconditionally
whenever ``message`` is truthy, with no None-guard of its own:

    TypeError: argument of type 'NoneType' is not a container or iterable

CI hit this for real via ``employee_user_link.safe_log_error`` in
``verenigingen/tests/integration/test_employee_user_link_security.py``
(``test_create_user_for_volunteer_without_permissions_is_refused``,
shard 8/12) -- a genuine caller that omits the title. This test exercises
the whole CLASS of 5 clones directly, at the narrowest possible layer, so a
future edit to any of them is caught here rather than by a real code path
that happens to omit a title.
"""

import frappe

from verenigingen.api.admin_membership_operations import _safe_log_error as _admin_membership_operations_log
from verenigingen.services.member.approval.application_helpers import (
    safe_log_error as _application_helpers_log,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.employee_user_link import safe_log_error as _employee_user_link_log
from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
    safe_log_error as _account_creation_request_log,
)
from verenigingen.verenigingen.doctype.volunteer.volunteer import safe_log_error as _volunteer_log

# The whole class this defect belongs to: every (message, title=None)-shaped
# clone in the tree, keyed by name for a readable subTest failure.
_SAFE_LOG_ERROR_CLONES = {
    "application_helpers.safe_log_error": _application_helpers_log,
    "account_creation_request.safe_log_error": _account_creation_request_log,
    "volunteer.safe_log_error": _volunteer_log,
    "employee_user_link.safe_log_error": _employee_user_link_log,
    "admin_membership_operations._safe_log_error": _admin_membership_operations_log,
}


class TestSafeLogErrorNoneTitleRegression(EnhancedTestCase):
    def test_call_with_no_title_does_not_raise_and_records_both_fields(self):
        for name, helper in _SAFE_LOG_ERROR_CLONES.items():
            with self.subTest(helper=name):
                marker = frappe.generate_hash(length=8)
                message = f"PROBE-{marker} diagnostic content, no title supplied"

                # The regression: this raised TypeError with title=None + a
                # truthy message, for every clone, before the fix below.
                helper(message)

                # tabError Log is MyISAM (non-transactional): frappe.log_error()
                # does a plain insert() in the current transaction, and a
                # same-connection query sees it immediately (read-your-own-
                # writes) -- no commit needed to read it back here.
                rows = frappe.get_all(
                    "Error Log",
                    filters={"error": ["like", f"%{marker}%"]},
                    fields=["name", "method", "error"],
                    order_by="creation desc",
                    limit=1,
                )
                self.assertTrue(rows, f"{name}: no Error Log row written for a no-title call")
                self.assertTrue(rows[0].method, f"{name}: title/method must not be empty/None")
                self.assertIn(marker, rows[0].error or "", f"{name}: full message must be recorded")
                frappe.delete_doc("Error Log", rows[0].name, force=True, ignore_permissions=True)
