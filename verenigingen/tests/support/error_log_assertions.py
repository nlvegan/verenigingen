"""Assert that an operator-facing Error Log row really says what it should.

`expectErrorLog` is a **suppression**, not an assertion: it only tells the harness'
teardown check to ignore matching rows (`tests/utils/error_log_guard.py`). A test that
calls it and nothing else passes just as happily when the `frappe.log_error` is deleted
outright -- which is how six truncated, mis-titled log rows shipped through a green
suite in PR #575.

Two things need asserting, and the second is the one that was missed:

1. the row is titled as intended, and
2. its message is **complete**.

`frappe.log_error`'s real signature is `log_error(title, message, ...)` -- arg1 is the
**title** -- and it stores `method=title`, `error=traceback`. So the common positional
`log_error(f"...long message...", "Short Title")` puts the MESSAGE in `method`, a
**Data** field, which truncates it at 140 characters mid-word; the title never reaches
the title field at all.

Measured on test_site_1, and worth stating precisely because it is easy to overstate:
for a 158-character message the stored `method` is **140** chars and cut mid-word, while
`error` comes back **188** chars with the tail intact. **The text is NOT lost** -- what
is lost is the TITLE column, which now shows a truncated message, so the Error Log list
view is unreadable and cannot be filtered by title. That is the defect; data loss is
not. The keyword form (`title=`, `message=`) gives `method` the title and `error` the
full body.

**Locate the row by a UNIQUE fragment, never by title alone.** `tabError Log` is
**MyISAM** -- non-transactional -- so its rows survive the per-test rollback AND persist
between runs. A title-only lookup happily returns a previous run's row: the first
version of this helper did exactly that, and its "control" failed for a stale-row
mismatch rather than for the truncation it was meant to detect. Searching `error` for a
per-test identifier both pins the right row and makes the positional form fail loudly,
because under it the identifier is in `method` and `error` holds only the title.

Call this while the test is still running: `EnhancedTestCase`'s captured-insert drain
deletes the row at teardown.
"""

import frappe


def assert_error_log(test_case, title, unique, must_contain=()):
    """Assert an Error Log row whose message contains `unique` and every fragment.

    `unique` must be an identifier that appears ONLY in this test's message -- a
    generated payment reference, a fixture token, a customer name. It is what
    distinguishes this row from a leftover.

    `must_contain` should include the identifiers an operator needs in order to act
    (the payment id, the Payment Entry name), because those sit at the END of these
    messages and are exactly what truncation removes.
    """
    rows = frappe.get_all(
        "Error Log",
        filters={"error": ["like", f"%{unique}%"]},
        fields=["name", "method", "error"],
        order_by="creation desc",
        limit=5,
    )
    test_case.assertTrue(
        rows,
        f"expected an Error Log row whose message mentions {unique!r} (title {title!r}); "
        f"it was never logged, and `expectErrorLog` alone would not have noticed.",
    )
    row = rows[0]
    test_case.assertEqual(
        row["method"],
        title,
        f"Error Log title should be {title!r}, got {row['method']!r}. A message in this "
        f"field means log_error was called positionally.",
    )
    message = row["error"] or ""
    for fragment in must_contain:
        test_case.assertIn(
            str(fragment),
            message,
            f"Error Log {title!r} is missing {fragment!r}, which an operator needs in "
            f"order to act on this. Got: {message!r}",
        )
    return message
