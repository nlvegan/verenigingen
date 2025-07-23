# Compatibility import layer for test utilities
# This file provides backward compatibility for tests that import from this location
from verenigingen.tests.utils.test_utils import mock_email_sending, setup_test_environment

__all__ = ['mock_email_sending', 'setup_test_environment']