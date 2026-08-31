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

from unittest.mock import patch

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
