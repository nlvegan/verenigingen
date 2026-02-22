# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

import unittest

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory

if not hasattr(unittest, "skip_test_for_test_record_creation"):

    def skip_test_for_test_record_creation(cls):
        """Decorator to skip automatic test record creation"""
        return cls

    # Add to unittest module
    unittest.skip_test_for_test_record_creation = skip_test_for_test_record_creation


class VereningingenTestCase(unittest.TestCase):
    """Base test class for Verenigingen tests with helpful utility methods"""

    @classmethod
    def setUpClass(cls):
        """Set up common test environment"""
        super().setUpClass()
        # Disable automatic test record creation
        frappe.flags.make_test_records = False
        cls.factory = CoreTestDataFactory()

    def create_test_member(self, **kwargs):
        """Delegate to CoreTestDataFactory"""
        return self.factory.create_test_member(**kwargs)

    def create_test_volunteer(self, member=None, **kwargs):
        """Delegate to CoreTestDataFactory"""
        return self.factory.create_test_volunteer(member=member, **kwargs)
