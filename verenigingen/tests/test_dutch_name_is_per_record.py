"""#780: a member's tussenvoegsel is used because THEY have one, not because the site looks Dutch.

`update_member_full_name` used to read `is_dutch_installation() and <doc>.tussenvoegsel`.
The first clause was answered by a Redis-cached scan for any Company row with
country "Netherlands" -- memoized for an hour by whichever caller ran first, and
cached as False for five minutes after any exception.

Two consequences:

* CI went red on `test_complete_member_application_to_active_workflow` because a
  fresh site's default company is Indian (ERPNext's `before_tests` runs
  `setup_complete(country="India")`), so whether the particle survived depended on
  whether another test in the same shard had already created a Dutch company.
* In production, a member with "van" in their name joining an association not
  detected as Dutch had it silently stripped from `full_name` -- an immigrant with
  a Dutch name, or a Dutch association whose Company row has no country set.

The record already answers the question, so these tests pin that the output no
longer varies with the site-wide flag.

The flag itself moved in the #780 follow-up: it is now the declared setting
`Verenigingen Settings.enable_dutch_name_fields`, which governs whether forms
OFFER the field, and the Redis-cached Company scan is gone. These tests toggle
the setting rather than the retired cache key -- pinning the dead key would have
left them unable to fail, because re-introducing the flag into
`update_member_full_name` would read the setting and the key would be ignored.
"""

import unittest

import frappe

from verenigingen.utils.dutch_name_service import update_member_full_name
from verenigingen.utils.dutch_name_utils import DUTCH_NAME_FIELDS_FIELD, SETTINGS_DOCTYPE


def _member(first, tussenvoegsel, last, middle=None):
    doc = frappe.new_doc("Member")
    doc.first_name = first
    doc.tussenvoegsel = tussenvoegsel
    doc.last_name = last
    if middle:
        doc.middle_name = middle
    return doc


class TestDutchNameIsPerRecord(unittest.TestCase):
    def setUp(self):
        rows = frappe.db.sql(
            "select value from tabSingles where doctype=%s and field=%s",
            (SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD),
        )
        self._original = rows[0][0] if rows else None

    def tearDown(self):
        if self._original is None:
            frappe.db.sql(
                "delete from tabSingles where doctype=%s and field=%s",
                (SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD),
            )
        else:
            frappe.db.set_single_value(SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD, self._original)
        frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)

    def _full_name_with_flag(self, flag_value, doc):
        frappe.db.set_single_value(SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD, int(flag_value))
        frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)
        update_member_full_name(doc)
        return doc.full_name

    def test_the_particle_survives_when_the_site_does_not_look_dutch(self):
        """The measured #780 failure: on develop this returned 'Jan Test'."""
        name = self._full_name_with_flag(False, _member("Jan", "van", "Test"))
        self.assertEqual(name, "Jan van Test")

    def test_the_result_does_not_depend_on_the_site_wide_flag(self):
        """Control: both flag values agree, so the flag is genuinely out of the path."""
        as_dutch = self._full_name_with_flag(True, _member("Jan", "van", "Test"))
        as_foreign = self._full_name_with_flag(False, _member("Jan", "van", "Test"))
        self.assertEqual(as_dutch, as_foreign)
        self.assertEqual(as_dutch, "Jan van Test")

    def test_a_member_without_a_tussenvoegsel_is_unaffected(self):
        """The clause was already false for them; nothing about their name changes."""
        self.assertEqual(self._full_name_with_flag(False, _member("Alice", None, "Smith")), "Alice Smith")
        self.assertEqual(self._full_name_with_flag(True, _member("Alice", None, "Smith")), "Alice Smith")

    def test_an_empty_tussenvoegsel_still_falls_through_to_middle_name(self):
        """Truthiness, not hasattr: the legacy middle_name path must stay reachable.

        Every Member HAS the field, so gating on `hasattr` took the tussenvoegsel
        branch even when it was blank and skipped the particle parsing below it.
        """
        doc = _member("Piet", "", "Jansen", middle="de")
        self.assertEqual(self._full_name_with_flag(True, doc), "Piet de Jansen")


if __name__ == "__main__":
    unittest.main()
