"""Write the missing ``Ponto Settings.sandbox_mode`` / ``Mollie Settings.test_mode`` rows as 1 (#2509).

A site that saved these Singles before the field existed reads the flag as 0, which selects the
production Ponto client / live Mollie key. The row is seeded only while no live credential is
configured; otherwise it is left alone and an Error Log row asks an operator to decide (maintainer
ruling on #2509). Existing rows (0 included) are never touched; idempotent.
"""

import frappe
from frappe.utils.password import get_decrypted_password

from verenigingen.utils.single_check_defaults import seed_missing_check_default


def _password_set(doctype, fieldname):
    return bool(get_decrypted_password(doctype, doctype, fieldname, raise_exception=False))


def _mollie_live_credentials():
    return _password_set("Mollie Settings", "live_secret_key")


def _ponto_live_credentials():
    return bool(
        frappe.db.get_single_value("Ponto Settings", "production_client_id")
        or _password_set("Ponto Settings", "production_client_secret")
    )


GATEWAYS = (
    ("Ponto Settings", "sandbox_mode", _ponto_live_credentials),
    ("Mollie Settings", "test_mode", _mollie_live_credentials),
)


def execute():
    for doctype, fieldname, has_live_credentials in GATEWAYS:
        seed_missing_check_default(doctype, fieldname, has_live_credentials=has_live_credentials)
