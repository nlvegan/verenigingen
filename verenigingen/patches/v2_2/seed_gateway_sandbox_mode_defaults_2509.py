"""Write the missing ``Ponto Settings.sandbox_mode`` / ``Mollie Settings.test_mode`` rows as 1 (#2509).

A site that saved these Singles before the field existed reads the flag as 0, which selects the
production Ponto client / live Mollie key. The row is seeded only while no live credential is
configured; otherwise it is left alone and an Error Log row asks an operator to decide (maintainer
ruling on #2509). Existing rows (0 included) are never touched; idempotent.
"""

from verenigingen.utils.single_check_defaults import (
    mollie_has_live_credentials,
    ponto_has_live_credentials,
    seed_missing_check_default,
)

GATEWAYS = (
    ("Ponto Settings", "sandbox_mode", ponto_has_live_credentials),
    ("Mollie Settings", "test_mode", mollie_has_live_credentials),
)


def execute():
    for doctype, fieldname, has_live_credentials in GATEWAYS:
        seed_missing_check_default(doctype, fieldname, has_live_credentials=has_live_credentials)
