"""
Helpers for writing caller-supplied strings into Select fields.

A Select only accepts values from its own options list, and `_validate_selects()`
rejects anything else on save. Several code paths take a string from an API caller,
an imported record or a Python function name and assign it straight to a Select,
where the resulting ValidationError is then swallowed by a broad `except` — so the
row is silently dropped and the caller still sees success. Use `coerce_select_option`
at those boundaries so the value is clamped to something the field can hold.
"""

import frappe


def get_select_options(doctype: str, fieldname: str) -> list:
    """Return the declared options of a Select field, in declaration order."""
    field = frappe.get_meta(doctype).get_field(fieldname)
    return [option.strip() for option in (field.options or "").split("\n") if option.strip()]


def coerce_select_option(doctype: str, fieldname: str, value, fallback: str) -> str:
    """
    Return `value` if the Select accepts it, otherwise `fallback`.

    `fallback` must itself be a declared option — passing one that is not simply
    moves the rejection, so it is checked rather than trusted.
    """
    options = get_select_options(doctype, fieldname)
    if fallback not in options:
        raise ValueError(f"{doctype}.{fieldname} has no option {fallback!r} to fall back to")
    return value if value in options else fallback
