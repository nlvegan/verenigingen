# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Keep ``frappe.form_dict`` a LocalProxy across tests (#1991).

``frappe.form_dict`` is a ``LocalProxy`` bound to ``frappe.local.form_dict``. A test
that writes ``frappe.form_dict = frappe._dict({...})`` replaces that proxy on the
*module* for the rest of the process (measured on test_site_3: the attribute's type
goes from ``frappe.utils.local.LocalProxy`` to ``frappe._dict``). From then on
``frappe.form_dict`` no longer follows ``frappe.local.form_dict``, which
``frappe.set_user()``, ``frappe.init()`` and the request path reset, so every later
page test reads a stale dict. In a CI shard (one process for ~116 modules) that turns a
passing module red whenever the shard re-pack puts it after a polluter.

The guard restores the proxy at the start of a test AND via ``addCleanup`` after it, so
the last polluter in a class cannot leak into the next class (``EnhancedTestCase`` used
to restore only at ``setUp``, which does nothing for the next class if that one is a
``VereningingenTestCase``, which restored nothing at all).
"""

import frappe


def restore_form_dict_proxy():
    """Re-bind ``frappe.form_dict`` to a fresh LocalProxy, same expression as frappe's own."""
    frappe.form_dict = frappe.local("form_dict")


def guard_form_dict(test):
    """Call from a harness ``setUp``: restore now, and again when the test finishes."""
    restore_form_dict_proxy()
    test.addCleanup(restore_form_dict_proxy)
