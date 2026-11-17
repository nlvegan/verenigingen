"""Keep background-written fields of a Single from being rolled back by a stale save (#2739).

Some Singles carry status fields that a background job writes with
``db_set`` / ``set_single_value`` / ``set_value`` and ``update_modified=False``. ``modified``
does not move, so Frappe's stale-save check cannot refuse a form loaded before the write, and a
Single save rewrites every ``tabSingles`` row from the in-memory doc. Calling this from the
Single's ``validate`` re-reads the stored values, so only the fields staff edit come from the doc.
"""

# A save that IS the writer (it sets one of the owned fields on purpose) sets this flag.
WRITER_SAVE_FLAG = "writer_owned_fields_save"


def keep_stored_single_fields(doc, fields):
    """Overwrite ``fields`` on a Single's in-memory ``doc`` with the stored values."""
    import frappe

    if doc.flags.get(WRITER_SAVE_FLAG):
        return
    rows = frappe.db.sql(
        "SELECT field, value FROM `tabSingles` WHERE doctype = %s AND field IN %s",
        (doc.doctype, tuple(fields)),
    )
    stored = dict(rows)
    for field in fields:
        # A field with no stored row is None, as a fresh Single reads it.
        doc.set(field, stored.get(field))
