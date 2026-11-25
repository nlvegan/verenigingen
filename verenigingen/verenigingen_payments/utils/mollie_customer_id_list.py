"""Split a ``mollie_customer_id`` field value into its individual ids (#2675).

The field is a plain Data field and a comma-separated list is a supported value, so every
reader that attributes a payment (or refuses a shared id) must work per individual id, never
on the whole string.

Deliberately NOT ``parse_mollie_customer_ids``: that one validates the ``cst_`` + 10 character
format, logs an Error Log row per bad token and caps the count. Attribution must neither drop a
stored id silently nor write Error Log rows from a read path; it only needs exact tokens.
"""

from typing import Dict, Iterable, List, Optional


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


def index_rows_by_customer_id(rows: Iterable) -> Dict[str, list]:
    """Map every individual id to the rows listing it (a row with N ids appears under all N)."""
    by_id: Dict[str, list] = {}
    for row in rows:
        for customer_id in split_mollie_customer_ids(row.mollie_customer_id):
            by_id.setdefault(customer_id, []).append(row)
    return by_id
