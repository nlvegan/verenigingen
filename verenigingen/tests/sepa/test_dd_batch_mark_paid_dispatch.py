"""#1207: the Direct Debit Batch "Mark Invoices as Paid" button must be reachable.

The button used to call ``frappe.call({method: 'mark_invoices_as_paid', doc: frm.doc})``,
which dispatches through ``frappe.handler.run_doc_method``. That checks
``is_whitelisted`` on the BOUND INSTANCE method, which never carried
``@frappe.whitelist()``, so every click raised PermissionError before any batch
logic ran.

Whitelisting gates DISPATCH only, so these tests replay the dispatch the JS asks
for. The call is read out of the shipped ``.js`` file, not hardcoded here: if the
JS goes back to a doc-bound call, or names something that is not whitelisted, the
test follows it and reddens.

Scope: "Submit to Bank" / ``process_batch`` is deliberately NOT touched (no bank
API exists; its removal is a separate maintainer decision).

Probe shortcut, stated: the batch is a DRAFT with one real invoice row. A draft is
refused by the module function's own "must be submitted" guard, so reaching that
exact message proves dispatch and authorization let the call through into the batch
logic. It does not exercise the Payment Entry loop (see the out-of-scope note in
test_dd_batch_pipeline_coverage.py: that path commits).
"""

import re
from pathlib import Path

import frappe

from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
from verenigingen.tests.sepa.test_dd_batch_pipeline_coverage import (
    _BatchPipelineBase as _BatchBase,
)
from verenigingen.utils.error_handling import PermissionError as VPermissionError

BATCH_DIR = Path(__file__).resolve().parents[2] / "verenigingen_payments" / "doctype" / "direct_debit_batch"
JS_PATH = BATCH_DIR / "direct_debit_batch.js"
GUARD_MESSAGE = "Batch must be submitted before marking invoices as paid"


def _read_mark_paid_call():
    """Return (method, uses_doc, call_block) of the single frappe.call naming mark_invoices_as_paid."""
    source = JS_PATH.read_text()
    blocks = re.findall(r"frappe\.call\(\{(.*?)\n\t\t\t\}\);", source, flags=re.S)
    matches = [b for b in blocks if re.search(r"method:\s*['\"][^'\"]*mark_invoices_as_paid['\"]", b)]
    assert len(matches) == 1, f"expected exactly one mark_invoices_as_paid call in the JS, got {len(matches)}"
    block = matches[0]
    method = re.search(r"method:\s*['\"]([^'\"]+)['\"]", block).group(1)
    return method, bool(re.search(r"\bdoc:\s*frm\.doc", block)), block


class TestMarkInvoicesAsPaidDispatch(_BatchBase):
    def setUp(self):
        super().setUp()
        self.batch, _member, _mandate = self._one_invoice_batch()
        # Treasurer is the finance caller: its profile carries Verenigingen Staff (the
        # doctype's write role) AND clears the CRITICAL tier @critical_api demands.
        # Staff alone has doctype write but is capped at HIGH (the #1231 Staff-submit state).
        self.treasurer = self.create_test_user_with_roles(roles=["Verenigingen Staff"])
        assign_role_profile_to_user(self.treasurer.name, "Verenigingen Treasurer")
        self.staff = self.create_test_user_with_roles(roles=["Verenigingen Staff"])
        self.outsider = self.create_test_user_with_roles(roles=["Verenigingen Member"])
        self.method, self.uses_doc, self.call_block = _read_mark_paid_call()
        args_match = re.search(r"args:\s*\{\s*(\w+):\s*frm\.doc\.name", self.call_block)
        self.args_key = args_match.group(1) if args_match else None

    def _dispatch_as(self, user):
        """Replay the call the JS makes, through the same gates frappe.handler applies."""
        original = frappe.session.user
        try:
            frappe.set_user(user)
            if self.uses_doc:
                frappe.handler.run_doc_method(
                    method=self.method.rsplit(".", 1)[-1],
                    docs=frappe.get_doc("Direct Debit Batch", self.batch.name).as_json(),
                )
                return None
            fn = frappe.handler.get_attr(self.method)
            frappe.handler.is_whitelisted(fn)
            return frappe.call(fn, **{self.args_key: self.batch.name})
        finally:
            frappe.set_user(original)

    def test_js_names_a_dotted_module_function_not_a_doc_bound_call(self):
        self.assertFalse(self.uses_doc, "run_doc_method is gated on the unwhitelisted instance method")
        self.assertIn(".", self.method, "bare method names are deprecated shorthand")
        self.assertEqual(self.args_key, "batch_name")
        self.assertRegex(self.call_block, r"args:\s*\{\s*batch_name:\s*frm\.doc\.name\s*\}")
        self.assertIn(frappe.get_attr(self.method), frappe.whitelisted)

    def test_progress_dialog_is_hidden_on_every_outcome(self):
        """callback runs on success only; a refused/thrown call must still hide the dialog."""
        always = re.search(r"\balways\s*(?::\s*function)?\s*\([^)]*\)\s*\{(.*?)\}", self.call_block, re.S)
        self.assertIsNotNone(always, "no always() handler on the call")
        self.assertIn("frappe.hide_progress()", always.group(1))

    def test_finance_role_reaches_the_batch_logic(self):
        """Dispatch must reach the batch's own guard, not a PermissionError."""
        # The module function logs the guard it re-raises; that row is intended.
        self.expectErrorLog("SEPA Direct Debit Payment Error")
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._dispatch_as(self.treasurer.name)
        self.assertIn(GUARD_MESSAGE, str(ctx.exception))

    def test_user_without_the_role_is_refused_by_the_security_tier(self):
        """Control: refused by @critical_api's tier gate (not by 'not whitelisted', not the batch guard)."""
        for user in (self.outsider.name, self.staff.name):
            with self.assertRaises(VPermissionError) as ctx:
                self._dispatch_as(user)
            self.assertIn("Access denied", str(ctx.exception))
            self.assertNotIn(GUARD_MESSAGE, str(ctx.exception))
            self.assertNotIn("not whitelisted", str(ctx.exception))
