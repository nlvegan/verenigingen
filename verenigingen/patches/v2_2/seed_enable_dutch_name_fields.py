"""#780: seed `Verenigingen Settings.enable_dutch_name_fields` on existing installs.

This patch is load-bearing, not cosmetic. An unseeded Check on a Single doctype reads
as **0, not None** -- measured on frappe 16.30.0: `cast_fieldtype("Check", None) -> 0`,
because `tabSingles` carries no row until the document is saved. So the field's JSON
`default` never reaches an already-installed site, and without this seed every existing
install would silently stop offering the tussenvoegsel field the moment it upgraded.

The seed reproduces what the old heuristic answered, so no install changes behaviour,
with one deliberate widening: an install whose System Settings declares country
"Netherlands" is seeded on even when no Company row carries a country. That direction
only ever turns the field ON, and #780's asymmetry argument is that a visible empty
input is recoverable while a missing one silently loses a name particle at the only
moment it can be captured.

Belgium is NOT seeded on, even though Flemish members use tussenvoegsels, because the
old predicate did not offer the field there either and a patch should not change what
an install does. A Belgian association ticks the box once.
"""

import frappe

from verenigingen.utils.dutch_name_utils import DUTCH_NAME_FIELDS_FIELD, SETTINGS_DOCTYPE


def execute():
    frappe.reload_doc("verenigingen", "doctype", "verenigingen_settings")

    if _already_has_a_stored_value():
        return

    should_offer = _should_offer_dutch_name_fields(
        country=frappe.db.get_single_value("System Settings", "country"),
        company_countries=frappe.get_all("Company", pluck="country"),
    )
    frappe.db.set_single_value(SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD, int(should_offer))


def _already_has_a_stored_value():
    """Idempotence: never overwrite a choice an administrator has already made.

    Queried directly rather than through `get_single_value`, which casts a missing
    row to 0 and so cannot distinguish "unset" from "deliberately off".
    """
    return bool(
        frappe.db.sql(
            "select 1 from tabSingles where doctype=%s and field=%s limit 1",
            (SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD),
        )
    )


def _should_offer_dutch_name_fields(country, company_countries):
    """Reproduce the pre-#780 answer: a Netherlands trace anywhere in the install."""
    if country == "Netherlands":
        return True
    return any(c == "Netherlands" for c in company_countries or [])
