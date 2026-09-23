"""Bank Transaction's per-bank-account reference uniqueness key (#1267, #809's derived-key pattern).

`bank_transaction_creator.py`'s own idempotency lookup (`_find_matching_bank_transaction`,
fixed in #383) is already scoped to `(bank_account, reference_number)`: `reference_number`
alone is not unique across accounts by design (different banks do not coordinate reference
numbering), so a global uniqueness guarantee would actively break that lookup -- see #1267's
comment thread for the measured collision that motivated this scoping decision.

Two things stop the obvious `ALTER TABLE ... ADD UNIQUE INDEX (bank_account, reference_number)`
from working:

1. `reference_number` is a `Small Text` field, which MariaDB stores as `TEXT`. A `TEXT`
   column used in a key requires an explicit prefix length ("BLOB/TEXT column ... used in key
   specification without a key length"), and a composite index spanning `bank_account` (a
   `Link`/`varchar(140)`) and a prefix of `reference_number` would silently stop
   distinguishing references that agree on the prefix.
2. Blank references must be exempt (MT940's `NONREF`, and several writers that default a
   missing reference to `""`). MariaDB enforces uniqueness across `''` the same as any other
   value -- it does NOT treat `''` like `NULL` -- so a plain composite index would reject every
   second blank-reference transaction on one account.

The fix used for the sibling Mollie Payment Entry guard (#809) solves both: express the scope
in the DATA as a single derived `Data` field instead of an index over the raw columns. This
field carries a key when both `bank_account` and `reference_number` are non-blank, and `NULL`
otherwise -- MariaDB does not enforce uniqueness across `NULL`s, so blank-reference rows are
exempt without needing any special-casing at read time.

The constraint MUST be declared as a Custom Field rather than created with raw DDL.
`MariaDBTable.alter()` (frappe/database/mariadb/schema.py) drops any unique index on a column
that DocType/Custom Field metadata does not declare, treating it as an orphan of a deleted
field -- silently, on essentially every `bench migrate`. See #809 and #1267.

The key is HASHED (not a plain concatenation) because `bank_account` (up to 140 chars) plus
`reference_number` (unbounded `TEXT`) does not fit in a `Data` field (`varchar(140)`). The
patch's duplicate report groups by the raw columns, so nothing is lost diagnostically.
"""

import hashlib

FIELDNAME = "custom_reference_number_key"

# ASCII unit separator: not expected in a bank account name or a bank-issued reference, so
# ("a\x1fb", "") and ("a", "b") cannot collide by construction.
_SEPARATOR = "\x1f"

# The SQL half of the same predicate used by the backfill patch.
# test_bank_transaction_reference_key asserts the two halves agree on a corpus; they are two
# expressions of one rule and will drift the moment only one of them is edited.
IN_SCOPE_SQL_CONDITION = (
    "(bank_account IS NOT NULL AND bank_account != '' "
    "AND reference_number IS NOT NULL AND reference_number != '')"
)


def is_in_scope(bank_account, reference_number) -> bool:
    """True when both halves of the key are present.

    Mirrors `IN_SCOPE_SQL_CONDITION`: blank (`None` or `""`) on either side takes the row
    out of scope, which is what lets it repeat freely.
    """
    return bool(bank_account) and bool(reference_number)


def build_reference_key(bank_account, reference_number):
    """The key for a Bank Transaction with a real reference on a real account, or `None`.

    `None` (not `""`) is the out-of-scope value on purpose: `NULL` is what exempts a row
    from the unique index. Frappe happens to normalise `""` to `NULL` on a unique field, but
    relying on that would make the exemption depend on a framework detail rather than on this
    function.
    """
    if not is_in_scope(bank_account, reference_number):
        return None

    raw = _SEPARATOR.join([bank_account or "", reference_number or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def set_bank_transaction_reference_key(doc, method=None):
    """`validate` on Bank Transaction: keep the key in step with the fields it derives from.

    Not `before_insert`: `bank_account` and `reference_number` are both editable on a draft
    (see `_try_submit_existing_draft`'s resubmission path), so a key frozen at insert time
    would guard the tuple the row used to have.

    Not `before_save` either. `run_before_save_methods` (frappe/model/document.py) dispatches
    `validate` + `before_save` for `_action == "save"` but `validate` + `before_SUBMIT` for
    `_action == "submit"` -- so a `before_save` handler does NOT run on a bare `.submit()`.
    `validate` fires on both actions, so it is the only single registration that covers them.
    See #809's identical reasoning for `Payment Entry.custom_mollie_idempotency_key`.

    Guarded on the field existing, for the window where this code is live on a site whose
    doctype cache predates the field. A `doc.set()` on a field the DocType lacks is a silent
    no-op, so without this guard the failure would be invisible rather than absent.
    """
    if not doc.meta.has_field(FIELDNAME):
        return

    doc.set(FIELDNAME, build_reference_key(doc.bank_account, doc.reference_number))
