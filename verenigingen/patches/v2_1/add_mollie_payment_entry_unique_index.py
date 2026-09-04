"""Superseded by the Mollie idempotency Custom Field (#809). Intentionally a no-op.

This patch used to run

    CREATE UNIQUE INDEX idx_mollie_payment_ref_unique
    ON `tabPayment Entry` (reference_no, payment_type, party)

while its own docstring described that index as "partial/conditional - it only enforces
uniqueness for entries with reference_no starting with 'tr_'". It is not, and cannot be:
MariaDB has no partial indexes, so the index covered EVERY Payment Entry row. This app
legitimately reuses non-Mollie `reference_no` values across many rows -- invoice numbers,
payroll batch references, POS settlement batches; 221 duplicate groups / 1084 rows on
veg11 as of 2026-09-04 -- so on a real site the DDL simply fails.

Two further defects made that worse rather than loud:

* The duplicate pre-check used `LIKE 'tr_%'` with the underscore UNESCAPED. `_` is a
  single-character LIKE wildcard, so the check also matched `trXsomething` and was wider
  than the shape it meant to describe.
* When the pre-check found duplicates it logged and RETURNED. Frappe records a patch as
  executed whenever `execute()` returns without raising
  (`frappe.modules.patch_handler.execute_patch`), so the decline was indistinguishable
  from success and nothing ever looked again -- #746. Measured 2026-09-04: this patch is
  marked done in `Patch Log` on all five test sites and on veg11, and the index exists on
  none of them.

Emptying it rather than deleting it is deliberate. The patch name is already recorded on
every existing site, so removing the entry from `patches.txt` would change nothing there,
while a site that has NOT yet reached it would otherwise still create the broken unscoped
index on its next `bench migrate` -- silently reintroducing the bug next to its fix.

The replacement is `v2_2.add_mollie_payment_entry_idempotency_key`, which scopes the
constraint through the data (a key for Mollie-style references, NULL for everything else)
via a declared Custom Field, so Frappe's schema sync preserves it.
"""


def execute():
    """No-op. See the module docstring: the index this used to create cannot exist."""
    return
