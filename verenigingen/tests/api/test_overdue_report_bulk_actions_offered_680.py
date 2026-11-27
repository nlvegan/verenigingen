"""#680: the overdue-payments report must only offer bulk actions the server accepts.

``execute_bulk_payment_action`` refuses an action outside its ``valid_actions`` list, and the
report dialog's callback then reported "{undefined} records processed". The dialog's options
and the server's list are both read from source (the options only exist in JS), so no data
is touched.
"""

import ast
import os
import re
import unittest

import verenigingen
from verenigingen.api import payment_processing

APP = os.path.dirname(verenigingen.__file__)
REPORT_JS = os.path.join(
    APP, "verenigingen", "report", "overdue_member_payments", "overdue_member_payments.js"
)


def _server_valid_actions_680():
    tree = ast.parse(open(payment_processing.__file__).read())
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "execute_bulk_payment_action"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "valid_actions" for t in node.targets
        ):
            return {e.value for e in node.value.elts}
    raise AssertionError("valid_actions assignment not found")


def _dialog_options_680():
    src = open(REPORT_JS).read()
    block = src[src.index("function show_bulk_payment_actions_dialog") :]
    options = re.search(r"fieldname: 'action'.*?options: \[(.*?)\]", block, re.S).group(1)
    return set(re.findall(r"'([^']+)'", options))


PENDING_JS = os.path.join(
    APP,
    "verenigingen",
    "report",
    "pending_membership_applications",
    "pending_membership_applications.js",
)


class TestOverdueReportBulkActionsOffered680(unittest.TestCase):
    def test_every_offered_action_is_accepted_by_the_server(self):
        offered, accepted = _dialog_options_680(), _server_valid_actions_680()
        self.assertEqual(offered - accepted, set(), "dialog offers actions the endpoint refuses")

    def test_parsers_see_real_options(self):
        """Control: the readers find the known-good actions, so an empty set cannot pass."""
        self.assertIn("Send Payment Reminders", _dialog_options_680())
        self.assertIn("Send Payment Reminders", _server_valid_actions_680())
        self.assertNotIn("Suspend Memberships", _server_valid_actions_680())

    def test_pending_applications_report_has_no_stub_bulk_dialog(self):
        """The report's 'Bulk Actions' dialog only msgprint-ed "Bulk action executed" and did
        nothing (maintainer ruling on #680: remove, do not implement)."""
        src = open(PENDING_JS).read()
        self.assertIn("frappe.query_reports['Pending Membership Applications']", src)  # control
        self.assertNotIn("Bulk action executed", src)
        self.assertNotIn("Approve Selected", src)
