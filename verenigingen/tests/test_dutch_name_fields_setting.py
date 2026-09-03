"""#780 (remainder): whether name-particle fields are OFFERED is a declared setting.

Group A of #780 -- every site that writes a *stored* name -- was fixed in #786 by
reading the record: a populated `tussenvoegsel` IS the declaration. What remained
are the sites where no record exists yet, so per-record data cannot answer:

* the public application form and the desk Member form, which decide whether to
  render the tussenvoegsel input at all;
* `setup_dutch_name_fields()`, which provisions the Custom Field on User.

Those still routed through `is_dutch_installation()`, whose answer came from a
Redis-cached scan for any Company row with country "Netherlands" -- memoized for
an hour by whichever caller happened to run first, and cached as False for five
minutes after any exception. That made a site-wide display decision depend on
shard order, and it is why CI went red on a fresh site whose default company is
Indian while this bench stayed green on twelve leaked Dutch test companies.

It now reads `Verenigingen Settings.enable_dutch_name_fields`. These tests pin the
two properties that matter: the setting decides, and Company rows do not.

The name says "Dutch" for the *language*, not the country: tussenvoegsels are used
in Flanders too, which is why this is a declaration rather than `country == "NL"`.

Measured while writing this, on frappe 16.30.0: an unseeded Check on a Single
doctype reads as **0, not None** -- `cast_fieldtype("Check", None) -> 0` -- because
`tabSingles` carries no row until the document is saved. So the JSON `default` does
NOT reach an already-installed site, which makes the seeding patch load-bearing
rather than cosmetic. `test_an_unseeded_setting_reads_as_off` pins that
measurement so the patch cannot later be deleted as redundant.
"""

import unittest

import frappe

from verenigingen.utils.dutch_name_utils import is_dutch_installation

DOCTYPE = "Verenigingen Settings"
FIELD = "enable_dutch_name_fields"


def _read_raw():
    """The stored Singles value, bypassing every cast and cache."""
    rows = frappe.db.sql(
        "select value from tabSingles where doctype=%s and field=%s", (DOCTYPE, FIELD)
    )
    return rows[0][0] if rows else None


def _forget():
    """Drop the per-request value cache so the next read hits the database."""
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)


class TestDutchNameFieldsSetting(unittest.TestCase):
    def setUp(self):
        self._original = _read_raw()
        self.addCleanup(self._restore)

    def _restore(self):
        if self._original is None:
            frappe.db.sql(
                "delete from tabSingles where doctype=%s and field=%s", (DOCTYPE, FIELD)
            )
        else:
            frappe.db.set_single_value(DOCTYPE, FIELD, self._original)
        _forget()

    def _set(self, value):
        frappe.db.set_single_value(DOCTYPE, FIELD, value)
        _forget()

    def test_the_setting_decides(self):
        self._set(1)
        self.assertTrue(is_dutch_installation())
        self._set(0)
        self.assertFalse(is_dutch_installation())

    def test_company_countries_do_not_decide(self):
        """The #780 regression guard: a Netherlands Company must not flip the answer.

        Arrange the condition rather than detect it, so this runs the same path
        here and on a fresh CI site -- this bench has twelve leaked Dutch test
        companies and CI has none, which is the whole reason #780 was invisible
        locally.
        """
        company = frappe.defaults.get_defaults().get("company")
        if not company or not frappe.db.exists("Company", company):
            company = frappe.get_all("Company", limit=1, pluck="name")[0]
        original_country = frappe.db.get_value("Company", company, "country")
        self.addCleanup(frappe.db.set_value, "Company", company, "country", original_country)

        self._set(0)
        frappe.db.set_value("Company", company, "country", "Netherlands")
        self.assertFalse(
            is_dutch_installation(),
            f"{company} is a Netherlands company but the setting is off; the answer "
            "must come from the setting, not from a scan of Company rows.",
        )

    def test_an_unseeded_setting_reads_as_off(self):
        """Pins the measurement that makes the seeding patch load-bearing.

        An unseeded Check on a Single reads as 0, so the JSON default never
        reaches an existing install. If this ever starts returning True, the
        patch has become redundant and this test should be revisited -- until
        then, deleting the patch silently hides the field on every upgrade.
        """
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DOCTYPE, FIELD))
        _forget()
        self.assertIsNone(_read_raw())
        self.assertFalse(is_dutch_installation())


class TestSeedPatch(unittest.TestCase):
    """The patch preserves each install's current behaviour."""

    def test_a_netherlands_company_seeds_on(self):
        from verenigingen.patches.v2_2.seed_enable_dutch_name_fields import (
            _should_offer_dutch_name_fields,
        )

        self.assertTrue(_should_offer_dutch_name_fields(country="Belgium", company_countries=["Netherlands"]))
        self.assertTrue(_should_offer_dutch_name_fields(country="Netherlands", company_countries=["India"]))

    def test_an_install_with_no_dutch_trace_seeds_off(self):
        from verenigingen.patches.v2_2.seed_enable_dutch_name_fields import (
            _should_offer_dutch_name_fields,
        )

        self.assertFalse(_should_offer_dutch_name_fields(country="India", company_countries=["India", "Germany"]))
        self.assertFalse(_should_offer_dutch_name_fields(country=None, company_countries=[]))

    def test_execute_never_overrides_an_administrators_choice(self):
        """The idempotence guard, end to end rather than through the pure helper.

        Without this, someone "simplifying" _already_has_a_stored_value() into an
        unconditional write would turn the field back on for every install that had
        deliberately switched it off, and nothing in the suite would object. The
        guard cannot be expressed through _should_offer_dutch_name_fields, which by
        design does not know whether a value is already stored.
        """
        from verenigingen.patches.v2_2.seed_enable_dutch_name_fields import execute

        original = _read_raw()
        self.addCleanup(_forget)
        if original is None:
            self.addCleanup(
                frappe.db.sql,
                "delete from tabSingles where doctype=%s and field=%s",
                (DOCTYPE, FIELD),
            )
        else:
            self.addCleanup(frappe.db.set_single_value, DOCTYPE, FIELD, original)

        # An administrator has explicitly turned it off. This site carries Netherlands
        # companies, so the seeding predicate would answer True if it were consulted.
        frappe.db.set_single_value(DOCTYPE, FIELD, 0)
        _forget()
        execute()
        _forget()
        self.assertEqual(_read_raw(), "0")
        self.assertFalse(is_dutch_installation())

    def test_execute_seeds_an_unseeded_install(self):
        """The other half: with nothing stored, the patch writes a value."""
        from verenigingen.patches.v2_2.seed_enable_dutch_name_fields import execute

        original = _read_raw()
        self.addCleanup(_forget)
        if original is None:
            self.addCleanup(
                frappe.db.sql,
                "delete from tabSingles where doctype=%s and field=%s",
                (DOCTYPE, FIELD),
            )
        else:
            self.addCleanup(frappe.db.set_single_value, DOCTYPE, FIELD, original)

        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DOCTYPE, FIELD))
        _forget()
        execute()
        _forget()
        self.assertIsNotNone(_read_raw(), "the patch must store a value on an unseeded install")


if __name__ == "__main__":
    unittest.main()
