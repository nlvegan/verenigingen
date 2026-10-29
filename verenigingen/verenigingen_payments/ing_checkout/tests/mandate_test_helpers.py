# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Shared seam stub for the ING Checkout mandate tests.

`test_mandate_service_unit.py` and `test_mandate_payload_spec_unit.py` are both
mock-only suites whose subject is the Pay.nl payload and response handling, not
mandate resolution. They need resolution stubbed at the seam so they keep that
subject -- and they need the SAME stub, because two copies of it would be a
copy-paste that the next fix reaches only one of (`duplicate_helper_validator`
blocks exactly that, and did).

Resolution itself is covered against real `Member` and `SEPA Mandate` documents in
`test_ing_checkout_mandate_resolution.py`. That separation is the point: a mocked
`Member` is what hid #623, so nothing here may stand in for a real one.
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.verenigingen_payments.utils.mandate_candidates import MandateChoice

_RESOLVER = (
    "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service."
    "MandateService._resolve_membership_mandate"
)


def resolves_to(mandate_name):
    """Patch the resolver to hand back one mandate, as `unambiguous_active_mandate` would.

    `patch` uses `create=False`, so renaming or removing `_resolve_membership_mandate`
    breaks every caller loudly instead of silently stubbing a method that no longer
    exists.
    """
    return patch(_RESOLVER, return_value=MandateChoice(frappe._dict(name=mandate_name), 1))


def routes_get_doc(docs_by_doctype):
    """Build a `frappe.get_doc` side_effect that stubs ONLY the doctypes named.

    A bare `patch("frappe.get_doc")` replaces the function for the whole process, so
    framework code reached from the code under test (`today()` -> System Settings ->
    `frappe.client_cache` loader -> `frappe.get_doc`) gets the mock too, and on a cold
    cache the mock is pickled into the cache (`PicklingError`, shard-order dependent).
    Any other named doctype therefore goes to the REAL `get_doc`. A dict argument
    (`frappe.get_doc({...})`, i.e. a document being built, as `log_error` does) still
    gets a MagicMock, so no real row is inserted.

    Call this BEFORE entering `patch("frappe.get_doc", ...)`: it captures the real
    function at call time.
    """
    real_get_doc = frappe.get_doc

    def _get_doc(*args, **kwargs):
        doctype = args[0] if args else kwargs.get("doctype")
        if isinstance(doctype, str):
            if doctype in docs_by_doctype:
                return docs_by_doctype[doctype]
            return real_get_doc(*args, **kwargs)
        return MagicMock()

    return _get_doc
