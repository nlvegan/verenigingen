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

## Scope: SYSTEM-ISSUED references only, marked by the WRITER (#1267, #1349)

The first version of this constraint applied to every non-blank `(bank_account,
reference_number)` pair. PR #1340's review reproduced a real defect that scope caused:
`reference_number` on an MT940-imported row is the PAYER's own end-to-end reference (SEPA
EREF), not something this app or any system it talks to issues -- two distinct, legitimate
payments (e.g. the same member paying twice with an unchanged standing-order reference) can
share it on the same account. See the maintainer's amended decision on #1267 and the review
at PR #1340#issuecomment-5793704294.

The amended version then recognised system-issued references by PREFIX (`tr_`, `stl_`,
`baltr_`, `EB-`). #1349: a payer can type any of those into a payment reference, so an MT940
line "EB-2024" was classified as system-issued and its twin on the same account was refused.
A prefix is a guess about who wrote the string; the writer knows.

So a row is system-issued only when its WRITER says so:

- **Mollie** payment / settlement / balance-transaction ids and **e-Boekhouden**
  `EB-<mutation_id>` set the Check field `custom_reference_is_system_issued` (see
  `SYSTEM_ISSUED_FIELDNAME`) when they create the row, through `BankTransactionCreator`.
- The **Mollie reversal** (refund/chargeback) rows set it too: their reference is
  `build_reversal_key()`, the webhook's idempotency key, so a concurrent duplicate delivery
  must be refused by the database.
- **Ponto** rows are marked by `custom_ponto_transaction_id`, the same id written next to
  `reference_number` (UUIDs have no prefix to guess from). That signal is unchanged.

