"""Ratchet (#1291): a doctype form script may only call controller methods that exist.

`frm.call('name', ...)` and `frappe.call({method: 'name', doc: frm.doc})` are doc-bound:
Frappe dispatches them through `run_doc_method` to `name` on THAT doctype's controller. A
name the controller lacks does not fail at build time; the button just throws on click.
`verenigingen_settings.js` shipped two such buttons (`revoke_key`, `generate_webhook_secret`)
that live only on Verenigingen Payments Settings.

Whitelisting is only consulted at dispatch, so the check is membership in
`frappe.whitelisted`, which is exactly what `run_doc_method` consults.
"""

import re
from pathlib import Path

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

DOCTYPE_ROOT = Path(__file__).resolve().parents[2] / "verenigingen" / "doctype"

# frm.call('name' / frm.call("name"): Frappe's form.js attaches `doc: this.doc` for the string
# form only. `frm.call({method: 'bare'})` WITHOUT a doc is resolved to a module-level function
# of the doctype's module instead, so it is not doc-bound and is not scanned here.
FRM_CALL = re.compile(r"""frm\.call\(\s*["']([A-Za-z_]\w*)["']""")
# a bare (undotted) `method: 'name'` ...
BARE_METHOD = re.compile(r"""\bmethod\s*:\s*["']([A-Za-z_]\w*)["']""")
# ... that is doc-bound when `doc: frm.doc` sits in the same call object literal


def enclosing_object(text, pos):
    """The `{...}` literal around `pos`, found by balancing braces outward."""
    depth, start = 0, pos
    while start > 0:
        start -= 1
        if text[start] == "}":
            depth += 1
        elif text[start] == "{":
            if depth == 0:
                break
            depth -= 1
    depth, end = 0, start
    for end in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        if depth == 0:
            break
    return text[start : end + 1]


def doc_bound_calls(js_text):
    """Every bare method name a form script dispatches through run_doc_method."""
    names = set(FRM_CALL.findall(js_text))
    for match in BARE_METHOD.finditer(js_text):
        if re.search(r"\bdoc\s*:\s*frm\.doc\b", enclosing_object(js_text, match.start())):
            names.add(match.group(1))
    return names


def unresolved_calls(doctype_dir, doctype):
    js_text = (DOCTYPE_ROOT / doctype_dir / f"{doctype_dir}.js").read_text(encoding="utf-8")
    controller = frappe.get_doc({"doctype": doctype}).__class__
    return sorted(
        name
        for name in doc_bound_calls(js_text)
        if not (callable(getattr(controller, name, None)) and getattr(controller, name) in frappe.whitelisted)
    )


class TestFormScriptDocCallsResolve(EnhancedTestCase):
    def test_verenigingen_settings_calls_only_whitelisted_controller_methods(self):
        self.assertEqual(unresolved_calls("verenigingen_settings", "Verenigingen Settings"), [])

    def test_the_scan_sees_each_call_shape(self):
        """Control: the scanner must find every shape, or the test above can pass blind."""
        js = """
            frm.call('string_form', {a: 1});
            frm.call("double_quoted");
            frm.call({method: 'module_level', args: {}});
            frm.call({method: 'object_form_doc_bound', doc: frm.doc});
            frappe.call({method: 'doc_bound', doc: frm.doc, args: {}});
            frappe.call({method: 'verenigingen.api.dotted', args: {}});
            frappe.call({method: 'not_doc_bound', args: {}});
        """
        self.assertEqual(
            doc_bound_calls(js), {"string_form", "double_quoted", "object_form_doc_bound", "doc_bound"}
        )

    def test_a_method_missing_from_the_controller_is_reported(self):
        """Control: a name the controller lacks (the #1291 shape) is flagged, a real one is not."""
        controller = frappe.get_doc({"doctype": "Verenigingen Settings"}).__class__
        self.assertFalse(hasattr(controller, "revoke_key"))
        payments = frappe.get_doc({"doctype": "Verenigingen Payments Settings"}).__class__
        self.assertIn(payments.revoke_key, frappe.whitelisted)
