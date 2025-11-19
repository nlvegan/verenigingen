# Bridge module for Mollie webhook security tests
# This imports the actual test from the integrations directory

import sys
import os

# Add the mollie tests directory to the path
mollie_tests_path = os.path.join(os.path.dirname(__file__), '..', 'integrations', 'mollie', 'tests')
if mollie_tests_path not in sys.path:
    sys.path.insert(0, mollie_tests_path)

# Import all tests from the actual test file
from test_webhook_security import *