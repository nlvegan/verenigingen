"""#631: the migration forces sepa_strict_mandate_validation on, even for a
site that already carries an EXPLICIT stored value for the field.

This is deliberately NOT the "seed only if unset" idiom used elsewhere
(`seed_enable_dutch_name_fields.py`): `update_single()` rewrites every field of
a Single doctype on any full-document save, so an install whose Settings page
has ever been saved even once already has an explicit `0` row here --
indistinguishable from a deliberate opt-out. A seed-if-unset patch would be a
no-op for exactly the installs #631 is about. See the patch module's own
docstring for the full reasoning.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.force_enable_sepa_strict_mandate_validation import execute

SETTINGS_DOCTYPE = "Verenigingen Settings"
FIELD = "sepa_strict_mandate_validation"


class TestForceEnableSepaStrictMandateValidation(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self._original = frappe.db.sql(
            "select value from `tabSingles` where doctype=%s and field=%s", (SETTINGS_DOCTYPE, FIELD)
        )

    def tearDown(self):
        frappe.db.delete("Singles", {"doctype": SETTINGS_DOCTYPE, "field": FIELD})
        if self._original:
            frappe.db.sql(
                "insert into `tabSingles` (doctype, field, value) values (%s, %s, %s)",
                (SETTINGS_DOCTYPE, FIELD, self._original[0][0]),
            )
        super().tearDown()

    def test_forces_on_when_explicitly_stored_as_off(self):
        """An install whose Settings form was saved while the field still held
        its old default (0) must end up strict after this patch runs."""
        frappe.db.set_single_value(SETTINGS_DOCTYPE, FIELD, 0)
        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, FIELD), 0)

        execute()

        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, FIELD), 1)

    def test_forces_on_when_never_configured(self):
        """A genuinely brand-new install (no tabSingles row at all) must also
        come out strict."""
        frappe.db.delete("Singles", {"doctype": SETTINGS_DOCTYPE, "field": FIELD})
        self.assertFalse(
            frappe.db.sql(
                "select 1 from `tabSingles` where doctype=%s and field=%s", (SETTINGS_DOCTYPE, FIELD)
            )
        )

        execute()

        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, FIELD), 1)
