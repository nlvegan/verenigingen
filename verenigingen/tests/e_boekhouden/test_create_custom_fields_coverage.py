"""
Coverage sweep for create_eboekhouden_custom_fields.py

Target: verenigingen/e_boekhouden/utils/create_eboekhouden_custom_fields.py

LIVENESS: LIVE. ensure_eboekhouden_fields() / update_mutation_type_field_options()
are whitelisted @critical_api admin endpoints; create_eboekhouden_tracking_fields()
is the install-time custom-field bootstrap for the E-Boekhouden tracking fields used
throughout the migration (eboekhouden_mutation_nr, eboekhouden_invoice_number, ...).

Testable surface (REAL DB, idempotent install-time logic):
- create_eboekhouden_tracking_fields  -- creates/updates the tracking Custom Fields
- ensure_eboekhouden_fields           -- whitelisted wrapper around the above
- update_mutation_type_field_options  -- normalises the mutation-type Select options

IMPORTANT -- POLLUTION SAFETY: create_custom_fields() + frappe.db.commit() PERSIST
past the test rollback. On veg11 all ten E-Boekhouden tracking fields already exist
(verified before writing these tests), so these calls are no-op idempotent UPDATES
that create no new committed rows. The tests assert the post-condition (the field
still exists with the expected fieldtype/options) and idempotency (a second call is
clean), and do NOT create fields on doctypes that lack them. tearDown additionally
re-asserts no stray E-Boekhouden Custom Field appeared on an unexpected doctype.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_create_custom_fields_coverage
"""

import frappe

from verenigingen.e_boekhouden.utils.create_eboekhouden_custom_fields import (
    create_eboekhouden_tracking_fields,
    ensure_eboekhouden_fields,
    update_mutation_type_field_options,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# The (doctype, fieldname) pairs the bootstrap is responsible for. Every one of
# these is expected to pre-exist on veg11; the install call is an idempotent update.
_EXPECTED_FIELDS = [
    ("Sales Invoice", "eboekhouden_invoice_number"),
    ("Sales Invoice", "eboekhouden_mutation_nr"),
    ("Purchase Invoice", "eboekhouden_invoice_number"),
    ("Purchase Invoice", "eboekhouden_mutation_nr"),
    ("Customer", "eboekhouden_relation_code"),
    ("Supplier", "eboekhouden_relation_code"),
    ("Journal Entry", "eboekhouden_mutation_nr"),
    ("Journal Entry", "eboekhouden_mutation_type"),
    ("Payment Entry", "eboekhouden_mutation_nr"),
    ("Payment Entry", "eboekhouden_mutation_type"),
    ("Account", "eboekhouden_grootboek_nummer"),
]


class TestCreateEboekhoudenCustomFields(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Guard: these tests rely on the fields already being installed so the
        # install call is a no-op update. Snapshot the set of E-Boekhouden Custom
        # Fields so tearDown can detect any unexpected new committed row.
        cls._baseline_eboekhouden_cf = {
            (r.dt, r.fieldname)
            for r in frappe.get_all(
                "Custom Field",
                filters={"fieldname": ["like", "eboekhouden_%"]},
                fields=["dt", "fieldname"],
            )
        }

    def tearDown(self):
        # Detect pollution: any E-Boekhouden Custom Field not in the baseline was
        # created by a test and must be removed so veg11 is left untouched.
        current = {
            (r.dt, r.fieldname)
            for r in frappe.get_all(
                "Custom Field",
                filters={"fieldname": ["like", "eboekhouden_%"]},
                fields=["dt", "fieldname"],
            )
        }
        stray = current - self._baseline_eboekhouden_cf
        for dt, fieldname in stray:
            name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
            if name:
                frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
        if stray:
            frappe.db.commit()
        super().tearDown()
        self.assertFalse(stray, f"create_custom_fields leaked stray Custom Fields: {stray}")

    def test_create_tracking_fields_returns_success(self):
        result = create_eboekhouden_tracking_fields()
        self.assertTrue(result["success"], result)
        self.assertIn("message", result)

    def test_all_expected_fields_present_after_call(self):
        create_eboekhouden_tracking_fields()
        for dt, fieldname in _EXPECTED_FIELDS:
            with self.subTest(dt=dt, fieldname=fieldname):
                self.assertTrue(
                    frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}),
                    f"expected Custom Field {dt}.{fieldname}",
                )

    def test_field_definitions_match_spec(self):
        create_eboekhouden_tracking_fields()
        # Spot-check the key field attributes the migration relies on.
        si_inv = frappe.get_doc(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "eboekhouden_invoice_number"}
        )
        self.assertEqual(si_inv.fieldtype, "Data")
        self.assertEqual(si_inv.unique, 1)
        je_type = frappe.get_doc(
            "Custom Field", {"dt": "Journal Entry", "fieldname": "eboekhouden_mutation_type"}
        )
        self.assertEqual(je_type.fieldtype, "Select")

    def test_create_tracking_fields_is_idempotent(self):
        first = create_eboekhouden_tracking_fields()
        second = create_eboekhouden_tracking_fields()
        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        # No duplicate Custom Field rows (Custom Field name is unique per dt+fieldname,
        # but assert the count for one representative field stays at exactly one).
        rows = frappe.get_all(
            "Custom Field",
            filters={"dt": "Account", "fieldname": "eboekhouden_grootboek_nummer"},
        )
        self.assertEqual(len(rows), 1)

    def test_ensure_eboekhouden_fields_delegates(self):
        result = ensure_eboekhouden_fields()
        self.assertTrue(result["success"], result)

    def test_update_mutation_type_field_options_normalises_select(self):
        result = update_mutation_type_field_options()
        self.assertTrue(result["success"], result)
        self.assertIn("updates", result)
        # The two mutation-type Selects must carry the full 0..7 option set with a
        # leading blank option.
        for dt in ("Payment Entry", "Journal Entry"):
            with self.subTest(dt=dt):
                options = frappe.db.get_value(
                    "Custom Field", {"dt": dt, "fieldname": "eboekhouden_mutation_type"}, "options"
                )
                self.assertEqual(options, "\n0\n1\n2\n3\n4\n5\n6\n7")
