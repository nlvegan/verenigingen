# Integration tests for verenigingen/setup/add_settings_fields.py
#
# add_missing_email_settings_fields() is a whitelisted @critical_api repair
# endpoint (it has its own Critical Operation Rule fixture) that back-fills two
# email toggles onto Verenigingen Settings as Custom Fields.
#
# It had ZERO test coverage. These tests pin its two real behaviours:
#   1. On the current schema it is a NO-OP, because `enable_email_group_sync`
#      and `enable_email_analytics` were promoted into the Verenigingen Settings
#      DocType JSON. A fresh site therefore already has them and this endpoint
#      adds nothing -- it is effectively dead code kept as a repair hatch.
#   2. Its create branch cannot succeed while a native DocField of the same name
#      exists (Custom Field conflict validation), and the failure is swallowed
#      into a print rather than surfaced to the caller.
#
# The tests never leave a Custom Field behind: the one test that forces the
# create branch registers an unconditional cleanup and asserts the field is gone.

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup.add_settings_fields import add_missing_email_settings_fields

SETTINGS_DOCTYPE = "Verenigingen Settings"
TARGET_FIELDS = ["enable_email_group_sync", "enable_email_analytics"]
INSERT_AFTER = "monitoring_section"


def _custom_field_names():
    return frappe.get_all(
        "Custom Field",
        filters={"dt": SETTINGS_DOCTYPE, "fieldname": ["in", TARGET_FIELDS]},
        pluck="name",
    )


class TestAddMissingEmailSettingsFields(FrappeTestCase):
    def test_target_fields_are_native_docfields_not_custom_fields(self):
        """Both toggles now live in the Verenigingen Settings DocType JSON.

        That is what makes this endpoint a no-op, and it is also the property a
        fresh install depends on: the fields must exist without any patch or
        repair endpoint having run.
        """
        meta = frappe.get_meta(SETTINGS_DOCTYPE)
        for fieldname in TARGET_FIELDS:
            df = meta.get_field(fieldname)
            self.assertIsNotNone(df, f"{fieldname} must exist on {SETTINGS_DOCTYPE}")
            self.assertEqual(df.fieldtype, "Check")
        self.assertEqual(
            _custom_field_names(),
            [],
            "These toggles must be native DocFields, not Custom Fields",
        )

    def test_insert_after_anchor_exists(self):
        """The endpoint anchors both fields to `monitoring_section`.

        If that anchor ever disappears, a successfully created field would be
        appended at an arbitrary position in the form.
        """
        self.assertIsNotNone(
            frappe.get_meta(SETTINGS_DOCTYPE).get_field(INSERT_AFTER),
            f"insert_after anchor '{INSERT_AFTER}' no longer exists on {SETTINGS_DOCTYPE}",
        )

    def test_is_a_noop_on_the_current_schema(self):
        """Both fields already exist -> the skip branch runs for both, nothing is
        created, and the endpoint still reports success."""
        result = add_missing_email_settings_fields()

        self.assertTrue(result["success"])
        self.assertEqual(result["added_fields"], [])
        self.assertEqual(result["message"], "Added 0 new fields to Verenigingen Settings")
        self.assertEqual(_custom_field_names(), [])

    def test_repeated_calls_do_not_accumulate_custom_fields(self):
        add_missing_email_settings_fields()
        second = add_missing_email_settings_fields()

        self.assertEqual(second["added_fields"], [])
        self.assertEqual(_custom_field_names(), [])

    def test_create_branch_is_blocked_by_the_native_docfield(self):
        """Force the create branch and assert it cannot actually add the fields.

        The endpoint decides what to add from `frappe.get_meta(...).fields`. With
        the two toggles hidden from that meta it walks the insert path -- and
        Frappe's Custom Field conflict validation rejects each one because a
        DocField of the same fieldname already exists. The exception is caught
        and printed, so the caller still gets success=True with an empty
        added_fields list: the endpoint cannot report its own failure.
        """
        real_get_meta = frappe.get_meta

        def meta_without_email_toggles(doctype, *args, **kwargs):
            meta = real_get_meta(doctype, *args, **kwargs)
            if doctype != SETTINGS_DOCTYPE:
                return meta
            # A shallow proxy: only `fields` is narrowed, everything else is the
            # real meta object, so Custom Field validation runs for real.
            class _NarrowedMeta:
                def __init__(self, inner):
                    self._inner = inner
                    self.fields = [f for f in inner.fields if f.fieldname not in TARGET_FIELDS]

                def __getattr__(self, item):
                    return getattr(self._inner, item)

            return _NarrowedMeta(meta)

        def _cleanup():
            for name in _custom_field_names():
                frappe.delete_doc("Custom Field", name, force=1)
            frappe.db.commit()
            frappe.clear_cache(doctype=SETTINGS_DOCTYPE)

        self.addCleanup(_cleanup)

        original = frappe.get_meta
        frappe.get_meta = meta_without_email_toggles
        try:
            result = add_missing_email_settings_fields()
        finally:
            frappe.get_meta = original

        self.assertTrue(result["success"], "The endpoint reports success regardless")
        self.assertEqual(
            result["added_fields"],
            [],
            "A conflicting Custom Field must not be created for an existing DocField",
        )
        self.assertEqual(
            _custom_field_names(),
            [],
            "No Custom Field may shadow the native Verenigingen Settings toggles",
        )
