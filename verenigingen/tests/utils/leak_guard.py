"""Attribution for records a test leaves behind.

The drains in ``EnhancedTestCase`` delete what a test created, including records
that survived rollback because the test (or production code it called) issued a
commit. Some records resist deletion entirely -- a submitted document, a parent
with children, anything still linked -- and the drain's only response was to
count them and log ``N record(s) could not be deleted``.

A count is not actionable. The record stays in the database, a later test in the
same shard collides with it, and *that* test fails, naming neither the leftover
nor the test responsible. Across #326 and #327 that produced five failures in
four doctypes -- a Bank Account, a Region, two row counts and a Payment Ledger
Entry -- every one of them landing on an innocent test.

So the leak is recorded where it happens, with the identity and the reason.

Reporting follows the ``VERENIGINGEN_FAIL_ON_ERROR_LOG`` contract deliberately:
warn by default, fail only under an env flag. Turning this into a hard failure
everywhere at once would redden the suite in proportion to a debt that already
exists; the flag lets one CI job enforce it while the baseline ratchets down
(#328).
"""

import os

FAIL_ON_TEST_LEAK_ENV = "VERENIGINGEN_FAIL_ON_TEST_LEAK"

_TRUTHY = {"1", "true", "yes", "on"}

# Machine-readable prefix. CI greps for this, so it must stay stable and must
# not be reworded casually -- scripts/testing/check_test_leaks.py parses it.
LEAK_MARKER = "TEST-LEAK"


def fail_on_test_leak_enabled() -> bool:
    """True when a leaked record should FAIL the test rather than warn."""
    return str(os.environ.get(FAIL_ON_TEST_LEAK_ENV, "")).strip().lower() in _TRUTHY


def format_leak_lines(rows, test_id: str):
    """One machine-readable line per leaked record.

    ``TEST-LEAK <test id> <doctype>::<name> <reason>``

    Deliberately one line per record rather than a summary count: the whole
    point is that the identity survives into the log, so the next person can
    grep a shard for the doctype in their error message and land on the test
    that produced it.
    """
    return [
        f"{LEAK_MARKER} {test_id} {row.get('doctype')}::{row.get('name')} "
        f"{(row.get('error') or '').splitlines()[0][:200] if row.get('error') else 'no reason recorded'}"
        for row in rows
    ]


def format_leak_failure(rows, test_id: str) -> str:
    """Assertion message for the enforcing mode."""
    lines = "\n  ".join(format_leak_lines(rows, test_id))
    return (
        f"{len(rows)} record(s) survived cleanup in {test_id}. Each one stays in the "
        f"database for the rest of the shard, and the test that collides with it will "
        f"not name this cause:\n  {lines}"
    )
