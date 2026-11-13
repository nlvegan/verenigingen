"""#1355: a unique Custom Field must not also carry search_index.

Frappe creates one index per flag, so a column with both gets the UNIQUE index plus a redundant
non-unique `<field>_index`. A unique index already serves equality lookups; the second is pure write and
storage cost. The fixture is the only source on a fresh (CI) site, so the fixture test is the one that
guards new installs; the database tests guard the schema a site actually ends up with.

Probe shortcut: the duplicate-insert control writes minimal raw rows (names + the key column) because the
unique index is a database property and building a full Bank Transaction / Payment Entry / Customer
would add nothing; the rows are rolled back by the test harness.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

FIXTURE = "fixtures/custom_field.json"
# Written out so a scan that finds nothing cannot pass vacuously.
KNOWN_UNIQUE = {
    ("Bank Transaction", "custom_reference_number_key"),
    ("Payment Entry", "custom_mollie_idempotency_key"),
    ("Customer", "member"),
}


def _1355_unique_fixture_fields():
    with open(frappe.get_app_path("verenigingen", FIXTURE)) as f:
        return [r for r in json.load(f) if r.get("unique")]


def _1355_indexes_on(doctype, column):
    """{key_name: is_unique} for every index that covers `column` (any position)."""
    rows = frappe.db.sql(
        f"SHOW INDEX FROM `tab{doctype}` WHERE Column_name = %s", (column,), as_dict=True
    )
    return {r["Key_name"]: not r["Non_unique"] for r in rows}


class TestUniqueCustomFieldSingleIndex1355(FrappeTestCase):
    def test_fixture_unique_fields_do_not_also_set_search_index(self):
        rows = _1355_unique_fixture_fields()
        self.assertTrue(
            KNOWN_UNIQUE <= {(r["dt"], r["fieldname"]) for r in rows},
            "control: the scan must see the known unique Custom Fields",
        )
        both = [r["name"] for r in rows if r.get("search_index")]
        self.assertEqual(both, [], "unique Custom Fields must not also set search_index (double index)")

    def test_each_unique_column_has_exactly_one_index_and_it_is_unique(self):
        for doctype, column in sorted(KNOWN_UNIQUE):
            with self.subTest(doctype=doctype, column=column):
                self.assertEqual(_1355_indexes_on(doctype, column), {column: True})

    def test_index_probe_sees_a_plain_search_index(self):
        # Control for the probe: a search_index-only field must show its one NON-unique `_index` key.
        # Membership.procurios_membership_id is created by setup/__init__.py (after_install) with
        # search_index 1. If that field changes, move this control to another plain-search_index field.
        self.assertEqual(
            _1355_indexes_on("Membership", "procurios_membership_id"),
            {"procurios_membership_id_index": False},
        )

    def test_uniqueness_is_still_enforced(self):
        for doctype, column in sorted(KNOWN_UNIQUE):
            with self.subTest(doctype=doctype, column=column):
                value = f"t1355-{frappe.generate_hash(length=8)}"
                sql = f"INSERT INTO `tab{doctype}` (name, `{column}`) VALUES (%s, %s)"
                frappe.db.sql(sql, (f"{value}-a", value))
                with self.assertRaises(Exception) as raised:
                    frappe.db.sql(sql, (f"{value}-b", value))
                self.assertTrue(frappe.db.is_duplicate_entry(raised.exception))
