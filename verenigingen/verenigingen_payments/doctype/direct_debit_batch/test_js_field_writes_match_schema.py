"""Structural gate: direct_debit_batch.js must write field names the target
DocType actually has.

Why this needs a test at all (#1251/#1263 review):
    ``frappe.model.set_value(doctype, name, fieldname, value)`` and
    ``frm.set_value(fieldname, value)`` both silently no-op when ``fieldname``
    is not a real field on the target DocType -- no console error, no server
    round-trip failure, the value just never persists (see MEMORY.md:
    "assigning nonexistent doc field is silent no-op"). That is exactly what
    happened here TWICE with the same wrong name, ``mandate_date`` instead of
    the real field ``mandate_sign_date``:

    - :317, inside the ``invoices_add`` handler -- latent until #1251 also
      repaired the dead doctype registration it lived under.
    - :670, inside ``validate_mandates`` -- NOT gated by #1251's registration
      bug at all. The "Validate Mandates" button that calls it has no
      client-side visibility pre-check (unlike "Load Unpaid Invoices", which
      asks ``can_load_unpaid_invoices`` first) -- but the endpoint it calls,
      ``validate_invoice_mandate``, IS gated server-side, at
      ``@high_security_api(operation_type=OperationType.FINANCIAL)`` (HIGH is
      in ``PROFILE_ONLY_LEVELS`` in ``authorization_policy.py``, so it is only
      reachable via an assigned Role Profile). So this one was live for any
      user who could actually reach it, before this fix: clicking the button
      fetched the correct mandate sign date from the server and then silently
      failed to save it.

    A single corrected literal only proves that one call site; a sibling call
    with the same wrong name elsewhere in the file would pass unnoticed (as
    :670 did in the first pass of this fix). This test instead extracts every
    field name written by either call shape and checks it against the real
    DocType schema, so it generalises the gate instead of pinning one line.

Parsing scope, and what happens outside it (round-2 review finding):
    A first version of this test matched only a quoted string as the
    field-name argument, via a regex requiring ``['"]`` in that position. That
    silently passed on two shapes that are real, legitimate Frappe API calls
    and would have hidden the exact defect class this test exists to catch:

    - ``frm.set_value({ field1: v1, field2: v2 })`` -- the documented
      multi-field object-literal form (frappe/public/js/frappe/form/form.js,
      ``set_value``), not merely a hypothetical shape.
    - A field name passed as a variable/expression, e.g.
      ``frappe.model.set_value(cdt, cdn, someVar, value)``.

    Neither shape appears in this file today (see the "no unparseable calls"
    tests below, which assert that and fail loudly if it ever stops being
    true), but a scanner that silently skips what it cannot parse is this
    repo's single most-repeated failure. So this version does two things
    instead of one: (1) also parses the object-literal form and checks its
    keys, and (2) treats any OTHER shape (a variable, a template literal, a
    concatenation, ...) as a hard failure demanding manual audit, rather than
    quietly not matching it.

Scope: every ``frappe.model.set_value(...)`` call in this file targets a row
of the ``invoices`` child table (confirmed by reading the file -- there are no
other child tables here), so those field names are checked against
``Direct Debit Batch Invoice``. Every ``frm.set_value(...)`` call targets the
parent document, checked against ``Direct Debit Batch``. If a future edit adds
a ``frappe.model.set_value`` call against some other child table in this file,
this test's single-doctype assumption would need revisiting -- the control
tests below at least catch the scan going quiet, even if they cannot catch a
wrong-doctype assumption.
"""

import os
import re

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.js_source_scan import strip_js_comments

STRING_LITERAL_PATTERN = re.compile(r"""^(['"])(.*)\1$""", re.DOTALL)
# A top-level `key: ` or `'key': ` inside an object literal's body.
OBJECT_KEY_PATTERN = re.compile(r"""(?:^|[{,]\s*)(?:(['"])([^'"]+)\1|([A-Za-z_$][\w$]*))\s*:""")


def _js_path():
    return os.path.join(
        frappe.get_app_path("verenigingen"),
        "verenigingen_payments",
        "doctype",
        "direct_debit_batch",
        "direct_debit_batch.js",
    )


def _js_source():
    with open(_js_path(), encoding="utf-8") as fh:
        return strip_js_comments(fh.read())


def _iter_call_arg_lists(source, call_prefix):
    """Yield the raw text between the outer parens of every `call_prefix(...)`
    call in source, honouring nested (), {}, [] and quoted strings so an
    inner `)`, `}` or `,` does not end the scan early or split an argument
    incorrectly. `call_prefix` must already include the opening `(`."""
    start_idx = 0
    while True:
        start = source.find(call_prefix, start_idx)
        if start == -1:
            return
        i = start + len(call_prefix)
        depth = 1
        in_string = None
        arg_start = i
        while i < len(source) and depth > 0:
            ch = source[i]
            if in_string:
                if ch == "\\":
                    i += 1
                elif ch == in_string:
                    in_string = None
            elif ch in ("'", '"', "`"):
                in_string = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            i += 1
        yield source[arg_start : i - 1]
        start_idx = i


