"""
Shared DB helper utilities for raw-SQL table management.

These helpers abstract the repeated CREATE TABLE / INSERT audit patterns found
in sepa_race_condition_manager.

CALLER CONTRACT
---------------
- ``table_name`` and ``pk_column`` must be trusted identifiers (not user input).
  Each is validated against ``^[A-Za-z0-9_]+$`` and raises ``ValueError`` if it
  fails — this satisfies the project's SQL-field validator without parameterizing
  SQL identifiers (which the DB driver cannot do).
- Column names in ``row`` dicts follow the same rule.
- *Values* are always passed via parameterized ``%s`` / named-dict placeholders
  and are never interpolated into the SQL string.
"""

import re

import frappe

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _validate_identifier(name: str, label: str) -> None:
    """Raise ValueError if *name* is not a safe SQL identifier."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {label} {name!r}: must match ^[A-Za-z0-9_]+$ "
            "(only alphanumerics and underscores allowed)"
        )


def ensure_table_exists(create_sql: str, *, table_name: str) -> None:
    """Run *create_sql* (a CREATE TABLE IF NOT EXISTS statement); commit.

    Idempotent: calling twice does not raise.  A race condition in which two
    processes create the table simultaneously is logged at WARNING level and
    swallowed — the second caller still succeeds because the table now exists.

    WARNING: On error, this helper calls ``frappe.db.rollback()``.  Any
    pending (uncommitted) writes the caller holds will be lost.

    Parameters
    ----------
    create_sql:
        Full ``CREATE TABLE IF NOT EXISTS …`` statement.  The caller is
        responsible for the statement body; this helper only adds safety logging.
    table_name:
        Identifier used in log messages.  Must match ``^[A-Za-z0-9_]+$``.
    """
    _validate_identifier(table_name, "table_name")
    try:
        frappe.db.sql(create_sql)
        frappe.db.commit()
    except Exception as exc:
        # Log and swallow: the table either already exists (race) or there is a
        # benign duplicate-creation attempt — the IF NOT EXISTS clause handles
        # the latter; a race causes a harmless error that we absorb here.
        frappe.db.rollback()
        frappe.logger().warning("ensure_table_exists(%s): %s", table_name, exc)


def insert_audit_row(table_name: str, row: dict) -> str:
    """INSERT a row built from *row* (column -> value dict); return the inserted ``name``.

    All values are passed via parameterized placeholders.  ``table_name`` and
    every column name in *row* are identifier-validated before SQL construction.

    Parameters
    ----------
    table_name:
        Table to insert into (backtick-quoted in the query).
    row:
        Mapping of column name to value.  Must include a ``"name"`` key (used
        as the primary key and as the return value).

    Returns
    -------
    str
        The value of ``row["name"]``.
    """
    _validate_identifier(table_name, "table_name")
    for col in row:
        _validate_identifier(col, "column name")

    columns = list(row.keys())
    values = [row[c] for c in columns]

    col_sql = ", ".join(f"`{c}`" for c in columns)
    placeholder_sql = ", ".join(["%s"] * len(columns))

    frappe.db.sql(
        f"INSERT INTO `{table_name}` ({col_sql}) VALUES ({placeholder_sql})",  # noqa: S608
        values,
    )
    frappe.db.commit()
    return row["name"]
