#!/usr/bin/env python3
"""
Setup test environment for Mollie Backend Integration
Configures mocks and paths for testing without Frappe
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Frappe mock before any imports
try:
    import frappe
except ImportError:
    # Import and setup mock
    from verenigingen.tests.frappe_mock import frappe

    sys.modules["frappe"] = frappe
    print("✓ Frappe mock loaded")

# Now modules can be imported
print("Test environment configured successfully")
print(f"Project root: {project_root}")
print(f"Python path updated: {sys.path[0]}")
