"""Shared helper for escaping SQL LIKE wildcards.

Fixes #1153: this idiom had been copy-pasted three times in production code
(``sepa_mandate_manager.py``, ``periodic_donation_operations.py``,
``reversal_idempotency.py``) plus once in test code, and the copies disagreed
on the order of the three ``.replace()`` calls. One copy escaped the
backslash LAST:

    value.replace("%", "\\%").replace("_", "\\_").replace("\\", "\\\\")

That order is wrong and produces a pattern matching NEITHER the literal it
is meant to protect NOR the over-match it is meant to block: the first two
steps insert literal backslashes (``%`` -> ``\\%``), and the third step then
doubles those backslashes too (``\\%`` -> ``\\\\%``), which in a LIKE pattern
reads as an escaped backslash followed by an UNESCAPED ``%`` -- exactly the
wildcard the whole exercise was meant to neutralise.

The backslash must be escaped FIRST, before it is used to escape anything
else, so the backslashes the later steps insert are not themselves touched
again:

    value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
"""


def escape_sql_like_wildcards(value) -> str:
    """Escape ``%``, ``_`` and ``\\`` so ``value`` is safe as a LIKE literal.

    Order matters: the backslash MUST be escaped first, or the backslashes
    inserted by the ``%``/``_`` steps get doubled by the backslash step,
    producing a pattern that matches neither the literal nor blocks the
    wildcard over-match (see module docstring / #1153).

    The caller is still responsible for the surrounding LIKE syntax, e.g.
    ``frappe.db.sql("... WHERE col LIKE %s", (f"{escaped}%",))``.

    ``None`` raises rather than coercing. The three call sites this replaced did
    not agree on coercion -- ``sepa_mandate_manager`` wrote ``str(member_id)``
    deliberately, because a ``member_id`` can arrive as an int, while
    ``periodic_donation_operations`` called ``.replace()`` straight on its
    ``file_stem`` and so raised ``AttributeError`` on ``None`` at once.
    Coercing unconditionally would keep the looser behaviour and silently lose
    the stricter one: ``None`` would become the literal ``"None"``, the caller
    would build ``LIKE 'None%'``, and the query would return nothing while
    looking like it worked. A shared helper that answers a programming error
    with an empty result set is a footgun, so ints still coerce and ``None``
    does not.
    """
    if value is None:
        raise TypeError(
            "escape_sql_like_wildcards() received None. A LIKE pattern built from "
            "None would silently match nothing; pass a real value."
        )
    return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
