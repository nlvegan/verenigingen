"""Put ``frappe.flags`` back to what the CALLER had (#2559, #2577).

A function that raises a flag for the work it does must hand the flag back as it found it:
the previous value, or absence. ``finally: frappe.flags.x = False`` (or ``delattr``) clears a
flag the caller had already set, so a nested call silently switches off the outer scope's
behaviour (``in_import``, ``bulk_member_operations``, ...).
"""

from contextlib import contextmanager

import frappe

_MISSING = object()


@contextmanager
def restored_flags(*flag_names):
    """Snapshot ``frappe.flags`` for ``flag_names`` and restore it on every exit.

    Usable as ``with restored_flags("a", "b"):`` or as a decorator
    ``@restored_flags("a", "b")``. Restores the previous value, or removes the flag if the
    caller never had it. Covers a propagating exception too.
    """
    previous = {name: frappe.flags.get(name, _MISSING) for name in flag_names}
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is _MISSING:
                frappe.flags.pop(name, None)
            else:
                frappe.flags[name] = value
