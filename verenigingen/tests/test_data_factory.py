"""
Test Data Factory Module for Verenigingen Tests
This module provides a bridge to the fixtures test data factory
"""

from verenigingen.tests.fixtures.test_data_factory import TestDataFactory


# Stub class for TestDataContext
class TestDataContext:
    """Test data context manager for scoped test data creation"""

    def __init__(self):
        self.created_records = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup created records
        for doctype, name in reversed(self.created_records):
            try:
                import frappe
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True)
            except Exception:
                pass
        return False


# Re-export for backward compatibility
__all__ = ['TestDataFactory', 'TestDataContext']