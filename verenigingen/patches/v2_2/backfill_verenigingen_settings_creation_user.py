"""Backfill creation_user on Verenigingen Settings when missing.

The `creation_user` field on `Verenigingen Settings` is `reqd=1` in the
schema. Sites whose Settings doc was inserted before that requirement
existed have a NULL value. Subsequent `.save()` on the Settings doc
(e.g. via `_seed_default_document_categories`) then fails with a
MandatoryError, cascading into hundreds of test failures and any
production code that ever resaves the Settings.

Symptom in CI shard 4 (run 26363365112): 957 "Failed to create
Verenigingen Settings: ...creation_user" log lines.

Defaults to Administrator (the standard system user that would have
inserted the Settings doc had `creation_user` been required at the time).
"""

import frappe


def execute():
    if not frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
        return

    current = frappe.db.get_value("Verenigingen Settings", "Verenigingen Settings", "creation_user")
    if current:
        return

    frappe.db.set_value(
        "Verenigingen Settings",
        "Verenigingen Settings",
        "creation_user",
        "Administrator",
        update_modified=False,
    )
    frappe.db.commit()
    print("✅ Backfilled creation_user on Verenigingen Settings")