def _split_top_level_args(arg_text):
    """Split a call's argument-list text on top-level commas only."""
    if not arg_text.strip():
        return []
    args = []
    depth = 0
    in_string = None
    current = []
    i = 0
    while i < len(arg_text):
        ch = arg_text[i]
        if in_string:
            current.append(ch)
            if ch == "\\":
                i += 1
                if i < len(arg_text):
                    current.append(arg_text[i])
            elif ch == in_string:
                in_string = None
        elif ch in ("'", '"', "`"):
            in_string = ch
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    args.append("".join(current).strip())
    return args


def _classify_field_argument(arg_text):
    """Classify a single call argument that is supposed to name one or more
    target fields.

    Returns (fields, unparseable): `fields` is a set of field-name strings
    (empty if the argument could not be classified), `unparseable` is a bool.
    """
    arg_text = arg_text.strip()

    literal = STRING_LITERAL_PATTERN.match(arg_text)
    if literal:
        return {literal.group(2)}, False

    if arg_text.startswith("{") and arg_text.endswith("}"):
        keys = set()
        for match in OBJECT_KEY_PATTERN.finditer(arg_text):
            keys.add(match.group(2) or match.group(3))
        # An object literal with no keys we could extract (e.g. spread-only,
        # computed keys) is itself unparseable -- do not silently pass it.
        return keys, len(keys) == 0

    return set(), True


def _scan_model_set_value(source):
    """Every `frappe.model.set_value(doctype, name, fieldname_or_dict, ...)`
    call. Returns (fields, unparseable_snippets)."""
    fields = set()
    unparseable = []
    for arg_list in _iter_call_arg_lists(source, "frappe.model.set_value("):
        args = _split_top_level_args(arg_list)
        if len(args) < 3:
            unparseable.append(f"frappe.model.set_value({arg_list})")
            continue
        found, bad = _classify_field_argument(args[2])
        fields |= found
        if bad:
            unparseable.append(f"frappe.model.set_value({arg_list})")
    return fields, unparseable


def _scan_frm_set_value(source):
    """Every `frm.set_value(fieldname_or_dict, ...)` call. Returns (fields,
    unparseable_snippets)."""
    fields = set()
    unparseable = []
    for arg_list in _iter_call_arg_lists(source, "frm.set_value("):
        args = _split_top_level_args(arg_list)
        if not args or not args[0]:
            unparseable.append(f"frm.set_value({arg_list})")
            continue
        found, bad = _classify_field_argument(args[0])
        fields |= found
        if bad:
            unparseable.append(f"frm.set_value({arg_list})")
    return fields, unparseable


class TestDirectDebitBatchJsFieldWritesMatchSchema(EnhancedTestCase):
    def test_scan_finds_a_realistic_number_of_child_row_writes(self):
        """Control: if the parser silently stopped matching (e.g. the call
        shape changed), the real assertions below would vacuously pass."""
        fields, unparseable = _scan_model_set_value(_js_source())
        self.assertGreater(len(fields) + len(unparseable), 3, "frappe.model.set_value scan found too few")

    def test_scan_finds_a_realistic_number_of_parent_writes(self):
        fields, unparseable = _scan_frm_set_value(_js_source())
        self.assertGreater(len(fields) + len(unparseable), 3, "frm.set_value scan found too few")

    def test_no_unparseable_model_set_value_field_arguments(self):
        """Fail LOUD, not silently, on a field-name argument this scanner
        cannot classify (a variable, a template literal, a concatenation,
        ...) -- see the module docstring's "Parsing scope" section. An
        unparseable call needs a human to read it; that is different from
        (and a prerequisite to) the schema check below, which can only run on
        what it could classify."""
        _fields, unparseable = _scan_model_set_value(_js_source())
        self.assertEqual(
            unparseable,
            [],
            "frappe.model.set_value call(s) whose field-name argument is not a "
            f"string or object literal -- needs manual audit: {unparseable}",
        )

    def test_no_unparseable_frm_set_value_field_arguments(self):
        _fields, unparseable = _scan_frm_set_value(_js_source())
        self.assertEqual(
            unparseable,
            [],
            "frm.set_value call(s) whose field-name argument is not a string "
            f"or object literal -- needs manual audit: {unparseable}",
        )

    def test_child_row_field_writes_exist_on_direct_debit_batch_invoice(self):
        fields, _unparseable = _scan_model_set_value(_js_source())
        meta = frappe.get_meta("Direct Debit Batch Invoice")
        missing = sorted(f for f in fields if not meta.has_field(f))
        self.assertEqual(
            missing,
            [],
            "direct_debit_batch.js writes child-row field(s) via frappe.model.set_value "
            f"that do not exist on Direct Debit Batch Invoice (silent no-op): {missing}",
        )

    def test_parent_field_writes_exist_on_direct_debit_batch(self):
        fields, _unparseable = _scan_frm_set_value(_js_source())
        meta = frappe.get_meta("Direct Debit Batch")
        missing = sorted(f for f in fields if not meta.has_field(f))
        self.assertEqual(
            missing,
            [],
            "direct_debit_batch.js writes parent field(s) via frm.set_value that do not "
            f"exist on Direct Debit Batch (silent no-op): {missing}",
        )
