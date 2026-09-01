"""Workaround for #609: a whole-second `creation`/`modified` timestamp makes a
document unable to save or submit itself.

The defect (framework-level, not ours -- see #609 for the full derivation):

`frappe.utils.now()` always returns a string with six fractional digits
(``'2026-08-25 14:03:48.000000'``). `set_user_and_timestamp`
(``frappe/model/document.py``) assigns that string straight to `modified` and
`creation` in memory. When the SAME whole second later round-trips through the
database, MariaDB hands back a `datetime` object whose `str()` DROPS the
trailing `.000000` (``'2026-08-25 14:03:48'``) -- same instant, different
string. Two framework comparisons stringify both sides and therefore disagree
with themselves purely because of this in-memory/on-disk formatting mismatch:

- `check_if_latest` (`frappe/model/document.py:1106`):
  ``cstr(previous.modified) != cstr(self._original_modified)`` ->
  `TimestampMismatchError`
- `validate_set_only_once` (`frappe/model/document.py:912`):
  ``str(value) != str(original_value)`` for Datetime fields -> `creation` is a
  hard-coded `standard_set_once_fields` entry (`frappe/model/meta.py:144-147`),
  so this hits every DocType -> `CannotChangeConstantError`

Both fire only when a document is inserted and then saved/submitted from the
SAME in-memory object with no intervening `reload()`. Production hits this at
roughly 1-in-10^6 per document (measured on CI, see #609); a whole-second
`freeze_time()` in a test hits it 100% of the time.

The fix here does NOT touch the framework (forbidden by CLAUDE.md) and does
NOT re-read the database. It only needs to make the IN-MEMORY string match
what a DB round-trip of the same instant would already produce -- a
`datetime(6)` column stores '...48.000000' and '...48' identically, so
trimming the suffix here changes no persisted data, only the Python-side
string Frappe compares against itself later.
"""

import frappe

ZERO_MICROSECONDS_SUFFIX = ".000000"

#: Fields `set_user_and_timestamp` stamps with `now()` and that the two
#: framework comparisons above later stringify.
TIMESTAMP_FIELDS = ("modified", "creation")


def strip_whole_second_suffix(doc, fieldnames=TIMESTAMP_FIELDS):
    """Trim a trailing '.000000' from in-memory datetime-as-string fields.

    Returns the list of fieldnames actually changed. Callers use a non-empty
    return to make the workaround observable/assertable instead of a silent
    no-op -- this fires on essentially 0% of real documents, so a caller that
    wants proof it works needs a way to see it fire.
    """
    touched = []
    for fieldname in fieldnames:
        value = doc.get(fieldname)
        if isinstance(value, str) and value.endswith(ZERO_MICROSECONDS_SUFFIX):
            doc.set(fieldname, value[: -len(ZERO_MICROSECONDS_SUFFIX)])
            touched.append(fieldname)
    return touched


def normalize_whole_second_timestamps(doc, method=None):
    """`doc_events["*"]["after_insert"]` handler. See module docstring / #609.

    Registered on the wildcard doctype so every insert in every one of the 21
    production `insert()` -> `save()`/`submit()` sites is covered from one
    place, per #609's scope decision, rather than patching each call site.
    """
    touched = strip_whole_second_suffix(doc)
    if touched:
        # 1-in-10^6 per document in production (#609) -- a log line here costs
        # nothing and gives an operator something to grep for if it ever fires
        # somewhere the five money-moving sites' belt-and-braces reload() (see
        # those call sites) doesn't also cover.
        frappe.logger("timestamp_normalization").info(
            f"[#609] normalized whole-second timestamp on {doc.doctype} {doc.name}: {touched}"
        )
