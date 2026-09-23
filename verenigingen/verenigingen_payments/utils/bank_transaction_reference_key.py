"""Bank Transaction's per-bank-account reference uniqueness key (#1267, #809's derived-key pattern).

`bank_transaction_creator.py`'s own idempotency lookup (`_find_matching_bank_transaction`,
fixed in #383) is already scoped to `(bank_account, reference_number)`: `reference_number`
alone is not unique across accounts by design (different banks do not coordinate reference
numbering), so a global uniqueness guarantee would actively break that lookup.

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
field carries a key when the row is in scope, and `NULL` otherwise -- MariaDB does not
enforce uniqueness across `NULL`s, so out-of-scope rows are exempt without needing any
special-casing at read time.

The constraint MUST be declared as a Custom Field rather than created with raw DDL.
`MariaDBTable.alter()` (frappe/database/mariadb/schema.py) drops any unique index on a column
that DocType/Custom Field metadata does not declare, treating it as an orphan of a deleted
field -- silently, on essentially every `bench migrate`. See #809 and #1267.

The key is HASHED (not a plain concatenation) because `bank_account` (up to 140 chars) plus
`reference_number` (unbounded `TEXT`) does not fit in a `Data` field (`varchar(140)`). The
patch's duplicate report groups by the raw columns, so nothing is lost diagnostically.

## Scope: SYSTEM-ISSUED references only (amended maintainer decision, #1267)

The first version of this constraint applied to every non-blank `(bank_account,
reference_number)` pair. PR #1340's review reproduced a real defect that scope caused:
`reference_number` on an MT940-imported row is the PAYER's own end-to-end reference (SEPA
EREF), not something this app or any system it talks to issues -- two distinct, legitimate
payments (e.g. the same member paying twice with an unchanged standing-order reference) can
share it on the same account. `mt940_import.py`'s insert used to swallow the resulting
`UniqueValidationError`, so the second payment vanished with no trace. See the maintainer's
amended decision on #1267 and the review at PR #1340#issuecomment-5793704294.

So the key now applies ONLY where the reference comes from a system that already guarantees
it is unique BY CONSTRUCTION, never from what a human or another bank chose:

- **Mollie** payment / settlement / balance-transaction ids -- `tr_`, `stl_`, `baltr_`
  (confirmed against actual writers: `dues_payment_processor.py`, `payment_processors.py`,
  `balance_transaction_processor.py` and `bulk_transaction_importer.py` all set
  `reference_number` to the raw Mollie API id verbatim, never a caller-composed value).
- **e-Boekhouden** -- always exactly `f"EB-{mutation_id}"`, deliberately, per
  `payment_entry_handler.py`'s own comment: "Always use EB-{mutation_id} as reference for
  uniqueness ... Guaranteed unique per mutation." No other writer produces this shape.
- **Ponto** -- transaction ids are UUIDs with no distinguishing prefix, so this is the one
  case where a prefix guess would be unjustifiable. `transaction_importer.py` instead
  writes the SAME id into a dedicated column, `custom_ponto_transaction_id`, alongside
  `reference_number` -- a signal set by the writer itself, which is what this module checks
  instead of guessing from the reference's shape.

Everything else -- MT940 bank references, `member_management.py` / `bank_integration.py`'s
manual entries, and any future or unrecognised shape -- gets a `NULL` key: unconstrained by
default, not constrained by default. That is the maintainer's explicit instruction ("make an
unknown shape default to unconstrained, not constrained"), and it also means this module
never has to be taught about a new caller-supplied reference convention; only a new
SYSTEM-issued one needs to be added here.
"""

import hashlib

import frappe

from verenigingen.verenigingen_payments.utils.payment_services.constants import MOLLIE_LIVE_PAYMENT_PREFIX

FIELDNAME = "custom_reference_number_key"

PONTO_TRANSACTION_ID_FIELDNAME = "custom_ponto_transaction_id"

# ASCII unit separator: not expected in a bank account name or a bank-issued reference, so
# ("a\x1fb", "") and ("a", "b") cannot collide by construction.
_SEPARATOR = "\x1f"

