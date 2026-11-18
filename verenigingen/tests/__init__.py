import frappe

# Test dependencies
# Order matters - dependencies are loaded in sequence
global_test_dependencies = [
    "User",
    "Company",   # Required by Customer, Sales Invoice, and ERPNext DocTypes
    "Region",    # Required by Chapter (Link field)
    "Chapter",   # Required for many SEPA and membership tests
    "Donor",     # Required for customer integration tests
    "Customer",  # Required for member and donor tests
]

# #2438: bind the email factory in every consumer BEFORE any test patches it at its source.
# Gated on test mode: production code lazily imports modules under verenigingen.tests (www/monitoring_dashboard,
# utils/testing/sepa_payment_failure_scenarios), which would otherwise run this on a web request.
# `frappe.flags.in_test` is True under `bench run-tests` when this package is imported and False in a plain
# connected process (measured on test_site_6). The site must also be initialised: importing
# verenigingen_payments/utils/sepa_alerting_system.py (it builds a singleton at import) raised
# AttributeError on frappe.client_cache in a process with no frappe.init. `frappe.flags` itself raises
# RuntimeError when uninitialised, hence the getattr on frappe.local.
from verenigingen.tests.utils.email_factory_binders import preload_email_factory_binders  # noqa: E402

_flags = getattr(frappe.local, "flags", None)
if _flags and _flags.get("in_test") and getattr(frappe.local, "db", None) is not None:
    preload_email_factory_binders()
