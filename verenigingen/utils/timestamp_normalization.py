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

Both fire only when a whole-second `now()` lands on a `set_user_and_timestamp()`
call (insert OR any later save/submit) and the SAME in-memory object is then
saved/submitted again with no intervening `reload()`. Production hits this at
roughly 1-in-10^6 per write (measured on CI, see #609); a whole-second
`freeze_time()` in a test hits it 100% of the time.

**Not limited to insert.** #609's own production sites are all `insert()` ->
`submit()` pairs, but the defect itself is about ANY write, not only the
first one on a document. A live CI recurrence on an unrelated PR (#729) hit
it on the FIRST of two `submit()` calls on the same in-memory Sales Invoice
(a pre-existing test double-submit) -- the wildcard hook below was
originally registered under `after_insert` only, which does not fire for
that second write, and missed it. Reproduced directly (mock `now()` to a
whole second on a `save()` after a normal `insert()`) before switching the
registration to `on_update` -- which turned out to be ALSO insufficient
(`run_post_save_methods()` only calls `on_update` for `_action in ("save",
"submit")`, skipping a save on an already-submitted doc, `cancel()`, and
`db_set()`, all three of which stamp `modified` via the same `now()` call).
`on_change` is unconditional in `run_post_save_methods()` and is what
`db_set()` itself calls, so it is the event actually registered below.

The fix here does NOT touch the framework (forbidden by CLAUDE.md) and does
NOT re-read the database. It only needs to make the IN-MEMORY string match
what a DB round-trip of the same instant would already produce -- a
`datetime(6)` column stores '...48.000000' and '...48' identically, so
trimming the suffix here changes no persisted data, only the Python-side
string Frappe compares against itself later.

**Removal criterion.** This is a permanent workaround for an upstream bug,
not a temporary patch -- there is no version pin to bump. It can be deleted
(the `doc_events["*"]["on_change"]` registration, and this module) once a
released frappe compares `get_datetime(previous.modified)` /
`get_datetime(self._original_modified)` (or equivalent value-based
comparison) instead of `cstr()`/`str()` at `check_if_latest`
(`frappe/model/document.py:1106`) and `validate_set_only_once` (`:912`).
Upstream precedent for the general shape of this class of fix:
frappe#38219 ("reload Prepared Report before save to avoid
TimestampMismatchError").
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
    """`doc_events["*"]["on_change"]` handler. See module docstring / #609.

    Registered on the wildcard doctype under `on_change` -- the only
    doc-lifecycle event unconditionally fired for insert, save, submit,
    cancel, update-after-submit, AND `db_set()` (see module docstring for
    why `after_insert` and `on_update` both under-cover this) -- so every
    one of the 21 production `insert()` -> `save()`/`submit()` sites, and
    any other write, is covered from one place, per #609's scope decision,
    rather than patching each call site.
    """
    touched = strip_whole_second_suffix(doc)
    if touched:
        # 1-in-10^6 per document in production (#609). frappe.logger()
        # defaults to WARNING on a dev server, ERROR otherwise
        # (CLAUDE.md's "known traps"), so a bare .info() would silently
        # vanish in EITHER case -- but .error() is always at or above that
        # threshold regardless of dev_server, so it always reaches
        # logs/frappe.log (a real production site's operator can read that
        # file; this is not the CI-visibility trap the harness logger
        # exists for, since CI does not run this hook against an ephemeral
        # runner's own site).
        #
        # Deliberately NOT frappe.log_error(): it inserts an "Error Log"
        # document, and "*" applies to every doctype including that one --
        # if the mocked/real clock that produced THIS whole-second value is
        # still in effect, the Error Log insert gets stamped with the same
        # whole-second value, this handler fires again for it, and calls
        # log_error() again for ITS OWN Error Log, without end. Reproduced
        # directly (RecursionError) before reverting to a plain file log.
        frappe.logger("timestamp_normalization").error(
            f"[#609] normalized whole-second timestamp on {doc.doctype} {doc.name}: {touched}"
        )
