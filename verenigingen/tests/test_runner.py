# Test runner bridge module
# This module provides a bridge to the enhanced test runner for backward compatibility.

import sys
import os
import unittest

# Add the scripts directory to the path
scripts_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts', 'testing', 'runners')
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

try:
    from enhanced_test_runner import *
except ImportError:
    # Fallback for basic test functionality
    import unittest

    def run_tests():
        """Basic test runner fallback"""
        loader = unittest.TestLoader()
        suite = loader.discover('.')
        runner = unittest.TextTestRunner(verbosity=2)
        return runner.run(suite)