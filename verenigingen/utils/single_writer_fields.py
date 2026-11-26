"""Keep background-written fields of a Single from being rolled back by a stale save (#2739).

Some Singles carry status fields that a background job writes with
``db_set`` / ``set_single_value`` / ``set_value`` and ``update_modified=False``. ``modified``
does not move, so Frappe's stale-save check cannot refuse a form loaded before the write, and a
Single save rewrites every ``tabSingles`` row from the in-memory doc. Calling this from the
Single's ``validate`` re-reads the stored values, so only the fields staff edit come from the doc.
"""

# A save that IS the writer (it sets one of the owned fields on purpose) sets this flag.
WRITER_SAVE_FLAG = "writer_owned_fields_save"


def keep_stored_single_fields(doc, fields, coerce=None):
    """Overwrite ``fields`` on a Single's in-memory ``doc`` with the stored values.

    ``coerce`` maps a field to a callable applied to the stored string (``tabSingles`` holds
    text, so an Int field such as a counter needs ``cint``). A field with no stored row keeps
    the doc's own value: a first programmatic write has no row yet and must not be discarded.
    """
    import frappe

    if doc.flags.get(WRITER_SAVE_FLAG):
        return
    coerce = coerce or {}
    rows = frappe.db.sql(
        "SELECT field, value FROM `tabSingles` WHERE doctype = %s AND field IN %s",
        (doc.doctype, tuple(fields)),
    )
    for field, value in rows:
        doc.set(field, coerce[field](value) if field in coerce else value)


def stored_child_rows(doc, table_field, fields):
    """Stored values of ``fields`` for each saved row of ``doc``'s ``table_field``, by row name (#2792).

    A background job that writes child rows with ``update_modified=False`` or a raw UPDATE leaves the
    parent's ``modified`` alone, so a stale form passes the timestamp check and its save rewrites
    every row from the in-memory values. A row with no stored copy (a new row) is simply absent.
    """
    import frappe

    child_doctype = doc.meta.get_field(table_field).options
    rows = frappe.get_all(
        child_doctype,
        filters={"parent": doc.name, "parenttype": doc.doctype, "parentfield": table_field},
        fields=["name", *fields],
    )
    return {row.pop("name"): row for row in rows}
