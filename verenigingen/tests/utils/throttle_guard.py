# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Disarm Frappe's User-creation throttle for a test, without ``in_import`` (#2256).

``throttle_user_creation()`` raises "Throttled" once more than
``conf.get("throttle_user_limit", 60)`` Users were created in the last hour. It is skipped
under ``frappe.flags.in_import``, but that flag also disables defaults, select validation
and autoname, so the harness raises the limit instead. Both harness bases call this:
``EnhancedTestCase`` and ``VereningingenTestCase`` (which did not, #2256).
"""

import frappe

_KEY = "throttle_user_limit"
_RAISED = 1000000


def raise_throttle_user_limit(test):
    """Call from a harness ``setUp`` (instance) or ``setUpClass`` (the class): raise the
    limit now, restore it via ``addCleanup`` / ``addClassCleanup``.

    A cleanup rather than tearDown, so it still runs when setUp raises later. The class
    form covers Users inserted in setUpClass, which the per-test call does not reach.
    """
    previous = frappe.local.conf.get(_KEY)
    add_cleanup = test.addClassCleanup if isinstance(test, type) else test.addCleanup
    add_cleanup(_restore_throttle_user_limit, previous)
    frappe.local.conf[_KEY] = _RAISED


def _restore_throttle_user_limit(previous):
    """Delete the key when it was absent: a stored None makes ``count > limit`` raise
    TypeError instead of falling back to the default of 60. ``is None`` rather than
    falsiness, so a deliberate 0 survives."""
    if previous is None:
        frappe.local.conf.pop(_KEY, None)
    else:
        frappe.local.conf[_KEY] = previous
