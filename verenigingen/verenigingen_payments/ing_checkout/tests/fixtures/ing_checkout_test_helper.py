# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""Test-credential plumbing for the ING Checkout (Pay.nl) live integration suite.

Mirrors mollie/tests/mollie_test_helper.py::ensure_mollie_test_credentials.

The Pay.nl sandbox credentials live in common_site_config.json under
``paynl_test_service_id`` / ``paynl_test_token_code`` / ``paynl_test_api_token``
(copied from a configured site; never committed). When they are absent — e.g. CI
without the keys — the helper returns False and the live tests skip, so the
module stays green.
"""

import frappe


def ensure_ing_checkout_test_credentials() -> bool:
    """Populate this site's ING Checkout Settings from the sandbox credentials in
    site config, so integration tests can hit Pay.nl's real sandbox API.

    Returns:
        True if sandbox credentials are configured and ING Checkout Settings is
        ready; False otherwise (callers should skip the live integration tests).
    """
    service_id = frappe.conf.get("paynl_test_service_id")
    token_code = frappe.conf.get("paynl_test_token_code")
    api_token = frappe.conf.get("paynl_test_api_token")
    if not (service_id and token_code and api_token):
        return False

    settings = frappe.get_single("ING Checkout Settings")
    settings.enabled = 1
    settings.sandbox_mode = 1
    settings.service_id = service_id
    settings.token_code = token_code
    settings.api_token = api_token
    # The controller validate() only enforces credential presence/format, which
    # these sandbox values already satisfy, but we ignore it to stay robust to
    # future webhook-URL/domain checks (as the Mollie helper does).
    settings.flags.ignore_validate = True
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    # Ensure a freshly built PayNLClient reads the new credentials, not a cached
    # single doc.
    frappe.clear_document_cache("ING Checkout Settings", "ING Checkout Settings")
    return True
