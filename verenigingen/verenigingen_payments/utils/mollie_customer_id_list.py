"""Split a ``mollie_customer_id`` field value into its individual ids (#2675).

The field is a plain Data field and a comma-separated list is a supported value, so every
reader that attributes a payment (or refuses a shared id) must work per individual id, never
on the whole string.

Deliberately NOT ``parse_mollie_customer_ids``: that one validates the ``cst_`` + 10 character
format, logs an Error Log row per bad token and caps the count. Attribution must neither drop a
stored id silently nor write Error Log rows from a read path; it only needs exact tokens.
"""

from typing import Dict, Iterable, List, Optional

import frappe


def split_mollie_customer_ids(value: Optional[str]) -> List[str]:
    """Individual ids in a field value: stripped, empties dropped, duplicates removed, order kept."""
    if not value or not isinstance(value, str):
        return []
    seen: List[str] = []
    for token in value.split(","):
        token = token.strip()
        if token and token not in seen:
            seen.append(token)
    return seen


def field_value_after_resolving(stored: Optional[str], resolved_id: str) -> str:
    """What a writer that resolved ``resolved_id`` should leave in the field (#3251).

    A listed id leaves the list untouched; an unlisted id is appended when the field holds a list
    (so the other listed ids are not lost, as #2675's donor webhook does); a field with at most one
    id (or none) is replaced, which is the long-standing "stale single id -> fresh customer" behaviour.
    """
    listed = split_mollie_customer_ids(stored)
    if resolved_id in listed:
        return stored
    if len(listed) > 1:
        return ", ".join(listed + [resolved_id])
    return resolved_id


def index_rows_by_customer_id(rows: Iterable) -> Dict[str, list]:
    """Map every individual id to the rows listing it (a row with N ids appears under all N)."""
    by_id: Dict[str, list] = {}
    for row in rows:
        for customer_id in split_mollie_customer_ids(row.mollie_customer_id):
            by_id.setdefault(customer_id, []).append(row)
    return by_id


def names_listing_customer_id(
    doctype: str, customer_id: str, filters: Optional[dict] = None, limit=3
) -> List[str]:
    """Rows whose ``mollie_customer_id`` lists this id (#2675), ordered by name.

    The LIKE only narrows the candidates (and would also hit ``cst_123`` for ``cst_12``); the
    exact per-token test decides. The token test is case-sensitive (Mollie ids are); the MariaDB
    ``=`` it replaces was case-insensitive, so a payment id differing only in case no longer matches.
    """
    rows = frappe.get_all(
        doctype,
        filters={**(filters or {}), "mollie_customer_id": ["like", f"%{customer_id}%"]},
        fields=["name", "mollie_customer_id"],
        order_by="name asc",
    )
    names = [r.name for r in rows if customer_id in split_mollie_customer_ids(r.mollie_customer_id)]
    return names[:limit] if limit else names
