"""Register the ``door_unavailable`` notification type on existing sites (#2127).

A key with no row in Verenigingen Email Configuration counts as DISABLED, so without this row the
staff alert for an unusable /word-lid door would be skipped silently. This reuses the install seeder,
which only adds rows for keys that have none (the seeded row is Role-Based, naming the admin pair).
"""

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows


def execute():
    ensure_notification_registry_rows()
