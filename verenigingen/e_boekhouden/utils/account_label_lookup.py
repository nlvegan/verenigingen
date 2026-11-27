"""Resolve an Account by a fixed label without silently picking a first match (#1398).

The e-Boekhouden migration finds parent/group accounts by a fixed label
("Tax Assets", "Liquide middelen", ...). It used a bare substring LIKE through
``frappe.db.get_value``, which returns one arbitrary row: with both
"Tax Assets" and "Deferred Tax Assets" in the chart, either could become the
parent of a migrated account.
"""

import frappe

from verenigingen.utils.sql_like import escape_sql_like_wildcards


class AmbiguousAccountLabel(frappe.ValidationError):
    """More than one Account matches a label, so none may be chosen."""


def find_account_by_label(label, filters, exact_names=None):
    """Return the single Account name matching ``label`` within ``filters``.

    An exact ``account_name`` match (the first of ``exact_names``, default the
    label, that matches anything) wins over substring matches. Without an exact
    match, an escaped substring match is used if it is unique. Returns None when
    nothing matches; raises AmbiguousAccountLabel when the winning tier has
    more than one row. Disabled accounts are ignored so a stale one cannot turn
    a unique match into a refusal.
    """
    for exact in exact_names or [label]:
        rows = _account_names(filters, exact)
        if rows:
            return _single_or_refuse(label, rows)
    rows = _account_names(filters, ["like", f"%{escape_sql_like_wildcards(label)}%"])
    return _single_or_refuse(label, rows) if rows else None


def _account_names(filters, account_name):
    return frappe.get_all(
        "Account", filters={"disabled": 0, **filters, "account_name": account_name}, pluck="name", limit=5
    )


def _single_or_refuse(label, rows):
    if len(rows) > 1:
        # raise, not frappe.throw: callers may catch this and a throw would
        # leave a stray message in the user's message_log
        raise AmbiguousAccountLabel(f"Account label {label} is ambiguous: it matches {', '.join(rows)}")
    return rows[0]
