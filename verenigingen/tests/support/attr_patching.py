"""Small attribute-swapping context managers shared by the #701 savepoint tests
(`test_atomic_migration_operation_savepoints.py`, `test_migration_transaction_savepoints.py`).

`unittest.mock.patch.object` does not fit either case cleanly:

* `frappe.db.rollback` is a bound method on the live connection object, and these
  tests need the replacement to still call through to the real implementation
  while recording how it was invoked -- `patch.object(..., wraps=...)` works for a
  plain function but `frappe.db` is a singleton shared across the whole test
  process, so swapping the attribute directly and restoring it in a `finally` is
  the more explicit, less surprising choice here.
* `security_helper.rollback_to_savepoint` / `security_helper.release_savepoint_if_present`
  are plain names imported into that module's namespace (`from
  verenigingen.utils.transaction_errors import ...`), not `frappe.X` attributes,
  so patching `security_helper.frappe` (as the older mock-based
  `test_migration_transaction.py` suite does) does not reach them at all --
  they must be patched by name on the module itself.
"""

from contextlib import contextmanager

import frappe


@contextmanager
def patch_db_rollback(replacement):
    """Swap `frappe.db.rollback` for the duration of the block."""
    original = frappe.db.rollback
    frappe.db.rollback = replacement
    try:
        yield
    finally:
        frappe.db.rollback = original


@contextmanager
def patch_module_attr(module, name, replacement):
    """Swap a plain module-level attribute (a function imported by name, not a
    `frappe.db` method)."""
    original = getattr(module, name)
    setattr(module, name, replacement)
    try:
        yield
    finally:
        setattr(module, name, original)
