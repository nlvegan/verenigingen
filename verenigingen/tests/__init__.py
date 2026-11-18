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
# Some binders touch the database at import (sepa_alerting_system builds a singleton), so this runs
# only once a site is connected, as it always is under `bench run-tests`.
from verenigingen.tests.utils.email_factory_binders import preload_email_factory_binders  # noqa: E402

if getattr(frappe.local, "db", None) is not None:
    preload_email_factory_binders()