Everything else -- MT940 and every other importer of a payer/bank reference, manual entries
(`member_management.py`, `bank_integration.py`), and any future or unrecognised writer -- gets a `NULL` key: unconstrained by default, not constrained by
default (the maintainer's instruction on #1267). Only a new SYSTEM-issued writer has to opt
in. The cost of forgetting is the quiet kind (a duplicate is not refused), which is why
`test_bank_transaction_reference_writers` drives each Mollie/e-Boekhouden writer.

Rows created before #1349 carry no flag. `patches/v2_2/mark_system_issued_bank_transaction_
references_1349.py` sets it on the rows the prefix rule had constrained, so they keep their
guard when next saved (`validate` recomputes the key from the flag on EVERY save).
"""

import hashlib

import frappe

FIELDNAME = "custom_reference_number_key"

PONTO_TRANSACTION_ID_FIELDNAME = "custom_ponto_transaction_id"

# Check field set by the writer of a row whose reference a system issued (#1349).
SYSTEM_ISSUED_FIELDNAME = "custom_reference_is_system_issued"

# ASCII unit separator: not expected in a bank account name or a bank-issued reference, so
# ("a\x1fb", "") and ("a", "b") cannot collide by construction.
_SEPARATOR = "\x1f"

# The prefixes below are NOT used to classify a row any more (#1349: a payer can type one).
# They survive only as the frozen rule the pre-#1349 backfill patches ran under:
# `enforce_unique_bank_transaction_reference` keyed rows by them, and
# `mark_system_issued_bank_transaction_references_1349` flags the rows they had constrained.
# "tr_" is a literal rather than payment_services.constants.MOLLIE_LIVE_PAYMENT_PREFIX because
# importing that package from here is circular now that bank_transaction_creator imports this.
# Mollie settlement / balance-transaction id prefixes. Not in payment_services/constants.py
# (that module only names the payment/refund/customer prefixes Payment Entry cares about);
# confirmed against this app's own writers and docstrings --
# settlement_bank_transaction_processor.py / api/settlement_processing.py ("Mollie
# settlement ID (e.g., 'stl_jDk30akdN')") and api/balance_transaction_processing.py
# ("Balance transaction IDs start with 'baltr_'", already used there in a raw LIKE filter).
_MOLLIE_SETTLEMENT_PREFIX = "stl_"
_MOLLIE_BALANCE_TRANSACTION_PREFIX = "baltr_"
_MOLLIE_PREFIXES = (
    "tr_",
    _MOLLIE_SETTLEMENT_PREFIX,
    _MOLLIE_BALANCE_TRANSACTION_PREFIX,
)
# Deliberately excludes MOLLIE_TEST_PAYMENT_PREFIX ("test_"): this app's own test factory
# defaults Bank Transaction/Payment Entry references to "test_..." shapes, and pulling that
# prefix in would drag ordinary test fixtures into a constraint meant for live Mollie ids --
# the same reasoning mollie_idempotency_key.py already documents for Payment Entry.

_EBOEKHOUDEN_PREFIX = "eb-"


def is_system_issued_reference(reference_number, ponto_transaction_id=None, system_issued=False) -> bool:
    """True when the WRITER marked this row's reference as one this app or a payment system
    it talks to issued, rather than something a payer, another bank or a human typed in.

    `system_issued` is the writer's `custom_reference_is_system_issued` flag;
    `ponto_transaction_id` is the Ponto writer's own signal. The shape of
    `reference_number` is deliberately NOT consulted (#1349); it only has to be non-blank,
    because a blank reference is exempt whoever wrote it.
    """
    if ponto_transaction_id:
        return True
    return bool(system_issued) and bool(reference_number)


def legacy_prefix_matches(reference_number) -> bool:
    """The pre-#1349 prefix rule, kept ONLY for the patches that classify rows written
    before writers carried a flag. Case-insensitive to match `reference_number`'s
    `utf8mb4_unicode_ci` collation, as `legacy_prefix_sql_condition` is."""
    if not reference_number:
        return False
    lowered = reference_number.lower()
    return lowered.startswith(_MOLLIE_PREFIXES) or lowered.startswith(_EBOEKHOUDEN_PREFIX)


def legacy_prefix_sql_condition() -> str:
    """The SQL half of `legacy_prefix_matches`, with the same blank-account/blank-reference
    exemptions. Used by the patches only, never to classify a live row."""
    return (
        "(bank_account IS NOT NULL AND bank_account != '' "
        "AND reference_number IS NOT NULL AND reference_number != '' "
        r"AND (reference_number LIKE 'tr\_%' OR reference_number LIKE 'stl\_%' "
        r"OR reference_number LIKE 'baltr\_%' OR reference_number LIKE 'eb-%'))"
    )


def legacy_scope_sql_condition() -> str:
    """The pre-#1349 rule in full (prefix OR Ponto id), for `enforce_unique_bank_transaction_
    reference` only. Not the live rule: see `in_scope_sql_condition`."""
    if not frappe.db.has_column("Bank Transaction", PONTO_TRANSACTION_ID_FIELDNAME):
        return legacy_prefix_sql_condition()
    prefix = legacy_prefix_sql_condition()
    ponto = (
        "(bank_account IS NOT NULL AND bank_account != '' "
        "AND reference_number IS NOT NULL AND reference_number != '' "
        f"AND {PONTO_TRANSACTION_ID_FIELDNAME} IS NOT NULL AND {PONTO_TRANSACTION_ID_FIELDNAME} != '')"
    )
    return f"({prefix} OR {ponto})"


def build_reference_key(bank_account, reference_number, ponto_transaction_id=None, system_issued=False):
    """The key for a Bank Transaction with a system-issued reference on a real account, or
    `None`.

    `None` (not `""`) is the out-of-scope value on purpose: `NULL` is what exempts a row
    from the unique index. Frappe happens to normalise `""` to `NULL` on a unique field, but
    relying on that would make the exemption depend on a framework detail rather than on this
    function.
    """
    if not bank_account or not is_system_issued_reference(
        reference_number, ponto_transaction_id, system_issued
    ):
        return None

    raw = _SEPARATOR.join([bank_account, reference_number])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def in_scope_sql_condition() -> str:
    """The SQL half of `is_system_issued_reference`, computed live rather than as a module
    constant.

    `custom_ponto_transaction_id` and `custom_reference_is_system_issued` are installed by
    fixtures (`fixtures/custom_field.json`), and fixtures sync AFTER post_model_sync patches
    (`frappe/migrate.py`: `run_schema_updates()` runs patches, `post_schema_updates()` runs
    `sync_fixtures()` afterwards) -- so on a brand-new site's very first `bench migrate`,
    this can run before those columns exist. Treating a clause as absent in that case is
    correct: a brand-new site also has zero Bank Transaction rows for it to matter on.
    `test_bank_transaction_reference_key.py` asserts this function agrees with
    `is_system_issued_reference` on a corpus; they are two expressions of one rule and will
    drift the moment only one of them is edited.
    """
    signals = []
    if frappe.db.has_column("Bank Transaction", SYSTEM_ISSUED_FIELDNAME):
        signals.append(f"{SYSTEM_ISSUED_FIELDNAME} = 1")
    if frappe.db.has_column("Bank Transaction", PONTO_TRANSACTION_ID_FIELDNAME):
        signals.append(
            f"({PONTO_TRANSACTION_ID_FIELDNAME} IS NOT NULL AND {PONTO_TRANSACTION_ID_FIELDNAME} != '')"
        )
    scope_clause = f"({' OR '.join(signals)})" if signals else "0"

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
        build_reference_key(
            doc.bank_account,
            doc.reference_number,
            doc.get(PONTO_TRANSACTION_ID_FIELDNAME),
            doc.get(SYSTEM_ISSUED_FIELDNAME),
        ),
    )
