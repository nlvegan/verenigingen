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

Parsing scope -- read this before touching the parser again:
    This is **not a JS parser**, and after two rounds of trying to make it a
    slightly-better one, round 3 stopped. It checks exactly one shape and
    refuses everything else:

    - A field-name argument that is a **plain quoted string literal**
      (``'foo'`` or ``"foo"``) is checked against the schema. This covers all
      17 real call sites in this file today.
    - **Anything else is unparseable and hard-fails** the
      ``test_no_unparseable_*`` tests below with "needs manual audit" --
      a variable (``frappe.model.set_value(cdt, cdn, someVar, value)``), a
      template literal, a concatenation, AND an object literal
      (``frm.set_value({ field1: v1, field2: v2 })``, the documented
      multi-field form of ``frm.set_value``).

    An earlier version of this test (round 2) also tried to parse the
    object-literal form and extract its keys. That attempt itself shipped two
    defects in one round: a flat regex that harvested keys from *nested*
    objects (phantom "missing field" reports against fields never actually
    written), and a spread/computed-key case that was silently absorbed with
    no warning at all -- the exact "silently skip what it cannot parse"
    failure this test exists to avoid. Round 3 removed that code rather than
    patching it again: every object literal is now unparseable, full stop.
    That can never produce a phantom field and can never silently drop one --
    the tradeoff is that a real object-literal call site (none exist in this
    file today) will need a human to look at it once, which is the correct
    default for a gate that would otherwise have to guess.

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
    """Classify a single call argument that is supposed to name the target
    field.

    Returns (fields, unparseable). `fields` is a single-element set holding
    the literal field name when `arg_text` is a plain quoted string, else
    empty. `unparseable` is True for anything else, INCLUDING an object
    literal -- this scanner deliberately does not parse object literals; see
    the module docstring's "Parsing scope" section for why.
    """
    literal = STRING_LITERAL_PATTERN.match(arg_text.strip())
    if literal:
        return {literal.group(2)}, False
    return set(), True


def _scan_model_set_value(source):
    """Every `frappe.model.set_value(doctype, name, fieldname, ...)` call.
    Returns (fields, unparseable_snippets)."""
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
    """Every `frm.set_value(fieldname, ...)` call. Returns (fields,
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
        """Fail LOUD, not silently, on a field-name argument that is not a
        plain quoted string literal -- a variable, a template literal, a
        concatenation, or an object literal. See the module docstring's
        "Parsing scope" section for why object literals are refused rather
        than parsed. An unparseable call needs a human to read it; that is
        different from (and a prerequisite to) the schema check below, which
        can only run on what it could classify."""
        _fields, unparseable = _scan_model_set_value(_js_source())
        self.assertEqual(
            unparseable,
            [],
            "frappe.model.set_value call(s) whose field-name argument is not a "
            f"plain string literal -- needs manual audit: {unparseable}",
        )

    def test_no_unparseable_frm_set_value_field_arguments(self):
        _fields, unparseable = _scan_frm_set_value(_js_source())
        self.assertEqual(
            unparseable,
            [],
            "frm.set_value call(s) whose field-name argument is not a plain "
            f"string literal -- needs manual audit: {unparseable}",
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
