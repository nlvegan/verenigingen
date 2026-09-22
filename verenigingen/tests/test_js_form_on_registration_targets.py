"""Static/structural gate: `frappe.ui.form.on(doctype, {...})` must name a real DocType.

Why this needs a test at all (#1251):
    Frappe's script manager keys handler registrations by the exact doctype string
    passed to `frappe.ui.form.on` (`frappe.ui.form.handlers[doctype][event_name]`,
    frappe/public/js/frappe/form/script_manager.js). Dispatch later looks the handler
    up under the doctype of whatever fired the trigger -- for a grid row add/remove
    that is the CHILD row's doctype (frappe/public/js/frappe/form/grid.js:1046,
    grid_row.js:111); for a field-change trigger on a child-table field it is the
    same child doctype (frappe/public/js/frappe/form/form.js:305-326, binding via
    `frappe.model.on(df.options, "*", ...)`).

    None of this is validated anywhere: registering handlers against a doctype that
    does not exist raises no error at load time and no error at runtime -- the
    handlers are simply dead. That is exactly what
    `direct_debit_batch.js` did, registering `invoices_add` / `invoices_remove` /
    `amount` under `'Direct Debit Invoice'`, a doctype that was never defined (the
    real child doctype is `Direct Debit Batch Invoice`). Nothing short of a static
    scan catches this class of bug -- there is no server round-trip, no console
    error, nothing a manual smoke test would surface unless someone specifically
    tries to add a row by hand and notices the mandate fields stay blank.

This test scans every `.js` file shipped by the verenigingen app (skipping calls
whose first argument is not a plain string literal, such as
`this.frm.doctype + " Item"`, which a static regex cannot evaluate, and stripping
comments first so a JSDoc `@example` block cannot be mistaken for real code) and
asserts every literal doctype name named this way actually has a DocType record.

Two pre-existing hits are allowlisted rather than fixed here -- see
KNOWN_DEAD_REGISTRATIONS below for why each is not this PR's problem to fix.
"""

import glob
import os
import re

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

FORM_ON_PATTERN = re.compile(r"""frappe\.ui\.form\.on\(\s*(['"])([^'"]+)\1""")
BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_PATTERN = re.compile(r"//[^\n]*")

# (doctype, path-relative-to-app) pairs the scan below already knows are dead, kept
# out of the hard assertion so this test gates NEW occurrences of the class without
# blocking on unrelated, already-tracked defects.
KNOWN_DEAD_REGISTRATIONS = {
    # Documented as an "in a JSON but not in tabDocType (unmigrated)" case in
    # scripts/validation/doctype_name_validator.py's own docstring (measured
    # 2026-08-31) -- a pre-existing, already-tracked condition, not a new finding.
    ("Bank Integration Settings", "utils/doctype/bank_integration_settings/bank_integration_settings.js"),
    # #1256: an empty `{}` handler block (nothing to be dead) registered against a
    # doctype that has never existed. Filed separately; zero behavioural impact.
    (
        "Expulsion Report Entry Item",
        "verenigingen/doctype/expulsion_report_entry/expulsion_report_entry.js",
    ),
}


def _app_path():
    return frappe.get_app_path("verenigingen")


def _strip_comments(content):
    content = BLOCK_COMMENT_PATTERN.sub("", content)
    return LINE_COMMENT_PATTERN.sub("", content)


def _iter_form_on_doctype_targets():
    app_path = _app_path()
    for path in glob.glob(os.path.join(app_path, "**", "*.js"), recursive=True):
        if f"{os.sep}node_modules{os.sep}" in path:
            continue
        with open(path, encoding="utf-8", errors="ignore") as fh:
            content = _strip_comments(fh.read())
        for match in FORM_ON_PATTERN.finditer(content):
            yield match.group(2), os.path.relpath(path, app_path)


class TestFormOnRegistrationTargetsExist(EnhancedTestCase):
    def test_scan_finds_a_realistic_number_of_registrations(self):
        """Control: if the glob or regex silently stopped matching anything (e.g. a
        path filter typo), the real assertion below would vacuously pass. Measured on
        develop: ~90 literal-doctype `frappe.ui.form.on(...)` calls app-wide."""
        targets = list(_iter_form_on_doctype_targets())
        self.assertGreater(len(targets), 50, "form.on scan found suspiciously few targets")

    def test_comment_examples_are_not_scanned(self):
        """Control for the comment-stripping above: iban-masking.js's JSDoc
        `@example` block illustrates `frappe.ui.form.on('Custom DocType', ...)` --
        real, executed code never names this doctype. If comment-stripping regresses,
        this specific literal reappears in the scan and this test catches it even
        though 'Custom DocType' would otherwise look like a plausible real doctype
        name rather than an obvious scan artifact."""
        targets = list(_iter_form_on_doctype_targets())
        self.assertNotIn(
            "Custom DocType", {doctype for doctype, _path in targets}, "a comment example leaked into the scan"
        )

    def test_every_registered_doctype_exists(self):
        targets = list(_iter_form_on_doctype_targets())
        missing = sorted(
            {(doctype, path) for doctype, path in targets if not frappe.db.exists("DocType", doctype)}
            - KNOWN_DEAD_REGISTRATIONS
        )
        self.assertEqual(
            missing,
            [],
            "frappe.ui.form.on(...) registered against a doctype with no DocType "
            f"record (dead handler -- see #1251): {missing}",
        )
