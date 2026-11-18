"""Assert a stored date is "today" without racing the clock (#697).

`assertEqual(doc.some_date, today())` reads the clock twice: once inside the
production write and once in the assertion. If midnight (site time) falls
between the two reads the production value is yesterday's date and the test
fails although nothing is wrong. The helper accepts exactly that one case:
yesterday, and only while the site clock is still within a minute of midnight.
"""

from frappe.utils import add_days, getdate, now_datetime, today

MIDNIGHT_GRACE_SECONDS = 60


def assert_written_today(case, value, msg=None):
    """Assert `value` (date, datetime or ISO string) is today's date, tolerating a midnight straddle."""
    case.assertIsNotNone(value, msg or "expected today's date, got None")
    written = str(getdate(value))
    now = now_datetime()
    seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
    if seconds_since_midnight < MIDNIGHT_GRACE_SECONDS and written == str(getdate(add_days(today(), -1))):
        return
    case.assertEqual(written, today(), msg)
