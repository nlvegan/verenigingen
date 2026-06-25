"""
Shared DB helper utilities for raw-SQL table management.

These helpers abstract the repeated CREATE TABLE / UPDATE status / INSERT audit
patterns found in sepa_rollback_manager, sepa_notification_manager, and
sepa_race_condition_manager.

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


def update_row_status(
    table_name: str,
    pk_value: str,
    status: str,
    *,
    pk_column: str = "name",
    error_message: str | None = None,
    completed_at=None,
) -> None:
    """UPDATE ``status`` (and optionally ``error_message`` / ``completed_at``) on a row.

    All values are passed as parameterized arguments.  ``table_name`` and
    ``pk_column`` are identifier-validated before being embedded in the SQL
    string.

    Parameters
    ----------
    table_name:
        Table to update (backtick-quoted in the query).
    pk_value:
        Primary-key value that identifies the row.
    status:
        New value for the ``status`` column.
    pk_column:
        Name of the primary-key column (default ``"name"``).
    error_message:
        If supplied, written to an ``error_message`` column in the same UPDATE.
    completed_at:
        If supplied, written to a ``completed_at`` column in the same UPDATE.
    """
    _validate_identifier(table_name, "table_name")
    _validate_identifier(pk_column, "pk_column")

    set_clauses = ["status = %s"]
    params: list = [status]

    if error_message is not None:
        set_clauses.append("error_message = %s")
        params.append(error_message)

    if completed_at is not None:
        set_clauses.append("completed_at = %s")
        params.append(completed_at)

    set_sql = ", ".join(set_clauses)
    params.append(pk_value)

    frappe.db.sql(
        f"UPDATE `{table_name}` SET {set_sql} WHERE `{pk_column}` = %s",  # noqa: S608
        params,
    )
    frappe.db.commit()


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
