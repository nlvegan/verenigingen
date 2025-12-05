import frappe

# Test dependencies
# Order matters - dependencies are loaded in sequence
global_test_dependencies = [
    "User",
    "Region",    # Required by Chapter (Link field)
    "Chapter",   # Required for many SEPA and membership tests
    "Donor",     # Required for customer integration tests
    "Customer",  # Required for member and donor tests
]
