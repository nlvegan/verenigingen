# verenigingen/tests/test_fixture_export.py
"""Regression tests for verenigingen/hooks/fixtures.py export behaviour.

Context (#196): frappe/utils/fixtures.py derives the export filename for a
fixture entry as frappe.scrub(<doctype>) unless the entry gives an explicit
"prefix". Two or more entries for the same doctype that omit "prefix" all
write to the same file, and only the last one written survives. Before the
fix, three separate "Custom Field" entries in hooks/fixtures.py (btw_*,
custom_eboekhouden_grootboek_nummer, and the Mollie fields) all lacked a
prefix and therefore all wrote to fixtures/custom_field.json -- an export
kept only whichever entry happened to run last.

These tests exercise the real fixture list (via frappe.get_hooks, the same
call export_fixtures itself makes) and the real frappe export code, writing
to a scratch directory (never the live fixtures/ directory) so a test run
can never touch or corrupt committed fixture files.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import frappe
from frappe.utils.fixtures import export_fixtures


def _export_destinations(fixture_declarations):
    """Reproduce frappe.utils.fixtures.export_fixtures' filename derivation.

    frappe's own loop sets `prefix = None` ONCE, before the loop, and only
    reassigns it inside `if isinstance(fixture, dict): prefix = fixture.get(
    "prefix")`. A bare-string entry does NOT reset it, so it silently
    inherits whatever prefix the previous dict entry set. Modelling that
    quirk here (rather than assuming every entry resets to None) means a
    fixture list that relies on -- or is accidentally broken by -- that
    leak is caught, instead of the test computing a destination frappe
    would never actually produce.
    """
    destinations = {}
    prefix = None
    for index, entry in enumerate(fixture_declarations):
        if isinstance(entry, dict):
            doctype = entry.get("doctype") or entry.get("dt")
            prefix = entry.get("prefix")
        else:
            doctype = entry
            # prefix is NOT reset here -- matches frappe's own behaviour.

        filename = frappe.scrub(doctype)
        if prefix:
            filename = f"{prefix}_{filename}"
        destinations.setdefault(filename, []).append((index, doctype))
    return destinations


class TestFixtureDeclarationsDoNotCollide(unittest.TestCase):
    """Static check: no two declared fixture entries can clobber each other.

    This is the general form of the #196 bug -- any two entries that resolve
    to the same output filename (accounting for frappe's prefix-carries-
    across-bare-strings quirk) will silently clobber one another on export.
    This test enumerates every declared entry, not just "Custom Field", so a
    new colliding pair anywhere in the list -- including a FOURTH unprefixed
    "Custom Field" entry re-targeting fixtures/custom_field.json -- fails the
    suite immediately instead of waiting to be discovered via a corrupted
    export.
    """

    def test_no_two_fixture_entries_share_an_export_filename(self):
        fixture_declarations = frappe.get_hooks("fixtures", app_name="verenigingen")
        destinations = _export_destinations(fixture_declarations)

        colliding = {filename: entries for filename, entries in destinations.items() if len(entries) > 1}
        self.assertFalse(
            colliding,
            "These fixture entries export to the same filename and will silently "
            f"clobber one another on `bench export-fixtures`: {colliding}. "
            "Give the later entries a distinct 'prefix'.",
        )

    def test_no_declared_entry_targets_the_bare_custom_field_file(self):
        """fixtures/custom_field.json holds 64 undeclared rows (#196) that no
        entry in hooks.py covers. A regenerated custom_field.json would
        destroy them, so no entry may (re-)target that exact filename.
        """
        fixture_declarations = frappe.get_hooks("fixtures", app_name="verenigingen")
        destinations = _export_destinations(fixture_declarations)

        self.assertNotIn(
            "custom_field",
            destinations,
            "A fixture entry targets the bare, unprefixed custom_field.json. That "
            "file holds Custom Field rows (Sales Invoice.member, Customer.member, "
            "every Ponto field, etc.) that no entry in hooks/fixtures.py declares, "
            "and a real export would overwrite it -- give this entry a 'prefix'.",
        )


class TestExportFixturesDoesNotClobberCustomFields(unittest.TestCase):
    """Live check: exporting via the real frappe code preserves every group.

    Runs frappe.utils.fixtures.export_fixtures against test_site_1's real
    Custom Field records, redirected to a scratch directory so the
    committed verenigingen/fixtures/*.json files are never touched.
    """

    EXPECTED_CUSTOM_FIELD_FILES = {
        "btw_custom_field.json",
        "eboekhouden_grootboek_custom_field.json",
        "mollie_custom_field.json",
    }

    def setUp(self):
        self.scratch_dir = tempfile.mkdtemp(prefix="verenigingen_fixture_export_test_")
        self.fixtures_dir = os.path.join(self.scratch_dir, "fixtures")
        os.makedirs(self.fixtures_dir)
        self._real_get_app_path = frappe.get_app_path

    def tearDown(self):
        shutil.rmtree(self.scratch_dir, ignore_errors=True)

    def _redirect_get_app_path(self, app_name, *joins):
        if app_name != "verenigingen" or not joins or joins[0] != "fixtures":
            return self._real_get_app_path(app_name, *joins)
        if any("fixtures" in str(part) for part in joins[1:]):
            # Unrecognised shape -- fail closed rather than silently falling
            # through to the real (live) app path. This app has a recorded
            # incident of a test run rewriting fixtures inside the live tree.
            raise AssertionError(
                f"Unrecognised get_app_path({app_name!r}, {joins!r}) call -- refusing to "
                f"guess whether this is safe to redirect. Update the redirect logic."
            )
        return os.path.join(self.scratch_dir, *joins)

    def _run_export(self):
        with patch("frappe.utils.fixtures.frappe.get_app_path", side_effect=self._redirect_get_app_path):
            export_fixtures(app="verenigingen")

    def _load_exported_fieldnames(self, filename):
        path = os.path.join(self.fixtures_dir, filename)
        if not os.path.exists(path):
            return set()
        with open(path) as f:
            return {row["fieldname"] for row in json.load(f)}

    def test_btw_and_mollie_custom_fields_both_survive_one_export(self):
        # Precondition: both groups actually have live Custom Field data on
        # this site, otherwise the assertions below would pass vacuously.
        btw_count = frappe.db.count("Custom Field", {"fieldname": ["like", "btw_%"]})
        mollie_count = frappe.db.count(
            "Custom Field",
            {
                "fieldname": [
                    "in",
                    [
                        "custom_mollie_idempotency_key",
                        "custom_mollie_payment_id",
                        "custom_mollie_settlement_id",
                        "custom_processing_status",
                    ],
                ]
            },
        )
        self.assertGreater(btw_count, 0, "Expected btw_* Custom Field fixtures on this site")
        self.assertGreater(mollie_count, 0, "Expected Mollie Custom Field fixtures on this site")

        self._run_export()

        exported_filenames = set(os.listdir(self.fixtures_dir))

        # Pin the exact set of files the three Custom Field groups export
        # to. The pre-#196 bug wrote all three to "custom_field.json", so a
        # loose "at least 2 distinct names" check would miss a fix that only
        # partially separates them, and would also miss "custom_field.json"
        # itself reappearing as one of the destinations.
        custom_field_files = exported_filenames & (
            self.EXPECTED_CUSTOM_FIELD_FILES | {"custom_field.json"}
        )
        self.assertEqual(
            custom_field_files,
            self.EXPECTED_CUSTOM_FIELD_FILES,
            "Expected exactly the three prefixed Custom Field fixture files, found "
            f"{custom_field_files}. This is the #196 collision: unprefixed (or "
            "wrongly-prefixed) entries for the same doctype overwrite each other.",
        )

        all_fieldnames_by_file = {
            fname: self._load_exported_fieldnames(fname) for fname in self.EXPECTED_CUSTOM_FIELD_FILES
        }
        all_exported_fieldnames = set().union(*all_fieldnames_by_file.values())

        btw_fieldnames = {
            row.fieldname
            for row in frappe.get_all(
                "Custom Field", filters={"fieldname": ["like", "btw_%"]}, fields=["fieldname"]
            )
        }
        mollie_fieldnames = {
            row.fieldname
            for row in frappe.get_all(
                "Custom Field",
                filters={
                    "fieldname": [
                        "in",
                        [
                            "custom_mollie_idempotency_key",
                            "custom_mollie_payment_id",
                            "custom_mollie_settlement_id",
                            "custom_processing_status",
                        ],
                    ]
                },
                fields=["fieldname"],
            )
        }

        missing_btw = btw_fieldnames - all_exported_fieldnames
        missing_mollie = mollie_fieldnames - all_exported_fieldnames
        self.assertFalse(missing_btw, f"btw_* Custom Fields dropped by export (clobbered): {missing_btw}")
        self.assertFalse(
            missing_mollie, f"Mollie Custom Fields dropped by export (clobbered): {missing_mollie}"
        )

        # Each group's own file (not just "the union of all files") must
        # carry that group's fields -- this is what actually distinguishes
        # "both groups landed in the same clobbered file" (pre-#196 bug,
        # would still pass the union checks above) from "each group has
        # its own intact file" (the fix).
        btw_files_with_data = {
            fname for fname, names in all_fieldnames_by_file.items() if names & btw_fieldnames
        }
        mollie_files_with_data = {
            fname for fname, names in all_fieldnames_by_file.items() if names & mollie_fieldnames
        }
        self.assertTrue(btw_files_with_data, "No exported file contained any btw_* fields")
        self.assertTrue(mollie_files_with_data, "No exported file contained any Mollie fields")
        self.assertFalse(
            btw_files_with_data & mollie_files_with_data,
            f"btw_* and Mollie Custom Fields landed in the SAME file "
            f"({btw_files_with_data & mollie_files_with_data}) -- they should export "
            f"to distinct, non-colliding files.",
        )


if __name__ == "__main__":
    unittest.main()
