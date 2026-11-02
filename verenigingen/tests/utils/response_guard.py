# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Keep ``frappe.local.response`` well-formed across tests (#1983, second victim of #1697).

``frappe.init()`` binds ``frappe.local.response = _dict({"docs": []})`` and
``frappe.handler.run_doc_method`` ends with ``frappe.response.docs.append(doc)``. Many webhook
tests replace the response with a bare ``frappe._dict()`` (so that ``http_status_code``
assertions start clean). Whatever one of them leaves behind is inherited by every later test in
the same process, and a CI shard is one process for ~116 modules: a ``run_doc_method`` test that
the shard re-pack places after a leaker dies with
``AttributeError: 'NoneType' object has no attribute 'append'`` although its own code never
touched the response (#1980 on CI, #1697 before it).

The guard does two things, both called from the shared bases' ``setUp``:

* **Normalise** at the start of the test: a response that is not a dict with a ``docs`` list
  (left by a polluter that registers no guard, e.g. a plain ``FrappeTestCase``) is replaced by
  what ``frappe.init`` would have bound. Without this a victim is protected only from
  polluters that use the harness.
* **Restore** via ``addCleanup``: the response object bound when the test started (for a
  guardless polluter that was normalised above, that is the NORMALISED object, i.e. the bare
  response is healed permanently, not put back) is re-bound afterwards with its contents (including a copy of ``docs``) as they were, so the LAST polluter
  in a class cannot leak into the next class, and neither can an in-place
  ``response["http_status_code"] = ...`` or a doc appended by ``run_doc_method``.
"""

import copy

import frappe


def _is_well_formed(response):
    return isinstance(response, dict) and isinstance(response.get("docs"), list)


def _snapshot_response(response):
    """Copy one level of nested lists/dicts (`docs`, `headers`): the containers frappe and this
    app mutate in place. Not a deepcopy on purpose: `docs` holds live Documents and a response
    may hold a werkzeug Response, neither of which is safe or useful to copy."""
    return {k: (copy.copy(v) if isinstance(v, (list, dict)) else v) for k, v in response.items()}


def guard_local_response(test):
    """Call from a harness ``setUp``: normalise now, and restore the original when the test ends."""
    response = getattr(frappe.local, "response", None)
    if not _is_well_formed(response):
        response = frappe._dict(docs=[])
        frappe.local.response = response

    snapshot = _snapshot_response(response)

    def _restore():
        response.clear()
        response.update(snapshot)
        frappe.local.response = response

    test.addCleanup(_restore)
