# -*- coding: utf-8 -*-
# Compatibility shim for test_framework_enhanced imports

from verenigingen.tests.utils.test_base_framework import VerenigingenTestCase


# Stub class for PerformanceTestCase
class PerformanceTestCase(VerenigingenTestCase):
    """Performance test case base class"""
    pass


# Stub class for IntegrationTestCase
class IntegrationTestCase(VerenigingenTestCase):
    """Integration test case base class"""
    pass