# Mollie settlement / balance-transaction id prefixes. Not in payment_services/constants.py
# (that module only names the payment/refund/customer prefixes Payment Entry cares about);
# confirmed against this app's own writers and docstrings --
# settlement_bank_transaction_processor.py / api/settlement_processing.py ("Mollie
# settlement ID (e.g., 'stl_jDk30akdN')") and api/balance_transaction_processing.py
# ("Balance transaction IDs start with 'baltr_'", already used there in a raw LIKE filter).
_MOLLIE_SETTLEMENT_PREFIX = "stl_"
_MOLLIE_BALANCE_TRANSACTION_PREFIX = "baltr_"
_MOLLIE_PREFIXES = (
    MOLLIE_LIVE_PAYMENT_PREFIX,
    _MOLLIE_SETTLEMENT_PREFIX,
    _MOLLIE_BALANCE_TRANSACTION_PREFIX,
)
# Deliberately excludes MOLLIE_TEST_PAYMENT_PREFIX ("test_"): this app's own test factory
# defaults Bank Transaction/Payment Entry references to "test_..." shapes, and pulling that
# prefix in would drag ordinary test fixtures into a constraint meant for live Mollie ids --
# the same reasoning mollie_idempotency_key.py already documents for Payment Entry.

_EBOEKHOUDEN_PREFIX = "eb-"


def is_system_issued_reference(reference_number, ponto_transaction_id=None) -> bool:
    """True when `reference_number` is one this app or a payment system it talks to issued,
    rather than something a payer, another bank or a human typed in.

    Case-insensitive on the prefix checks, to match `reference_number`'s case-insensitive
    collation (`utf8mb4_unicode_ci`) -- the same reasoning `mollie_idempotency_key.py`
    documents: the SQL half matches `'EB-123'` and `'eb-123'` alike, so the Python half must
    too, or a row could be counted in-scope by one half and treated as out-of-scope by the
    other.
    """
    if ponto_transaction_id:
        return True
    if not reference_number:
        return False
    lowered = reference_number.lower()
    return lowered.startswith(_MOLLIE_PREFIXES) or lowered.startswith(_EBOEKHOUDEN_PREFIX)


def build_reference_key(bank_account, reference_number, ponto_transaction_id=None):
    """The key for a Bank Transaction with a system-issued reference on a real account, or
    `None`.

    `None` (not `""`) is the out-of-scope value on purpose: `NULL` is what exempts a row
    from the unique index. Frappe happens to normalise `""` to `NULL` on a unique field, but
    relying on that would make the exemption depend on a framework detail rather than on this
    function.
    """
    if not bank_account or not is_system_issued_reference(reference_number, ponto_transaction_id):
        return None

    raw = _SEPARATOR.join([bank_account, reference_number])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def in_scope_sql_condition() -> str:
    """The SQL half of `is_system_issued_reference`, computed live rather than as a module
    constant.

    `custom_ponto_transaction_id` is installed by a fixture (`fixtures/custom_field.json`),
    and fixtures sync AFTER post_model_sync patches
    (`frappe/migrate.py`: `run_schema_updates()` runs patches, `post_schema_updates()` runs
    `sync_fixtures()` afterwards) -- so on a brand-new site's very first `bench migrate`,
    this patch can run before that column exists. Treating the Ponto clause as absent in
    that case is correct: a brand-new site also has zero Bank Transaction rows for it to
    matter on. `test_bank_transaction_reference_key.py` asserts this function agrees with
    `is_system_issued_reference` on a corpus; they are two expressions of one rule and will
    drift the moment only one of them is edited.
    """
    prefix_clause = (
        r"(reference_number LIKE 'tr\_%' OR reference_number LIKE 'stl\_%' "
        r"OR reference_number LIKE 'baltr\_%' OR reference_number LIKE 'eb-%')"
    )
    if frappe.db.has_column("Bank Transaction", PONTO_TRANSACTION_ID_FIELDNAME):
        scope_clause = (
            f"({prefix_clause} OR ({PONTO_TRANSACTION_ID_FIELDNAME} IS NOT NULL "
            f"AND {PONTO_TRANSACTION_ID_FIELDNAME} != ''))"
        )
    else:
        scope_clause = prefix_clause

    return (
        "(bank_account IS NOT NULL AND bank_account != '' "
        "AND reference_number IS NOT NULL AND reference_number != '' "
        f"AND {scope_clause})"
    )


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

    doc.set(
        FIELDNAME,
        build_reference_key(doc.bank_account, doc.reference_number, doc.get(PONTO_TRANSACTION_ID_FIELDNAME)),
    )
