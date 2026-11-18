# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Shared SQL-budget helpers for the Mollie performance benchmarks (#2460).

Both twin benchmark modules (tests/performance and tests/payment) gate on SQL
statement counts instead of wall-clock time. The helpers live here so the twins
do not grow a duplicate-helper clone family.
"""

from contextlib import contextmanager
from datetime import datetime

import frappe

from verenigingen.verenigingen_payments.utils.payment_gateways import _process_subscription_payment

# SQL-statement budgets for _process_subscription_payment, measured on a warmed
# site (#2460): a paying call ran 233 statements, the first repeat 20 (it still
# creates the Error Log / meta state for the unmatched path), later repeats 2.
# Each budget leaves a little room for ERPNext drift but not for an extra query
# per call to go unnoticed.
PAYING_CALL_QUERY_BUDGET = 260
FIRST_REPEAT_QUERY_BUDGET = 30
REPEAT_CALL_QUERY_BUDGET = 4


@contextmanager
def mollie_benchmark_sql_counter():
    """Yield a list that collects every SQL statement run through frappe.db.sql.

    Same hook as IntegrationTestCase.assertQueryCount, but it hands the list back
    so a benchmark can print the count and assert on it afterwards.
    """
    queries = []
    orig_sql = frappe.db.__class__.sql

    def _sql_and_record(db, *args, **kwargs):
        queries.append(str(args[0]) if args else "")
        return orig_sql(db, *args, **kwargs)

    frappe.db.__class__.sql = _sql_and_record
    try:
        yield queries
    finally:
        frappe.db.__class__.sql = orig_sql


def run_counted_payment(gateway, member, customer, payment_id, subscription_id):
    """Process one payment; return (result, elapsed_ms, sql_statement_count)."""
    start_time = datetime.now()
    with mollie_benchmark_sql_counter() as queries:
        result = _process_subscription_payment(
            gateway, member.name, customer.name, payment_id, subscription_id
        )
    elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
    return result, elapsed_ms, len(queries)
