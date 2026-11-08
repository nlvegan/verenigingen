"""Give existing sites a notification row for every registry key that has none (#1959).

PR #1998 seeds one enabled row per registry key at install, which existing sites never run. A
key with no row in Verenigingen Email Configuration counts as DISABLED, so alerts and mails sent
with such a key were skipped silently. Maintainer ruling on #1959: add the missing rows at
migrate, via a patch, and never touch a row that exists (an admin may have turned it off or set
recipients).

This reuses the install seeder, which only appends rows for keys with none. A patch runs ONCE per
site: a registry key added after this patch ran needs its own patch (or "Sync Registry").
"""

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows


def execute():
    ensure_notification_registry_rows()
