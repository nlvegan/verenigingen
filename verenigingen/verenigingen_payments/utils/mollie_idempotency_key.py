"""Single home for the Mollie Payment Entry idempotency key (#809, #746).

`unified_payment_entry_creator.py` already refuses to book a second Payment Entry for a
`(payment_type, reference_no, party)` it has seen. That is check-then-act: two concurrent
webhook deliveries both read "no row" and both insert. #746 tried to close the race with a
plain unique index on those three columns, which cannot exist -- this app legitimately
reuses `reference_no` across non-Mollie Payment Entries (invoice numbers, payroll batch
references), 221 duplicate groups / 1084 rows on veg11 as of 2026-09-04.

MariaDB has no partial indexes, so the scope is expressed in the DATA instead: this field
carries a key for Mollie-style references and NULL for everything else, and MariaDB does
not enforce uniqueness across NULLs. `Member.user`, `Volunteer.member` and Payment Entry's
own `eboekhouden_mutation_nr` already rely on exactly that (the last one: a live unique
index with 158 NULLs across 3694 rows).

The constraint MUST be declared as a Custom Field rather than created with raw DDL.
`MariaDBTable.alter()` (frappe/database/mariadb/schema.py:97-126, "logic to drop unique
constraint for fields deleted from a doctype") drops any unique index on a column that
DocType/Custom Field metadata does not declare, treating it as an orphan of a deleted
field -- silently, on essentially every `bench migrate`. That is what killed the
generated-column approach #746 prototyped, and it is why this is a field and not an index.

The key is HASHED because Data is `varchar(140)` and `reference_no` (140) + `party` (140)
+ `payment_type` does not fit. The patch's duplicate report groups by the raw columns, so
nothing is lost diagnostically.
"""

import hashlib

FIELDNAME = "custom_mollie_idempotency_key"

# The reference shapes the Mollie writers produce. `unified_payment_entry_creator.py:56`
# builds `reference_no = mollie_payment_id + reference_suffix`, where the suffix is
# "_refund_<id>" / "_chargeback_<id>" -- so a refund and its original share a payment id
# and are separated only by the suffix and `payment_type`. That is why the key is the
# composite and NOT `custom_mollie_payment_id`, which would reject a legitimate refund
# (and is not written by this creator at all -- only by the settlement path).
_MOLLIE_PREFIXES = ("tr_", "re_")
_MOLLIE_INFIXES = ("_refund_", "_chargeback_")

# The SQL half of the same predicate, for the backfill patch. `test_mollie_idempotency_key`
# asserts the two halves agree on a corpus; they are two expressions of one rule and will
# drift the moment only one of them is edited.
# NOTE: the `%` wildcards below are literal SQL, so this fragment cannot be used in a
# query that also carries bind parameters -- MySQLdb interpolates with `%` formatting and
# reads them as format specifiers ("unsupported format character"). Every caller here
# embeds it in a parameterless query; escape values with `frappe.db.escape` if that ever
# has to change.
MOLLIE_REFERENCE_SQL_CONDITION = (
    r"(reference_no LIKE 'tr\_%' OR reference_no LIKE 're\_%' "
    r"OR reference_no LIKE '%\_refund\_%' OR reference_no LIKE '%\_chargeback\_%')"
)

# ASCII unit separator: cannot occur in a Mollie id, a payment type or a party name, so
# ("a\x1fb", "c") and ("a", "b\x1fc") cannot collide.
_SEPARATOR = "\x1f"


def is_mollie_style_reference(reference_no) -> bool:
    """True when `reference_no` is one the Mollie writers produce."""
    if not reference_no:
        return False
    return reference_no.startswith(_MOLLIE_PREFIXES) or any(
        infix in reference_no for infix in _MOLLIE_INFIXES
    )


def build_idempotency_key(reference_no, payment_type, party):
    """The key for a Mollie-style Payment Entry, or None for every other row.

    None (not "") is the out-of-scope value on purpose: NULL is what exempts a row from
    the unique index. Frappe happens to normalise "" to NULL on a unique field, but
    relying on that would make the exemption depend on a framework detail rather than on
    this function.
    """
    if not is_mollie_style_reference(reference_no):
        return None

    raw = _SEPARATOR.join([reference_no or "", payment_type or "", party or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def set_payment_entry_idempotency_key(doc, method=None):
    """`before_save` on Payment Entry: keep the key in step with the fields it derives from.

    `before_save` rather than `before_insert` because `reference_no`, `payment_type` and
    `party` are all editable on a draft, and a key that only matched the values at insert
    time would guard the wrong tuple. Both `insert()` and `_save()` call
    `run_before_save_methods()` (frappe/model/document.py:484, :592).

    Guarded on the field existing, for the window where this code is live on a site whose
    doctype cache predates the field -- the same shape as #780's and #797's guards. A
    `doc.set()` on a field the DocType lacks is a silent no-op, so without this guard the
    failure would be invisible rather than absent.
    """
    if not doc.meta.has_field(FIELDNAME):
        return

    doc.set(FIELDNAME, build_idempotency_key(doc.reference_no, doc.payment_type, doc.party))
