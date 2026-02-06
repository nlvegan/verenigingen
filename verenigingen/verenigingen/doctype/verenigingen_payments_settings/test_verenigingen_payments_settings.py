# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

# import frappe
from frappe.tests.utils import FrappeTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestVerenigingenPaymentsSettings(FrappeTestCase):
    """
    Integration tests for VerenigingenPaymentsSettings.
    Use this class for testing interactions between multiple components.
    """

    pass
