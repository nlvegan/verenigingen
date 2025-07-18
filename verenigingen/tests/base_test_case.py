"""
Base Test Case Module - Bridge for backward compatibility
"""

from verenigingen.tests.utils.base import VereningingenTestCase as BaseTestCase

# Re-export for backward compatibility
__all__ = ['BaseTestCase']